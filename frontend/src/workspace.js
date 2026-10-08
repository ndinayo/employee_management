export function workspacePath(account) {
  if (account?.can_admin || account?.can_manage) return "/dashboard";
  if (account?.has_employee_record && !account?.workspace_approved) return "/dashboard/contract";
  return "/dashboard";
}

// The shared header link reads differently per role: an admin opens the
// platform dashboard, everyone else their own workspace dashboard.
export function workspaceLabel(account) {
  if (account?.can_admin) return "Admin dashboard";
  return "Dashboard";
}
