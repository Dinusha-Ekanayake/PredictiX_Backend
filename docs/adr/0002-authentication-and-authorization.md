# ADR-0002: Authentication and authorization model

- Status: Accepted
- Date: 2026-11-23

## Context

The API serves three roles (user, admin, super admin) across several
warehouses. Earlier versions accepted a shared default password, issued tokens
without required claims, let admins grant roles above their own and allowed
some cross-warehouse reads by id.

## Decision

**Authentication**

- Passwords are stored as bcrypt hashes in `profiles.meta.password_hash`
  (`app/core/security.py`). There is no default-password path.
- The API issues its own HS256 JWT (PyJWT). `decode_token` requires `exp` and
  `sub`; anything else raises `InvalidTokenError` and becomes a 401.
- Token lifetime is 8 hours (`ACCESS_TOKEN_TTL_MINUTES=480`), chosen to cover a
  working shift without refresh tokens.
- Google sign-in goes through Supabase OAuth; the backend only accepts it once
  the Supabase session confirms a Google identity for that email.
- Demo accounts exist behind an environment flag (on by default for the
  coursework demo) and can be turned off in production.
- Login is rate limited per IP and per email (`app/core/rate_limit.py`); AI
  and report endpoints have their own limits.

**Authorization**

- Every protected route depends on `get_current_user`; role gates are
  `require_user`, `require_admin`, `require_super_admin` in `app/deps.py`.
- Data is scoped by warehouse. Users see their own records, admins see their
  active warehouse, super admins see all or the warehouse they selected.
  Objects fetched by id are checked with `assert_*_in_scope` and return 404
  (not 403) when outside scope, so ids cannot be probed.
- Admins cannot create or promote accounts above their own role or move users
  out of their warehouse (`assert_can_assign`).
- The frontend guards (`AuthGuard`, `RouteGuard`) are for user experience
  only; the API is the enforcement point.

## Alternatives considered

- **Supabase Auth for all logins with RLS.** Rejected for now: the backend
  connects as the table owner (RLS bypassed) and the existing user base uses
  backend-issued tokens. Moving would change every client.
- **Refresh tokens with short access tokens.** Deferred; adds storage and
  rotation logic not needed at the current scale.

## Consequences

- `app/tests/integration/test_authorization_matrix.py` checks each role
  against each sensitive endpoint and must pass before release.
- The JWT lives in `localStorage` on the frontend, so a strict CSP matters.
  The CSP currently runs in report-only mode and should be enforced once the
  reports are clean.
