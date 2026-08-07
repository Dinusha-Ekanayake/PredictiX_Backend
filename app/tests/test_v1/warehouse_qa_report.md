# Backend QA Report — Warehouse Section

## 1. Scope and Components
- **Router Files:**
  - [`warehouses.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/routers/warehouses.py)
- **Service & Cache Files:**
  - [`reference_data_cache.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/services/reference_data_cache.py)

---

## 2. Automated Tests Status
- **Test File Path:** [`app/tests/test_v1/test_warehouses.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/tests/test_v1/test_warehouses.py)
- **Total Tests:** 2 tests (passing).

---

## 3. Discovered Errors, Failures, and Vulnerabilities

### 🟡 Bug 1: Missing Conflict Check on Creation
- **Symptoms:** Database integrity exceptions (500 errors) when trying to insert a warehouse with a duplicate code.
- **Cause:** `create_warehouse` does not perform a check on `Warehouse.code` unique constraints:
  ```python
  @router.post("/", response_model=WarehouseOut, dependencies=[Depends(require_admin)])
  def create_warehouse(payload: WarehouseCreate, db: Session = Depends(get_db)):
      obj = Warehouse(**payload.model_dump())
      db.add(obj)
      db.commit()
  ```
- **Impact:** Crashes when entering duplicate records instead of returning a user-friendly `400 Bad Request`.

### 🟡 Inconsistency 2: Half-implemented Caching
- **Symptoms:** Cache invalidation occurs on write, but the list route bypasses the cache entirely.
- **Cause:** `create_warehouse` calls `invalidate_warehouse_names()`, but `list_warehouses` executes a direct DB query:
  ```python
  db.query(Warehouse).order_by(Warehouse.name).offset(offset).limit(limit).all()
  ```
- **Impact:** Decreased efficiency; listing queries hit the DB on every single call even though reference data is largely static.
