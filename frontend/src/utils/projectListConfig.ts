import type { Project } from "../api/client";
import type {
  ProjectListColumn,
  ProjectListConfig,
  ProjectListFilters,
  ProjectListSortBy,
  ProjectListSortDirection,
} from "../api/projectListViews";
import { IN_PROGRESS_LIFECYCLE } from "./projectFilters";

export const DEFAULT_PROJECT_LIST_COLUMNS: ProjectListColumn[] = [
  "project",
  "pm",
  "lifecycle",
  "progress",
  "next_task",
  "overdue",
  "warnings",
];

export const PROJECT_LIST_COLUMN_LABELS: Record<ProjectListColumn, string> = {
  project: "Projeto",
  pm: "PM",
  lifecycle: "Estado",
  progress: "Tarefas e progresso",
  next_task: "Próxima tarefa",
  overdue: "Atrasadas",
  warnings: "Avisos",
  installer: "Instalador",
  start_date: "Início",
  power_kwp: "Potência (kWp)",
};

export const PROJECT_LIST_SORT_LABELS: Record<ProjectListSortBy, string> = {
  name: "Nome do projeto",
  start_date: "Data de início",
  power_kwp: "Potência (kWp)",
  created_at: "Data de criação",
};

export const PROJECT_LIST_COLUMN_ORDER: ProjectListColumn[] = [
  "project",
  "pm",
  "lifecycle",
  "progress",
  "next_task",
  "overdue",
  "warnings",
  "installer",
  "start_date",
  "power_kwp",
];
const ALL_PROJECT_LIST_COLUMNS = PROJECT_LIST_COLUMN_ORDER;
const SORT_KEYS = Object.keys(PROJECT_LIST_SORT_LABELS) as ProjectListSortBy[];

export const defaultProjectListFilters = (): ProjectListFilters => ({
  search: "",
  status: "",
  lifecycle: [...IN_PROGRESS_LIFECYCLE],
  pm: "",
  active: "active",
  startFrom: "",
  startTo: "",
});

export const defaultProjectListConfig = (): ProjectListConfig => ({
  columns: [...DEFAULT_PROJECT_LIST_COLUMNS],
  sort_by: "name",
  sort_direction: "asc",
  filters: defaultProjectListFilters(),
});

function isProjectListColumn(value: unknown): value is ProjectListColumn {
  return typeof value === "string" && ALL_PROJECT_LIST_COLUMNS.includes(value as ProjectListColumn);
}

function isProjectListSortBy(value: unknown): value is ProjectListSortBy {
  return typeof value === "string" && SORT_KEYS.includes(value as ProjectListSortBy);
}

function isProjectListSortDirection(value: unknown): value is ProjectListSortDirection {
  return value === "asc" || value === "desc";
}

function normalizeColumns(columns: unknown): ProjectListColumn[] {
  if (!Array.isArray(columns)) return [...DEFAULT_PROJECT_LIST_COLUMNS];
  const seen = new Set<ProjectListColumn>();
  const normalized: ProjectListColumn[] = ["project"];
  seen.add("project");
  if (Array.isArray(columns)) {
    for (const value of columns) {
      if (!isProjectListColumn(value) || seen.has(value)) continue;
      seen.add(value);
      normalized.push(value);
    }
  }
  return normalized;
}

export function normalizeProjectListConfig(input: Partial<ProjectListConfig> | null | undefined): ProjectListConfig {
  const fallback = defaultProjectListConfig();
  const filters: Partial<ProjectListFilters> = input?.filters ?? {};
  return {
    columns: normalizeColumns(input?.columns),
    sort_by: isProjectListSortBy(input?.sort_by) ? input.sort_by : fallback.sort_by,
    sort_direction: isProjectListSortDirection(input?.sort_direction) ? input.sort_direction : fallback.sort_direction,
    filters: {
      search: typeof filters.search === "string" ? filters.search : fallback.filters.search,
      status: typeof filters.status === "string" ? filters.status : fallback.filters.status,
      lifecycle: Array.isArray(filters.lifecycle) ? filters.lifecycle.filter((value): value is string => typeof value === "string") : fallback.filters.lifecycle,
      pm: typeof filters.pm === "string" ? filters.pm : fallback.filters.pm,
      active: filters.active === "inactive" || filters.active === "all" || filters.active === "active" ? filters.active : fallback.filters.active,
      startFrom: typeof filters.startFrom === "string" ? filters.startFrom : fallback.filters.startFrom,
      startTo: typeof filters.startTo === "string" ? filters.startTo : fallback.filters.startTo,
    },
  };
}

function isNullishValue(value: unknown): boolean {
  return value === null || value === undefined || value === "";
}

function compareProjectValues(a: Project, b: Project, sortBy: ProjectListSortBy): number {
  const aValue = a[sortBy];
  const bValue = b[sortBy];
  const aNull = isNullishValue(aValue);
  const bNull = isNullishValue(bValue);
  if (aNull && bNull) return 0;
  if (aNull) return 1;
  if (bNull) return -1;

  if (sortBy === "name") {
    return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" });
  }
  if (sortBy === "power_kwp") return Number(a.power_kwp) - Number(b.power_kwp);
  return String(aValue).localeCompare(String(bValue), undefined, { numeric: true, sensitivity: "base" });
}

export function sortProjects(projects: Project[], sortBy: ProjectListSortBy, direction: ProjectListSortDirection): Project[] {
  return projects
    .map((project, index) => ({ project, index }))
    .sort((a, b) => {
      const compared = compareProjectValues(a.project, b.project, sortBy);
      if (compared !== 0) {
        // Nulls are deliberately kept at the end in either direction.
        const aNull = isNullishValue(a.project[sortBy]);
        const bNull = isNullishValue(b.project[sortBy]);
        if (aNull || bNull) return compared;
        return direction === "desc" ? -compared : compared;
      }
      return a.index - b.index;
    })
    .map(({ project }) => project);
}
