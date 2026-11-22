"""Guarded execution of SQL written by the chatbot's language model.

The API connects to Postgres as the owner role, which bypasses row-level
security, so a generated query cannot be trusted to respect a user's access by
being asked to in its prompt. Access is enforced here instead:

1. ``validate_generated_sql`` accepts a single SELECT/WITH statement and
   rejects schema-qualified names, system catalogs, comments and functions
   that read settings or run SQL from a string.
2. ``run_scoped_query`` runs it on its own connection, in a transaction that is
   always rolled back. Before the query runs, every public table is shadowed by
   a temporary view of the same name that holds only the rows the caller may
   see (the same rules the REST endpoints apply). ``profiles`` loses its
   ``meta`` column, which holds password hashes. Tables the chatbot has no
   reason to read are shadowed by empty views. The transaction is then made
   read-only with a statement timeout, and the result is capped.

Temporary relations are searched before ``public`` for unqualified names, and
qualified names are rejected by the validator, so the query can only ever
resolve to the scoped views.
"""
from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)

MAX_ROWS = 200
STATEMENT_TIMEOUT_MS = 5000


class UnsafeSQLError(ValueError):
    """The generated SQL is not a single, read-only, unqualified query."""


# ─── Validation ───────────────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"^\s*```[a-zA-Z]*\s*|\s*```\s*$")

_MUTATING_WORDS = (
    "INSERT", "UPDATE", "DELETE", "MERGE", "DROP", "ALTER", "CREATE", "TRUNCATE",
    "GRANT", "REVOKE", "COPY", "VACUUM", "REINDEX", "CLUSTER", "COMMENT",
    "SECURITY", "OWNER", "REFRESH",
)

# Any name qualified by one of these schemas (or any quoted name followed by a
# dot) could reach a real table instead of its scoped view.
_SCHEMA_QUALIFIER_RE = re.compile(
    r"""(\b(public|auth|storage|extensions|realtime|vault|net|cron|graphql\w*|
          supabase\w*|pgsodium\w*|pgbouncer|information_schema|pg_\w*)\s*\.)
        |("\s*\.)""",
    re.IGNORECASE | re.VERBOSE,
)

# Literal forms other than a plain '...' string. Dollar quoting ($$...$$), escape
# strings (E'...'), Unicode escapes (U&'...') and bit or hex strings (B'...',
# X'...') are lexed differently from '...', so allowing them would let text that
# looks like a string here run as SQL in Postgres. Generated queries never need
# them, and $ also covers positional parameters.
_IDENT_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_&")


def _blank_plain_literals(sql: str) -> str:
    """Replace each plain '...' literal with '' and return the remaining code.

    Raises UnsafeSQLError for a prefixed literal (E'', U&'', B'', X'', N''),
    a $ or backslash outside a literal, or an unterminated literal. With
    standard_conforming_strings on (the Postgres default), a plain literal
    ends at the first ' that is not doubled, which is exactly what this reads.
    """
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            if i > 0 and sql[i - 1] in _IDENT_CHARS:
                raise UnsafeSQLError("only plain '...' string literals are allowed")
            j = i + 1
            while True:
                if j >= n:
                    raise UnsafeSQLError("unterminated string literal")
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            out.append("''")
            i = j + 1
            continue
        if ch in "$\\":
            raise UnsafeSQLError("only plain '...' string literals are allowed")
        out.append(ch)
        i += 1
    return "".join(out)

# A word followed by "(" is either SQL syntax or a function call. Function calls
# must be on this list. A denylist cannot keep up with functions that run SQL
# held in a string (ts_stat, query_to_xml, dblink, ...); an allowlist can.
_ALLOWED_FUNCTIONS = frozenset("""
    count sum avg min max coalesce nullif greatest least
    round ceil ceiling floor abs trunc sign mod power sqrt
    lower upper initcap length char_length trim ltrim rtrim btrim substring substr
    left right replace split_part concat concat_ws position strpos lpad rpad
    to_char to_date to_timestamp to_number date_trunc date_part extract age
    now current_date current_timestamp make_date make_interval justify_days
    string_agg array_agg array_length cardinality unnest bool_and bool_or every
    jsonb_array_length jsonb_extract_path_text json_extract_path_text
    jsonb_array_elements_text jsonb_typeof
    row_number rank dense_rank ntile lag lead first_value last_value nth_value
    percent_rank cume_dist percentile_cont percentile_disc mode
    stddev stddev_samp stddev_pop variance var_samp var_pop corr width_bucket
""".split())

