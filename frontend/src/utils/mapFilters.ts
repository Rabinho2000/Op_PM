// Filtros do mapa operacional — lógica pura, testável sem Leaflet/jsdom.
// Filtram só o que o servidor já devolveu (`attention`, contagens,
// `has_material_on_site`); nunca recalculam a regra de attention (D-058).
import type { MapAttention, MapProject } from "../api/client";

export interface MapFilters {
  search: string;
  pm: string;
  status: string;
  attention: MapAttention | "";
  onlyWithPending: boolean; // pendências abertas OU tarefas operacionais abertas
  onlyWithMaterial: boolean; // só aplicável quando material_visible
}

export const EMPTY_MAP_FILTERS: MapFilters = {
  search: "",
  pm: "",
  status: "",
  attention: "",
  onlyWithPending: false,
  onlyWithMaterial: false,
};

export function filterMapProjects(projects: MapProject[], filters: MapFilters): MapProject[] {
  const term = filters.search.trim().toLowerCase();
  return projects.filter((p) => {
    if (term && !p.name.toLowerCase().includes(term) && !(p.client_name ?? "").toLowerCase().includes(term)) {
      return false;
    }
    if (filters.pm && p.pm_display_name !== filters.pm) return false;
    if (filters.status && p.status !== filters.status) return false;
    if (filters.attention && p.attention !== filters.attention) return false;
    if (filters.onlyWithPending && p.issues_count === 0 && p.operational_tasks_count === 0) return false;
    // Sem inventory.view `has_material_on_site` é null — nunca tratado como
    // "sem material": o filtro simplesmente não é oferecido (ver Map.tsx).
    if (filters.onlyWithMaterial && p.has_material_on_site !== true) return false;
    return true;
  });
}

export function canFilterByMaterial(projects: MapProject[]): boolean {
  return projects.some((p) => p.material_visible);
}
