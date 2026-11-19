import type { Project } from "../api/client";
import type {
  ProjectListColumn,
  ProjectListConfig,
  ProjectListFilters,
  ProjectListRowOptions,
  ProjectListSortBy,
  ProjectListSortDirection,
} from "../api/projectListViews";
import { compareNatural, isSortDirection, normalizeColumnList, oneOf, sortStable } from "./listConfig";
import { IN_PROGRESS_LIFECYCLE } from "./projectFilters";

export const DEFAULT_PROJECT_LIST_COLUMNS: ProjectListColumn[] = [
  "project",
  "pm",
  "lifecycle",
  "payments",
  "progress",
  "next_task",
  "overdue",
  "warnings",
];

export const PROJECT_LIST_COLUMN_LABELS: Record<ProjectListColumn, string> = {
  project: "Projeto",
  pm: "PM",
  lifecycle: "Estado",
  payments: "Pagamentos",
  progress: "Tarefas e progresso",
  next_task: "Próxima tarefa",
  overdue: "Atrasadas",
  warnings: "Avisos",
  installer: "Instalador",
  start_date: "Início",
  power_kwp: "Potência (kWp)",
  client: "Cliente",
  address: "Morada",
  contact: "Contacto e email",
  notes: "Notas",
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
  "payments",
  "progress",
  "next_task",
  "overdue",
  "warnings",
  "installer",
  "start_date",
  "power_kwp",
  "client",
  "address",
  "contact",
  "notes",
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
  row_options: defaultProjectListRowOptions(),
});

export const defaultProjectListRowOptions = (): ProjectListRowOptions => ({
  show_row_actions: true,
  show_warning_tags: true,
  inline_controls: true,
});

const isProjectListColumn = oneOf(ALL_PROJECT_LIST_COLUMNS);
const isProjectListSortBy = oneOf(SORT_KEYS);
const isProjectListSortDirection = isSortDirection;

export function normalizeProjectListConfig(input: Partial<ProjectListConfig> | null | undefined): ProjectListConfig {
  const fallback = defaultProjectListConfig();
  const filters: Partial<ProjectListFilters> = input?.filters ?? {};
  const rowOptions: Partial<ProjectListRowOptions> = input?.row_options ?? {};
  return {
    columns: normalizeColumnList(input?.columns, ALL_PROJECT_LIST_COLUMNS, DEFAULT_PROJECT_LIST_COLUMNS),
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
    row_options: {
      show_row_actions: typeof rowOptions.show_row_actions === "boolean" ? rowOptions.show_row_actions : fallback.row_options.show_row_actions,
      show_warning_tags: typeof rowOptions.show_warning_tags === "boolean" ? rowOptions.show_warning_tags : fallback.row_options.show_warning_tags,
      inline_controls: typeof rowOptions.inline_controls === "boolean" ? rowOptions.inline_controls : fallback.row_options.inline_controls,
    },
  };
}

function compareProjectValues(a: Project, b: Project, sortBy: ProjectListSortBy): number {
  if (sortBy === "name") return compareNatural(a.name, b.name);
  if (sortBy === "power_kwp") return Number(a.power_kwp) - Number(b.power_kwp);
  return compareNatural(a[sortBy], b[sortBy]);
}

export function sortProjects(projects: Project[], sortBy: ProjectListSortBy, direction: ProjectListSortDirection): Project[] {
  return sortStable(projects, (project) => project[sortBy], (a, b) => compareProjectValues(a, b, sortBy), direction);
}
