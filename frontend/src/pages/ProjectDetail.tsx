import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ApiError,
  collectProjectMaterial,
  consumeProjectMaterial,
  DEFAULT_TASK_TYPE_LABELS,
  deliverProjectMaterial,
  getProject,
  getProjectCommunicationData,
  getProjectHistory,
  getProjectInstallationData,
  getProjectInventory,
  getProjectLicensingData,
  InventoryItem,
  listInventoryItems,
  listPeople,
  listTasks,
  Person,
  Project,
  ProjectCommunicationData,
  PROJECT_STATUS_LABELS,
  ProjectHistoryEntry,
  ProjectInstallationData,
  ProjectInventorySummary,
  ProjectLicensingData,
  releaseProjectMaterial,
  reserveProjectMaterial,
  returnProjectMaterial,
  Task,
  TASK_ALLOWED_NEXT_STATUSES,
  TASK_PRIORITY_LABELS,
  TaskStatus,
  updateProject,
  updateProjectCommunicationData,
  updateProjectInstallationData,
  updateProjectLicensingData,
  updateTask,
} from "../api/client";
import Icon from "../components/Icon";
import { LifecycleStatusControl, useLifecycleStatuses } from "../components/LifecycleStatus";
import ProjectProcess from "../components/ProjectProcess";
import WorkPlanCard from "../components/WorkPlan";
import TaskFormModal from "../components/TaskForm";
import TaskStatusControl, { useTaskStatusChange } from "../components/TaskStatusControl";
import { useToast } from "../components/Toast";
import { Alert, Avatar, Badge, Card, EmptyState, ErrorState, LoadingState, Modal, ProgressBar } from "../components/ui";
import { useSession } from "../session/SessionContext";
import { formatDatePt, formatDateTimePt, relativeDayLabel, todayIsoLisbon } from "../utils/dates";
import {
  PROJECT_FIELD_LABELS,
  PROJECT_STATUS_TONES,
  TASK_PRIORITY_TONES,
  TASK_TYPE_ICONS,
} from "../utils/labels";

type TabKey = "resumo" | "processo" | "instalacao" | "licenciamento" | "tarefas" | "inventario" | "historico" | "cliente";

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

// --- Dados satélite do projeto (instalação/licenciamento/comunicação) ---
// Um único componente genérico: cada secção só difere na lista de campos
// e na função de gravação — evita repetir três vezes o mesmo padrão de
// "ver -> editar -> guardar" já usado por EditProjectModal acima.

interface DataFieldConfig<T> {
  key: keyof T & string;
  label: string;
  type?: "text" | "email" | "number" | "date" | "checkbox";
  multiline?: boolean;
}

function DataFieldRow({ label, value, type }: { label: string; value: unknown; type?: DataFieldConfig<object>["type"] }) {
  let display: React.ReactNode;
  if (value === null || value === undefined || value === "") {
    display = <span className="muted">—</span>;
  } else if (type === "checkbox") {
    display = value ? "Sim" : "Não";
  } else if (type === "date") {
    display = formatDatePt(String(value));
  } else if (typeof value === "string" && value.includes("\n")) {
    display = <span style={{ whiteSpace: "pre-wrap" }}>{value}</span>;
  } else {
    display = String(value);
  }
  return (
    <>
      <dt>{label}</dt>
      <dd>{display}</dd>
    </>
  );
}

