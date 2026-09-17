import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ApiError,
  DEFAULT_TASK_TYPE_LABELS,
  getProject,
  getProjectHistory,
  getProjectWorkflow,
  listPeople,
  listTasks,
  Person,
  Project,
  PROJECT_STATUS_LABELS,
  ProjectHistoryEntry,
  ProjectWorkflow as Workflow,
  Task,
  TASK_ALLOWED_NEXT_STATUSES,
  TASK_PRIORITY_LABELS,
  TaskStatus,
  updateProject,
  updateTask,
} from "../api/client";
import Icon from "../components/Icon";
import ProjectWorkflow from "../components/ProjectWorkflow";
import TaskFormModal from "../components/TaskForm";
import TaskStatusControl, { useTaskStatusChange } from "../components/TaskStatusControl";
import { useToast } from "../components/Toast";
import { Alert, Avatar, Badge, Card, EmptyState, ErrorState, LoadingState, Modal, ProgressBar } from "../components/ui";
import { formatDatePt, formatDateTimePt, relativeDayLabel, todayIsoLisbon } from "../utils/dates";
import {
  PROJECT_FIELD_LABELS,
  PROJECT_STATUS_TONES,
  TASK_PRIORITY_TONES,
  TASK_TYPE_ICONS,
} from "../utils/labels";

type TabKey = "percurso" | "resumo" | "tarefas" | "historico" | "cliente";

// Campos de texto oferecidos no formulário de edição, por ordem. Só são
// mostrados os que o servidor indica em `project.editable_fields` (D-028).
const TEXT_FIELDS: { key: keyof Project; multiline?: boolean; type?: string }[] = [
  { key: "name" },
  { key: "client_name" },
  { key: "client_contact" },
  { key: "client_email", type: "email" },
  { key: "address" },
  { key: "start_date", type: "date" },
  { key: "role" },
  { key: "equipment_notes", multiline: true },
  { key: "injection_notes", multiline: true },
  { key: "om_notes", multiline: true },
  { key: "notes", multiline: true },
];

const STANDARD_ORDER = ["visita_tecnica", "preparacao_instalacao", "instalacao", "comissionamento", "fotos_drive"];

// Alterações ao percurso de obra ficam no histórico como
// `percurso.etapa.NN.M` (subtarefa) ou `percurso.etapa.NN.contacto`, com o
// texto da subtarefa na nota (app/services/workflow.py).
function historyFieldLabel(h: ProjectHistoryEntry): string {
  const match = /^percurso\.etapa\.(\d+)/.exec(h.field_name);
  if (match) return `Percurso · etapa ${Number(match[1])}${h.note ? ` — ${h.note}` : ""}`;
  return PROJECT_FIELD_LABELS[h.field_name] ?? h.field_name;
}

function stepClass(task: Task | undefined): string {
  if (!task) return "step";
  if (task.status === "done") return "step step--done";
  if (task.status === "blocked") return "step step--blocked";
  if (task.status === "in_progress") return "step step--active";
  return "step";
}

