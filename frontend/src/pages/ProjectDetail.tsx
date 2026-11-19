import { FormEvent, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  errorMessage,
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
  InventoryMovement,
  InventoryOwner,
  getStoredInventoryOwner,
  INVENTORY_OWNER_STORAGE_KEY,
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
  reverseProjectMovement,
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
import ProjectDeletionModal from "../components/ProjectDeletionModal";
import ProjectPrimaryPhoto from "../components/ProjectPrimaryPhoto";
import ProjectPaymentsCard from "../components/ProjectPaymentsCard";
import { LifecycleStatusControl, useLifecycleStatuses } from "../components/LifecycleStatus";
import PmInlineSelect from "../components/PmInlineSelect";
import ProjectProcess from "../components/ProjectProcess";
import ClientReport from "../components/ClientReport";
import ProjectCableDesigns from "../components/ProjectCableDesigns";
import ProjectLicensingPanel from "../components/ProjectLicensingPanel";
import ProjectSafetySheet from "../components/ProjectSafetySheet";
import WorkPlanCard from "../components/WorkPlan";
import TaskFormModal from "../components/TaskForm";
import TaskStatusControl, { useTaskStatusChange } from "../components/TaskStatusControl";
import { useToast } from "../components/Toast";
import { Alert, Badge, Card, EmptyState, ErrorState, LoadingState, Modal, ProgressBar } from "../components/ui";
import { useSession } from "../session/SessionContext";
import { formatDatePt, formatDateTimePt, relativeDayLabel, todayIsoLisbon } from "../utils/dates";
import { formatQuantity } from "../utils/quantities";
import {
  PROJECT_FIELD_LABELS,
  PROJECT_STATUS_TONES,
  TASK_PRIORITY_TONES,
  TASK_TYPE_ICONS,
} from "../utils/labels";
import "./ProjectDetail.css";

type TabKey =
  | "resumo"
  | "processo"
  | "cabos"
  | "instalacao"
  | "licenciamento"
  | "seguranca"
  | "tarefas"
  | "inventario"
  | "historico"
  | "cliente"
  | "relatorio";

type InventoryRefreshStatus = "loading" | "ready" | "error";

type InventoryRefreshState = {
  status: InventoryRefreshStatus;
  error: string | null;
};

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
      setError(errorMessage(err, "Não foi possível guardar as alterações."));
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
      setError(errorMessage(err, "Não foi possível guardar as alterações."));
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
  owner,
  onClose,
  onDone,
  prefill,
}: {
  projectId: string;
  items: InventoryItem[];
  owner: InventoryOwner;
  onClose: () => void;
  onDone: () => void;
  prefill?: { action: InventoryAction; allowedActions: InventoryAction[]; item_id: string; quantity: string; reference: string; project_id: string; owner: InventoryOwner };
}) {
  const [form, setForm] = useState(() => prefill
    ? { action: prefill.action, item_id: prefill.item_id, quantity: prefill.quantity, reference: prefill.reference }
    : { action: "reserve" as InventoryAction, item_id: "", quantity: "", reference: "" });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [requestKeys] = useState(() => new Map<string, string>());
  const active = useRef(true);
  const submitting = useRef(false);
  useLayoutEffect(() => {
    active.current = true;
    return () => { active.current = false; };
  }, []);
  useLayoutEffect(() => {
    if (prefill && (prefill.project_id !== projectId || prefill.owner !== owner)) active.current = false;
  }, [projectId, owner, prefill]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (submitting.current || (prefill && (prefill.project_id !== projectId || prefill.owner !== owner))) return;
    setError(null);
    if (!form.item_id || !form.quantity) {
      setError("Escolha o item e indique a quantidade.");
      return;
    }
    submitting.current = true;
    setSaving(true);
    try {
      const itemId = prefill?.item_id ?? form.item_id;
      const payloadKey = JSON.stringify([projectId, owner, form.action, itemId, form.quantity, form.reference || ""]);
      if (prefill && !requestKeys.has(payloadKey)) requestKeys.set(payloadKey, crypto.randomUUID());
      const payload = { item_id: itemId, quantity: form.quantity, reference: form.reference || undefined, owner,
        ...(prefill ? { idempotency_key: requestKeys.get(payloadKey) } : {}) };
      const operation = {
        reserve: reserveProjectMaterial,
        consume: consumeProjectMaterial,
        release: releaseProjectMaterial,
        return: returnProjectMaterial,
        deliver: deliverProjectMaterial,
        collect: collectProjectMaterial,
      }[form.action];
      await operation(projectId, payload);
      if (!active.current || (prefill && (prefill.project_id !== projectId || prefill.owner !== owner))) return;
      onDone();
    } catch (err) {
      if (!active.current) return;
      setError(errorMessage(err, "Não foi possível registar o movimento."));
    } finally {
      submitting.current = false;
      if (active.current) setSaving(false);
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
      {prefill && <p className="muted">Cria um novo movimento; o original mantém-se no histórico.</p>}
      <form id="project-inventory-form" className="form-grid" onSubmit={handleSubmit}>
        <div className="field">
          <label htmlFor="inv-action">Ação</label>
          <select
            id="inv-action"
            className="select"
            value={form.action}
            onChange={(e) => setForm({ ...form, action: e.target.value as InventoryAction })}
          >
            {Object.entries(INVENTORY_ACTION_LABELS).filter(([value]) => !prefill || prefill.allowedActions.includes(value as InventoryAction)).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="inv-item">Item *</label>
          <select id="inv-item" className="select" value={form.item_id} disabled={!!prefill} onChange={(e) => setForm({ ...form, item_id: e.target.value })}>
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
            min={prefill ? "0.001" : "0"}
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

function ReverseMovementModal({
  movement,
  onClose,
  onDone,
}: {
  movement: InventoryMovement;
  onClose: () => void;
  onDone: (reason: string) => Promise<void>;
}) {
  const [reason, setReason] = useState("Anulação manual");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const normalizedReason = reason.trim();
    if (!normalizedReason) {
      setError("Indique o motivo da anulação.");
      return;
    }
    if (normalizedReason.length > 220) {
      setError("O motivo não pode exceder 220 caracteres.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onDone(normalizedReason);
    } catch (err) {
      setError(errorMessage(err, "Não foi possível anular o movimento."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title="Anular movimento"
      onClose={saving ? () => undefined : onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} disabled={saving}>
            Cancelar
          </button>
          <button type="submit" form="reverse-movement-form" className="btn btn--primary" disabled={saving}>
            {saving ? "A anular…" : "Confirmar anulação"}
          </button>
        </>
      }
    >
      <p>
        O movimento de <strong>{movement.item_name ?? "material"}</strong> será mantido no histórico e será criada uma linha
        compensatória. Esta operação não pode ser desfeita automaticamente.
      </p>
      {error && <Alert tone="danger">{error}</Alert>}
      <form id="reverse-movement-form" className="form-grid" onSubmit={handleSubmit}>
        <div className="field span-2">
          <label htmlFor="reverse-movement-reason">Motivo</label>
          <input
            id="reverse-movement-reason"
            className="input"
            value={reason}
            maxLength={220}
            onChange={(e) => setReason(e.target.value)}
            disabled={saving}
          />
          <span className="small muted">Fica registado no histórico (máximo 220 caracteres).</span>
        </div>
      </form>
    </Modal>
  );
}

function isProjectTab(value: string | null): value is TabKey {
  return ["resumo", "processo", "cabos", "instalacao", "licenciamento", "seguranca", "tarefas", "inventario", "historico", "cliente", "relatorio"].includes(value ?? "");
}

function isSafeRouteSuffix(value: unknown, prefix: "?" | "#"): value is string {
  if (typeof value !== "string") return false;
  if (value === "") return true;
  if (!value.startsWith(prefix) || /[\u0000-\u001f\u007f]/.test(value)) return false;
  return prefix !== "?" || !value.includes("#");
}

function projectListReturnPath(state: unknown): string {
  if (state === null || typeof state !== "object" || Array.isArray(state)) return "/projects";
  const from = (state as { from?: unknown }).from;
  if (from === null || typeof from !== "object" || Array.isArray(from)) return "/projects";
  const origin = from as { pathname?: unknown; search?: unknown; hash?: unknown };
  if (
    origin.pathname !== "/projects" ||
    !isSafeRouteSuffix(origin.search, "?") ||
    !isSafeRouteSuffix(origin.hash, "#")
  ) return "/projects";
  return `/projects${origin.search}${origin.hash}`;
}

export default function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const { notify } = useToast();
  const { can } = useSession();
  const navigate = useNavigate();
  const projectsReturnTo = projectListReturnPath(location.state);
  const [project, setProject] = useState<Project | null>(null);
  const lifecycleStatuses = useLifecycleStatuses();
  const [history, setHistory] = useState<ProjectHistoryEntry[] | null>(null);
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  // Erros por secção: uma falha de rede ou um 403 não pode passar por "sem dados".
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [tasksError, setTasksError] = useState<string | null>(null);
  const [peopleError, setPeopleError] = useState<string | null>(null);
  const [installationData, setInstallationData] = useState<ProjectInstallationData | null>(null);
  const [licensingData, setLicensingData] = useState<ProjectLicensingData | null>(null);
  const [communicationData, setCommunicationData] = useState<ProjectCommunicationData | null>(null);
  const [inventory, setInventory] = useState<ProjectInventorySummary | null>(null);
  const [inventoryOwner, setInventoryOwner] = useState<InventoryOwner>(getStoredInventoryOwner);
  const [inventoryCatalog, setInventoryCatalog] = useState<InventoryItem[]>([]);
  const [inventoryItems, setInventoryItems] = useState<InventoryItem[]>([]);
  const [inventoryRefresh, setInventoryRefresh] = useState<InventoryRefreshState>({ status: "loading", error: null });
  const [inventoryCatalogRefresh, setInventoryCatalogRefresh] = useState<InventoryRefreshState>({ status: "loading", error: null });
  const [reversedMovementIds, setReversedMovementIds] = useState<Set<string>>(() => new Set());
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>("resumo");
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [creatingTask, setCreatingTask] = useState(false);
  const [justDone, setJustDone] = useState<string | null>(null);
  const [operatingInventory, setOperatingInventory] = useState(false);
  const [inventoryPrefill, setInventoryPrefill] = useState<{ action: InventoryAction; allowedActions: InventoryAction[]; item_id: string; quantity: string; reference: string; project_id: string; owner: InventoryOwner } | undefined>();
  const [reversingMovement, setReversingMovement] = useState<InventoryMovement | null>(null);

  useEffect(() => {
    const requestedTab = searchParams.get("tab");
    setTab(isProjectTab(requestedTab) ? requestedTab : "resumo");
  }, [searchParams]);

  const chooseTab = (nextTab: TabKey) => {
    setTab(nextTab);
    const nextParams = new URLSearchParams(searchParams);
    if (nextTab === "resumo") nextParams.delete("tab");
    else nextParams.set("tab", nextTab);
    const query = nextParams.toString();
    navigate(
      {
        pathname: location.pathname,
        search: query ? `?${query}` : "",
        hash: location.hash,
      },
      { replace: true, state: location.state }
    );
  };

  const canViewInstallation = can("project.view_installation_data");
  const canEditInstallation = can("project.edit_installation_data");
  const canViewLicensing = can("project.view_licensing_data");
  const canEditLicensing = can("project.edit_licensing_data");
  const canViewCommunication = can("project.view_communication_data");
  const canEditCommunication = can("project.edit_communication_data");
  // Credenciais, SIM e excedente: só as flags `can_*` do ProjectRead (permissão + âmbito, calculadas
  // no servidor). Não se deduzem de /api/me nem de editable_fields. O servidor valida cada escrita.
  const canEditCredentials = project?.can_edit_credentials === true;
  const canRevealCredentials = project?.can_reveal_credentials === true;
  const canEditSimCards = project?.can_edit_sim_cards === true;
  const canRevealSimSecrets = project?.can_reveal_sim_secrets === true;
  const canEditSurplusContracts = project?.can_edit_surplus_contracts === true;
  const canViewCableDesigns = can("cable_design.view");
  const canViewInventory = can("inventory.view");
  const canOperateInventory =
    can("inventory.allocate_project") ||
    can("inventory.consume_project") ||
    can("inventory.release_project") ||
    can("inventory.deliver_project") ||
    can("inventory.collect_project");
  const canReverseInventory = can("inventory.reverse_project");

  useEffect(() => {
    if (inventoryPrefill && (inventoryPrefill.project_id !== projectId || inventoryPrefill.owner !== inventoryOwner)) {
      setInventoryPrefill(undefined);
      setOperatingInventory(false);
    }
  }, [projectId, inventoryOwner, inventoryPrefill]);

  const refreshInventoryItems = useCallback(async (): Promise<boolean> => {
    if (!canViewInventory) return true;
    setInventoryCatalogRefresh({ status: "loading", error: null });
    try {
      const items = await listInventoryItems(inventoryOwner);
      setInventoryCatalog(items);
      setInventoryItems(items.filter((item) => item.is_active));
      setInventoryCatalogRefresh({ status: "ready", error: null });
      return true;
    } catch (err) {
      setInventoryCatalogRefresh({
        status: "error",
        error: errorMessage(err, "Não foi possível atualizar o catálogo de inventário."),
      });
      return false;
    }
  }, [canViewInventory, inventoryOwner]);

  const refreshProjectInventory = useCallback(async (): Promise<boolean> => {
    if (!projectId || !canViewInventory) return true;
    setInventoryRefresh({ status: "loading", error: null });
    try {
      setInventory(await getProjectInventory(projectId, inventoryOwner));
      setInventoryRefresh({ status: "ready", error: null });
      return true;
    } catch (err) {
      setInventoryRefresh({
        status: "error",
        error: errorMessage(err, "Não foi possível atualizar o inventário."),
      });
      return false;
    }
  }, [projectId, canViewInventory, inventoryOwner]);

  const loadHistory = useCallback(() => {
    if (!projectId) return;
    setHistoryError(null);
    setHistory(null);
    getProjectHistory(projectId)
      .then(setHistory)
      .catch((e) => setHistoryError(errorMessage(e)));
  }, [projectId]);

  const loadTasks = useCallback(() => {
    if (!projectId) return;
    setTasksError(null);
    setTasks(null);
    listTasks({ project_id: projectId })
      .then(setTasks)
      .catch((e) => setTasksError(errorMessage(e)));
  }, [projectId]);

  const loadPeople = useCallback(() => {
    setPeopleError(null);
    listPeople()
      .then(setPeople)
      .catch((e) => setPeopleError(errorMessage(e)));
  }, []);

  const load = useCallback(async (): Promise<boolean> => {
    if (!projectId) return true;
    setError(null);
    getProject(projectId)
      .then(setProject)
      .catch((e) => setError(errorMessage(e)));
    // Se uma recarga falhar, os dados antigos saem do ecrã: o erro não pode ficar escondido atrás deles.
    getProjectHistory(projectId)
      .then((rows) => {
        setHistory(rows);
        setHistoryError(null);
      })
      .catch((e) => {
        setHistory(null);
        setHistoryError(errorMessage(e));
      });
    listTasks({ project_id: projectId })
      .then((rows) => {
        setTasks(rows);
        setTasksError(null);
      })
      .catch((e) => {
        setTasks(null);
        setTasksError(errorMessage(e));
      });
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
    const refreshResults = canViewInventory
      ? await Promise.all([refreshProjectInventory(), refreshInventoryItems()])
      : [true, true];
    return refreshResults.every(Boolean);
  }, [
    projectId,
    canViewInstallation,
    canViewLicensing,
    canViewCommunication,
    canViewInventory,
    refreshProjectInventory,
    refreshInventoryItems,
  ]);

  useEffect(() => {
    try {
      localStorage.setItem(INVENTORY_OWNER_STORAGE_KEY, inventoryOwner);
    } catch {
      // LocalStorage pode estar indisponível em modo privado.
    }
  }, [inventoryOwner]);

  useEffect(() => {
    setReversedMovementIds(new Set());
  }, [projectId]);
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    loadPeople();
  }, [loadPeople]);

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
      notify(errorMessage(e, "Não foi possível atualizar o responsável."), "error");
    }
  }

  async function handleReverseMovement(movementId: string, reason: string) {
    if (!projectId) return;
    await reverseProjectMovement(projectId, movementId, reason);
    setReversedMovementIds((current) => new Set(current).add(movementId));
    setReversingMovement(null);
    const refreshed = await load();
    if (refreshed) {
      notify("Movimento anulado. O registo original foi mantido.", "success");
    } else {
      notify("Movimento anulado, mas não foi possível atualizar os dados. Tente novamente.", "error");
    }
  }

  if (error) {
    return (
      <>
        <Link to={projectsReturnTo} className="back-link">
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
        <Link to={projectsReturnTo} className="back-link">
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
  // O SafetySheetRead não traz `can_edit`; reutiliza-se o âmbito de edição do
  // ProjectRead e respeita-se também a permissão dedicada aceite pelo PUT.
  const canEditSafetySheet = canEdit || can("project.safety_sheet.edit");
  const openTasks = (tasks ?? []).filter((t) => t.status !== "done" && t.status !== "cancelled");
  const inventoryRefreshFailed = inventoryRefresh.status === "error" || inventoryCatalogRefresh.status === "error";
  const inventoryRefreshBusy = inventoryRefresh.status === "loading" || inventoryCatalogRefresh.status === "loading";

  const tabs: { key: TabKey; label: string; count?: number }[] = [
    { key: "resumo", label: "Resumo" },
    { key: "processo", label: "Processo" },
    ...(canViewCableDesigns ? [{ key: "cabos" as TabKey, label: "Cabos" }] : []),
    ...(canViewInstallation ? [{ key: "instalacao" as TabKey, label: "Dados da instalação" }] : []),
    ...(canViewLicensing || canViewCommunication ? [{ key: "licenciamento" as TabKey, label: "Licenciamento e comunicações" }] : []),
    { key: "seguranca", label: "Segurança" },
    { key: "tarefas", label: "Tarefas", count: tasks?.length },
    ...(canViewInventory ? [{ key: "inventario" as TabKey, label: "Inventário", count: inventory?.reservations.length }] : []),
    { key: "historico", label: "Histórico", count: history?.length },
    { key: "cliente", label: "Cliente" },
    { key: "relatorio", label: "Relatório semanal" },
  ];

  return (
    <div className="project-detail-page">
      <Link to={projectsReturnTo} className="back-link">
        <Icon name="arrowLeft" size={16} /> Projetos
      </Link>

      <ProjectPrimaryPhoto
        key={project.id}
        projectId={project.id}
        hasPhoto={project.has_project_photo}
        canEdit={project.can_edit_project_photo}
        onPhotoChanged={(hasPhoto) => setProject((current) => (
          current?.id === project.id ? { ...current, has_project_photo: hasPhoto } : current
        ))}
      >
        <div className="hero__main project-detail-page__summary">
          <div className="badges project-detail-page__status">
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
          <div className="muted small project-detail-page__metadata">
            <span className="project-detail-page__meta project-detail-page__meta--pm">
              <span className="project-detail-page__meta-label">PM</span>
              <PmInlineSelect project={project} people={people} onChanged={setProject} />
            </span>
            <span className="project-detail-page__meta">Cliente: {project.client_name ?? "por identificar"}</span>
            <span className="project-detail-page__meta">Início: {formatDatePt(project.start_date)}</span>
            {project.power_kwp !== null && <span className="project-detail-page__meta">{project.power_kwp.toLocaleString("pt-PT")} kWp</span>}
          </div>
        </div>
      </ProjectPrimaryPhoto>

      <section className="project-detail-page__workflow" aria-label="Progresso e ações do projeto">
        <div className="steps project-detail-page__steps" aria-label="Checklist padrão">
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
        <div className="hero__progress project-detail-page__actions">
          <div className="small muted project-detail-page__progress-label">
            Progresso do workflow
          </div>
          <ProgressBar value={project.workflow_progress_percent} large label="Progresso do workflow" />
          {canEdit && (
            <button type="button" className="btn btn--primary btn--block project-detail-page__edit" onClick={() => setEditing(true)}>
              <Icon name="wrench" size={16} /> Editar projeto
            </button>
          )}
          {project.can_delete === true && (
            <button type="button" className="btn btn--danger btn--block project-detail-page__delete" onClick={() => setDeleting(true)}>
              Apagar projeto
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

      <div className="tabs project-detail-page__tabs" role="tablist" aria-label="Secções do projeto">
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
            onClick={() => chooseTab(t.key)}
            onKeyDown={(e) => {
              if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
              const idx = tabs.findIndex((x) => x.key === tab);
              const next = tabs[(idx + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
              chooseTab(next.key);
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

        {tab === "cabos" && canViewCableDesigns && <ProjectCableDesigns projectId={project.id} />}

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
              {project.payments != null && (
                <ProjectPaymentsCard
                  project={project}
                  onPaymentsChanged={(payments) => setProject((current) => current ? { ...current, payments } : current)}
                />
              )}
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
                <div className="stat__value">{tasks === null ? (tasksError ? "—" : "…") : openTasks.length}</div>
                <button type="button" className="btn btn--sm" style={{ marginTop: 8 }} onClick={() => chooseTab("tarefas")}>
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
          <ProjectLicensingPanel
            projectId={project.id}
            licensing={licensingData}
            communication={communicationData}
            canViewLicensing={canViewLicensing}
            canEditLicensing={canEditLicensing}
            canViewCommunication={canViewCommunication}
            canEditCommunication={canEditCommunication}
            canEditCredentials={canEditCredentials}
            canRevealCredentials={canRevealCredentials}
            canEditSimCards={canEditSimCards}
            canRevealSimSecrets={canRevealSimSecrets}
            canEditSurplusContracts={canEditSurplusContracts}
            onLicensingSaved={setLicensingData}
            onCommunicationSaved={setCommunicationData}
          />
        )}

        {tab === "seguranca" && <ProjectSafetySheet projectId={project.id} canEdit={canEditSafetySheet} />}

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
            {peopleError && (
              <Alert
                tone="warning"
                title="Não foi possível carregar a lista de pessoas."
                action={
                  <button type="button" className="btn btn--sm" onClick={loadPeople}>
                    Tentar novamente
                  </button>
                }
              >
                Não é possível atribuir responsáveis até a lista ser carregada. {peopleError}
              </Alert>
            )}
            {tasks === null && !tasksError && <LoadingState />}
            {tasks === null && tasksError && <ErrorState message={tasksError} onRetry={loadTasks} />}
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
          <>
            <div className="cluster section-gap" role="group" aria-label="Inventário por proprietário">
              <button type="button" className={`btn btn--sm${inventoryOwner === "solcor" ? " btn--primary" : ""}`} aria-pressed={inventoryOwner === "solcor"} onClick={() => setInventoryOwner("solcor")}>
                Solcor
              </button>
              <button type="button" className={`btn btn--sm${inventoryOwner === "verde_milenar" ? " btn--primary" : ""}`} aria-pressed={inventoryOwner === "verde_milenar"} onClick={() => setInventoryOwner("verde_milenar")}>
                Verde Milenar
              </button>
            </div>
            {inventoryRefreshFailed && (
              <Alert
                tone="danger"
                title="Inventário desatualizado"
                action={
                  <button type="button" className="btn btn--sm" onClick={() => void load()} disabled={inventoryRefreshBusy}>
                    {inventoryRefreshBusy ? "A atualizar…" : "Tentar novamente"}
                  </button>
                }
              >
                {inventoryRefresh.status === "error" && (
                  <div>
                    <strong>Não foi possível atualizar o inventário.</strong> {inventoryRefresh.error}
                  </div>
                )}
                {inventoryCatalogRefresh.status === "error" && (
                  <div>
                    <strong>Não foi possível atualizar o catálogo.</strong> {inventoryCatalogRefresh.error}
                  </div>
                )}
                {inventory !== null && <div>Os dados apresentados são os últimos conhecidos até o refresh terminar.</div>}
              </Alert>
            )}
            <div className="grid grid--main-side">
            <Card
              title="Necessidades de material"
              icon="database"
              actions={
                canOperateInventory && (
                  <button
                    type="button"
                    className="btn btn--sm"
                    onClick={() => setOperatingInventory(true)}
                    disabled={inventoryCatalogRefresh.status !== "ready"}
                    title={inventoryCatalogRefresh.status === "ready" ? undefined : "Aguarde a atualização do catálogo."}
                  >
                    <Icon name="plus" size={14} /> Movimento
                  </button>
                )
              }
            >
              {inventory === null ? (
                inventoryRefresh.status === "loading" ? (
                  <LoadingState rows={3} />
                ) : (
                  <EmptyState compact icon="database" title="Dados de inventário indisponíveis." />
                )
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
                        <td>{formatQuantity(r.quantity_required, r.item_unit)} {r.item_unit}</td>
                        <td>{formatQuantity(r.reserved, r.item_unit)} {r.item_unit}</td>
                        <td>{formatQuantity(r.consumed, r.item_unit)} {r.item_unit}</td>
                        <td>{formatQuantity(r.missing, r.item_unit)} {r.item_unit}</td>
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
                inventoryRefresh.status === "loading" ? (
                  <LoadingState rows={2} />
                ) : (
                  <EmptyState compact icon="mapPin" title="Dados de inventário indisponíveis." />
                )
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
                      <Badge tone="warning">{formatQuantity(o.quantity, o.item_unit)} {o.item_unit}</Badge>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card title="Movimentos deste projeto" icon="history">
              {inventory === null ? (
                inventoryRefresh.status === "loading" ? (
                  <LoadingState rows={3} />
                ) : (
                  <EmptyState compact icon="history" title="Dados de inventário indisponíveis." />
                )
              ) : inventory.reservations.length === 0 ? (
                <EmptyState compact icon="history" title="Sem movimentos de inventário neste projeto." />
              ) : (
                <ul className="list">
                  {inventory.reservations.map((m) => {
                    const itemUnit = inventoryCatalog.find((item) => item.id === m.item_id)?.unit;
                    const hasReversal = inventory.reservations.some((candidate) => candidate.reversal_of_movement_id === m.id);
                    const canReverse =
                      canReverseInventory && !reversedMovementIds.has(m.id) && !m.reversal_of_movement_id && !hasReversal;
                    const shortcutActions: InventoryAction[] = m.reversal_of_movement_id || hasReversal || reversedMovementIds.has(m.id)
                      ? []
                      : m.movement_type === "reserva"
                        ? [ ...(can("inventory.deliver_project") ? ["deliver" as const] : []), ...(can("inventory.consume_project") ? ["consume" as const] : []) ]
                        : m.movement_type === "entrega" && can("inventory.consume_project") ? ["consume"] : [];
                    return (
                      <li key={m.id} className="list__item">
                        <div className="list__main">
                          <span className="list__title">
                            {m.item_name ?? "—"} · {formatQuantity(m.quantity, itemUnit)} {itemUnit ?? ""}
                          </span>
                          <div className="list__meta">
                            {m.reversal_of_movement_id ? "Anulação" : m.movement_type} · {formatDateTimePt(m.created_at)}
                            {m.reference ? ` · ${m.reference}` : ""}
                          </div>
                        </div>
                        {canReverse && (
                          <button
                            type="button"
                            className="btn btn--sm"
                            onClick={() => setReversingMovement(m)}
                            aria-label={`Anular movimento de ${m.item_name ?? "material"}`}
                          >
                            Anular
                          </button>
                        )}
                        {shortcutActions.length > 0 && (
                          <button type="button" className="btn btn--sm" aria-label={`Atualizar movimento de ${m.item_name ?? "material"}`} onClick={() => {
                            setInventoryPrefill({ action: shortcutActions[0], allowedActions: shortcutActions, item_id: m.item_id, quantity: m.quantity, reference: m.reference ?? "", project_id: project.id, owner: inventoryOwner });
                            setOperatingInventory(true);
                          }}>Atualizar</button>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </Card>
          </div>
          </>
        )}

        {tab === "historico" && (
          <Card title="Histórico de alterações" icon="history">
            {history === null && !historyError && <LoadingState />}
            {history === null && historyError && <ErrorState message={historyError} onRetry={loadHistory} />}
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

        {tab === "relatorio" && <ClientReport projectId={project.id} />}

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
            chooseTab("tarefas");
            load();
          }}
        />
      )}
      {operatingInventory && (!inventoryPrefill || (inventoryPrefill.project_id === projectId && inventoryPrefill.project_id === project.id && inventoryPrefill.owner === inventoryOwner)) && (
        <ProjectInventoryOperationModal
          key={`${project.id}:${inventoryOwner}:${inventoryPrefill ? "shortcut" : "normal"}`}
          projectId={project.id}
          items={inventoryItems}
          owner={inventoryOwner}
          prefill={inventoryPrefill}
          onClose={() => { setOperatingInventory(false); setInventoryPrefill(undefined); }}
          onDone={() => {
            setOperatingInventory(false);
            setInventoryPrefill(undefined);
            notify("Movimento de inventário registado.", "success");
            load();
          }}
        />
      )}
      {reversingMovement && (
        <ReverseMovementModal
          movement={reversingMovement}
          onClose={() => setReversingMovement(null)}
          onDone={(reason) => handleReverseMovement(reversingMovement.id, reason)}
        />
      )}
      {deleting && (
        <ProjectDeletionModal
          project={project}
          onClose={() => setDeleting(false)}
          onDeleted={() => {
            setDeleting(false);
            notify("Projeto apagado.", "success");
            navigate("/projects", { replace: true });
          }}
        />
      )}
    </div>
  );
}