function DataSectionCard<T extends object>({
  title,
  icon,
  tone,
  fields,
  data,
  canView,
  canEdit,
  onSave,
}: {
  title: string;
  icon: Parameters<typeof Icon>[0]["name"];
  tone?: "brand" | "success" | "warning" | "danger" | "info" | "violet" | "neutral";
  fields: DataFieldConfig<T>[];
  data: T | null;
  canView: boolean;
  canEdit: boolean;
  onSave: (changes: Partial<T>) => Promise<T>;
}) {
  const { notify } = useToast();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<string, string | boolean>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!canView) {
    return (
      <Card title={title} icon={icon} tone={tone}>
        <EmptyState compact icon="lock" title="Sem permissão para ver estes dados." />
      </Card>
    );
  }

  if (data === null) {
    return (
      <Card title={title} icon={icon} tone={tone}>
        <LoadingState rows={4} />
      </Card>
    );
  }

  function startEditing() {
    const initial: Record<string, string | boolean> = {};
    for (const f of fields) {
      const value = data![f.key];
      initial[f.key] = f.type === "checkbox" ? Boolean(value) : value === null || value === undefined ? "" : String(value);
    }
    setDraft(initial);
    setError(null);
    setEditing(true);
  }

  async function handleSave() {
    const changes: Record<string, unknown> = {};
    for (const f of fields) {
      const current = data![f.key];
      const draftValue = draft[f.key];
      let normalized: unknown;
      if (f.type === "checkbox") normalized = Boolean(draftValue);
      else if (f.type === "number") normalized = draftValue === "" ? null : Number(draftValue);
      else normalized = draftValue === "" ? null : draftValue;
      const currentComparable = current ?? (f.type === "checkbox" ? false : null);
      if (String(normalized) !== String(currentComparable)) {
        changes[f.key] = normalized;
      }
    }
    if (Object.keys(changes).length === 0) {
      setEditing(false);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSave(changes as Partial<T>);
      setEditing(false);
      notify("Dados atualizados.", "success");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Não foi possível guardar as alterações.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card
      title={title}
      icon={icon}
      tone={tone}
      actions={
        canEdit && !editing ? (
          <button type="button" className="btn btn--sm" onClick={startEditing}>
            <Icon name="wrench" size={14} /> Editar
          </button>
        ) : undefined
      }
    >
      {error && (
        <div style={{ marginBottom: 12 }}>
          <Alert tone="danger">{error}</Alert>
        </div>
      )}
      {!editing ? (
        <dl className="kv">
          {fields.map((f) => (
            <DataFieldRow key={f.key} label={f.label} value={data[f.key]} type={f.type} />
          ))}
        </dl>
      ) : (
        <div className="form-grid">
          {fields.map((f) => (
            <div key={f.key} className={`field ${f.multiline ? "span-2" : ""}`}>
              <label htmlFor={`f-${f.key}`}>{f.label}</label>
              {f.type === "checkbox" ? (
                <input
                  id={`f-${f.key}`}
                  type="checkbox"
                  checked={Boolean(draft[f.key])}
                  onChange={(e) => setDraft({ ...draft, [f.key]: e.target.checked })}
                />
              ) : f.multiline ? (
                <textarea
                  id={`f-${f.key}`}
                  className="textarea"
                  rows={3}
                  value={(draft[f.key] as string) ?? ""}
                  onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
                />
              ) : (
                <input
                  id={`f-${f.key}`}
                  className="input"
                  type={f.type === "number" ? "number" : f.type === "date" ? "date" : f.type === "email" ? "email" : "text"}
                  value={(draft[f.key] as string) ?? ""}
                  onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
                />
              )}
            </div>
          ))}
          <div className="span-2" style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button type="button" className="btn" onClick={() => setEditing(false)} disabled={saving}>
              Cancelar
            </button>
            <button type="button" className="btn btn--primary" onClick={handleSave} disabled={saving}>
              {saving ? "A guardar…" : "Guardar"}
            </button>
          </div>
        </div>
      )}
    </Card>
  );
}

const INSTALLATION_FIELDS: DataFieldConfig<ProjectInstallationData>[] = [
  { key: "client_nif", label: "NIF" },
  { key: "contact_person_name", label: "Pessoa de contacto" },
  { key: "contact_person_role", label: "Função" },
  { key: "contact_email", label: "Email de contacto", type: "email" },
  { key: "contact_phone", label: "Telefone" },
  { key: "address", label: "Morada" },
  { key: "district", label: "Distrito" },
  { key: "municipality", label: "Concelho" },
  { key: "power_kwp", label: "Potência (kWp)", type: "number" },
  { key: "panel_count", label: "Nº de painéis", type: "number" },
  { key: "panel_power_wp", label: "Potência dos painéis (Wp)", type: "number" },
  { key: "inverters", label: "Inversores" },
  { key: "batteries", label: "Baterias" },
  { key: "has_backup", label: "Backup", type: "checkbox" },
  { key: "ev_chargers", label: "Carregadores VE" },
  { key: "installation_type", label: "Tipo de instalação" },
  { key: "injection_type", label: "Injeção" },
  { key: "om_notes", label: "O&M", multiline: true },
  { key: "notes", label: "Notas", multiline: true },
];

