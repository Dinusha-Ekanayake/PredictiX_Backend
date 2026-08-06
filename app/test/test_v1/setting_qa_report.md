# Frontend QA Report — Setting Section

## 1. Scope and Components
- **Page Files:**
  - [`admin/settings/page.tsx`](file:///c:/Users/USER/Desktop/chakablast/PredictiX-Frontend/src/app/\(admin\)/admin/settings/page.tsx)
  - [`user/settings/page.tsx`](file:///c:/Users/USER/Desktop/chakablast/PredictiX-Frontend/src/app/\(user\)/user/settings/page.tsx)
- **API Files:**
  - [`userProfileApi.ts`](file:///c:/Users/USER/Desktop/chakablast/PredictiX-Frontend/src/lib/api/userProfileApi.ts)

---

## 2. Code Review and Manual QA Findings

### 🔴 Bug 1: Complete Bypass of Dedicated Notification Preferences Table
- **Symptoms:** The `user_notification_preferences` table in the database is never populated, and the backend `/notification-preferences` API endpoints are never called by the client settings page.
- **Cause:** The settings page saves all switches directly as a JSON payload inside the user profile's metadata:
  ```typescript
  await updateMyProfile({
    settings: {
      emailNotifications,
      criticalAlerts,
      compactView,
    },
  });
  ```
- **Impact:** Architectural waste and code rot. The dedicated table and backend router are completely unused by the application frontend.

### 🟡 Issue 2: Hardcoded/Missing Settings Options
- **Symptoms:** The UI lacks support for specific notification channels (e.g. SMS, Web Push), although the backend model has support for channel types.
