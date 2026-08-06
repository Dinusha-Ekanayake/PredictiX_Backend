# Frontend QA Report — Asset Section

## 1. Scope and Components
- **Page Files:**
  - [`admin/assets/page.tsx`](file:///c:/Users/USER/Desktop/chakablast/PredictiX-Frontend/src/app/\(admin\)/admin/assets/page.tsx)
  - [`user/assets/page.tsx`](file:///c:/Users/USER/Desktop/chakablast/PredictiX-Frontend/src/app/\(user\)/user/assets/page.tsx)
- **Service Files:**
  - [`assetService.ts`](file:///c:/Users/USER/Desktop/chakablast/PredictiX-Frontend/src/components/admin/assets/assetService.ts)

---

## 2. Code Review and Manual QA Findings

### 🔴 Bug 1: Promise.all All-or-Nothing Failure in Stats Loading
- **Symptoms:** The asset page displays empty KPI boxes and warehouse filters without showing any error messages.
- **Cause:** `loadStatsAndWarehouses` fetches all three resources in a `Promise.all` block:
  ```typescript
  const [statsData, analyticsData, whOptions] = await Promise.all([
    getAssetStats(),
    getAssetAnalytics(),
    getWarehouseOptions(),
  ]);
  ```
  If any of these three APIs fails (e.g. if the analytics endpoint returns a database error), the entire promise rejects, leaving the state variables for all three empty.
- **Impact:** Complete failure to load basic dropdowns and stats if a single secondary analytics endpoint fails.

### 🟡 Issue 2: Client-side listCache Expire Key Collision
- **Symptoms:** Filtering or changing pages can sometimes show old cached lists.
- **Cause:** The `listCache` maps query string params:
  ```typescript
  const key = params.toString();
  ```
  But `params.toString()` doesn't include the page number when checking for page limits in some places, or caching pages without keys including page index might return the same page list. (In `listAssets`, it does: `params.set("limit", String(pageSize)); params.set("offset", String((page - 1) * pageSize));` before calling `params.toString()`, so it works, but the cache expires after 15 seconds. If the data is edited on the server by another admin, the user will see stale data for 15 seconds unless they trigger a manual refresh).
