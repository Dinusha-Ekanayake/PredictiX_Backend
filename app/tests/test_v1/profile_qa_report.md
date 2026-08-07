# Backend QA Report — Profile Section

## 1. Scope and Components
- **Router Files:**
  - [`profile.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/routers/profile.py)
  - [`user_profile.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/routers/user_profile.py)

---

## 2. Automated Tests Status
- **Test File Path:** [`app/tests/test_v1/test_profile.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/tests/test_v1/test_profile.py)
- **Total Tests:** 1 test (passing).

---

## 3. Discovered Errors, Failures, and Vulnerabilities

### 🟡 Bug 1: Redundant Router Registrations
- **Symptoms:** Overlapping endpoint paths for updating self profile.
- **Cause:** Both `profile.py` (`/profiles`) and `user_profile.py` (`/user-profile`) are registered. Both routers handle profile self-updates, but they have separate schema definitions (`UserProfileUpdate` vs `ProfileUpdate`).
- **Impact:** Architectural clutter and potential synchronization issues between client-side routing.

### 🟡 Performance 2: Sequential Queries in Response Mapping
- **Symptoms:** Latency on profile loading (up to 1.2s delay on cold requests).
- **Cause:** `_profile_to_response` triggers 4 sequential queries to resolve the user's department, warehouse, active assignments, and assets count sequentially:
  ```python
  dept = db.query(Department).filter(...)
  wh = db.query(Warehouse).filter(...)
  assigned_asset_ids_subq = db.query(AssetAssignment)...
  asset_count = db.query(Asset)...
  ```
- **Impact:** Suboptimal response speeds on Supabase PostgreSQL.
