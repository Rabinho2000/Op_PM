import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ApiError,
  DEFAULT_TASK_TYPE_LABELS,
  getProject,
  getProjectHistory,
  listPeople,
  listTasks,
  Person,
  Project,
  PROJECT_STATUS_LABELS,
  ProjectHistoryEntry,
  TASK_ALLOWED_NEXT_STATUSES,
  TASK_PRIORITY_LABELS,
  TASK_STATUS_LABELS,
  Task,
  TaskStatus,
  updateProject,
  updateTask,
} from "../api/client";
import { formatDatePt } from "../utils/dates";

// Campos editáveis via API (ver app/schemas/projects.py:ProjectUpdate) —
// clickup_status_mirror fica sempre de fora, fonte de verdade ClickUp.
const EDITABLE_FIELDS: { key: keyof Project; label: string; multiline?: boolean }[] = [
  { key: "name", label: "Nome" },
  { key: "client_name", label: "Cliente" },
  { key: "client_contact", label: "Contacto" },
  { key: "client_email", label: "Email" },
  { key: "address", label: "Morada" },
  { key: "role", label: "Papel (legado)" },
  { key: "equipment_notes", label: "Equipamento", multiline: true },
  { key: "notes", label: "Notas", multiline: true },
];

export default function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [history, setHistory] = useState<ProjectHistoryEntry[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [people, setPeople] = useState<Person[]>([]);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [taskError, setTaskError] = useState<string | null>(null);

  function load() {
    if (!projectId) return;
    setError(null);
    getProject(projectId)
      .then((p) => {
        setProject(p);
        const d: Record<string, string> = {};
        for (const f of EDITABLE_FIELDS) d[f.key] = (p[f.key] as string) ?? "";
        setDraft(d);
      })
      .catch((e) => setError(e instanceof ApiError ? e.detail : String(e)));
    getProjectHistory(projectId)
      .then(setHistory)
      .catch(() => setHistory([]));
    listTasks({ project_id: projectId })
      .then(setTasks)
      .catch(() => setTasks([]));
  }

  useEffect(load, [projectId]);
  useEffect(() => {
    listPeople().then(setPeople).catch(() => setPeople([]));
  }, []);

  async function handleTaskStatusChange(task: Task, status: TaskStatus) {
    setTaskError(null);
    try {
      await updateTask(task.id, { status });
      load();
    } catch (e) {
      setTaskError(e instanceof ApiError ? e.detail : String(e));
    }
  }

  async function handleTaskAssign(task: Task, personId: string) {
    setTaskError(null);
    try {
      await updateTask(task.id, { assigned_to_person_id: personId || null });
      load();
    } catch (e) {
      setTaskError(e instanceof ApiError ? e.detail : String(e));
    }
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!projectId || !project) return;
    setSaving(true);
    setSaveError(null);
    const changes: Record<string, string> = {};
    for (const f of EDITABLE_FIELDS) {
      const current = (project[f.key] as string) ?? "";
      if (draft[f.key] !== current) changes[f.key] = draft[f.key];
    }
    if (Object.keys(changes).length === 0) {
      setSaving(false);
      return;
    }
    try {
      await updateProject(projectId, changes);
      load();
    } catch (e) {
      setSaveError(e instanceof ApiError ? `${e.status}: ${e.detail}` : String(e));
    } finally {
      setSaving(false);
    }
  }

  if (error) {
    return (
      <div style={{ fontFamily: "system-ui, sans-serif", padding: "1.5rem" }}>
        <Link to="/projects">&larr; Projetos</Link>
        <p style={{ color: "crimson" }}>Erro: {error}</p>
      </div>
    );
  }

  if (!project) {
    return (
      <div style={{ fontFamily: "system-ui, sans-serif", padding: "1.5rem" }}>
        <p>A carregar…</p>
      </div>
    );
  }

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", padding: "1.5rem", maxWidth: 900 }}>
      <Link to="/projects">&larr; Projetos</Link>
      <h1>{project.name}</h1>
      <p style={{ color: "#666" }}>
        PM: {project.pm_display_name ?? "— (não atribuído)"} · Estado: {PROJECT_STATUS_LABELS[project.status]} ·{" "}
        {project.is_active ? "Ativo" : "Inativo"}
        {project.overdue_tasks_count > 0 && (
          <span style={{ color: "#a66" }}> · {project.overdue_tasks_count} tarefa(s) atrasada(s)</span>
        )}
      </p>

      <div style={{ marginBottom: "1rem" }}>
        <div style={{ background: "#eee", borderRadius: 6, height: 10, maxWidth: 400, overflow: "hidden" }}>
          <div
            style={{
              width: `${project.workflow_progress_percent}%`,
              background: "#4F8A3B",
              height: "100%",
            }}
          />
        </div>
        <span style={{ fontSize: "0.8rem", color: "#666" }}>
          Progresso do workflow: {project.workflow_progress_percent}%
        </span>
      </div>

      {project.photos_pending_warning && (
        <div
          style={{
            background: "#fff4d6",
            border: "1px solid #e0b73a",
            borderRadius: 6,
            padding: "0.75rem 1rem",
            marginBottom: "1rem",
          }}
        >
          ⚠️ Visita técnica/comissionamento concluídos — confirmar que as fotos foram colocadas na Drive e concluir a
          tarefa "Colocar fotos na Drive".
        </div>
      )}

      <section style={{ marginBottom: "1.5rem" }}>
        <h2>Tarefas</h2>
        {taskError && <p style={{ color: "crimson" }}>{taskError}</p>}
        {tasks.length === 0 && <p style={{ color: "#666" }}>Sem tarefas para este projeto.</p>}
        {tasks.length > 0 && (
          <table style={{ borderCollapse: "collapse", width: "100%" }}>
            <thead>
              <tr style={{ textAlign: "left", borderBottom: "2px solid #ccc" }}>
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
                  <td style={{ padding: "0.4rem" }}>{DEFAULT_TASK_TYPE_LABELS[t.task_type] ?? t.title}</td>
                  <td style={{ padding: "0.4rem" }}>
                    <select
                      value={t.assigned_to_person_id ?? ""}
                      onChange={(e) => handleTaskAssign(t, e.target.value)}
                    >
                      <option value="">— sem responsável —</option>
                      {people.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.display_name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td style={{ padding: "0.4rem" }}>{TASK_PRIORITY_LABELS[t.priority]}</td>
                  <td style={{ padding: "0.4rem", color: t.is_overdue ? "#a66" : undefined }}>
                    {formatDatePt(t.due_date)}
                  </td>
                  <td style={{ padding: "0.4rem" }}>
                    <select value={t.status} onChange={(e) => handleTaskStatusChange(t, e.target.value as TaskStatus)}>
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
      </section>

      <div style={{ display: "flex", gap: "2rem", flexWrap: "wrap" }}>
        <form onSubmit={handleSave} style={{ flex: "1 1 380px", minWidth: 320 }}>
          <h2>Editar</h2>
          {EDITABLE_FIELDS.map((f) => (
            <div key={f.key} style={{ marginBottom: "0.6rem" }}>
              <label style={{ display: "block", fontSize: "0.85rem", color: "#555" }}>{f.label}</label>
              {f.multiline ? (
                <textarea
                  value={draft[f.key] ?? ""}
                  onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
                  style={{ width: "100%", boxSizing: "border-box", padding: "0.4rem" }}
                  rows={3}
                />
              ) : (
                <input
                  value={draft[f.key] ?? ""}
                  onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
                  style={{ width: "100%", boxSizing: "border-box", padding: "0.4rem" }}
                />
              )}
            </div>
          ))}
          {saveError && <p style={{ color: "crimson" }}>{saveError}</p>}
          <button type="submit" disabled={saving} style={{ padding: "0.5rem 1rem" }}>
            {saving ? "A guardar…" : "Guardar alterações"}
          </button>
        </form>

        <div style={{ flex: "1 1 380px", minWidth: 320 }}>
          <h2>Histórico</h2>
          {history.length === 0 && <p style={{ color: "#666" }}>Sem alterações registadas.</p>}
          <ul style={{ listStyle: "none", padding: 0, maxHeight: 500, overflowY: "auto" }}>
            {history.map((h) => (
              <li key={h.id} style={{ borderBottom: "1px solid #eee", padding: "0.5rem 0", fontSize: "0.85rem" }}>
                <strong>{h.field_name}</strong>: {h.old_value ?? "(vazio)"} → {h.new_value ?? "(vazio)"}
                <br />
                <span style={{ color: "#888" }}>
                  {h.changed_by_person_name ?? "sistema"} · {h.source} ·{" "}
                  {new Date(h.changed_at).toLocaleString("pt-PT")}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
