# Frontend QA Report — Helpdesk Section

## 1. Scope and Components
- **Page Files:**
  - [`help-desk/page.tsx`](file:///c:/Users/USER/Desktop/chakablast/PredictiX-Frontend/src/app/help-desk/page.tsx)

---

## 2. Code Review and Manual QA Findings

### 🟡 Issue 1: Static Category Filters vs Dynamic DB Categories
- **Symptoms:** FAQs created with custom categories via the API/DB will not match any filtering pill in the frontend.
- **Cause:** The category list is hardcoded in the frontend:
  ```typescript
  const categories = React.useMemo(() => [
    { id: "all", label: "All Topics" },
    { id: "ticket", label: "Ticket" },
    { id: "asset", label: "Asset" },
    { id: "user", label: "User" },
    { id: "warehouse", label: "Warehouse" },
    { id: "general", label: "General" },
  ], []);
  ```
  If an FAQ is inserted with a category like `"pdm"` or `"billing"`, the user cannot filter by it unless clicking "All Topics".
- **Impact:** Custom categories are unreachable via filter pills.

### 🟡 Issue 2: Role Flickering on Initial Mount
- **Symptoms:** Administrative edit/delete controls flicker visible/invisible during client hydration.
- **Cause:** `isAdmin` state reads from `localStorage` inside a standard React `useEffect`:
  ```typescript
  React.useEffect(() => {
    const r = (window.localStorage.getItem("predictix.user.role") ?? "").toLowerCase();
    setIsAdmin(r === "admin" || r === "super_admin");
  }, []);
  ```
- **Impact:** Minor layout shifts and flicker on loading.
