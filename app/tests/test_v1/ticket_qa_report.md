# Backend QA Report — Ticket Section

## 1. Scope and Components
- **Router Files:** 
  - [`tickets.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/routers/tickets.py) (Admin/General tickets)
  - [`user_tickets.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/routers/user_tickets.py) (User-role self-service tickets)
  - [`ticket_comments.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/routers/ticket_comments.py)
  - [`ticket_attachments.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/routers/ticket_attachments.py)
  - [`ticket_status_history.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/routers/ticket_status_history.py)
  - [`ticket_summaries.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/routers/ticket_summaries.py)
- **Service Files:** 
  - [`user_ticket_service.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/services/user_ticket_service.py)

---

## 2. Automated Tests Status
- **Test File Path:** [`app/tests/user_tickets/`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/tests/user_tickets/)
- **Total Tests:** 22 unit tests.

---

## 3. Discovered Errors, Failures, and Inconsistencies

### 🔴 Bug 1: Assignee Authorization Failure (FIXED)
- **Symptoms:** The test case `test_user_can_view_ticket_when_assignee` in `test_service.py` was failing.
- **Cause:** `user_can_view_ticket` in `user_ticket_service.py` checked if `ticket.created_by == user_id` and did not allow the assignee to view/list the ticket.
- **Fix Applied:** Modified `user_can_view_ticket` and `build_user_tickets_query` to check for `ticket.created_by == user_id or ticket.assigned_to == user_id`. All 22 tests are now passing successfully.

### 🟡 Inconsistency 2: Divergent Ticket Number Formats
- **Symptoms:** Tickets created via admin endpoints have formats like `T-0001`, while user endpoints generate numbers like `TKT-2026-0001`.
- **Cause:** 
  - `tickets.py` uses `_generate_ticket_number(db)` which calculates `T-{count + 1:04d}`.
  - `user_ticket_service.py` uses `generate_ticket_number(db)` which generates `TKT-{year}-{count_this_year + 1:04d}`.
- **Impact:** Inconsistent UI display and data sorting issues.

### 🟡 Vulnerability 3: Missing Exception Handling in Admin Ticket Creation
- **Symptoms:** A DB commit failure in `create_ticket` in `tickets.py` returns an unhandled 500 error instead of a clean 400 Bad Request.
- **Cause:** No `try...except` block surrounds `db.commit()` in `tickets.py:create_ticket`, whereas `user_tickets.py` correctly wraps it in `try...except Exception as exc: db.rollback(); raise HTTPException(...)`.
