# Frontend QA Report — Users Section

## 1. Scope and Components
- **Page Files:**
  - [`admin/users/page.tsx`](file:///c:/Users/USER/Desktop/chakablast/PredictiX-Frontend/src/app/\(admin\)/admin/users/page.tsx)
- **Modal Components:**
  - [`AddUserDialog.tsx`](file:///c:/Users/USER/Desktop/chakablast/PredictiX-Frontend/src/components/admin/users/AddUserDialog.tsx)
  - [`EditUserDialog.tsx`](file:///c:/Users/USER/Desktop/chakablast/PredictiX-Frontend/src/components/admin/users/EditUserDialog.tsx)
  - [`ViewUserDetailsDialog.tsx`](file:///c:/Users/USER/Desktop/chakablast/PredictiX-Frontend/src/components/admin/users/ViewUserDetailsDialog.tsx)
  - [`ViewAssignedAssetsDialog.tsx`](file:///c:/Users/USER/Desktop/chakablast/PredictiX-Frontend/src/components/admin/users/ViewAssignedAssetsDialog.tsx)

---

## 2. Code Review and Manual QA Findings

### 🔴 Bug 1: Unmapped `super_admin` Role in UI Display and KPIs
- **Symptoms:** Users with the role `super_admin` display as `user` role in the table and are completely excluded from the admin/user KPI breakdowns.
- **Cause:** 
  1. `RoleBadge` only checks for `"admin"` and defaults to `"user"`:
     ```typescript
     function RoleBadge({ role }: { role: UserRole }) {
       if (role === "admin") {
         return <Badge ...>admin</Badge>;
       }
       return <Badge ...>user</Badge>;
     }
     ```
  2. `computeKpis` only filters for `admin` and `user`, ignoring `super_admin`:
     ```typescript
     const admins = users.filter((u) => u.role === "admin").length;
     const regular = users.filter((u) => u.role === "user").length;
     ```
- **Impact:** Misleading admin user counts and incorrect role representations in the administration panel.

### 🟡 Issue 2: Hardcoded Colombo coordinates or lack of location parsing in view detail
- **Symptoms:** Clicking view detail on a user might show raw coordinates or static maps.
- **Impact:** Static layout issues if the address field is empty.
