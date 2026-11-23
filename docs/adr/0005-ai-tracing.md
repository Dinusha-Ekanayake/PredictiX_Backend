# ADR-0005: In-house AI tracing instead of Langfuse or LangSmith

- Status: Accepted
- Date: 2026-11-23

## Context

Staff need to answer "how did the chatbot get this answer?" for any reply:
which intent was chosen, what was retrieved, which prompts went to the model,
what SQL ran and which actions were offered. Langfuse and LangSmith are the
common hosted tools for this.

## Decision

Traces are recorded in-house (`app/ai/agent/tracing.py`) and stored in the
project database (`ai_traces`, migration 013).

- A trace starts per request and is held in a `ContextVar`, so any layer can
  call `record(kind, ...)` without passing it around.
- Step kinds: `request`, `intent`, `rewrite`, `handler`, `retrieval`,
  `llm_call`, `sql`, `action`, `report_context`, `error`, `result`.
- Each value is clipped (2000 characters, 200 steps) to bound row size.
- The trace id is returned with every answer and shown in the chat UI as
  "Ref xxxxxxxx", so a user can quote it.
- `GET /chatbot/traces/{id}` and `GET /chatbot/traces` apply the same
  visibility as the data: own traces for users, the active warehouse for
  admins, everything for super admins (`app/services/ai_trace_service.py`).
- Saving a trace never fails the user's request.

## Alternatives considered

| Option | Why not chosen as the source of truth |
|--------|--------------------------------------|
| Langfuse Cloud / LangSmith | Prompts and SQL results contain fleet and staff data; sending them to a third party needs a data-processing decision by the project owner |
| Self-hosted Langfuse | Extra service (Postgres, ClickHouse, web app) to run and secure for a small deployment |
| Log files only | Not queryable by trace id and not access-controlled per warehouse |

## Consequences

- Traces are covered by the same backups and access rules as the rest of the
  data.
- An optional exporter can forward finished traces to Langfuse from
  `finish_trace()` if the project owner approves sending that data; the
  in-house record stays authoritative.
- The table grows with usage; a retention job (for example 90 days) should be
  added before production load.
