import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  DEFAULT_TASK_TYPE_LABELS,
  Person,
  Project,
  TASK_ALLOWED_NEXT_STATUSES,
  TASK_PRIORITY_LABELS,
  TASK_STATUS_LABELS,
  Task,
  TaskPriority,
  TaskStatus,
  createTask,
  listPeople,
  listProjects,
  listTasks,
  updateTask,
} from "../api/client";
import { formatDatePt } from "../utils/dates";

const ALL_STATUSES: TaskStatus[] = ["todo", "in_progress", "blocked", "done", "cancelled"];

export default function Tasks() {
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [statusFilter, setStatusFilter] = useState<TaskStatus | "">("");
  const [assigneeFilter, setAssigneeFilter] = useState("");
  const [overdueOnly, setOverdueOnly] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [showCreate, setShowCreate] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [newTask, setNewTask] = useState({
    project_id: "",
    title: "",
    priority: "medium" as TaskPriority,
    assigned_to_person_id: "",
    due_date: "",
    description: "",
  });

  function load() {
    setError(null);
    listTasks({
      status: statusFilter || undefined,
      assigned_to_person_id: assigneeFilter || undefined,
      overdue_only: overdueOnly || undefined,
    })
      .then(setTasks)
      .catch((e) => setError(e instanceof ApiError ? e.detail : String(e)));
  }

  useEffect(() => {
    listPeople().then(setPeople).catch(() => setPeople([]));
    listProjects({ is_active: true }).then(setProjects).catch(() => setProjects([]));
  }, []);

  useEffect(load, [statusFilter, assigneeFilter, overdueOnly]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreateError(null);
    if (!newTask.project_id || !newTask.title.trim()) {
      setCreateError("Escolha um projeto e indique um título.");
      return;
    }
    try {
      await createTask({
        project_id: newTask.project_id,
        title: newTask.title.trim(),
        priority: newTask.priority,
        assigned_to_person_id: newTask.assigned_to_person_id || undefined,
        due_date: newTask.due_date || undefined,
        description: newTask.description,
      });
      setNewTask({ project_id: "", title: "", priority: "medium", assigned_to_person_id: "", due_date: "", description: "" });
      setShowCreate(false);
      load();
    } catch (e) {
      setCreateError(e instanceof ApiError ? `${e.status}: ${e.detail}` : String(e));
    }
  }

  async function handleStatusChange(task: Task, status: TaskStatus) {
    try {
      await updateTask(task.id, { status });
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    }
  }

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", padding: "1.5rem" }}>
      <h1>Tarefas</h1>

      <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1rem", flexWrap: "wrap", alignItems: "center" }}>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as TaskStatus | "")} style={{ padding: "0.4rem" }}>
          <option value="">Todos os estados</option>
          {ALL_STATUSES.map((s) => (
            <option key={s} value={s}>
              {TASK_STATUS_LABELS[s]}
            </option>
          ))}
        </select>
        <select value={assigneeFilter} onChange={(e) => setAssigneeFilter(e.target.value)} style={{ padding: "0.4rem" }}>
          <option value="">Todos os responsáveis</option>
          {people.map((p) => (
            <option key={p.id} value={p.id}>
              {p.display_name}
            </option>
          ))}
        </select>
        <label style={{ fontSize: "0.9rem" }}>
          <input type="checkbox" checked={overdueOnly} onChange={(e) => setOverdueOnly(e.target.checked)} /> só
          atrasadas
        </label>
        <button type="button" onClick={() => setShowCreate((v) => !v)} style={{ marginLeft: "auto", padding: "0.4rem 0.8rem" }}>
          {showCreate ? "Cancelar" : "Nova tarefa"}
        </button>
      </div>

      {showCreate && (
        <form
          onSubmit={handleCreate}
          style={{ border: "1px solid #ddd", borderRadius: 8, padding: "1rem", marginBottom: "1rem", maxWidth: 480 }}
        >
          <h2 style={{ fontSize: "1rem", marginTop: 0 }}>Nova tarefa</h2>
          <div style={{ marginBottom: "0.5rem" }}>
            <label style={{ display: "block", fontSize: "0.85rem" }}>Projeto</label>
            <select
              value={newTask.project_id}
              onChange={(e) => setNewTask({ ...newTask, project_id: e.target.value })}
              style={{ width: "100%", padding: "0.4rem" }}
            >
              <option value="">— escolher —</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
          <div style={{ marginBottom: "0.5rem" }}>
            <label style={{ display: "block", fontSize: "0.85rem" }}>Título</label>
            <input
              value={newTask.title}
              onChange={(e) => setNewTask({ ...newTask, title: e.target.value })}
              style={{ width: "100%", padding: "0.4rem", boxSizing: "border-box" }}
            />
          </div>
          <div style={{ marginBottom: "0.5rem" }}>
            <label style={{ display: "block", fontSize: "0.85rem" }}>Prioridade</label>
            <select
              value={newTask.priority}
              onChange={(e) => setNewTask({ ...newTask, priority: e.target.value as TaskPriority })}
              style={{ width: "100%", padding: "0.4rem" }}
            >
              {Object.entries(TASK_PRIORITY_LABELS).map(([k, label]) => (
                <option key={k} value={k}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          <div style={{ marginBottom: "0.5rem" }}>
            <label style={{ display: "block", fontSize: "0.85rem" }}>Responsável</label>
            <select
              value={newTask.assigned_to_person_id}
              onChange={(e) => setNewTask({ ...newTask, assigned_to_person_id: e.target.value })}
              style={{ width: "100%", padding: "0.4rem" }}
            >
              <option value="">— sem responsável —</option>
              {people.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.display_name}
                </option>
              ))}
            </select>
          </div>
          <div style={{ marginBottom: "0.5rem" }}>
            <label style={{ display: "block", fontSize: "0.85rem" }}>Prazo</label>
            <input
              type="date"
              value={newTask.due_date}
              onChange={(e) => setNewTask({ ...newTask, due_date: e.target.value })}
              style={{ width: "100%", padding: "0.4rem", boxSizing: "border-box" }}
            />
          </div>
          <div style={{ marginBottom: "0.5rem" }}>
            <label style={{ display: "block", fontSize: "0.85rem" }}>Descrição</label>
            <textarea
              value={newTask.description}
              onChange={(e) => setNewTask({ ...newTask, description: e.target.value })}
              style={{ width: "100%", padding: "0.4rem", boxSizing: "border-box" }}
              rows={2}
            />
          </div>
          {createError && <p style={{ color: "crimson" }}>{createError}</p>}
          <button type="submit" style={{ padding: "0.5rem 1rem" }}>
            Criar tarefa
          </button>
        </form>
      )}

      {error && <p style={{ color: "crimson" }}>Erro: {error}</p>}
      {tasks === null && !error && <p>A carregar…</p>}
      {tasks && tasks.length === 0 && <p>Nenhuma tarefa encontrada (ou sem permissão para ver nenhuma).</p>}

      {tasks && tasks.length > 0 && (
        <table style={{ borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "2px solid #ccc" }}>
              <th style={{ padding: "0.4rem" }}>Projeto</th>
              <th style={{ padding: "0.4rem" }}>Tarefa</th>
              <th style={{ padding: "0.4rem" }}>Responsável</th>
              <th style={{ padding: "0.4rem" }}>Prioridade</th>
              <th style={{ padding: "0.4rem" }}>Prazo</th>
              <th style={{ padding: "0.4rem" }}>Estado</th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((t) => (
              <tr key={t.id} style={{ borderBottom: "1px solid #eee", background: t.is_overdue ? "#fff4f4" : undefined }}>
                <td style={{ padding: "0.4rem" }}>
                  <Link to={`/projects/${t.project_id}`}>{t.project_name ?? "—"}</Link>
                </td>
                <td style={{ padding: "0.4rem" }}>{DEFAULT_TASK_TYPE_LABELS[t.task_type] ?? t.title}</td>
                <td style={{ padding: "0.4rem" }}>{t.assigned_to_display_name ?? "—"}</td>
                <td style={{ padding: "0.4rem" }}>{TASK_PRIORITY_LABELS[t.priority]}</td>
                <td style={{ padding: "0.4rem", color: t.is_overdue ? "#a66" : undefined }}>
                  {formatDatePt(t.due_date)}
                </td>
                <td style={{ padding: "0.4rem" }}>
                  <select value={t.status} onChange={(e) => handleStatusChange(t, e.target.value as TaskStatus)}>
                    {TASK_ALLOWED_NEXT_STATUSES[t.status].map((s) => (
                      <option key={s} value={s}>
                        {TASK_STATUS_LABELS[s]}
                      </option>
                    ))}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
