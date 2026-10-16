import { DragEvent, ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ApiError,
  DEFAULT_TASK_TYPE_LABELS,
  listPeople,
  listProjects,
  listTasks,
  Person,
  Project,
  Task,
  TASK_ALLOWED_NEXT_STATUSES,
  TASK_CATEGORY_LABELS,
  TASK_PRIORITY_LABELS,
  TASK_STATUS_LABELS,
  TaskFilters,
  TaskPriority,
  TaskStatus,
} from "../api/client";
import {
  createTaskListView,
  deleteTaskListView,
  getTaskListPreferences,
  listTaskListViews,
  TaskListColumn,
  TaskListConfig,
  TaskListFilters,
  TaskListView,
  updateTaskListPreferences,
  updateTaskListView,
} from "../api/taskListViews";
import Icon from "../components/Icon";
import TaskFormModal from "../components/TaskForm";
import TaskStatusControl, { useTaskStatusChange } from "../components/TaskStatusControl";
import { useToast } from "../components/Toast";
import { Avatar, Badge, EmptyState, ErrorState, LoadingState, PageHeader } from "../components/ui";
import { useSession } from "../session/SessionContext";
import { formatDatePt, formatDateTimePt, relativeDayLabel, todayIsoLisbon } from "../utils/dates";
import { TASK_PRIORITY_TONES, TASK_STATUS_TONES, TASK_TYPE_ICONS } from "../utils/labels";
import {
  DEFAULT_TASK_LIST_COLUMNS,
  defaultTaskListConfig,
  normalizeTaskListConfig,
  TASK_LIST_COLUMN_LABELS,
  TASK_LIST_COLUMN_ORDER,
  TASK_LIST_SORT_LABELS,
  sortTasks,
} from "../utils/taskListConfig";
import "./Tasks.css";

const ALL_STATUSES: TaskStatus[] = ["todo", "in_progress", "blocked", "done", "cancelled"];
const PRIORITIES: TaskPriority[] = ["urgent", "high", "medium", "low"];
const KANBAN_PAGE = 20;
const TASK_LIST_QUERY_KEYS = [
  "project_id",
  "assigned_to_person_id",
  "priority",
  "prioridade",
  "overdue_only",
  "atrasadas",
  "status",
  "view",
  "sort_by",
  "sort_direction",
  "columns",
] as const;

type View = "lista" | "kanban";

type TaskListFilterPatch = Partial<TaskListFilters>;

function taskLabel(t: Task): string {
  return t.task_type === "custom" ? t.title : DEFAULT_TASK_TYPE_LABELS[t.task_type] ?? t.title;
}