function EditProjectModal({
  project,
  onClose,
  onSaved,
}: {
  project: Project;
  onClose: () => void;
  onSaved: (p: Project) => void;
}) {
  const fields = TEXT_FIELDS.filter((f) => project.editable_fields.includes(f.key));
  const [draft, setDraft] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map((f) => [f.key, (project[f.key] as string | null) ?? ""]))
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const changes: Record<string, string | null> = {};
    for (const f of fields) {
      const current = (project[f.key] as string | null) ?? "";
      if (draft[f.key] !== current) {
        // Datas vazias têm de ir como null (o servidor não aceita "").
        changes[f.key] = f.type === "date" && draft[f.key] === "" ? null : draft[f.key];
      }
    }
    if (Object.keys(changes).length === 0) {
      onClose();
      return;
    }
    setSaving(true);
    setError(null);
    try {
      onSaved(await updateProject(project.id, changes as Partial<Project>));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Não foi possível guardar as alterações.");
    } finally {
      setSaving(false);
    }
  }

  const adminOnlyHidden = project.editable_fields.length > 0 && !project.editable_fields.includes("name");

  return (
    <Modal
      title="Editar projeto"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancelar
          </button>
          <button type="submit" form="project-form" className="btn btn--primary" disabled={saving}>
            {saving ? "A guardar…" : "Guardar alterações"}
          </button>
        </>
      }
    >
      <form id="project-form" className="form-grid" onSubmit={handleSubmit}>
        {error && (
          <div className="span-2">
            <Alert tone="danger">{error}</Alert>
          </div>
        )}
        {adminOnlyHidden && (
          <div className="span-2">
            <Alert tone="info">
              Como PM deste projeto pode editar notas de acompanhamento. Dados do cliente, datas e atribuição são
              alterados pela Chefia de Operações.
            </Alert>
          </div>
        )}
        {fields.map((f) => (
          <div key={f.key} className={`field ${f.multiline ? "span-2" : ""}`}>
            <label htmlFor={`p-${f.key}`}>{PROJECT_FIELD_LABELS[f.key] ?? f.key}</label>
            {f.multiline ? (
              <textarea
                id={`p-${f.key}`}
                className="textarea"
                rows={3}
                value={draft[f.key]}
                onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
              />
            ) : (
              <input
                id={`p-${f.key}`}
                className="input"
                type={f.type ?? "text"}
                value={draft[f.key]}
                onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
              />
            )}
          </div>
        ))}
      </form>
    </Modal>
  );
}

