import type { MeResponse } from "../api/client";

export const INSTALLER_ACCESS_PERMISSIONS = [
  "project.view_assigned_installer",
  "task.view_assigned_installer",
  "works_calendar.view_assigned_installer",
  "installer_team.view_assigned_installer",
  "inventory.view_assigned_installer",
  "time_bank.view_own",
] as const;

const STAFF_SCOPE_PERMISSIONS = [
  "project.view_all",
  "project.view_own",
  "calendar.view",
  "inventory.view",
  "inventory.manage",
  "installer.manage",
  "admin.manage_users",
] as const;

export function isInstallerCollaborator(me: MeResponse | null): boolean {
  if (!me) return false;
  const hasScopedCapability = INSTALLER_ACCESS_PERMISSIONS.some((permission) => me.permissions.includes(permission));
  const hasStaffScope = STAFF_SCOPE_PERMISSIONS.some((permission) => me.permissions.includes(permission));
  return hasScopedCapability && !hasStaffScope;
}

export function hasInstallerCapability(me: MeResponse | null, permission: (typeof INSTALLER_ACCESS_PERMISSIONS)[number]): boolean {
  return Boolean(me?.permissions.includes(permission));
}
