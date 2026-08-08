# Backend QA Report — Setting Section

## 1. Scope and Components
- **Router Files:**
  - [`notification_preferences.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/routers/notification_preferences.py)

---

## 2. Automated Tests Status
- **Test File Path:** [`app/tests/qa_automated/test_settings.py`](file:///c:/Users/USER/Desktop/chakablast/PredictiX_backend/app/tests/qa_automated/test_settings.py)
- **Total Tests:** 1 test (passing).

---

## 3. Discovered Errors, Failures, and Vulnerabilities

### 🔴 Bug 1: Missing Ownership Check on Preference Deletion
- **Symptoms:** Security vulnerability where users can delete other users' notification settings.
- **Cause:** `delete_user_notification_preference` only takes `preference_id` and has no logic checking if the calling user owns that preference:
  ```python
  @router.delete("/{preference_id}")
  def delete_user_notification_preference(preference_id: str, db: Session = Depends(get_db)):
      obj = db.query(UserNotificationPreference).filter(UserNotificationPreference.id == preference_id).first()
      # No ownership validation!
  ```
- **Impact:** Privilege escalation risk.

### 🟡 Bug 2: Incomplete CRUD (No Preference Update Endpoint)
- **Symptoms:** Inability to update a preference status (e.g. switching email alerts off).
- **Cause:** No `PUT` endpoint exists in `notification_preferences.py` to toggle `is_enabled`. The client is forced to delete and recreate.
- **Impact:** Clunky API usage patterns for standard setting toggles.
