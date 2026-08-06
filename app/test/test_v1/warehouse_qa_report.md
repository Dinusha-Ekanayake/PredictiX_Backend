# Frontend QA Report — Warehouse Section

## 1. Scope and Components
- **Page Files:**
  - [`admin/warehouse/page.tsx`](file:///c:/Users/USER/Desktop/chakablast/PredictiX-Frontend/src/app/\(admin\)/admin/warehouse/page.tsx)
- **Modal Components:**
  - [`WarehouseReportModal.tsx`](file:///c:/Users/USER/Desktop/chakablast/PredictiX-Frontend/src/components/admin/warehouse/WarehouseReportModal.tsx)

---

## 2. Code Review and Manual QA Findings

### 🔴 Bug 1: Missing Authentication Token in Report Generation API Call
- **Symptoms:** Trying to generate a warehouse report from the UI fails immediately with an error (HTTP 401 Unauthorized).
- **Cause:** The `handleGenerate` function calls `fetch(REPORT_API)` without attaching the authorization header:
  ```typescript
  const res = await fetch(REPORT_API, {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
      // Missing Authorization Header!
    },
  });
  ```
  However, the backend `/warehouse-dashboard/generate-report` endpoint is part of the `warehouse_dashboard` router which is gated behind the `require_user` FastAPI dependency.
- **Impact:** Report generation fails for logged-in users because no token is sent.
- **Fix:** Update `handleGenerate` to attach the Bearer token:
  ```typescript
  const res = await fetch(REPORT_API, {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
      ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {}),
    },
  });
  ```

---

## 3. Positive Implementation Note
- Unlike other pages, `fetchData()` uses `Promise.allSettled` instead of `Promise.all`. This allows the page to load successfully even if one service fails (e.g. departments-overview failing doesn't block the summary from rendering), which is a great resilient pattern.
