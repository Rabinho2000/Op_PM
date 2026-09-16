import { FormEvent, useState } from "react";
import {
  ApiError,
  createTask,
  Person,
  Project,
  Task,
  TASK_PRIORITY_LABELS,
  TaskPriority,
} from "../api/client";
import { Alert, Modal } from "./ui";

// Criação de tarefa — só é oferecida para projetos onde o servidor indica
// `can_manage_tasks`; o POST continua validado no backend.
export default function TaskFormModal({
  projects,
  people,
  fixedProjectId,
  onClose,
  onCreated,
}: {
  projects: Project[];
  people: Person[];
  fixedProjectId?: string;
  onClose: () => void;
  onCreated: (task: Task) => void;
}) {
  const [form, setForm] = useState({
    project_id: fixedProjectId ?? "",
    title: "",
    priority: "medium" as TaskPriority,
    assigned_to_person_id: "",
    due_date: "",
    description: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const allowedProjects = projects.filter((p) => p.can_manage_tasks);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!form.project_id || !form.title.trim()) {
      setError("Escolha o projeto e indique um título para a tarefa.");
      return;
    }
    setSaving(true);
    try {
      const task = await createTask({
        project_id: form.project_id,
        title: form.title.trim(),
        priority: form.priority,
        assigned_to_person_id: form.assigned_to_person_id || undefined,
        due_date: form.due_date || undefined,
        description: form.description,
      });
      onCreated(task);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Não foi possível criar a tarefa.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title="Nova tarefa"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancelar
          </button>
          <button type="submit" form="task-form" className="btn btn--primary" disabled={saving}>
            {saving ? "A criar…" : "Criar tarefa"}
          </button>
        </>
      }
    >
      <form id="task-form" className="form-grid" onSubmit={handleSubmit}>
        {error && (
          <div className="span-2">
            <Alert tone="danger">{error}</Alert>
          </div>
        )}
        {!fixedProjectId && (
          <div className="field span-2">
            <label htmlFor="t-project">Projeto *</label>
            <select
              id="t-project"
              className="select"
              value={form.project_id}
              required
              onChange={(e) => setForm({ ...form, project_id: e.target.value })}
            >
              <option value="">— escolher projeto —</option>
              {allowedProjects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="field span-2">
          <label htmlFor="t-title">Título *</label>
          <input
            id="t-title"
            className="input"
            value={form.title}
            required
            maxLength={256}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            placeholder="Ex.: Confirmar data de instalação com o cliente"
          />
        </div>
        <div className="field">
          <label htmlFor="t-priority">Prioridade</label>
          <select
            id="t-priority"
            className="select"
            value={form.priority}
            onChange={(e) => setForm({ ...form, priority: e.target.value as TaskPriority })}
          >
            {(Object.keys(TASK_PRIORITY_LABELS) as TaskPriority[]).map((k) => (
              <option key={k} value={k}>
                {TASK_PRIORITY_LABELS[k]}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="t-due">Prazo</label>
          <input
            id="t-due"
            className="input"
            type="date"
            value={form.due_date}
            onChange={(e) => setForm({ ...form, due_date: e.target.value })}
          />
        </div>
        <div className="field span-2">
          <label htmlFor="t-assignee">Responsável</label>
          <select
            id="t-assignee"
            className="select"
            value={form.assigned_to_person_id}
            onChange={(e) => setForm({ ...form, assigned_to_person_id: e.target.value })}
          >
            <option value="">— sem responsável —</option>
            {people
              .filter((p) => p.is_active)
              .map((p) => (
                <option key={p.id} value={p.id}>
                  {p.display_name}
                </option>
              ))}
          </select>
        </div>
        <div className="field span-2">
          <label htmlFor="t-desc">Descrição</label>
          <textarea
            id="t-desc"
            className="textarea"
            rows={3}
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
          />
        </div>
      </form>
    </Modal>
  );
}