export default function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>();
  const { notify } = useToast();
  const [project, setProject] = useState<Project | null>(null);
  const [history, setHistory] = useState<ProjectHistoryEntry[] | null>(null);
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [workflowError, setWorkflowError] = useState<string | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>("percurso");
  const [editing, setEditing] = useState(false);
  const [creatingTask, setCreatingTask] = useState(false);
  const [justDone, setJustDone] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!projectId) return;
    setError(null);
    getProject(projectId)
      .then(setProject)
      .catch((e) => setError(e instanceof ApiError ? e.detail : "Não foi possível contactar o servidor."));
    getProjectHistory(projectId)
      .then(setHistory)
      .catch(() => setHistory([]));
    listTasks({ project_id: projectId })
      .then(setTasks)
      .catch(() => setTasks([]));
    setWorkflowError(null);
    getProjectWorkflow(projectId)
      .then(setWorkflow)
      .catch((e) => setWorkflowError(e instanceof ApiError ? e.detail : "Não foi possível carregar o percurso de obra."));
  }, [projectId]);

  useEffect(load, [load]);
  useEffect(() => {
    listPeople()
      .then(setPeople)
      .catch(() => setPeople([]));
  }, []);

  const { change: changeStatus, busyId } = useTaskStatusChange(
    useCallback(
      (updated: Task) => {
        if (updated.status === "done") {
          setJustDone(updated.id);
          window.setTimeout(() => setJustDone(null), 1200);
        }
        load();
      },
      [load]
    )
  );

  async function handleAssign(task: Task, personId: string) {
    try {
      await updateTask(task.id, { assigned_to_person_id: personId || null });
      notify("Responsável atualizado.", "success");
      load();
    } catch (e) {
      notify(e instanceof ApiError ? e.detail : "Não foi possível atualizar o responsável.", "error");
    }
  }

  if (error) {
    return (
      <>
        <Link to="/projects" className="back-link">
          <Icon name="arrowLeft" size={16} /> Projetos
        </Link>
        <div className="card">
          <ErrorState message={error} onRetry={load} />
        </div>
      </>
    );
  }

  if (!project) {
    return (
      <>
        <Link to="/projects" className="back-link">
          <Icon name="arrowLeft" size={16} /> Projetos
        </Link>
        <div className="card">
          <LoadingState label="A carregar o projeto…" rows={6} />
        </div>
      </>
    );
  }

  const today = todayIsoLisbon();
  const byType = new Map((tasks ?? []).map((t) => [t.task_type, t]));
  const photosTask = byType.get("fotos_drive");
  const canEdit = project.editable_fields.length > 0;
  const openTasks = (tasks ?? []).filter((t) => t.status !== "done" && t.status !== "cancelled");

  const tabs: { key: TabKey; label: string; count?: number }[] = [
    { key: "percurso", label: "Percurso de obra" },
    { key: "resumo", label: "Resumo" },
    { key: "tarefas", label: "Tarefas", count: tasks?.length },
    { key: "historico", label: "Histórico", count: history?.length },
    { key: "cliente", label: "Cliente" },
  ];

  return (
    <>
      <Link to="/projects" className="back-link">
        <Icon name="arrowLeft" size={16} /> Projetos
      </Link>

      <section className="card hero" aria-labelledby="project-title">
        <div className="hero__main">
          <div className="badges">
            <Badge tone={PROJECT_STATUS_TONES[project.status]} dot>
              {PROJECT_STATUS_LABELS[project.status]}
            </Badge>
            {!project.is_active && <Badge>Inativo</Badge>}
            {project.overdue_tasks_count > 0 && (
              <Badge tone="danger">
                {project.overdue_tasks_count} tarefa{project.overdue_tasks_count > 1 ? "s" : ""} atrasada
                {project.overdue_tasks_count > 1 ? "s" : ""}
              </Badge>
            )}
            {project.photos_pending_warning && (
              <Badge tone="warning">
                <Icon name="camera" size={12} /> Fotografias pendentes
              </Badge>
            )}
          </div>
          <h1 id="project-title">{project.name}</h1>
          <div className="muted small" style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center" }}>
            <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
              {project.pm_display_name ? (
                <>
                  <Avatar name={project.pm_display_name} small /> PM: {project.pm_display_name}
                </>
              ) : (
                <Badge tone="warning">Sem PM atribuído</Badge>
              )}
            </span>
            <span>Cliente: {project.client_name ?? "por identificar"}</span>
            <span>Início: {formatDatePt(project.start_date)}</span>
            {project.power_kwp !== null && <span>{project.power_kwp.toLocaleString("pt-PT")} kWp</span>}
          </div>
          <div className="steps" style={{ marginTop: 14 }} aria-label="Checklist padrão">
            {STANDARD_ORDER.map((type) => {
              const task = byType.get(type);
              return (
                <span key={type} className={stepClass(task)}>
                  <Icon name={task?.status === "done" ? "check" : TASK_TYPE_ICONS[type]} size={13} />
                  {DEFAULT_TASK_TYPE_LABELS[type]}
                </span>
              );
            })}
          </div>
        </div>
        <div className="hero__progress">
          <div className="small muted" style={{ marginBottom: 6 }}>
            Percurso de obra
            {workflow?.current_stage_number != null && <> · etapa {workflow.current_stage_number} de {workflow.stages.length}</>}
          </div>
          <ProgressBar
            value={workflow ? workflow.progress_percent : project.workflow_progress_percent}
            large
            label="Progresso do percurso de obra"
          />
          {canEdit && (
            <button type="button" className="btn btn--block" style={{ marginTop: 14 }} onClick={() => setEditing(true)}>
              <Icon name="wrench" size={16} /> Editar projeto
            </button>
          )}
        </div>
      </section>

      {project.photos_pending_warning && (
        <Alert
          tone="warning"
          title="Fotografias por colocar na Drive"
          action={
            photosTask?.can_edit && TASK_ALLOWED_NEXT_STATUSES[photosTask.status].includes("done") && photosTask.status !== "done" ? (
              <button
                type="button"
                className="btn btn--sm"
                disabled={busyId === photosTask.id}
                onClick={() => changeStatus(photosTask, "done")}
              >
                <Icon name="check" size={14} /> Marcar como colocadas
              </button>
            ) : undefined
          }
        >
          A visita técnica ou o comissionamento já foram concluídos. Confirme que as fotografias estão na Drive e conclua
          a tarefa “Colocar fotos na Drive”.
        </Alert>
      )}

      <div className="tabs" role="tablist" aria-label="Secções do projeto">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            id={`tab-${t.key}`}
            aria-selected={tab === t.key}
            aria-controls={`panel-${t.key}`}
            tabIndex={tab === t.key ? 0 : -1}
            className="tab"
            onClick={() => setTab(t.key)}
            onKeyDown={(e) => {
              if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
              const idx = tabs.findIndex((x) => x.key === tab);
              const next = tabs[(idx + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
              setTab(next.key);
              document.getElementById(`tab-${next.key}`)?.focus();
            }}
          >
            {t.label}
            {t.count !== undefined && <span className="tab__count">{t.count}</span>}
          </button>
        ))}
      </div>

      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "percurso" &&
          (workflowError ? (
            <div className="card">
              <ErrorState message={workflowError} onRetry={load} />
            </div>
          ) : workflow ? (
            <ProjectWorkflow
              projectId={project.id}
              workflow={workflow}
              onChange={(updated) => {
                setWorkflow(updated);
                getProjectHistory(project.id)
                  .then(setHistory)
                  .catch(() => undefined);
              }}
            />
          ) : (
            <div className="card">
              <LoadingState label="A carregar o percurso de obra…" rows={6} />
            </div>
          ))}
        {tab === "resumo" && (
          <div className="grid grid--main-side">
            <Card title="Dados do projeto" icon="folder">
              <dl className="kv">
                <dt>Nome</dt>
                <dd>{project.name}</dd>
                <dt>Estado</dt>
                <dd>{PROJECT_STATUS_LABELS[project.status]}</dd>
                <dt>PM</dt>
                <dd>{project.pm_display_name ?? "—"}</dd>
                <dt>Data de início</dt>
                <dd>{formatDatePt(project.start_date)}</dd>
                <dt>Potência</dt>
                <dd>{project.power_kwp !== null ? `${project.power_kwp.toLocaleString("pt-PT")} kWp` : project.power_raw ?? "—"}</dd>
                <dt>Estado no ClickUp</dt>
                <dd>{project.clickup_status_mirror ?? "—"}</dd>
                <dt>Papel / observação</dt>
                <dd>{project.role || "—"}</dd>
                <dt>Notas</dt>
                <dd style={{ whiteSpace: "pre-wrap" }}>{project.notes || "—"}</dd>
                {project.equipment_notes && (
                  <>
                    <dt>Equipamento</dt>
                    <dd style={{ whiteSpace: "pre-wrap" }}>{project.equipment_notes}</dd>
                  </>
                )}
              </dl>
            </Card>
            <div className="grid">
              <Card title="Próximo passo" icon="flag" tone="info">
                {project.next_task_title ? (
                  <>
                    <div style={{ fontWeight: 650 }}>{project.next_task_title}</div>
                    <div
                      className={`small ${
                        project.next_task_due_date && project.next_task_due_date < today ? "text-danger" : "muted"
                      }`}
                    >
                      {project.next_task_due_date
                        ? `Prazo ${formatDatePt(project.next_task_due_date)} · ${relativeDayLabel(project.next_task_due_date, today)}`
                        : "Sem prazo definido"}
                    </div>
                  </>
                ) : (
                  <EmptyState compact title="Sem tarefas em aberto." />
                )}
              </Card>
              <Card title="Dados em falta" icon="info" tone="warning">
                {project.has_pm && project.has_email && project.has_contact && project.has_coordinates ? (
                  <EmptyState compact title="Dados completos." />
                ) : (
                  <div className="badges">
                    {!project.has_pm && <Badge tone="warning">PM</Badge>}
                    {!project.has_email && <Badge tone="warning">Email do cliente</Badge>}
                    {!project.has_contact && <Badge tone="warning">Contacto do cliente</Badge>}
                    {!project.has_coordinates && <Badge tone="warning">Coordenadas</Badge>}
                  </div>
                )}
              </Card>
              <Card title="Tarefas em aberto" icon="tasks">
                <div className="stat__value">{tasks === null ? "…" : openTasks.length}</div>
                <button type="button" className="btn btn--sm" style={{ marginTop: 8 }} onClick={() => setTab("tarefas")}>
                  Ver tarefas
                </button>
              </Card>
            </div>
          </div>
        )}

        {tab === "tarefas" && (
          <Card
            title="Tarefas do projeto"
            icon="tasks"
            flush
            actions={
              project.can_manage_tasks ? (
                <button type="button" className="btn btn--primary btn--sm" onClick={() => setCreatingTask(true)}>
                  <Icon name="plus" size={14} /> Nova tarefa
                </button>
              ) : undefined
            }
          >
            {tasks === null && <LoadingState />}
            {tasks?.length === 0 && <EmptyState icon="tasks" title="Sem tarefas neste projeto." />}
            {tasks && tasks.length > 0 && (
              <div className="table-wrap">
                <table className="table">
                  <caption className="sr-only">Tarefas do projeto</caption>
                  <thead>
                    <tr>
                      <th scope="col">Tarefa</th>
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
                          <span className="cell-title">
                            {t.task_type === "custom" ? t.title : DEFAULT_TASK_TYPE_LABELS[t.task_type] ?? t.title}
                          </span>
                          {(t.notes || t.description) && <span className="cell-sub">{t.notes || t.description}</span>}
                        </td>
                        <td>
                          {t.can_edit ? (
                            <select
                              className="select select--compact"
                              aria-label={`Responsável por ${t.title}`}
                              value={t.assigned_to_person_id ?? ""}
                              onChange={(e) => handleAssign(t, e.target.value)}
                            >
                              <option value="">— sem responsável —</option>
                              {people.map((p) => (
                                <option key={p.id} value={p.id}>
                                  {p.display_name}
                                </option>
                              ))}
                            </select>
                          ) : (
                            t.assigned_to_display_name ?? <span className="muted">—</span>
                          )}
                        </td>
                        <td>
                          <Badge tone={TASK_PRIORITY_TONES[t.priority]}>{TASK_PRIORITY_LABELS[t.priority]}</Badge>
                        </td>
                        <td className={`nowrap ${t.is_overdue ? "text-danger" : ""}`}>
                          {formatDatePt(t.due_date)}
                          {t.is_overdue && <span className="cell-sub text-danger">atrasada</span>}
                        </td>
                        <td>
                          <TaskStatusControl
                            task={t}
                            busy={busyId === t.id}
                            onChange={(task, status: TaskStatus) => changeStatus(task, status)}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        )}

        {tab === "historico" && (
          <Card title="Histórico de alterações" icon="history">
            {history === null && <LoadingState />}
            {history?.length === 0 && <EmptyState compact icon="history" title="Sem alterações registadas." />}
            {history && history.length > 0 && (
              <ol className="timeline">
                {history.map((h) => (
                  <li key={h.id}>
                    <div>
                      <strong>{historyFieldLabel(h)}</strong>:{" "}
                      <span className="muted">{h.old_value || "(vazio)"}</span> → {h.new_value || "(vazio)"}
                    </div>
                    <div className="small muted">
                      {h.changed_by_person_name ?? "Sistema"} · {formatDateTimePt(h.changed_at)}
                      {h.source !== "ui" && ` · origem: ${h.source}`}
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </Card>
        )}

        {tab === "cliente" && (
          <Card title="Informação do cliente" icon="user">
            <dl className="kv">
              <dt>Cliente</dt>
              <dd>{project.client_name ?? <span className="muted">por identificar</span>}</dd>
              <dt>Contacto</dt>
              <dd>{project.client_contact ?? <span className="muted">em falta</span>}</dd>
              <dt>Email</dt>
              <dd>
                {project.client_email ? (
                  <a href={`mailto:${project.client_email}`}>{project.client_email}</a>
                ) : (
                  <span className="muted">em falta</span>
                )}
              </dd>
              <dt>Morada</dt>
              <dd>{project.address ?? <span className="muted">em falta</span>}</dd>
              <dt>Coordenadas</dt>
              <dd>
                {project.lat !== null && project.lon !== null ? (
                  `${project.lat.toFixed(4)}, ${project.lon.toFixed(4)}`
                ) : (
                  <span className="muted">em falta</span>
                )}
              </dd>
            </dl>
          </Card>
        )}
      </div>

      {editing && (
        <EditProjectModal
          project={project}
          onClose={() => setEditing(false)}
          onSaved={(p) => {
            setProject(p);
            setEditing(false);
            notify("Projeto atualizado.", "success");
            load();
          }}
        />
      )}
      {creatingTask && (
        <TaskFormModal
          projects={[project]}
          people={people}
          fixedProjectId={project.id}
          onClose={() => setCreatingTask(false)}
          onCreated={() => {
            setCreatingTask(false);
            notify("Tarefa criada.", "success");
            setTab("tarefas");
            load();
          }}
        />
      )}
    </>
  );
}
