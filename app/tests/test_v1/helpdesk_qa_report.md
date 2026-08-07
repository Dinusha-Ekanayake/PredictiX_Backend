# Backend QA Report — Helpdesk Section

## 1. Scope and Components
- **Router Files:**
  - [`faqs.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/routers/faqs.py)

---

## 2. Automated Tests Status
- **Test File Path:** [`app/tests/test_v1/test_helpdesk.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/tests/test_v1/test_helpdesk.py)
- **Total Tests:** 1 test (passing).

---

## 3. Discovered Errors, Failures, and Vulnerabilities

### 🟡 Bug 1: Inconsistent Client Usage (Bypassing ORM)
- **Symptoms:** FAQs are not managed by database transactions or the SQLAlchemy connection pool.
- **Cause:** The faqs router imports and calls the Supabase client directly:
  ```python
  from app.db.supabase_client import supabase
  # ...
  response = supabase.from_("faqs").select(...)
  ```
  Every other entity in the application is managed via SQLAlchemy ORM models and standard database sessions.
- **Impact:** Divergent architecture patterns, making database migrations, debugging, and testing harder to maintain.

### 🟡 Issue 2: Naive Timezone Updates
- **Symptoms:** Timezone discrepancies when updating FAQs.
- **Cause:** `update_faq` sets a naive UTC timestamp:
  ```python
  updates["updated_at"] = datetime.utcnow().isoformat()
  ```
- **Impact:** Can cause display/comparison glitches when compared against postgres timezone-aware timestamps (`timestamptz`).
