export function workspacePath(account) {
  if (account?.can_admin) return "/admin";
  if (account?.can_manage) return "/dashboard";
  if (account?.has_employee_record && !account?.workspace_approved) return "/MyAccount/contract";
  return "/MyAccount";
}

// The shared header link reads differently per role: an admin and an employer
// open a dashboard, an employee opens their own account.
export function workspaceLabel(account) {
  if (account?.can_admin) return "Admin dashboard";
  if (account?.can_manage) return "Dashboard";
  return "My Account";
}
