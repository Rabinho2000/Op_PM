export interface LocatedProject {
  key: string;
  projectId: string;
  name: string;
  status: string;
  lat: number;
  lon: number;
}

export const PROJECT_CLUSTER_OPTIONS = {
  maxClusterRadius: 50,
  spiderfyOnMaxZoom: true,
  zoomToBoundsOnClick: true,
} as const;

export function groupCoincidentProjects<T extends LocatedProject>(projects: readonly T[]): T[][] {
  const byPosition = new Map<string, T[]>();
  for (const project of projects) {
    const key = `${project.lat},${project.lon}`;
    const group = byPosition.get(key);
    if (group) group.push(project);
    else byPosition.set(key, [project]);
  }
  return Array.from(byPosition.values()).filter((group) => group.length > 1);
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => {
    switch (character) {
      case "&":
        return "&amp;";
      case "<":
        return "&lt;";
      case ">":
        return "&gt;";
      case '"':
        return "&quot;";
      default:
        return "&#39;";
    }
  });
}

export function buildProjectLocationPopup(projects: readonly LocatedProject[]): string {
  const entries = projects
    .map(
      (project) =>
        `<li><a href="/projects/${escapeHtml(encodeURIComponent(project.projectId))}">${escapeHtml(project.name)}</a> — <span>${escapeHtml(project.status)}</span></li>`
    )
    .join("");
  return `<ul class="map-project-location-popup">${entries}</ul>`;
}