function errorDetail(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

function parseTaskPriority(value: string | null): TaskPriority | "" {
  return PRIORITIES.includes(value as TaskPriority) ? (value as TaskPriority) : "";
}

function parseTaskStatus(value: string | null): TaskStatus | "" {
  return ALL_STATUSES.includes(value as TaskStatus) ? (value as TaskStatus) : "";
}

function hasTaskListQuery(params: URLSearchParams): boolean {
  return TASK_LIST_QUERY_KEYS.some((key) => params.has(key));
}

export function taskConfigFromUrl(params: URLSearchParams): TaskListConfig {
  const fallback = defaultTaskListConfig();
  const rawColumns = params.getAll("columns");
  const rawView = params.get("view");
  const rawSort = params.get("sort_by");
  const rawDirection = params.get("sort_direction");
  const rawPriority = params.get("priority") ?? params.get("prioridade");
  const rawOverdue = params.get("overdue_only") ?? params.get("atrasadas");
  return normalizeTaskListConfig({
    ...fallback,
    columns: rawColumns.length > 0 ? (rawColumns as TaskListConfig["columns"]) : fallback.columns,
    sort_by: rawSort as TaskListConfig["sort_by"],
    sort_direction: rawDirection as TaskListConfig["sort_direction"],
    view: rawView as View,
    filters: {
      ...fallback.filters,
      project_id: params.get("project_id") ?? "",
      assigned_to_person_id: params.get("assigned_to_person_id") ?? "",
      priority: parseTaskPriority(rawPriority),
      status: parseTaskStatus(params.get("status")),
      overdue_only: rawOverdue === "1" || rawOverdue === "true",
    },
  });
}

export function taskParamsForConfig(params: URLSearchParams, config: TaskListConfig): URLSearchParams {
  const next = new URLSearchParams(params);
  for (const key of TASK_LIST_QUERY_KEYS) next.delete(key);
  const fallback = defaultTaskListConfig();
  const filters = config.filters;
  if (filters.project_id) next.set("project_id", filters.project_id);
  if (filters.assigned_to_person_id) next.set("assigned_to_person_id", filters.assigned_to_person_id);
  if (filters.priority) next.set("prioridade", filters.priority);
  if (filters.overdue_only) next.set("atrasadas", "1");
  if (filters.status) next.set("status", filters.status);
  if (config.view !== fallback.view) next.set("view", config.view);
  if (config.sort_by !== fallback.sort_by) next.set("sort_by", config.sort_by);
  if (config.sort_direction !== fallback.sort_direction) next.set("sort_direction", config.sort_direction);
  if (JSON.stringify(config.columns) !== JSON.stringify(fallback.columns)) {
    config.columns.forEach((column) => next.append("columns", column));
  }
  return next;
}

function taskFiltersForApi(config: TaskListConfig): TaskFilters {
  return {
    project_id: config.filters.project_id || undefined,
    assigned_to_person_id: config.filters.assigned_to_person_id || undefined,
    priority: config.filters.priority || undefined,
    overdue_only: config.filters.overdue_only || undefined,
    // Published behavior: status is retained in config but is not a Kanban filter.
    status: config.view === "lista" ? config.filters.status || undefined : undefined,
  };
}

function ColumnConfigurator({
  columns,
  onChange,
  onRestore,
}: {
  columns: TaskListColumn[];
  onChange: (columns: TaskListColumn[]) => void;
  onRestore: () => void;
}) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const close = () => {
    setOpen(false);
    triggerRef.current?.focus();
  };

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) close();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const toggleColumn = (column: TaskListColumn, checked: boolean) => {
    if (column === "task") return;
    if (checked) onChange(columns.includes(column) ? columns : [...columns, column]);
    else onChange(columns.filter((current) => current !== column));
  };

  const moveColumn = (column: TaskListColumn, offset: -1 | 1) => {
    const index = columns.indexOf(column);
    const target = index + offset;
    if (index < 0 || target < 0 || target >= columns.length) return;
    const next = [...columns];
    [next[index], next[target]] = [next[target], next[index]];
    if (next[0] !== "task") return;
    onChange(next);
  };

  return (
    <div ref={containerRef} className="tasks-list__column-menu">
      <button
        ref={triggerRef}
        type="button"
        className="btn btn--sm btn--ghost"
        aria-expanded={open}
        aria-controls="task-list-column-dialog"
        onClick={() => setOpen((current) => !current)}
      >
        Colunas
      </button>
      {open && (
        <div id="task-list-column-dialog" className="tasks-list__column-dialog" role="dialog" aria-label="Configurar colunas">
          <div className="tasks-list__column-dialog-header">
            <strong>Colunas visíveis na Lista</strong>
            <button type="button" className="btn btn--sm btn--ghost" onClick={close}>
              Fechar configuração de colunas
            </button>
          </div>
          <div className="tasks-list__column-options">
            {TASK_LIST_COLUMN_ORDER.map((column) => {
              const index = columns.indexOf(column);
              const visible = index >= 0;
              const label = TASK_LIST_COLUMN_LABELS[column];
              return (
                <div key={column} className="tasks-list__column-option">
                  <label className="checkbox">
                    <input
                      type="checkbox"
                      aria-label={`Mostrar ${label}`}
                      checked={visible}
                      disabled={column === "task"}
                      onChange={(event) => toggleColumn(column, event.target.checked)}
                    />
                    {label}
                    {column === "task" && <span className="small muted">obrigatória</span>}
                  </label>
                  {visible && (
                    <span className="tasks-list__column-order">
                      <button
                        type="button"
                        className="btn btn--sm btn--ghost"
                        aria-label={`Subir coluna ${label}`}
                        disabled={index === 0}
                        onClick={() => moveColumn(column, -1)}
                      >
                        ↑
                      </button>
                      <button
                        type="button"
                        className="btn btn--sm btn--ghost"
                        aria-label={`Descer coluna ${label}`}
                        disabled={index === columns.length - 1}
                        onClick={() => moveColumn(column, 1)}
                      >
                        ↓
                      </button>
                    </span>
                  )}
                </div>
              );
            })}
          </div>
          <button type="button" className="btn btn--sm btn--ghost" onClick={onRestore}>
            Restaurar colunas padrão
          </button>
        </div>
      )}
    </div>
  );
}

