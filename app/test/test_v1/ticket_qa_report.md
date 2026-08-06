# Frontend QA Report — Ticket Section

## 1. Scope and Components
- **Page Files:**
  - [`admin/tickets/page.tsx`](file:///c:/Users/USER/Desktop/chakablast/PredictiX-Frontend/src/app/\(admin\)/admin/tickets/page.tsx)
  - [`user/tickets/page.tsx`](file:///c:/Users/USER/Desktop/chakablast/PredictiX-Frontend/src/app/\(user\)/user/tickets/page.tsx)
- **Service & Utility Files:**
  - [`ticketService.ts`](file:///c:/Users/USER/Desktop/chakablast/PredictiX-Frontend/src/lib/ticketService.ts)
  - [`NewTicketDialog.tsx`](file:///c:/Users/USER/Desktop/chakablast/PredictiX-Frontend/src/components/admin/dialogs/NewTicketDialog.tsx)
  - [`TicketDetailsDialog.tsx`](file:///c:/Users/USER/Desktop/chakablast/PredictiX-Frontend/src/components/admin/dialogs/TicketDetailsDialog.tsx)

---

## 2. Code Review and Manual QA Findings

### 🟡 Bug 1: Missing Support for `pending` and `cancelled` Statuses
- **Symptoms:** Tickets with status `pending` or `cancelled` are not included in status counts or KPI cards on the dashboard and ticket list.
- **Cause:** The frontend only initializes and displays counts for four statuses: `open`, `in-progress`, `resolved`, and `closed`:
  ```typescript
  const [statusCounts, setStatusCounts] = React.useState<Record<string, number>>({ 
    open: 0, 
    "in-progress": 0, 
    resolved: 0, 
    closed: 0 
  });
  ```
- **Impact:** Any ticket set to `pending` or `cancelled` by backend processes or admins will be ignored/lost in status counts.

### 🟡 Issue 2: LocalStorage Flash on SSR
- **Symptoms:** Flickering UI role layout.
- **Cause:** Role checks read directly from `window.localStorage` inside a standard `useEffect`:
  ```typescript
  React.useEffect(() => {
    const role = window.localStorage.getItem("predictix.user.role");
    setIsAdmin(role === "admin" || role === "ADMIN");
  }, []);
  ```
- **Impact:** Since Next.js uses SSR/Static Generation, the layout compiles on the server without knowledge of `localStorage`. This leads to a flash of layout shifts when hydration completes.