const LICENSING_FIELDS: DataFieldConfig<ProjectLicensingData>[] = [
  { key: "upac_number", label: "Nº UPAC" },
  { key: "dgeg_number", label: "Nº DGEG" },
  { key: "cadastro_number", label: "Nº de cadastro" },
  { key: "licensing_status", label: "Estado do licenciamento" },
  { key: "registration_date", label: "Data de registo", type: "date" },
  { key: "certification_request_date", label: "Data de pedido de certificação", type: "date" },
  { key: "inspecting_entity", label: "Entidade inspetora" },
  { key: "inspection_date", label: "Data de inspeção", type: "date" },
  { key: "certificate_date", label: "Data de certificado", type: "date" },
  { key: "installer", label: "Instalador" },
  { key: "commercializer", label: "Comercializador" },
  { key: "annual_production_kwh", label: "Produção anual (kWh)", type: "number" },
  { key: "comments", label: "Comentários", multiline: true },
];

const COMMUNICATION_FIELDS: DataFieldConfig<ProjectCommunicationData>[] = [
  { key: "operator", label: "Operador" },
  { key: "gsm_m2m_number", label: "Número GSM/M2M" },
  { key: "card_identifier", label: "Identificador do cartão" },
  { key: "communication_status", label: "Estado da comunicação" },
  { key: "notes", label: "Notas", multiline: true },
];

type InventoryAction = "reserve" | "consume" | "release" | "return" | "deliver" | "collect";

const INVENTORY_ACTION_LABELS: Record<InventoryAction, string> = {
  reserve: "Reservar",
  consume: "Consumir",
  release: "Libertar reserva",
  return: "Devolver ao stock",
  deliver: "Entregar no local",
  collect: "Recolher do local",
};

