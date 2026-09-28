export function workspacePath(account) {
  if (account?.can_admin) return "/dashboard";
  if (account?.can_manage) return "/dashboard";
  if (account?.has_employee_record && !account?.workspace_approved) return "/MyAccount/contract";
  return "/MyAccount";
}
