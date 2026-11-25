# ADR-0003: Sandboxed text-to-SQL for the chatbot

- Status: Accepted
- Date: 2026-11-23

## Context

The chatbot's DB orchestrator (Table Selector, SQL Generator, DB Execution,
Self-Healer) asks an LLM to write SQL for questions the fixed tools do not
cover. The backend connects as the database owner, which bypasses row-level
security. A prompt-injected or simply wrong query could therefore read other
warehouses, password hashes or system catalogs, or change data.

## Decision

Model-written SQL is never trusted. It runs through `app/ai/agent/safe_sql.py`
with layered controls, any one of which blocks the main attacks:

1. **Static validation** (`validate_generated_sql`)
   - one statement, must start with `SELECT` or `WITH`, no mutating keywords;
   - a literal tokenizer blanks ordinary `'...'` strings and rejects
     dollar quotes, `E'...'`, `U&'...'`, bit strings and backslashes, so no
     subquery can hide inside a string;
   - no schema qualifiers and no `pg_*` names;
   - every function call must be on an allowlist (aggregates, date, math,
     string functions); anything that executes SQL from text is not on it.
2. **Per-caller scoping** (`build_scope_statements`): inside the transaction,
   a `TEMP VIEW` with the same name shadows each public table and filters it
   to the caller's rows (own records, active warehouse, or nothing when an
   admin has no warehouse). Hidden columns such as `profiles.meta` are left
   out of the view.
3. **Session limits**: `SET LOCAL search_path = pg_temp, public`,
   `transaction_read_only = on`, `statement_timeout = 5000` ms, results capped
   at 200 rows. The transaction is always rolled back.
4. **Driver execution**: the query runs on the raw DB-API cursor with no
   parameters, so `%` and `:` in the text are not parameter markers.

## Alternatives considered

- **A dedicated read-only Postgres role with RLS policies per table.**
  Stronger, and the long-term target, but needs policies for every table and a
  second connection pool on Supabase. The temp-view approach gives the same
  scoping without schema changes.
- **No free-form SQL, fixed tools only.** Safest, but loses the analytics
  questions the architecture is designed to answer.

## Consequences

- New tables are shadowed automatically from the catalog; a table that needs
  scoping beyond warehouse or owner columns must be added to the scope rules.
- Adding a function to the allowlist is a security review item.
- `app/tests/unit/test_security_review_fixes.py`,
  `test_adversarial_suite.py` and the live
  `app/tests/integration/test_sql_sandbox_live.py` cover known bypasses and
  must keep passing.
