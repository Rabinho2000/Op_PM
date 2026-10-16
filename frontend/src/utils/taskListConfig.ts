import type { Task, TaskPriority, TaskStatus } from "../api/client";
import type {
  TaskListColumn,
  TaskListConfig,
  TaskListFilters,
  TaskListSortBy,
  TaskListSortDirection,
  TaskListViewMode,
} from "../api/taskListViews";

export const DEFAULT_TASK_LIST_COLUMNS: TaskListColumn[] = [
  "task",
  "project",
  "assignee",
  "priority",
  "due_date",
  "status",
];

export const TASK_LIST_COLUMN_LABELS: Record<TaskListColumn, string> = {
  task: "Tarefa",
  project: "Projeto",
  assignee: "Responsável",
  priority: "Prioridade",
  due_date: "Prazo",
  status: "Estado",
  category: "Categoria",
  created_at: "Criada em",
};

export const TASK_LIST_COLUMN_ORDER: TaskListColumn[] = [
  "task",
  "project",
  "assignee",
  "priority",
  "due_date",
  "status",
  "category",
  "created_at",
];

export const TASK_LIST_SORT_LABELS: Record<TaskListSortBy, string> = {
  default: "Ordem do servidor",
  title: "Título da tarefa",
  due_date: "Prazo",
  priority: "Prioridade",
  created_at: "Data de criação",
  project_name: "Nome do projeto",
};

const TASK_LIST_SORT_KEYS = Object.keys(TASK_LIST_SORT_LABELS) as TaskListSortBy[];
const TASK_PRIORITY_ORDER: Record<TaskPriority, number> = { urgent: 0, high: 1, medium: 2, low: 3 };
const TASK_STATUS_KEYS: TaskStatus[] = ["todo", "in_progress", "blocked", "done", "cancelled"];
const TASK_PRIORITY_KEYS: TaskPriority[] = ["low", "medium", "high", "urgent"];

export const defaultTaskListFilters = (): TaskListFilters => ({
  project_id: "",
  assigned_to_person_id: "",
  priority: "",
  status: "",
  overdue_only: false,
});

export const defaultTaskListConfig = (): TaskListConfig => ({
  columns: [...DEFAULT_TASK_LIST_COLUMNS],
  sort_by: "default",
  sort_direction: "asc",
  view: "lista",
  filters: defaultTaskListFilters(),
});

function isTaskListColumn(value: unknown): value is TaskListColumn {
  return typeof value === "string" && TASK_LIST_COLUMN_ORDER.includes(value as TaskListColumn);
}

function isTaskListSortBy(value: unknown): value is TaskListSortBy {
  return typeof value === "string" && TASK_LIST_SORT_KEYS.includes(value as TaskListSortBy);
}

function isTaskListSortDirection(value: unknown): value is TaskListSortDirection {
  return value === "asc" || value === "desc";
}

function isTaskListViewMode(value: unknown): value is TaskListViewMode {
  return value === "lista" || value === "kanban";
}

function isTaskPriority(value: unknown): value is TaskPriority | "" {
  return value === "" || (typeof value === "string" && TASK_PRIORITY_KEYS.includes(value as TaskPriority));
}

function isTaskStatus(value: unknown): value is TaskStatus | "" {
  return value === "" || (typeof value === "string" && TASK_STATUS_KEYS.includes(value as TaskStatus));
}

function normalizeColumns(columns: unknown): TaskListColumn[] {
  if (!Array.isArray(columns)) return [...DEFAULT_TASK_LIST_COLUMNS];
  const seen = new Set<TaskListColumn>();
  const normalized: TaskListColumn[] = ["task"];
  seen.add("task");
  for (const value of columns) {
    if (!isTaskListColumn(value) || seen.has(value)) continue;
    seen.add(value);
    normalized.push(value);
  }
  return normalized;
}

export function normalizeTaskListConfig(input: Partial<TaskListConfig> | null | undefined): TaskListConfig {
  const fallback = defaultTaskListConfig();
  const filters: Partial<TaskListFilters> = input?.filters && typeof input.filters === "object" ? input.filters : {};
  return {
    columns: normalizeColumns(input?.columns),
    sort_by: isTaskListSortBy(input?.sort_by) ? input.sort_by : fallback.sort_by,
    sort_direction: isTaskListSortDirection(input?.sort_direction) ? input.sort_direction : fallback.sort_direction,
    view: isTaskListViewMode(input?.view) ? input.view : fallback.view,
    filters: {
      project_id: typeof filters.project_id === "string" ? filters.project_id : fallback.filters.project_id,
      assigned_to_person_id:
        typeof filters.assigned_to_person_id === "string" ? filters.assigned_to_person_id : fallback.filters.assigned_to_person_id,
      priority: isTaskPriority(filters.priority) ? filters.priority : fallback.filters.priority,
      status: isTaskStatus(filters.status) ? filters.status : fallback.filters.status,
      overdue_only: typeof filters.overdue_only === "boolean" ? filters.overdue_only : fallback.filters.overdue_only,
    },
  };
}

function isNullish(value: unknown): boolean {
  return value === null || value === undefined || value === "";
}

function compareNatural(a: unknown, b: unknown): number {
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

function compareTaskValues(a: Task, b: Task, sortBy: Exclude<TaskListSortBy, "default">): number {
  if (sortBy === "priority") return TASK_PRIORITY_ORDER[a.priority] - TASK_PRIORITY_ORDER[b.priority];
  if (sortBy === "title") return compareNatural(a.title || a.task_type, b.title || b.task_type);
  if (sortBy === "project_name") return compareNatural(a.project_name, b.project_name);
  if (sortBy === "due_date") return compareNatural(a.due_date, b.due_date);
  return compareNatural(a.created_at, b.created_at);
}

export function sortTasks(tasks: Task[], sortBy: TaskListSortBy, direction: TaskListSortDirection): Task[] {
  if (sortBy === "default") return [...tasks];
  return tasks
    .map((task, index) => ({ task, index }))
    .sort((left, right) => {
      const aValue = sortValue(left.task, sortBy);
      const bValue = sortValue(right.task, sortBy);
      const aNull = isNullish(aValue);
      const bNull = isNullish(bValue);
      if (aNull || bNull) {
        if (aNull && bNull) return left.index - right.index;
        return aNull ? 1 : -1;
      }
      const compared = compareTaskValues(left.task, right.task, sortBy);
      return compared === 0 ? left.index - right.index : direction === "desc" ? -compared : compared;
    })
    .map(({ task }) => task);
}

function sortValue(task: Task, sortBy: Exclude<TaskListSortBy, "default">): unknown {
  switch (sortBy) {
    case "title":
      return task.title || task.task_type;
    case "project_name":
      return task.project_name;
    case "due_date":
      return task.due_date;
    case "priority":
      return task.priority;
    case "created_at":
      return task.created_at;
  }
}
