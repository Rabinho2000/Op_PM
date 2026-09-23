import { DragEvent, useCallback, useEffect, useState } from "react";
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
  TASK_PRIORITY_LABELS,
  TASK_STATUS_LABELS,
  TaskFilters,
  TaskPriority,
  TaskStatus,
} from "../api/client";
import Icon from "../components/Icon";
import TaskFormModal from "../components/TaskForm";
import TaskStatusControl, { useTaskStatusChange } from "../components/TaskStatusControl";
import { useToast } from "../components/Toast";
import { Avatar, Badge, EmptyState, ErrorState, LoadingState, PageHeader } from "../components/ui";
import { formatDatePt, relativeDayLabel, todayIsoLisbon } from "../utils/dates";
import { TASK_PRIORITY_TONES, TASK_STATUS_TONES, TASK_TYPE_ICONS } from "../utils/labels";

const ALL_STATUSES: TaskStatus[] = ["todo", "in_progress", "blocked", "done", "cancelled"];
const PRIORITIES: TaskPriority[] = ["urgent", "high", "medium", "low"];
const KANBAN_PAGE = 20;

type View = "lista" | "kanban";

function taskLabel(t: Task): string {
  return t.task_type === "custom" ? t.title : DEFAULT_TASK_TYPE_LABELS[t.task_type] ?? t.title;
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

export default function Tasks() {
  const [searchParams] = useSearchParams();
  const { notify } = useToast();
  const [view, setView] = useState<View>(() => {
    try {
      return localStorage.getItem("op_pm_tasks_view") === "kanban" ? "kanban" : "lista";
    } catch {
      return "lista";
    }
  });
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [projectFilter, setProjectFilter] = useState("");
  const [assigneeFilter, setAssigneeFilter] = useState("");
  const [priorityFilter, setPriorityFilter] = useState<TaskPriority | "">(() => {
    const fromUrl = searchParams.get("prioridade");
    return PRIORITIES.find((p) => p === fromUrl) ?? "";
  });
  const [statusFilter, setStatusFilter] = useState<TaskStatus | "">("");
  const [overdueOnly, setOverdueOnly] = useState(searchParams.get("atrasadas") === "1");
  const [creating, setCreating] = useState(false);
  const [justDone, setJustDone] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<TaskStatus | null>(null);
  const [expanded, setExpanded] = useState<Partial<Record<TaskStatus, boolean>>>({});

  useEffect(() => {
    try {
      localStorage.setItem("op_pm_tasks_view", view);
    } catch {
      // preferência só local — ignorar se indisponível
    }
  }, [view]);

  useEffect(() => {
    listPeople()
      .then(setPeople)
      .catch(() => setPeople([]));
    listProjects({ is_active: true })
      .then(setProjects)
      .catch(() => setProjects([]));
  }, []);

  const load = useCallback(() => {
    const filters: TaskFilters = {
      project_id: projectFilter || undefined,
      assigned_to_person_id: assigneeFilter || undefined,
      priority: priorityFilter || undefined,
      overdue_only: overdueOnly || undefined,
      status: view === "lista" ? statusFilter || undefined : undefined,
    };
    setError(null);
    listTasks(filters)
      .then(setTasks)
      .catch((e) => setError(e instanceof ApiError ? e.detail : "Não foi possível contactar o servidor."));
  }, [projectFilter, assigneeFilter, priorityFilter, overdueOnly, statusFilter, view]);

  useEffect(() => {
    setTasks(null);
    load();
  }, [load]);

  const { change, busyId } = useTaskStatusChange(
    useCallback(
      (updated: Task) => {
        if (updated.status === "done") {
          setJustDone(updated.id);
          window.setTimeout(() => setJustDone(null), 1200);
        }
        // Atualização local imediata; o recarregamento confirma com o servidor.
        setTasks((current) => current?.map((t) => (t.id === updated.id ? updated : t)) ?? null);
        load();
      },
      [load]
    )
  );

  function handleDrop(e: DragEvent, status: TaskStatus) {
    e.preventDefault();
    setDropTarget(null);
    const id = e.dataTransfer.getData("text/plain");
    const task = tasks?.find((t) => t.id === id);
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
  const canCreate = projects.some((p) => p.can_manage_tasks);
  const hasFilters = Boolean(projectFilter || assigneeFilter || priorityFilter || statusFilter || overdueOnly);
  const clearFilters = () => {
    setProjectFilter("");
    setAssigneeFilter("");
    setPriorityFilter("");
    setStatusFilter("");
    setOverdueOnly(false);
  };

  return (
    <>
      <PageHeader
        title="Tarefas"
        subtitle="Acompanhe prazos, prioridades e responsáveis de todas as tarefas visíveis ao seu perfil."
        actions={
          <>
            <div className="segmented" role="group" aria-label="Modo de visualização">
              <button type="button" aria-pressed={view === "lista"} onClick={() => setView("lista")}>
                <Icon name="list" size={16} /> Lista
              </button>
              <button type="button" aria-pressed={view === "kanban"} onClick={() => setView("kanban")}>
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

      <form className="toolbar" aria-label="Filtros de tarefas" onSubmit={(e) => e.preventDefault()}>
        <div className="field field--wide">
          <label htmlFor="tf-project">Projeto</label>
          <select id="tf-project" className="select" value={projectFilter} onChange={(e) => setProjectFilter(e.target.value)}>
            <option value="">Todos os projetos</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="tf-assignee">Responsável</label>
          <select
            id="tf-assignee"
            className="select"
            value={assigneeFilter}
            onChange={(e) => setAssigneeFilter(e.target.value)}
          >
            <option value="">Todos</option>
            {people.map((p) => (
              <option key={p.id} value={p.id}>
                {p.display_name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="tf-priority">Prioridade</label>
          <select
            id="tf-priority"
            className="select"
            value={priorityFilter}
            onChange={(e) => setPriorityFilter(e.target.value as TaskPriority | "")}
          >
            <option value="">Todas</option>
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {TASK_PRIORITY_LABELS[p]}
              </option>
            ))}
          </select>
        </div>
        {view === "lista" && (
          <div className="field">
            <label htmlFor="tf-status">Estado</label>
            <select
              id="tf-status"
              className="select"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as TaskStatus | "")}
            >
              <option value="">Todos</option>
              {ALL_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {TASK_STATUS_LABELS[s]}
                </option>
              ))}
            </select>
          </div>
        )}
        <label className="checkbox">
          <input type="checkbox" checked={overdueOnly} onChange={(e) => setOverdueOnly(e.target.checked)} />
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
                  <th scope="col" className="col-main">Tarefa</th>
                  <th scope="col">Projeto</th>
                  <th scope="col">Responsável</th>
                  <th scope="col">Prioridade</th>
                  <th scope="col">Prazo</th>
                  <th scope="col">Estado</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((t) => (
                  <tr
                    key={t.id}
                    className={`${t.is_overdue ? "row--danger" : t.priority === "urgent" ? "row--urgent" : ""} ${
                      justDone === t.id ? "just-done" : ""
                    }`}
                  >
                    <td>
                      <span className="cell-title" style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
                        <Icon name={TASK_TYPE_ICONS[t.task_type] ?? "tasks"} size={15} className="muted" />
                        {taskLabel(t)}
                      </span>
                      {t.status === "done" && (
                        <span className="cell-sub" style={{ color: "var(--success)" }}>
                          <Icon name="check" size={12} /> concluída
                        </span>
                      )}
                    </td>
                    <td>
                      <Link to={`/projects/${t.project_id}`}>{t.project_name ?? "—"}</Link>
                    </td>
                    <td className="nowrap">
                      {t.assigned_to_display_name ? (
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                          <Avatar name={t.assigned_to_display_name} small />
                          {t.assigned_to_display_name}
                        </span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td>
                      <Badge tone={TASK_PRIORITY_TONES[t.priority]}>{TASK_PRIORITY_LABELS[t.priority]}</Badge>
                    </td>
                    <td className="nowrap">
                      <span className={t.is_overdue ? "text-danger" : undefined}>{formatDatePt(t.due_date)}</span>
                      {t.due_date && (
                        <span className={`cell-sub ${t.is_overdue ? "text-danger" : ""}`}>
                          {t.is_overdue ? "atrasada · " : ""}
                          {relativeDayLabel(t.due_date, today)}
                        </span>
                      )}
                    </td>
                    <td>
                      <TaskStatusControl task={t} busy={busyId === t.id} onChange={change} />
                    </td>
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
              const column = tasks.filter((t) => t.status === status);
              const visible = expanded[status] ? column : column.slice(0, KANBAN_PAGE);
              return (
                <section
                  key={status}
                  className={`kanban__col ${dropTarget === status ? "drop-target" : ""}`}
                  aria-label={`${TASK_STATUS_LABELS[status]} (${column.length})`}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDropTarget(status);
                  }}
                  onDragLeave={() => setDropTarget((current) => (current === status ? null : current))}
                  onDrop={(e) => handleDrop(e, status)}
                >
                  <div className="kanban__head">
                    <Badge tone={TASK_STATUS_TONES[status]} dot>
                      {TASK_STATUS_LABELS[status]}
                    </Badge>
                    <span className="small muted">{column.length}</span>
                  </div>
                  <div className="kanban__cards">
                    {column.length === 0 && <div className="small muted" style={{ padding: "8px 6px" }}>Sem tarefas</div>}
                    {visible.map((t) => (
                      <TaskCard
                        key={t.id}
                        task={t}
                        today={today}
                        busy={busyId === t.id}
                        highlight={justDone === t.id}
                        onStatusChange={change}
                      />
                    ))}
                    {column.length > visible.length && (
                      <button
                        type="button"
                        className="btn btn--sm btn--ghost"
                        onClick={() => setExpanded((e) => ({ ...e, [status]: true }))}
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
    </>
  );
}
