# Backend QA Report — Users Section

## 1. Scope and Components
- **Router Files:**
  - [`users.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/routers/users.py)
- **Schema Files:**
  - [`user_profile.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/schemas/user_profile.py)

---

## 2. Automated Tests Status
- **Test File Path:** [`app/tests/qa_automated/test_users.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/tests/qa_automated/test_users.py)
- **Total Tests:** 1 test (passing).

---

## 3. Discovered Errors, Failures, and Vulnerabilities

### 🔴 Bug 1: ThreadPool Bypasses FastAPI Dependency Injection
- **Symptoms:** Standard mock injections via `dependency_overrides` fail to mock database calls in tests.
- **Cause:** The `list_users` endpoint runs sub-queries concurrently inside a `ThreadPoolExecutor` using raw `SessionLocal()` instances rather than using the injected `db` Session:
  ```python
  def _fetch_users(scoped_wh: str | None, limit: int, offset: int) -> list[Profile]:
      with SessionLocal() as s:
          ...
  ```
- **Impact:** 
  1. Prevents mock testing (making it hard to write unit tests).
  2. Bypasses transaction boundaries, preventing rollback capability.
  3. Increased risk of database connection pool exhaustion if many concurrent requests are made.

### 🟡 Bug 2: Missing Password Strength Validation
- **Symptoms:** Weak or empty passwords can be registered.
- **Cause:** If no password is provided during user creation, a hardcoded default `"Predictix@123"` is set:
  ```python
  raw_password = (data.password or "").strip() or _default_password()
  ```
  No validation exists to ensure password complexity is met.
- **Impact:** Risk of brute-force security compromises.
