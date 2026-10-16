import type { LifecycleStatus, Project } from "../api/client";

/** Projects without a current catalog entry are intentionally visible together. */
export const NO_LIFECYCLE_STATUS_KEY = "__sem_estado__";

export interface ProjectLifecycleGroup {
  key: string;
  label: string;
  status: string | null;
  projects: Project[];
}

function groupKey(status: string | null, catalogCodes: Set<string>): string {
  return status && catalogCodes.has(status) ? status : NO_LIFECYCLE_STATUS_KEY;
}

/**
 * Groups the already-filtered API result by the business lifecycle state.
 *
 * The catalog controls group order and labels. Projects are never sorted here:
 * their order within a group is the chronological order returned by the API.
 * A missing or stale status remains visible in one explicit "Sem estado" group.
 */
export function groupProjectsByLifecycle(projects: Project[], statuses: LifecycleStatus[]): ProjectLifecycleGroup[] {
  const catalogCodes = new Set(statuses.map((status) => status.code));
  const groups = new Map<string, ProjectLifecycleGroup>();

  for (const project of projects) {
    const key = groupKey(project.lifecycle_status, catalogCodes);
    const status = key === NO_LIFECYCLE_STATUS_KEY ? null : key;
    const label = status ? statuses.find((item) => item.code === status)?.label ?? status : "Sem estado";
    const existing = groups.get(key);
    if (existing) {
      existing.projects.push(project);
    } else {
      groups.set(key, { key, label, status, projects: [project] });
    }
  }

  const catalogOrder = new Map(statuses.map((status, index) => [status.code, index]));
  const firstSeen = new Map<string, number>();
  [...groups.keys()].forEach((key, index) => firstSeen.set(key, index));

  return [...groups.values()].sort((a, b) => {
    const aOrder = a.key === NO_LIFECYCLE_STATUS_KEY ? Number.POSITIVE_INFINITY : (catalogOrder.get(a.key) ?? Number.POSITIVE_INFINITY);
    const bOrder = b.key === NO_LIFECYCLE_STATUS_KEY ? Number.POSITIVE_INFINITY : (catalogOrder.get(b.key) ?? Number.POSITIVE_INFINITY);
    return aOrder - bOrder || (firstSeen.get(a.key) ?? 0) - (firstSeen.get(b.key) ?? 0);
  });
}
