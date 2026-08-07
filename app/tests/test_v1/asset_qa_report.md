# Backend QA Report — Asset Section

## 1. Scope and Components
- **Router Files:**
  - [`assets.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/routers/assets.py)
  - [`asset_assignments.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/routers/asset_assignments.py)
  - [`asset_component_rul.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/routers/asset_component_rul.py)
  - [`asset_documents.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/routers/asset_documents.py)
  - [`asset_reports.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/routers/asset_reports.py)
  - [`asset_status_history.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/routers/asset_status_history.py)
  - [`asset_summaries.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/routers/asset_summaries.py)

---

## 2. Automated Tests Status
- **Test File Path:** [`app/tests/test_v1/test_assets.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/tests/test_v1/test_assets.py)
- **Total Tests:** 1 test (passing).

---

## 3. Discovered Errors, Failures, and Vulnerabilities

### 🟡 Bug 1: Lack of Enum Constraints for Asset Status Updates
- **Symptoms:** Invalid statuses like "broken" or "destroyed" can be saved directly in the DB.
- **Cause:** Unlike the ticket section, which implements strict normalization and domain lists (`VALID_STATUSES`), `assets.py` lacks status constraints.
- **Impact:** Compromises data integrity and dashboard KPI reliability.

### 🟡 Performance 2: Heavy Query Join for Asset Listing
- **Symptoms:** Pagination latency on the asset list endpoint.
- **Cause:** The listing endpoint does left outer joins with `PdmBatchPrediction` to fetch the latest health scores.
- **Impact:** As prediction logs scale, this listing query becomes a performance bottleneck.