_SYNTAX_BEFORE_PAREN = frozenset("""
    select from join in exists any all some as on and or not when then else case
    where by having values over filter within cast lateral using group order
    partition union intersect except limit offset distinct is between like ilike
    similar array row nulls asc desc with
    numeric decimal varchar char character float double precision integer int
    bigint smallint real timestamp timestamptz date time interval text boolean
""".split())

_SYSTEM_NAME_RE = re.compile(r'(\bpg_\w*)|("pg_)', re.IGNORECASE)

_CALL_RE = re.compile(r'(?:\b([A-Za-z_][A-Za-z0-9_]*)|("[^"]*"))\s*\(')


def strip_code_fences(raw: str) -> str:
    """Remove a surrounding ```sql ... ``` fence from model output."""
    return _FENCE_RE.sub("", str(raw or "")).strip()


def validate_generated_sql(raw: str) -> str:
    """Return the cleaned query, or raise UnsafeSQLError."""
    sql = strip_code_fences(raw).strip()
    while sql.endswith(";"):
        sql = sql[:-1].rstrip()
    if not sql:
        raise UnsafeSQLError("empty query")

    # Only plain literals are accepted, read the way Postgres reads them, so
    # the checks below see all of the code and none of the data. A filter like
    # ILIKE '%update%' is not mistaken for a statement.
    code = _blank_plain_literals(sql)

    if ";" in code:
        raise UnsafeSQLError("more than one statement")
    if "--" in code or "/*" in code:
        raise UnsafeSQLError("comments are not allowed")
    if not re.match(r"^\(?\s*(SELECT|WITH)\b", code, re.IGNORECASE):
        raise UnsafeSQLError("only SELECT queries are allowed")
    upper = code.upper()
    for word in _MUTATING_WORDS:
        if re.search(rf"\b{word}\b", upper):
            raise UnsafeSQLError(f"{word} is not allowed")
    if _SCHEMA_QUALIFIER_RE.search(code):
        raise UnsafeSQLError("schema-qualified names are not allowed")
    # System catalogs (pg_user, pg_stat_activity, ...) resolve without a schema
    # prefix, and every one of them is named pg_*.
    if _SYSTEM_NAME_RE.search(code):
        raise UnsafeSQLError("system catalogs are not allowed")
    for match in _CALL_RE.finditer(code):
        name = (match.group(1) or "").lower()
        if match.group(2) is not None or (
            name not in _ALLOWED_FUNCTIONS and name not in _SYNTAX_BEFORE_PAREN
        ):
            raise UnsafeSQLError(f"function {match.group(1) or match.group(2)} is not allowed")
    return sql


# ─── Scope ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SqlScope:
    """Who is asking. UUIDs are validated so they can be inlined as literals."""

    user_id: str
    is_admin: bool
    warehouse_id: Optional[str]

    @classmethod
    def build(cls, *, user_id: Any, is_admin: bool, warehouse_id: Any) -> "SqlScope":
        return cls(
            user_id=_uuid_or_none(user_id) or "00000000-0000-0000-0000-000000000000",
            is_admin=bool(is_admin),
            warehouse_id=_uuid_or_none(warehouse_id),
        )