function TaskCard({
  task,
  today,
  busy,
  highlight,
  onStatusChange,
}: {
  task: Task;
  today: string;
  busy: boolean;
  highlight: boolean;
  onStatusChange: (task: Task, status: TaskStatus) => void;
}) {
  const classes = [
    "task-card",
    task.is_overdue ? "task-card--overdue" : task.priority === "urgent" ? "task-card--urgent" : "",
    task.status === "done" ? "task-card--done" : "",
    highlight ? "just-done" : "",
  ].join(" ");

  return (
    <article
      className={classes}
      draggable={task.can_edit}
      onDragStart={(e) => {
        e.dataTransfer.setData("text/plain", task.id);
        e.dataTransfer.effectAllowed = "move";
      }}
      aria-label={taskLabel(task)}
      data-testid={`task-card-${task.id}`}
    >
      <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
        <Icon name={TASK_TYPE_ICONS[task.task_type] ?? "tasks"} size={16} className="muted" />
        <div style={{ minWidth: 0 }}>
          <div className="task-card__title">{taskLabel(task)}</div>
          <Link className="task-card__project" to={`/projects/${task.project_id}`}>
            {task.project_name ?? "—"}
          </Link>
        </div>
      </div>
      <div className="badges">
        <Badge tone={TASK_PRIORITY_TONES[task.priority]}>{TASK_PRIORITY_LABELS[task.priority]}</Badge>
        {task.is_overdue && <Badge tone="danger">Atrasada</Badge>}
      </div>
      <div className="task-card__foot">
        <span className={`small ${task.is_overdue ? "text-danger" : "muted"}`}>
          <Icon name="clock" size={12} /> {task.due_date ? relativeDayLabel(task.due_date, today) : "sem prazo"}
        </span>
        {task.assigned_to_display_name ? (
          <Avatar name={task.assigned_to_display_name} small />
        ) : (
          <span className="small muted">sem responsável</span>
        )}
      </div>
      <TaskStatusControl task={task} busy={busy} onChange={onStatusChange} />
    </article>
  );
}

function renderTaskCell(
  column: TaskListColumn,
  task: Task,
  today: string,
  busy: boolean,
  onStatusChange: (task: Task, status: TaskStatus) => void,
): ReactNode {
  switch (column) {
    case "task":
      return (
        <>
          <span className="cell-title" style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
            <Icon name={TASK_TYPE_ICONS[task.task_type] ?? "tasks"} size={15} className="muted" />
            {taskLabel(task)}
          </span>
          {task.status === "done" && (
            <span className="cell-sub" style={{ color: "var(--success)" }}>
              <Icon name="check" size={12} /> concluída
            </span>
          )}
        </>
      );
    case "project":
      return <Link to={`/projects/${task.project_id}`}>{task.project_name ?? "—"}</Link>;
    case "assignee":
      return task.assigned_to_display_name ? (
        <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
          <Avatar name={task.assigned_to_display_name} small />
          {task.assigned_to_display_name}
        </span>
      ) : (
        <span className="muted">—</span>
      );
    case "priority":
      return <Badge tone={TASK_PRIORITY_TONES[task.priority]}>{TASK_PRIORITY_LABELS[task.priority]}</Badge>;
    case "due_date":
      return (
        <>
          <span className={task.is_overdue ? "text-danger" : undefined}>{formatDatePt(task.due_date)}</span>
          {task.due_date && (
            <span className={`cell-sub ${task.is_overdue ? "text-danger" : ""}`}>
              {task.is_overdue ? "atrasada · " : ""}
              {relativeDayLabel(task.due_date, today)}
            </span>
          )}
        </>
      );
    case "status":
      return <TaskStatusControl task={task} busy={busy} onChange={onStatusChange} />;
    case "category":
      return TASK_CATEGORY_LABELS[task.category] ?? task.category;
    case "created_at":
      return formatDateTimePt(task.created_at);
  }
}