function ProjectInventoryOperationModal({
  projectId,
  items,
  onClose,
  onDone,
}: {
  projectId: string;
  items: InventoryItem[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [form, setForm] = useState({ action: "reserve" as InventoryAction, item_id: "", quantity: "", reference: "" });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!form.item_id || !form.quantity) {
      setError("Escolha o item e indique a quantidade.");
      return;
    }
    setSaving(true);
    try {
      const payload = { item_id: form.item_id, quantity: form.quantity, reference: form.reference || undefined };
      const operation = {
        reserve: reserveProjectMaterial,
        consume: consumeProjectMaterial,
        release: releaseProjectMaterial,
        return: returnProjectMaterial,
        deliver: deliverProjectMaterial,
        collect: collectProjectMaterial,
      }[form.action];
      await operation(projectId, payload);
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Não foi possível registar o movimento.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title="Movimento de inventário do projeto"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancelar
          </button>
          <button type="submit" form="project-inventory-form" className="btn btn--primary" disabled={saving}>
            {saving ? "A guardar…" : "Aplicar"}
          </button>
        </>
      }
    >
      {error && <Alert tone="danger">{error}</Alert>}
      <form id="project-inventory-form" className="form-grid" onSubmit={handleSubmit}>
        <div className="field">
          <label htmlFor="inv-action">Ação</label>
          <select
            id="inv-action"
            className="select"
            value={form.action}
            onChange={(e) => setForm({ ...form, action: e.target.value as InventoryAction })}
          >
            {Object.entries(INVENTORY_ACTION_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="inv-item">Item *</label>
          <select id="inv-item" className="select" value={form.item_id} onChange={(e) => setForm({ ...form, item_id: e.target.value })}>
            <option value="">— escolha —</option>
            {items.map((i) => (
              <option key={i.id} value={i.id}>
                {i.name} ({i.unit})
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="inv-quantity">Quantidade *</label>
          <input
            id="inv-quantity"
            className="input"
            type="number"
            step="0.001"
            min="0"
            value={form.quantity}
            onChange={(e) => setForm({ ...form, quantity: e.target.value })}
          />
        </div>
        <div className="field span-2">
          <label htmlFor="inv-reference">Referência</label>
          <input id="inv-reference" className="input" value={form.reference} onChange={(e) => setForm({ ...form, reference: e.target.value })} />
        </div>
      </form>
    </Modal>
  );
}

export default function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>();
  const { notify } = useToast();
  const { can } = useSession();
  const [project, setProject] = useState<Project | null>(null);
  const lifecycleStatuses = useLifecycleStatuses();
  const [history, setHistory] = useState<ProjectHistoryEntry[] | null>(null);
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [installationData, setInstallationData] = useState<ProjectInstallationData | null>(null);
  const [licensingData, setLicensingData] = useState<ProjectLicensingData | null>(null);
  const [communicationData, setCommunicationData] = useState<ProjectCommunicationData | null>(null);
  const [inventory, setInventory] = useState<ProjectInventorySummary | null>(null);
  const [inventoryItems, setInventoryItems] = useState<InventoryItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>("resumo");
  const [editing, setEditing] = useState(false);
  const [creatingTask, setCreatingTask] = useState(false);
  const [justDone, setJustDone] = useState<string | null>(null);
  const [operatingInventory, setOperatingInventory] = useState(false);

  const canViewInstallation = can("project.view_installation_data");
  const canEditInstallation = can("project.edit_installation_data");
  const canViewLicensing = can("project.view_licensing_data");
  const canEditLicensing = can("project.edit_licensing_data");
  const canViewCommunication = can("project.view_communication_data");
  const canEditCommunication = can("project.edit_communication_data");
  const canViewInventory = can("inventory.view");
  const canOperateInventory =
    can("inventory.allocate_project") ||
    can("inventory.consume_project") ||
    can("inventory.release_project") ||
    can("inventory.deliver_project") ||
    can("inventory.collect_project");

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
    if (canViewInstallation) {
      getProjectInstallationData(projectId)
        .then(setInstallationData)
        .catch(() => setInstallationData(null));
    }
    if (canViewLicensing) {
      getProjectLicensingData(projectId)
        .then(setLicensingData)
        .catch(() => setLicensingData(null));
    }
    if (canViewCommunication) {
      getProjectCommunicationData(projectId)
        .then(setCommunicationData)
        .catch(() => setCommunicationData(null));
    }
    if (canViewInventory) {
      getProjectInventory(projectId)
        .then(setInventory)
        .catch(() => setInventory(null));
    }
  }, [projectId, canViewInstallation, canViewLicensing, canViewCommunication, canViewInventory]);

  useEffect(load, [load]);
  useEffect(() => {
    listPeople()
      .then(setPeople)
      .catch(() => setPeople([]));
    if (canViewInventory) {
      listInventoryItems()
        .then(setInventoryItems)
        .catch(() => setInventoryItems([]));
    }
  }, [canViewInventory]);

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
    { key: "resumo", label: "Resumo" },
    { key: "processo", label: "Processo" },
    ...(canViewInstallation ? [{ key: "instalacao" as TabKey, label: "Dados da instalação" }] : []),
    ...(canViewLicensing || canViewCommunication ? [{ key: "licenciamento" as TabKey, label: "Licenciamento" }] : []),
    { key: "tarefas", label: "Tarefas", count: tasks?.length },
    ...(canViewInventory ? [{ key: "inventario" as TabKey, label: "Inventário", count: inventory?.reservations.length }] : []),
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
            Progresso do workflow
          </div>
          <ProgressBar value={project.workflow_progress_percent} large label="Progresso do workflow" />
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
        {tab === "processo" && <ProjectProcess projectId={project.id} />}

        {tab === "resumo" && (
          <div className="grid grid--main-side">
            <Card title="Dados do projeto" icon="folder">
              <dl className="kv">
                <dt>Nome</dt>
                <dd>{project.name}</dd>
                <dt>Estado do projeto</dt>
                <dd>
                  <LifecycleStatusControl project={project} statuses={lifecycleStatuses} onChanged={setProject} />
                </dd>
                <dt>Tarefas</dt>
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
              <WorkPlanCard project={project} onChanged={setProject} />
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

        {tab === "instalacao" && (
          <DataSectionCard
            title="Dados da instalação"
            icon="wrench"
            fields={INSTALLATION_FIELDS}
            data={installationData}
            canView={canViewInstallation}
            canEdit={canEditInstallation}
            onSave={async (changes) => {
              const updated = await updateProjectInstallationData(project.id, changes);
              setInstallationData(updated);
              return updated;
            }}
          />
        )}

        {tab === "licenciamento" && (
          <div className="grid grid--main-side">
            <DataSectionCard
              title="Licenciamento"
              icon="checkCircle"
              fields={LICENSING_FIELDS}
              data={licensingData}
              canView={canViewLicensing}
              canEdit={canEditLicensing}
              onSave={async (changes) => {
                const updated = await updateProjectLicensingData(project.id, changes);
                setLicensingData(updated);
                return updated;
              }}
            />
            <DataSectionCard
              title="Comunicação / M2M"
              icon="lock"
              tone="violet"
              fields={COMMUNICATION_FIELDS}
              data={communicationData}
              canView={canViewCommunication}
              canEdit={canEditCommunication}
              onSave={async (changes) => {
                const updated = await updateProjectCommunicationData(project.id, changes);
                setCommunicationData(updated);
                return updated;
              }}
            />
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

        {tab === "inventario" && (
          <div className="grid grid--main-side">
            <Card
              title="Necessidades de material"
              icon="database"
              actions={
                canOperateInventory && (
                  <button type="button" className="btn btn--sm" onClick={() => setOperatingInventory(true)}>
                    <Icon name="plus" size={14} /> Movimento
                  </button>
                )
              }
            >
              {inventory === null ? (
                <LoadingState rows={3} />
              ) : inventory.requirements.length === 0 ? (
                <EmptyState compact icon="database" title="Sem necessidades de material registadas." />
              ) : (
                <table className="table">
                  <thead>
                    <tr>
                      <th>Item</th>
                      <th>Necessário</th>
                      <th>Reservado</th>
                      <th>Consumido</th>
                      <th>Em falta</th>
                      <th>Stock</th>
                    </tr>
                  </thead>
                  <tbody>
                    {inventory.requirements.map((r) => (
                      <tr key={r.id}>
                        <td>{r.item_name ?? "—"}</td>
                        <td>
                          {r.quantity_required} {r.item_unit}
                        </td>
                        <td>
                          {r.reserved} {r.item_unit}
                        </td>
                        <td>
                          {r.consumed} {r.item_unit}
                        </td>
                        <td>
                          {r.missing} {r.item_unit}
                        </td>
                        <td>
                          <Badge tone={r.available_stock_sufficient ? "success" : "danger"}>
                            {r.available_stock_sufficient ? "suficiente" : "insuficiente"}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>

            <Card title="Material no local" icon="mapPin">
              {inventory === null ? (
                <LoadingState rows={2} />
              ) : inventory.on_site.length === 0 ? (
                <EmptyState compact icon="mapPin" title="Nenhum material entregue e ainda no local." />
              ) : (
                <ul className="list">
                  {inventory.on_site.map((o) => (
                    <li key={o.item_id} className="list__item">
                      <div className="list__main">
                        <span className="list__title">{o.item_name ?? "—"}</span>
                        <div className="list__meta">Por recolher ou consumir — independente da reserva.</div>
                      </div>
                      <Badge tone="warning">
                        {o.quantity} {o.item_unit}
                      </Badge>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card title="Movimentos deste projeto" icon="history">
              {inventory === null ? (
                <LoadingState rows={3} />
              ) : inventory.reservations.length === 0 ? (
                <EmptyState compact icon="history" title="Sem movimentos de inventário neste projeto." />
              ) : (
                <ul className="list">
                  {inventory.reservations.map((m) => (
                    <li key={m.id} className="list__item">
                      <div className="list__main">
                        <span className="list__title">
                          {m.item_name ?? "—"} · {m.quantity}
                        </span>
                        <div className="list__meta">
                          {m.movement_type} · {formatDateTimePt(m.created_at)}
                          {m.reference ? ` · ${m.reference}` : ""}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
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
                      <strong>{PROJECT_FIELD_LABELS[h.field_name] ?? h.field_name}</strong>:{" "}
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
      {operatingInventory && (
        <ProjectInventoryOperationModal
          projectId={project.id}
          items={inventoryItems}
          onClose={() => setOperatingInventory(false)}
          onDone={() => {
            setOperatingInventory(false);
            notify("Movimento de inventário registado.", "success");
            load();
          }}
        />
      )}
    </>
  );
}