def _uuid_or_none(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def _eq(column: str, value: Optional[str]) -> str:
    if value is None:
        return "FALSE"
    return f"{column}::text = '{value}'"


def _row_filters(scope: SqlScope) -> dict[str, str]:
    """WHERE clause per table, matching the REST endpoints' visibility rules.

    Admins and super admins see their active warehouse. An admin with no
    warehouse sees nothing, as the REST endpoints refuse them (400). Users see
    their own warehouse plus anything assigned to or raised by them.
    """
    uid, wh = scope.user_id, scope.warehouse_id
    if scope.is_admin:
        in_wh = _eq("warehouse_id", wh)
        assets = tickets = profiles = departments = reports = in_wh
        comments_extra = "TRUE"
    else:
        in_wh = _eq("warehouse_id", wh)
        assets = f"({in_wh} OR {_eq('assigned_to', uid)})"
        tickets = f"({in_wh} OR {_eq('created_by', uid)} OR {_eq('assigned_to', uid)})"
        profiles = departments = in_wh
        reports = _eq("generated_by", uid)
        comments_extra = "is_internal IS NOT TRUE"

    asset_ids = f"asset_id IN (SELECT id FROM public.assets WHERE {assets})"
    ticket_ids = f"ticket_id IN (SELECT id FROM public.tickets WHERE {tickets})"
    return {
        "warehouses": "TRUE",
        "model_registry": "TRUE",
        "assets": assets,
        "tickets": tickets,
        "profiles": profiles,
        "departments": departments,
        "reports": reports,
        "report_sources": f"report_id IN (SELECT id FROM public.reports WHERE {reports})",
        "notifications": _eq("user_id", uid),
        "maintenance_events": asset_ids,
        "sensor_readings": asset_ids,
        "pdm_batch_predictions": asset_ids,
        "pdm_prediction_history": asset_ids,
        "asset_status_history": asset_ids,
        "asset_assignments": asset_ids,
        "asset_failure_predictions": asset_ids,
        "asset_cost_predictions": asset_ids,
        "prediction_runs": asset_ids,
        "ticket_status_history": ticket_ids,
        "ticket_comments": f"{ticket_ids} AND {comments_extra}",
    }


# Columns never exposed to generated SQL.
_HIDDEN_COLUMNS = {"profiles": {"meta"}}

_CATALOG_TTL_SECONDS = 600
_catalog_lock = threading.Lock()
_catalog: Optional[dict[str, list[str]]] = None
_catalog_loaded_at = 0.0


def _public_relations(conn) -> dict[str, list[str]]:
    """Public tables and views with their columns, re-read every 10 minutes.

    Re-reading picks up tables added since the process started, so a new
    table is shadowed (by an empty view) rather than reachable directly.
    """
    global _catalog, _catalog_loaded_at
    with _catalog_lock:
        if _catalog is None or time.monotonic() - _catalog_loaded_at > _CATALOG_TTL_SECONDS:
            rows = conn.execute(text(
                "SELECT c.relname, a.attname "
                "FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped "
                "WHERE n.nspname = 'public' AND c.relkind IN ('r','v','m','p','f') "
                "ORDER BY c.relname, a.attnum"
            )).fetchall()
            catalog: dict[str, list[str]] = {}
            for rel, col in rows:
                catalog.setdefault(rel, []).append(col)
            _catalog = catalog
            _catalog_loaded_at = time.monotonic()
        return _catalog


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def build_scope_statements(scope: SqlScope, relations: dict[str, list[str]]) -> str:
    """One SQL batch that shadows every public relation with a scoped view."""
    filters = _row_filters(scope)
    statements = []
    for rel, columns in sorted(relations.items()):
        hidden = _HIDDEN_COLUMNS.get(rel, set())
        cols = ", ".join(_quote_ident(c) for c in columns if c not in hidden)
        where = filters.get(rel, "FALSE")
        statements.append(
            f"CREATE TEMP VIEW {_quote_ident(rel)} AS "
            f"SELECT {cols} FROM public.{_quote_ident(rel)} WHERE {where}"
        )
    return ";\n".join(statements)


def run_scoped_query(engine: Engine, sql: str, scope: SqlScope) -> list[dict]:
    """Validate and run generated SQL against the caller's scoped views.

    Raises UnsafeSQLError for rejected SQL and lets database errors propagate
    so the caller can retry with a corrected query. Nothing it does persists.
    The SQL, the scope it ran under and its outcome go to the current AI trace.
    """
    from app.ai.agent.tracing import record

    scope_note = {"role": "admin" if scope.is_admin else "user", "warehouse_id": scope.warehouse_id}
    try:
        query = validate_generated_sql(sql)
    except UnsafeSQLError as refused:
        record("sql", sql=sql, outcome="refused by sandbox", reason=str(refused), scope=scope_note)
        raise
    try:
        rows = _execute_scoped(engine, query, scope)
    except Exception as exc:
        record("sql", sql=query, outcome="database error", error=f"{type(exc).__name__}: {str(exc).splitlines()[0][:300]}",
               scope=scope_note)
        raise
    record("sql", sql=query, outcome="ok", rows=len(rows), scope=scope_note)
    return rows


def _execute_scoped(engine: Engine, query: str, scope: SqlScope) -> list[dict]:
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            batch = build_scope_statements(scope, _public_relations(conn))
            conn.exec_driver_sql(batch)
            conn.exec_driver_sql("SET LOCAL search_path = pg_temp, public")
            conn.exec_driver_sql("SET LOCAL transaction_read_only = on")
            conn.exec_driver_sql(f"SET LOCAL statement_timeout = {int(STATEMENT_TIMEOUT_MS)}")
            # Run on the driver cursor with no parameters, so the text is sent
            # as written: '%' in ILIKE '%x%' and ':30' in a literal are never
            # read as placeholders.
            cursor = conn.connection.cursor()
            try:
                cursor.execute(f"SELECT * FROM (\n{query}\n) AS agent_query LIMIT {MAX_ROWS}")
                keys = [column[0] for column in cursor.description]
                return [dict(zip(keys, row)) for row in cursor.fetchall()]
            finally:
                cursor.close()
        finally:
            trans.rollback()
