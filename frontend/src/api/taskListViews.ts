import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from "./client";

export type TaskListColumn =
  | "task"
  | "project"
  | "assignee"
  | "priority"
  | "due_date"
  | "status"
  | "category"
  | "created_at";

export type TaskListSortBy = "default" | "title" | "due_date" | "priority" | "created_at" | "project_name";
export type TaskListSortDirection = "asc" | "desc";
export type TaskListViewMode = "lista" | "kanban";

export interface TaskListFilters {
  project_id: string;
  assigned_to_person_id: string;
  priority: "" | "low" | "medium" | "high" | "urgent";
  status: "" | "todo" | "in_progress" | "blocked" | "done" | "cancelled";
  overdue_only: boolean;
}

export interface TaskListConfig {
  columns: TaskListColumn[];
  sort_by: TaskListSortBy;
  sort_direction: TaskListSortDirection;
  view: TaskListViewMode;
  filters: TaskListFilters;
}

export interface TaskListPreferences {
  config: TaskListConfig;
}

export interface TaskListView {
  id: string;
  name: string;
  config: TaskListConfig;
  created_at: string;
  updated_at: string;
}

export interface TaskListViewInput {
  name: string;
  config: TaskListConfig;
}

export interface TaskListViewPatch {
  name?: string;
  config?: TaskListConfig;
}

export const getTaskListPreferences = () => apiGet<TaskListPreferences>("/api/me/task-list-preferences");
export const updateTaskListPreferences = (config: TaskListConfig) =>
  apiPut<TaskListPreferences>("/api/me/task-list-preferences", { config });

export const listTaskListViews = () => apiGet<TaskListView[]>("/api/me/task-list-views");
export const createTaskListView = (payload: TaskListViewInput) =>
  apiPost<TaskListView>("/api/me/task-list-views", payload);
export const updateTaskListView = (id: string, patch: TaskListViewPatch) =>
  apiPatch<TaskListView>(`/api/me/task-list-views/${id}`, patch);
export const deleteTaskListView = (id: string) => apiDelete<void>(`/api/me/task-list-views/${id}`);