export default function Tasks() {
  const { me } = useSession();
  const [params, setParams] = useSearchParams();
  const { notify } = useToast();
  const accountKey = me?.user_id ?? me?.email ?? "anonymous";
  const accountKeyRef = useRef(accountKey);
  accountKeyRef.current = accountKey;
  const paramsRef = useRef(params);
  paramsRef.current = params;
  const initialUrlView = hasTaskListQuery(params);
  const [config, setConfig] = useState<TaskListConfig>(() => (initialUrlView ? taskConfigFromUrl(params) : defaultTaskListConfig()));
  const configRef = useRef(config);
  configRef.current = config;
  const [viewReady, setViewReady] = useState(initialUrlView);
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [justDone, setJustDone] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<TaskStatus | null>(null);
  const [expanded, setExpanded] = useState<Partial<Record<TaskStatus, boolean>>>({});
  const [reloadKey, setReloadKey] = useState(0);
  const [preferenceStatus, setPreferenceStatus] = useState<"loading" | "ready" | "error">(initialUrlView ? "ready" : "loading");
  const [preferenceError, setPreferenceError] = useState<string | null>(null);
  const [preferenceSaveError, setPreferenceSaveError] = useState<string | null>(null);
  const [preferenceSaving, setPreferenceSaving] = useState(false);
  const [preferenceSaved, setPreferenceSaved] = useState(false);
  const [preferenceReloadKey, setPreferenceReloadKey] = useState(0);
  const [savedViews, setSavedViews] = useState<TaskListView[]>([]);
  const [savedViewsLoading, setSavedViewsLoading] = useState(true);
  const [savedViewsError, setSavedViewsError] = useState<string | null>(null);
  const [savedViewsActionError, setSavedViewsActionError] = useState<string | null>(null);
  const [savedViewsSaving, setSavedViewsSaving] = useState(false);
  const [savedViewsManagingId, setSavedViewsManagingId] = useState<string | null>(null);
  const [selectedSavedViewId, setSelectedSavedViewId] = useState("");
  const [savedViewsReloadKey, setSavedViewsReloadKey] = useState(0);
  const userInteracted = useRef(false);
  const preferenceAccountRef = useRef<string | null>(null);
  const preferenceRequestRef = useRef(0);
  const taskRequestRef = useRef(0);
  const lastObservedParams = useRef(params.toString());

  useEffect(() => {
    let cancelled = false;
    const requestAccountKey = accountKey;
    listPeople().then((result) => {
      if (!cancelled && accountKeyRef.current === requestAccountKey) setPeople(result);
    }).catch(() => {
      if (!cancelled && accountKeyRef.current === requestAccountKey) setPeople([]);
    });
    listProjects({ is_active: true }).then((result) => {
      if (!cancelled && accountKeyRef.current === requestAccountKey) setProjects(result);
    }).catch(() => {
      if (!cancelled && accountKeyRef.current === requestAccountKey) setProjects([]);
    });
    return () => {
      cancelled = true;
    };
  }, [accountKey]);

  useEffect(() => {
    const signature = params.toString();
    if (signature === lastObservedParams.current) return;
    lastObservedParams.current = signature;
    userInteracted.current = true;
    const next = hasTaskListQuery(params) ? taskConfigFromUrl(params) : defaultTaskListConfig();
    configRef.current = next;
    setConfig(next);
    setViewReady(true);
    setPreferenceSaved(false);
  }, [params]);

  useEffect(() => {
    let cancelled = false;
    const requestId = ++preferenceRequestRef.current;
    const requestAccountKey = accountKey;
    const currentParams = paramsRef.current;
    const explicitUrl = hasTaskListQuery(currentParams);
    const accountChanged = preferenceAccountRef.current !== accountKey;
    if (accountChanged) {
      preferenceAccountRef.current = accountKey;
      userInteracted.current = false;
      const next = explicitUrl ? taskConfigFromUrl(currentParams) : defaultTaskListConfig();
      configRef.current = next;
      setConfig(next);
      setViewReady(explicitUrl);
    }
    setPreferenceStatus("loading");
    setPreferenceError(null);
    getTaskListPreferences()
      .then((response) => {
        if (cancelled || requestId !== preferenceRequestRef.current || accountKeyRef.current !== requestAccountKey) return;
        if (!explicitUrl && !userInteracted.current) {
          const next = normalizeTaskListConfig(response.config);
          configRef.current = next;
          setConfig(next);
        }
        setViewReady(true);
        setPreferenceStatus("ready");
      })
      .catch((reason) => {
        if (cancelled || requestId !== preferenceRequestRef.current || accountKeyRef.current !== requestAccountKey) return;
        setViewReady(true);
        setPreferenceStatus("error");
        setPreferenceError(errorDetail(reason, "Não foi possível carregar a preferência de abertura."));
      });
    return () => {
      cancelled = true;
    };
  }, [accountKey, preferenceReloadKey]);

  useEffect(() => {
    let cancelled = false;
    const requestAccountKey = accountKey;
    setSavedViews([]);
    setSelectedSavedViewId("");
    setSavedViewsLoading(true);
    setSavedViewsError(null);
    listTaskListViews()
      .then((views) => {
        if (!cancelled && accountKeyRef.current === requestAccountKey) setSavedViews(views);
      })
      .catch((reason) => {
        if (!cancelled && accountKeyRef.current === requestAccountKey) setSavedViewsError(errorDetail(reason, "Não foi possível carregar as vistas pessoais."));
      })
      .finally(() => {
        if (!cancelled && accountKeyRef.current === requestAccountKey) setSavedViewsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [accountKey, savedViewsReloadKey]);

  const filters = config.filters;
  const view = config.view;
  const accountReady = preferenceAccountRef.current === accountKey;
  const filterSignature = `${filters.project_id}|${filters.assigned_to_person_id}|${filters.priority}|${filters.status}|${filters.overdue_only}`;

  const load = useCallback(() => {
    const requestId = ++taskRequestRef.current;
    const requestAccountKey = accountKeyRef.current;
    const activeConfig = normalizeTaskListConfig(configRef.current);
    setError(null);
    setTasks(null);
    listTasks(taskFiltersForApi(activeConfig))
      .then((result) => {
        if (requestId === taskRequestRef.current && accountKeyRef.current === requestAccountKey) setTasks(result);
      })
      .catch((reason) => {
        if (requestId === taskRequestRef.current && accountKeyRef.current === requestAccountKey) {
          setError(errorDetail(reason, "Não foi possível contactar o servidor."));
        }
      });
  }, []);

  useEffect(() => {
    if (!viewReady || !accountReady) return;
    load();
  }, [accountReady, config.view, filterSignature, load, reloadKey, viewReady]);

  const sortedTasks = useMemo(
    () => sortTasks(tasks ?? [], config.sort_by, config.sort_direction),
    [config.sort_by, config.sort_direction, tasks]
  );

  const { change, busyId } = useTaskStatusChange(
    useCallback(
      (updated: Task) => {
        if (updated.status === "done") {
          setJustDone(updated.id);
          window.setTimeout(() => setJustDone(null), 1200);
        }
        setTasks((current) => current?.map((task) => (task.id === updated.id ? updated : task)) ?? null);
        load();
      },
      [load]
    )
  );

  function commitConfig(next: TaskListConfig | ((current: TaskListConfig) => TaskListConfig)) {
    const normalized = normalizeTaskListConfig(typeof next === "function" ? next(configRef.current) : next);
    configRef.current = normalized;
    userInteracted.current = true;
    setConfig(normalized);
    setViewReady(true);
    setPreferenceSaved(false);
    const nextParams = taskParamsForConfig(paramsRef.current, normalized);
    if (nextParams.toString() !== paramsRef.current.toString()) setParams(nextParams);
  }

  const updateFilters = (patch: TaskListFilterPatch) =>
    commitConfig((current) => ({ ...current, filters: { ...current.filters, ...patch } }));

  function handleDrop(e: DragEvent, status: TaskStatus) {
    e.preventDefault();
    setDropTarget(null);
    const id = e.dataTransfer.getData("text/plain");
    const task = tasks?.find((candidate) => candidate.id === id);
    if (!task || task.status === status) return;
    if (!task.can_edit) {
      notify("Não tem permissão para alterar esta tarefa.", "error");
      return;
    }
    if (!TASK_ALLOWED_NEXT_STATUSES[task.status].includes(status)) {
      notify(
        `Não é possível passar de “${TASK_STATUS_LABELS[task.status]}” para “${TASK_STATUS_LABELS[status]}”.`,
        "error"
      );
      return;
    }
    void change(task, status);
  }

  const today = todayIsoLisbon();
  const canCreate = projects.some((project) => project.can_manage_tasks);
  const hasFilters = Boolean(filters.project_id || filters.assigned_to_person_id || filters.priority || filters.status || filters.overdue_only);
  const clearFilters = () => updateFilters(defaultTaskListConfig().filters);

  async function handleSavePreferences() {
    const actionAccountKey = accountKey;
    setPreferenceSaving(true);
    setPreferenceSaveError(null);
    setPreferenceSaved(false);
    try {
      await updateTaskListPreferences(normalizeTaskListConfig(configRef.current));
      if (accountKeyRef.current === actionAccountKey) {
        setPreferenceSaved(true);
        notify("Preferência de abertura guardada.", "success");
      }
    } catch (reason) {
      if (accountKeyRef.current === actionAccountKey) setPreferenceSaveError(errorDetail(reason, "Não foi possível guardar a preferência de abertura."));
    } finally {
      if (accountKeyRef.current === actionAccountKey) setPreferenceSaving(false);
    }
  }

  async function handleCreateSavedView() {
    const enteredName = window.prompt("Nome da vista:");
    const name = enteredName?.trim();
    if (!name) {
      if (enteredName !== null) setSavedViewsActionError("Introduza um nome para guardar a vista.");
      return;
    }
    const actionAccountKey = accountKey;
    setSavedViewsActionError(null);
    setSavedViewsSaving(true);
    try {
      const savedView = await createTaskListView({ name, config: normalizeTaskListConfig(configRef.current) });
      if (accountKeyRef.current !== actionAccountKey) return;
      setSavedViews((current) => [...current, savedView]);
      setSelectedSavedViewId(savedView.id);
      notify("Vista pessoal guardada.", "success");
    } catch (reason) {
      if (accountKeyRef.current === actionAccountKey) setSavedViewsActionError(errorDetail(reason, "Não foi possível guardar a vista pessoal."));
    } finally {
      if (accountKeyRef.current === actionAccountKey) setSavedViewsSaving(false);
    }
  }

  const selectedSavedView = savedViews.find((candidate) => candidate.id === selectedSavedViewId);

  function handleApplySavedView() {
    if (!selectedSavedView) return;
    setSavedViewsActionError(null);
    commitConfig(normalizeTaskListConfig(selectedSavedView.config));
    notify("Vista aplicada.", "success");
  }

  async function handleUpdateSavedView() {
    if (!selectedSavedView) return;
    const actionAccountKey = accountKey;
    setSavedViewsActionError(null);
    setSavedViewsManagingId(selectedSavedView.id);
    try {
      const updated = await updateTaskListView(selectedSavedView.id, { config: normalizeTaskListConfig(configRef.current) });
      if (accountKeyRef.current !== actionAccountKey) return;
      setSavedViews((current) => current.map((candidate) => (candidate.id === updated.id ? updated : candidate)));
      notify("Vista pessoal atualizada.", "success");
    } catch (reason) {
      if (accountKeyRef.current === actionAccountKey) setSavedViewsActionError(errorDetail(reason, "Não foi possível atualizar a vista pessoal."));
    } finally {
      if (accountKeyRef.current === actionAccountKey) setSavedViewsManagingId(null);
    }
  }

  async function handleRenameSavedView() {
    if (!selectedSavedView) return;
    const enteredName = window.prompt("Novo nome da vista:", selectedSavedView.name);
    const name = enteredName?.trim();
    if (!name) {
      if (enteredName !== null) setSavedViewsActionError("Introduza um nome para a vista.");
      return;
    }
    const actionAccountKey = accountKey;
    setSavedViewsActionError(null);
    setSavedViewsManagingId(selectedSavedView.id);
    try {
      const updated = await updateTaskListView(selectedSavedView.id, { name });
      if (accountKeyRef.current !== actionAccountKey) return;
      setSavedViews((current) => current.map((candidate) => (candidate.id === updated.id ? updated : candidate)));
      notify("Vista pessoal renomeada.", "success");
    } catch (reason) {
      if (accountKeyRef.current === actionAccountKey) setSavedViewsActionError(errorDetail(reason, "Não foi possível renomear a vista pessoal."));
    } finally {
      if (accountKeyRef.current === actionAccountKey) setSavedViewsManagingId(null);
    }
  }

  async function handleDeleteSavedView() {
    if (!selectedSavedView || !window.confirm(`Eliminar a vista «${selectedSavedView.name}»?`)) return;
    const actionAccountKey = accountKey;
    const id = selectedSavedView.id;
    setSavedViewsActionError(null);
    setSavedViewsManagingId(id);
    try {
      await deleteTaskListView(id);
      if (accountKeyRef.current !== actionAccountKey) return;
      setSavedViews((current) => current.filter((candidate) => candidate.id !== id));
      setSelectedSavedViewId("");
      notify("Vista pessoal eliminada.", "success");
    } catch (reason) {
      if (accountKeyRef.current === actionAccountKey) setSavedViewsActionError(errorDetail(reason, "Não foi possível eliminar a vista pessoal."));
    } finally {
      if (accountKeyRef.current === actionAccountKey) setSavedViewsManagingId(null);
    }
  }

  return (
    <div className="tasks-page">
      <PageHeader
        title="Tarefas"
        subtitle="Acompanhe prazos, prioridades e responsáveis de todas as tarefas visíveis ao seu perfil."
        actions={
          <>
            <div className="segmented" role="group" aria-label="Modo de visualização">
              <button type="button" aria-pressed={view === "lista"} onClick={() => commitConfig((current) => ({ ...current, view: "lista" }))}>
                <Icon name="list" size={16} /> Lista
              </button>
              <button type="button" aria-pressed={view === "kanban"} onClick={() => commitConfig((current) => ({ ...current, view: "kanban" }))}>
                <Icon name="columns" size={16} /> Kanban
              </button>
            </div>
            {canCreate && (
              <button type="button" className="btn btn--primary" onClick={() => setCreating(true)}>
                <Icon name="plus" size={16} /> Nova tarefa
              </button>
            )}
          </>
        }
      />

      {preferenceError && (
        <div className="tasks-list__preference-alert" role="alert">
          <span>Preferência de abertura indisponível: {preferenceError}</span>
          <button type="button" className="btn btn--sm btn--ghost" onClick={() => setPreferenceReloadKey((key) => key + 1)}>
            Tentar carregar preferência
          </button>
        </div>
      )}
      {preferenceSaveError && (
        <div className="tasks-list__preference-alert" role="alert">
          <span>{preferenceSaveError}</span>
          <button type="button" className="btn btn--sm btn--ghost" onClick={handleSavePreferences} disabled={preferenceSaving}>
            Tentar guardar
          </button>
        </div>
      )}

      <form className="toolbar" aria-label="Filtros de tarefas" onSubmit={(event) => event.preventDefault()}>
        <div className="field field--wide">
          <label htmlFor="tf-project">Projeto</label>
          <select id="tf-project" className="select" value={filters.project_id} onChange={(event) => updateFilters({ project_id: event.target.value })}>
            <option value="">Todos os projetos</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="tf-assignee">Responsável</label>
          <select id="tf-assignee" className="select" value={filters.assigned_to_person_id} onChange={(event) => updateFilters({ assigned_to_person_id: event.target.value })}>
            <option value="">Todos</option>
            {people.map((person) => (
              <option key={person.id} value={person.id}>
                {person.display_name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="tf-priority">Prioridade</label>
          <select id="tf-priority" className="select" value={filters.priority} onChange={(event) => updateFilters({ priority: event.target.value as TaskPriority | "" })}>
            <option value="">Todas</option>
            {PRIORITIES.map((priority) => (
              <option key={priority} value={priority}>
                {TASK_PRIORITY_LABELS[priority]}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="tf-status">Estado</label>
          <select
            id="tf-status"
            className="select"
            value={filters.status}
            disabled={view === "kanban"}
            aria-describedby={view === "kanban" ? "tf-status-help" : undefined}
            onChange={(event) => updateFilters({ status: event.target.value as TaskStatus | "" })}
          >
            <option value="">Todos</option>
            {ALL_STATUSES.map((status) => (
              <option key={status} value={status}>
                {TASK_STATUS_LABELS[status]}
              </option>
            ))}
          </select>
          {view === "kanban" && <span id="tf-status-help" className="small muted">O filtro de estado aplica-se apenas à Lista.</span>}
        </div>
        <label className="checkbox">
          <input type="checkbox" checked={filters.overdue_only} onChange={(event) => updateFilters({ overdue_only: event.target.checked })} />
          Só atrasadas
        </label>
        {hasFilters && (
          <div className="toolbar__end">
            <button type="button" className="btn btn--ghost" onClick={clearFilters}>
              <Icon name="x" size={16} /> Limpar filtros
            </button>
          </div>
        )}
      </form>

      <div className="tasks-list__settings" role="toolbar" aria-label="Configuração da lista de tarefas">
        <ColumnConfigurator
          columns={config.columns}
          onChange={(columns) => commitConfig((current) => ({ ...current, columns }))}
          onRestore={() => commitConfig((current) => ({ ...current, columns: [...DEFAULT_TASK_LIST_COLUMNS] }))}
        />
        <div className="field">
          <label htmlFor="task-list-sort">Ordenar por</label>
          <select id="task-list-sort" className="select" value={config.sort_by} onChange={(event) => commitConfig((current) => ({ ...current, sort_by: event.target.value as TaskListConfig["sort_by"] }))}>
            {Object.entries(TASK_LIST_SORT_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="task-list-sort-direction">Direção</label>
          <select id="task-list-sort-direction" className="select" value={config.sort_direction} onChange={(event) => commitConfig((current) => ({ ...current, sort_direction: event.target.value as TaskListConfig["sort_direction"] }))}>
            <option value="asc">Ascendente</option>
            <option value="desc">Descendente</option>
          </select>
        </div>
        <div className="field tasks-list__saved-view-field">
          <label htmlFor="task-list-saved-view">Vistas pessoais</label>
          <select id="task-list-saved-view" className="select" value={selectedSavedViewId} onChange={(event) => setSelectedSavedViewId(event.target.value)} disabled={savedViewsLoading}>
            <option value="">{savedViewsLoading ? "A carregar…" : "Selecionar vista pessoal"}</option>
            {savedViews.map((savedView) => (
              <option key={savedView.id} value={savedView.id}>
                {savedView.name}
              </option>
            ))}
          </select>
        </div>
        <div className="tasks-list__view-actions">
          <button type="button" className="btn btn--sm btn--ghost" onClick={handleApplySavedView} disabled={!selectedSavedViewId || savedViewsManagingId !== null}>
            Aplicar vista
          </button>
          <button type="button" className="btn btn--sm btn--ghost" onClick={() => void handleCreateSavedView()} disabled={savedViewsSaving}>
            {savedViewsSaving ? "A guardar…" : "Guardar vista atual como…"}
          </button>
          <button type="button" className="btn btn--sm" onClick={handleSavePreferences} disabled={preferenceSaving || preferenceStatus === "loading"}>
            {preferenceSaving ? "A guardar…" : "Guardar preferência de abertura"}
          </button>
          {selectedSavedViewId && (
            <>
              <button type="button" className="btn btn--sm btn--ghost" onClick={() => void handleUpdateSavedView()} disabled={savedViewsManagingId !== null}>
                {savedViewsManagingId === selectedSavedViewId ? "A atualizar…" : "Atualizar vista"}
              </button>
              <button type="button" className="btn btn--sm btn--ghost" onClick={() => void handleRenameSavedView()} disabled={savedViewsManagingId !== null}>
                {savedViewsManagingId === selectedSavedViewId ? "A gerir…" : "Renomear vista"}
              </button>
              <button type="button" className="btn btn--sm btn--ghost" onClick={() => void handleDeleteSavedView()} disabled={savedViewsManagingId !== null}>
                {savedViewsManagingId === selectedSavedViewId ? "A gerir…" : "Eliminar vista"}
              </button>
            </>
          )}
        </div>
        {savedViewsError && (
          <span className="small text-danger" role="alert">
            {savedViewsError} <button type="button" className="btn btn--sm btn--ghost" onClick={() => setSavedViewsReloadKey((key) => key + 1)}>Tentar carregar vistas</button>
          </span>
        )}
        {savedViewsActionError && <span className="small text-danger" role="alert">{savedViewsActionError}</span>}
      </div>
      <p className="small muted tasks-list__kanban-help">As colunas configuradas aplicam-se à Lista; o Kanban mantém sempre as colunas por estado.</p>
      {preferenceSaved && <p className="small text-success" role="status">Preferência de abertura guardada.</p>}

      {error && (
        <div className="card">
          <ErrorState message={error} onRetry={load} />
        </div>
      )}
      {!error && tasks === null && (
        <div className="card">
          <LoadingState label="A carregar tarefas…" rows={5} />
        </div>
      )}
      {!error && tasks?.length === 0 && (
        <div className="card">
          <EmptyState
            icon="tasks"
            title="Nenhuma tarefa encontrada"
            text={hasFilters ? "Nenhuma tarefa corresponde aos filtros escolhidos." : "Não há tarefas visíveis para o seu perfil."}
            action={
              hasFilters ? (
                <button type="button" className="btn btn--sm" onClick={clearFilters}>
                  Limpar filtros
                </button>
              ) : undefined
            }
          />
        </div>
      )}

      {!error && tasks && tasks.length > 0 && view === "lista" && (
        <div className="card">
          <div className="card__header" style={{ paddingBottom: 12 }}>
            <span className="small muted" aria-live="polite">
              {tasks.length} tarefa{tasks.length === 1 ? "" : "s"}
            </span>
          </div>
          <div className="table-wrap">
            <table className="table">
              <caption className="sr-only">Lista de tarefas</caption>
              <thead>
                <tr>
                  {config.columns.map((column) => (
                    <th key={column} scope="col" className={column === "task" ? "col-main" : undefined}>
                      {TASK_LIST_COLUMN_LABELS[column]}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sortedTasks.map((task) => (
                  <tr
                    key={task.id}
                    className={`${task.is_overdue ? "row--danger" : task.priority === "urgent" ? "row--urgent" : ""} ${justDone === task.id ? "just-done" : ""}`}
                  >
                    {config.columns.map((column) => (
                      <td key={column} data-label={TASK_LIST_COLUMN_LABELS[column]} className={column === "assignee" || column === "due_date" ? "nowrap" : undefined}>
                        {renderTaskCell(column, task, today, busyId === task.id, change)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!error && tasks && tasks.length > 0 && view === "kanban" && (
        <>
          <p className="small muted" style={{ marginTop: 0 }}>
            Arraste um cartão para outra coluna ou use o seletor de estado no cartão.
          </p>
          <div className="kanban">
            {ALL_STATUSES.map((status) => {
              const column = sortedTasks.filter((task) => task.status === status);
              const visible = expanded[status] ? column : column.slice(0, KANBAN_PAGE);
              return (
                <section
                  key={status}
                  className={`kanban__col ${dropTarget === status ? "drop-target" : ""}`}
                  aria-label={`${TASK_STATUS_LABELS[status]} (${column.length})`}
                  onDragOver={(event) => {
                    event.preventDefault();
                    setDropTarget(status);
                  }}
                  onDragLeave={() => setDropTarget((current) => (current === status ? null : current))}
                  onDrop={(event) => handleDrop(event, status)}
                >
                  <div className="kanban__head">
                    <Badge tone={TASK_STATUS_TONES[status]} dot>
                      {TASK_STATUS_LABELS[status]}
                    </Badge>
                    <span className="small muted">{column.length}</span>
                  </div>
                  <div className="kanban__cards">
                    {column.length === 0 && <div className="small muted" style={{ padding: "8px 6px" }}>Sem tarefas</div>}
                    {visible.map((task) => (
                      <TaskCard
                        key={task.id}
                        task={task}
                        today={today}
                        busy={busyId === task.id}
                        highlight={justDone === task.id}
                        onStatusChange={change}
                      />
                    ))}
                    {column.length > visible.length && (
                      <button
                        type="button"
                        className="btn btn--sm btn--ghost"
                        onClick={() => setExpanded((current) => ({ ...current, [status]: true }))}
                      >
                        Mostrar mais {column.length - visible.length}
                      </button>
                    )}
                  </div>
                </section>
              );
            })}
          </div>
        </>
      )}

      {creating && (
        <TaskFormModal
          projects={projects}
          people={people}
          onClose={() => setCreating(false)}
          onCreated={() => {
            setCreating(false);
            notify("Tarefa criada.", "success");
            load();
          }}
        />
      )}
    </div>
  );
}
