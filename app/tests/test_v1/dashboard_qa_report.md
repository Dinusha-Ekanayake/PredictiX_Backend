# Backend QA Report — Dashboard Section

## 1. Scope and Components
- **Router Files:**
  - [`admin_dashboard.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/routers/admin_dashboard.py)
  - [`warehouse_dashboard.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/routers/warehouse_dashboard.py)
- **Service Files:**
  - [`dashboard_cache.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/services/dashboard_cache.py)

---

## 2. Automated Tests Status
- **Test File Path:** [`app/tests/qa_automated/test_dashboard.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/tests/qa_automated/test_dashboard.py)
- **Total Tests:** 2 tests (both passing).

---

## 3. Discovered Errors, Failures, and Vulnerabilities

### 🟡 Vulnerability 1: Insecure SQL Assembly via F-Strings
- **Symptoms:** None currently, but poses a code safety risk.
- **Cause:** Raw SQL is interpolated using Python f-strings rather than query-builder methods or strict bind-parameters:
  ```python
  kpi_row = db.execute(text(f"""
      SELECT ...
      WHERE {_assets_in}
  """), _wh).fetchone()
  ```
- **Impact:** If `_assets_in` were to ever receive input from request query parameters, it would expose the database to SQL injection attacks.

### 🟡 Bug 2: Cache Key Collisions for Super Admins
- **Symptoms:** Super-admins might see data from other super-admins' active scoping or experience cache bleeding.
- **Cause:** The dashboard cache relies on `warehouse_id` as the key:
  ```python
  wh_id = active_warehouse_id(current_user)
  return _cache.get_or_refresh(..., key=wh_id)
  ```
  If a super-admin does not have a scoped warehouse, `wh_id` is `None`. This maps to the same cache entry `None` for all super-admins.
- **Impact:** Bleeding of dashboard views across super-admins.

### 🟡 Performance 3: Suboptimal Queries on Large Tables
- **Symptoms:** High API latency (exceeding 2 seconds) on large prediction datasets.
- **Cause:** Aggregates use subqueries with `DISTINCT ON (asset_id) ... ORDER BY asset_id, created_at DESC`.
- **Impact:** Without a composite index on `(asset_id, created_at DESC)` in Supabase, these cause full table scans.
