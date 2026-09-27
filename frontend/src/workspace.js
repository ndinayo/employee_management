export function workspacePath(account) {
  if (account?.can_admin) return "/admin";
  if (account?.can_manage) return "/dashboard";
  return "/account";
}
