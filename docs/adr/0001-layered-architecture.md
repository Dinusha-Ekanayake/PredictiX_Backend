# ADR-0001: Thin routers over a service layer

- Status: Accepted
- Date: 2026-11-23

## Context

Several routers held business logic directly: database queries, storage
uploads, password policy and trace visibility rules. Routers also imported
private helpers from each other (for example `maintenance.py` used
`assets._assert_asset_in_scope`). This made the logic hard to unit test without
FastAPI and coupled unrelated routers.

## Decision

Code is split into three layers:

| Layer | Location | Responsibility |
|-------|----------|----------------|
| HTTP | `app/routers/*` | Parse and validate requests (Pydantic), resolve the caller (`deps.get_current_user`), check access, map domain exceptions to HTTP status codes |
| Domain | `app/services/*_service.py`, `app/ai/*` | Business rules. Plain functions that take a SQLAlchemy `Session` and raise domain exceptions; no FastAPI imports |
| Shared access rules | `app/deps.py` | Role checks and warehouse scoping (`assert_asset_in_scope`, `scoped_warehouse_id`, `assert_can_assign`) used by every router |

Rules:

- A router never imports another router.
- A service raises its own exception types (for example
  `image_upload_service.ImageTooLarge`, `account_service.PasswordChangeRejected`)
  and the router decides the status code.
- Messages carried by domain exceptions are written to be safe to show users.

## Consequences

- Services are testable with a fake or real session and no HTTP client.
- Status-code mapping is visible in one place per endpoint.
- Older routers that still contain logic are migrated when they are next
  changed rather than in one large rewrite, to keep risk low.
