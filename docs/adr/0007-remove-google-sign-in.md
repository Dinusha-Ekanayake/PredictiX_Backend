# ADR-0007: Remove Google sign-in

- Status: Accepted
- Date: 2026-11-24
- Amends: [ADR-0002](0002-authentication-and-authorization.md)

## Context

PredictiX offered two ways to sign in:
- email and password, verified against a bcrypt hash in `profiles.meta`;
- Google sign-in, where the browser obtained a Supabase OAuth session and `POST /auth/google-login` exchanged it for an API token.

Accounts in PredictiX are never self-registered. Administrators create them for drivers, warehouse staff and managers, and an account is only useful once it is attached to a role and a warehouse.

The Google path had drifted:
- The login page no longer showed a Google button, but the endpoint, the `/login/callback` page and the super-admin hand-off through `sessionStorage` were still deployed.
- It needed its own configuration: a Google OAuth client, Supabase provider settings and redirect URLs for every frontend domain. It also had its own failure modes, such as an unconfirmed address or an email matching no profile.
- It was a second, live authentication entry point that nothing used.

## Decision

Remove Google sign-in completely. Email and password is the only way to sign in.

- Backend: delete `POST /auth/google-login` and its request model.
- Frontend: delete `/login/callback` and the OAuth super-admin hand-off on the login page.
- An account without a password hash cannot sign in until an administrator sets a password. The admin-set password flow already exists.

## Consequences

- One authentication path to secure, test and document, and no OAuth client or redirect URLs to maintain per deployment.
- Users who had only ever signed in with Google need an administrator to set a password for them before their next sign-in.
- Avatars saved from Google profiles remain valid URLs. The frontend still allows `*.googleusercontent.com` images so those pictures keep displaying.
- If single sign-on is needed later, it should be added as an organisation-level identity provider (OIDC/SAML) bound to provisioned accounts, under a new ADR.
