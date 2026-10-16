import { apiDelete, apiGet, apiPatch, apiPost, apiPut, ProjectStatus } from "./client";

export type ProjectListColumn =
  | "project"
  | "pm"
  | "lifecycle"
  | "progress"
  | "next_task"
  | "overdue"
  | "warnings"
  | "installer"
  | "start_date"
  | "power_kwp";

export type ProjectListSortBy = "name" | "start_date" | "power_kwp" | "created_at";
export type ProjectListSortDirection = "asc" | "desc";
export type ProjectListActiveFilter = "active" | "inactive" | "all";

export interface ProjectListFilters {
  search: string;
  status: ProjectStatus | "";
  lifecycle: string[];
  pm: string;
  active: ProjectListActiveFilter;
  startFrom: string;
  startTo: string;
}

export interface ProjectListConfig {
  columns: ProjectListColumn[];
  sort_by: ProjectListSortBy;
  sort_direction: ProjectListSortDirection;
  filters: ProjectListFilters;
}

export interface ProjectListPreferences {
  config: ProjectListConfig;
}

export interface ProjectListView {
  id: string;
  name: string;
  config: ProjectListConfig;
  created_at: string;
  updated_at: string;
}

export interface ProjectListViewInput {
  name: string;
  config: ProjectListConfig;
}

export interface ProjectListViewPatch {
  name?: string;
  config?: ProjectListConfig;
}

export const getProjectListPreferences = () => apiGet<ProjectListPreferences>("/api/me/project-list-preferences");
export const updateProjectListPreferences = (config: ProjectListConfig) =>
  apiPut<ProjectListPreferences>("/api/me/project-list-preferences", { config });

export const listProjectListViews = () => apiGet<ProjectListView[]>("/api/me/project-list-views");
export const createProjectListView = (payload: ProjectListViewInput) =>
  apiPost<ProjectListView>("/api/me/project-list-views", payload);
export const updateProjectListView = (id: string, patch: ProjectListViewPatch) =>
  apiPatch<ProjectListView>(`/api/me/project-list-views/${id}`, patch);
export const deleteProjectListView = (id: string) => apiDelete<void>(`/api/me/project-list-views/${id}`);
