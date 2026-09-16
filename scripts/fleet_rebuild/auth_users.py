"""Supabase Auth account management for the fleet rebuild.

**Creating an account here is not enough to log in.** This project has two
separate credential stores, and the application's own login path does not
consult this one:

* ``auth.users`` (managed here, via the GoTrue Admin API) backs
  ``profiles.id``, which is a foreign key to it, so the row must exist, and
  any Supabase-side flow.
* ``profiles.meta['password_hash']`` (a bcrypt hash written by
  ``load.set_password_hashes``) is what ``POST /auth/login`` actually verifies, see ``app/routers/auth.py::_authenticate_profile``. With no hash stored it
  falls back to the single global ``DEFAULT_PASSWORD``, so the intended
  password is silently rejected.

An account created through this module alone therefore signs in fine against
Supabase directly and still fails at the application's login screen. Always
follow account creation with ``set_password_hashes`` for the same people, and
verify with ``app.routers.auth.post_login`` rather than
:func:`verify_login` below, the latter tests Supabase, which is the store
that is *not* used.

Accounts go through the Admin API rather than being written straight into
``auth.users`` because direct inserts have to reproduce GoTrue's identity rows
exactly, and getting that subtly wrong breaks Supabase-side flows.

Creating a user fires the ``on_auth_user_created`` trigger, which inserts a
bare ``public.profiles`` row (id, email, full_name, role='user',
status='active'). That row cannot be relied on to survive the wipe, so profile
writes in ``load.py`` are an UPSERT rather than an UPDATE.
"""

from __future__ import annotations

import time
from typing import Callable, Iterable

from supabase import create_client

from .db import load_env


def client():
    env = load_env()
    return create_client(env["SUPABASE_URL"], env["SUPABASE_SERVICE_ROLE_KEY"])


def list_all_users(sb, page_size: int = 200, max_pages: int = 200) -> list:
    """Every auth user, paged.

    Stops only on an empty page. Stopping on a page shorter than ``page_size``
    would be wrong: GoTrue clamps ``per_page`` server-side, so *every* page is
    shorter than a large requested size and the loop would exit after the
    first, silently under-enumerating the directory and leaving stale accounts
    behind on a supposedly full cleanup.
    """
    users: list = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        batch = sb.auth.admin.list_users(page=page, per_page=page_size)
        if not batch:
            break
        fresh = [u for u in batch if str(u.id) not in seen]
        if not fresh:
            break
        seen.update(str(u.id) for u in fresh)
        users.extend(fresh)
    return users


def create_users(
    sb,
    roster: Iterable[dict],
    existing_by_email: dict[str, str] | None = None,
    progress: Callable[[str], None] = print,
    retries: int = 3,
) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Create each roster account; return ``({email: user_id}, failures)``.

    An email that already exists is updated in place (password, confirmation
    and metadata) rather than skipped, so a re-run converges on the intended
    state instead of leaving a stale account behind.
    """
    existing_by_email = existing_by_email or {}
    ids: dict[str, str] = {}
    failures: list[tuple[str, str]] = []
    roster = list(roster)

    for i, person in enumerate(roster, 1):
        email = person["email"]
        attrs = {
            "email": email,
            "password": person["password"],
            "email_confirm": True,
            "user_metadata": {"full_name": person["full_name"]},
        }
        for attempt in range(1, retries + 1):
            try:
                if email in existing_by_email:
                    uid = existing_by_email[email]
                    sb.auth.admin.update_user_by_id(uid, {
                        "password": person["password"],
                        "email_confirm": True,
                        "user_metadata": {"full_name": person["full_name"]},
                    })
                    ids[email] = uid
                else:
                    res = sb.auth.admin.create_user(attrs)
                    ids[email] = str(res.user.id)
                break
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                msg = str(exc)
                if "already" in msg.lower() and "registered" in msg.lower():
                    # Raced or pre-existing: resolve the id and move on.
                    try:
                        found = [u for u in list_all_users(sb) if u.email == email]
                        if found:
                            ids[email] = str(found[0].id)
                            break
                    except Exception:
                        pass
                if attempt == retries:
                    failures.append((email, msg))
                else:
                    time.sleep(1.5 * attempt)

        if i % 100 == 0 or i == len(roster):
            progress(f"  auth users {i}/{len(roster)}  created={len(ids)}  failed={len(failures)}")

    return ids, failures


def delete_users_except(
    sb, keep_ids: set[str], progress: Callable[[str], None] = print
) -> tuple[int, list[tuple[str, str]]]:
    """Hard-delete every auth user whose id is not in ``keep_ids``.

    Deleting an auth user cascades ``public.profiles`` (FK ON DELETE CASCADE),
    which in turn cascades that person's notifications, assignments and
    comments, so this is only ever run as part of a full rebuild.
    """
    users = list_all_users(sb)
    targets = [u for u in users if str(u.id) not in keep_ids]
    deleted, failures = 0, []
    for i, u in enumerate(targets, 1):
        try:
            sb.auth.admin.delete_user(str(u.id))
            deleted += 1
        except Exception as exc:  # noqa: BLE001
            failures.append((u.email or str(u.id), str(exc)))
        if i % 50 == 0 or i == len(targets):
            progress(f"  deleted {i}/{len(targets)}  ok={deleted}  failed={len(failures)}")
    return deleted, failures


def verify_login(email: str, password: str) -> tuple[bool, str]:
    """Sign in against **Supabase Auth** with the anon key.

    This proves the ``auth.users`` credential is correct. It does **not** prove
    the account can log into the application: ``POST /auth/login`` checks
    ``profiles.meta['password_hash']`` instead and never calls Supabase. A
    PASS here with no stored hash is exactly the false positive that ships a
    broken demo account. Use ``app.routers.auth.post_login`` to check the
    real path.
    """
    env = load_env()
    anon = create_client(env["SUPABASE_URL"], env["SUPABASE_KEY"])
    try:
        res = anon.auth.sign_in_with_password({"email": email, "password": password})
        ok = bool(res.session and res.session.access_token)
        anon.auth.sign_out()
        return ok, "signed in" if ok else "no session returned"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
