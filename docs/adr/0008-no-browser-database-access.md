# ADR-0008: No direct database access from browsers

- Status: Accepted
- Date: 2026-11-24
- Related: [ADR-0002](0002-authentication-and-authorization.md)

## Context

PredictiX authenticates users with its own JWTs (ADR-0002), not with Supabase Auth. The frontend nevertheless shipped the Supabase anon key and used it directly for:
- ticket attachment uploads to the `ticket-attachments` bucket;
- reads of `profiles`, `assets`, `warehouses` and `departments` for the ticket view.

The anon key is public. Supabase grants `anon` and `authenticated` full rights on every new table by default, and several tables carried `USING (true)` policies. Probing with the anon key showed:
- every ticket could be read, and updates and deletes were permitted;
- FAQs, which the chatbot retrieves from, could be inserted;
- internal knowledge-base articles could be read;
- attachments could be listed, uploaded, overwritten and deleted;
- SECURITY DEFINER functions were callable over `/rpc`.

The backend's own `SUPABASE_KEY` was the anon key as well, so parts of the API worked *only because* the database was open to everyone.

Because PredictiX does not use Supabase Auth, row-level security can never identify a PredictiX user (`auth.uid()` is always null). RLS therefore cannot express PredictiX's role and warehouse rules. Those rules live in the API.

## Decision

The browser never talks to the database or to storage directly. Every read and write goes through the API, which authenticates the caller and applies the role and warehouse rules.

- **Server.** The API uses its own Postgres connection (`DATABASE_URL`) or the service-role key, chosen by `app.db.supabase_client.supabase_key()`. It refuses a public key outright, and production will not start without a server key.
- **Attachments.** These are uploaded through `POST /ticket-attachments/upload` and `POST /user/tickets/{id}/attachments/upload`. The API checks access, reads the file type from its bytes, caps the size and names the object.
- **Ticket view.** Names and history come from `GET /tickets/{id}/details`.
- **Database.** Migration 016 revokes every table, sequence and function right from `anon` and `authenticated`, and changes the default privileges so new objects get none. It also drops the permissive policies, removes the open storage policy, and sets size and type limits on the buckets.
- **Verification.** `scripts/security/check_public_access.py` uses the anon key the way an attacker would, with requests that change nothing, and fails on any exposure. It runs daily in CI.

## Consequences

- A single enforcement point for authorization. RLS stays enabled on every table as defence in depth, but grants nothing to the public roles.
- Public bucket objects are still served by URL. Object names contain a random UUID, so they cannot be enumerated, but anyone holding a URL can open the file. Moving attachments to a private bucket with short-lived signed URLs is the next step if attachments become sensitive.
- Adding a table needs no extra lock-down. If a future feature truly needs browser access, it must come with Supabase Auth or signed requests and a new ADR.
