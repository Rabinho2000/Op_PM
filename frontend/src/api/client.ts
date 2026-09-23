// Cliente da API. Fase 1 (D-031): login real via Microsoft Entra ID
// (MSAL, ver src/auth/msal.ts) já está implementado — quando há uma conta
// MSAL ativa, todo o pedido leva `Authorization: Bearer <access token da
// API>`. O mecanismo de desenvolvimento (X-Dev-User-Email) continua a
// existir só para local/test (ver src/auth/msal.ts:devLoginEnabled e
// app/security/current_user.py no backend) e nunca é enviado ao mesmo
// tempo que um Bearer token — os dois caminhos são mutuamente exclusivos,
// tal como no backend. Nenhuma chave/segredo de integração (Claude, Graph,
// ClickUp, Financial, Entra) é colocada aqui: essas só existem no backend.
import { SessionExpiredError, devLoginEnabled, getActiveMsalAccount, getApiAccessToken, logoutFromMicrosoft } from "../auth/msal";

// "/" (ou vazio) = mesma origem do frontend — usado pela demonstração em
// Docker, onde o nginx encaminha /api, /me e /health para o backend.
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(/\/+$/, "");
const DEV_USER_STORAGE_KEY = "op_pm_dev_user_email";

// Hardening (fecho da Fase 1): `devLoginEnabled` já desliga a SECÇÃO da UI
// de login de desenvolvimento (src/pages/Login.tsx) fora de local/test —
// mas isso sozinho não impedia um valor antigo, guardado em localStorage
// antes de um build de produção (ou antes de alguém desligar
// VITE_ENABLE_DEV_LOGIN), de continuar a ser lido e enviado como
// `X-Dev-User-Email` para sempre. As três funções abaixo tratam
// `devLoginEnabled=false` como "não há utilizador de desenvolvimento
// nenhum", ponto final — nunca leem nem escrevem localStorage nesse caso —
// e uma limpeza corre uma vez ao carregar este módulo para remover
// qualquer valor antigo já guardado.
export function getDevUser(): string | null {
  if (!devLoginEnabled) return null;
  try {
    return localStorage.getItem(DEV_USER_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setDevUser(email: string): void {
  if (!devLoginEnabled) return; // nunca grava um login de desenvolvimento fora de local/test
  try {
    localStorage.setItem(DEV_USER_STORAGE_KEY, email);
  } catch {
    // localStorage indisponível (ex. modo privado) — sessão não persiste
    // entre recarregamentos, mas a aplicação continua utilizável.
  }
}

export function clearDevUser(): void {
  try {
    localStorage.removeItem(DEV_USER_STORAGE_KEY);
  } catch {
    // ver setDevUser
  }
}

if (!devLoginEnabled) {
  // Limpa qualquer valor antigo (ex. gravado numa sessão de
  // desenvolvimento anterior, antes de um build de produção) — nunca deve
  // sobreviver silenciosamente a uma mudança de VITE_ENABLE_DEV_LOGIN.
  clearDevUser();
}

// true quando há uma sessão MSAL real ativa — App.tsx/NavBar.tsx usam
// isto (em vez de espreitar o MSAL diretamente) para decidir o que
// mostrar, mantendo um único ponto de verdade sobre "qual sessão está
// ativa" nesta camada.
export function hasActiveSession(): boolean {
  return getActiveMsalAccount() !== null || getDevUser() !== null;
}

export function getSessionDisplayName(): string | null {
  const account = getActiveMsalAccount();
  if (account) return account.username || account.name || "sessão Microsoft";
  return getDevUser();
}

// Termina a sessão atual, seja ela qual for — nunca deixa as duas por
// engano (ex. um login de desenvolvimento antigo esquecido em
// localStorage depois de mudar para login real).
export async function logoutCurrentSession(): Promise<void> {
  const account = getActiveMsalAccount();
  clearDevUser();
  if (account) {
    await logoutFromMicrosoft(); // navega para fora da app (postLogoutRedirectUri)
  }
}

function redirectToExpiredSession(): void {
  if (typeof window === "undefined") return;
  if (window.location.pathname === "/login") return;
  window.location.assign("/login?sessionExpired=1");
}

class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(`${status}: ${detail}`);
    this.status = status;
    this.detail = detail;
  }
}

async function authHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = {};
  const usingMsal = getActiveMsalAccount() !== null;
  if (usingMsal) {
    let token: string | null;
    try {
      // Renovação silenciosa: acquireTokenSilent (dentro de
      // getApiAccessToken) tenta sempre usar/renovar o token em cache
      // primeiro, sem qualquer interação visível ao utilizador.
      token = await getApiAccessToken();
    } catch (err) {
      if (err instanceof SessionExpiredError) {
        redirectToExpiredSession();
      }
      throw err;
    }
    if (token) headers["Authorization"] = `Bearer ${token}`;
  } else {
    const devUser = getDevUser();
    if (devUser) headers["X-Dev-User-Email"] = devUser;
  }
  return headers;
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (res.status === 401 && getActiveMsalAccount() !== null) {
    // O backend recusou o token (ex. revogado, ou utilizador nunca
    // provisionado) mesmo depois de uma renovação silenciosa bem-sucedida
    // — trata como sessão expirada em vez de repetir o pedido às cegas.
    redirectToExpiredSession();
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // corpo não-JSON — mantém statusText
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(await authHeaders()),
    ...(init?.headers as Record<string, string> | undefined),
  };
  const res = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  return handleResponse<T>(res);
}

// Upload multipart — nunca define Content-Type manualmente, o browser
// tem de gerar o boundary do multipart/form-data sozinho.
async function requestUpload<T>(path: string, formData: FormData): Promise<T> {
  const headers = await authHeaders();
  const res = await fetch(`${API_BASE_URL}${path}`, { method: "POST", body: formData, headers });
  return handleResponse<T>(res);
}

const apiGet = <T>(path: string) => request<T>(path);
const apiPatch = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
const apiPost = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined });
const apiUpload = <T>(path: string, formData: FormData) => requestUpload<T>(path, formData);

export { ApiError };

// --- /health, /me ---

export interface HealthResponse {
  status: string;
  app_env: string;
  database_dialect: string;
  integrations: Record<string, boolean>;
  demo_mode?: boolean;
  dev_login_available?: boolean;
}

export interface MeResponse {
  user_id: string;
  email: string;
  person_id: string;
  display_name?: string;
  roles: string[];
  role_labels?: string[];
  permissions: string[];
}

export const getHealth = () => apiGet<HealthResponse>("/health");
export const getMe = () => apiGet<MeResponse>("/me");

// --- /api/people ---

export interface Person {
  id: string;
  display_name: string;
  email: string | null;
  is_active: boolean;
}

export const listPeople = () => apiGet<Person[]>("/api/people");

// --- /api/projects ---

export interface Project {
  id: string;
  name: string;
  client_name: string | null;
  client_contact: string | null;
  client_email: string | null;
  address: string | null;
  lat: number | null;
  lon: number | null;
  power_kwp: number | null;
  power_raw: string | null;
  pm_person_id: string | null;
  pm_display_name: string | null;
  start_date: string | null;
  clickup_status_mirror: string | null;
  role: string | null;
  equipment_notes: string | null;
  injection_notes: string | null;
  om_notes: string | null;
  commercial_assumptions: string | null;
  upac_registration: string | null;
  m2m_card: string | null;
  upac_connection_date_raw: string | null;
  award_year_raw: string | null;
  is_active: boolean;
  notes: string;
  has_pm: boolean;
  has_email: boolean;
  has_coordinates: boolean;
  has_contact: boolean;
  created_at: string;
  updated_at: string;

  // Derivados de tarefas — ver backend app/services/projects.py:compute_project_task_summary
  status: "nao_iniciado" | "em_curso" | "concluido";
  next_task_title: string | null;
  next_task_due_date: string | null;
  overdue_tasks_count: number;
  workflow_progress_percent: number;
  photos_pending_warning: boolean;

  // Permissões efetivas do utilizador atual sobre este projeto (servidor).
  editable_fields: string[];
  can_manage_tasks: boolean;
}

export type ProjectStatus = Project["status"];

export const PROJECT_STATUS_LABELS: Record<Project["status"], string> = {
  nao_iniciado: "Não iniciado",
  em_curso: "Em curso",
  concluido: "Concluído",
};

export interface ProjectHistoryEntry {
  id: string;
  project_id: string;
  field_name: string;
  old_value: string | null;
  new_value: string | null;
  changed_by_person_id: string | null;
  changed_by_person_name: string | null;
  source: string;
  note: string;
  related_staging_record_id: string | null;
  changed_at: string;
}

export interface ProjectFilters {
  pm_person_id?: string;
  is_active?: boolean;
  q?: string;
  status?: ProjectStatus;
  start_from?: string;
  start_to?: string;
}

export function listProjects(filters: ProjectFilters = {}): Promise<Project[]> {
  const params = new URLSearchParams();
  if (filters.pm_person_id) params.set("pm_person_id", filters.pm_person_id);
  if (filters.is_active !== undefined) params.set("is_active", String(filters.is_active));
  if (filters.q) params.set("q", filters.q);
  if (filters.status) params.set("status", filters.status);
  if (filters.start_from) params.set("start_from", filters.start_from);
  if (filters.start_to) params.set("start_to", filters.start_to);
  const qs = params.toString();
  return apiGet<Project[]>(`/api/projects${qs ? `?${qs}` : ""}`);
}

export const getProject = (id: string) => apiGet<Project>(`/api/projects/${id}`);
export const updateProject = (id: string, changes: Partial<Project>) =>
  apiPatch<Project>(`/api/projects/${id}`, changes);
export const getProjectHistory = (id: string) => apiGet<ProjectHistoryEntry[]>(`/api/projects/${id}/history`);

// --- /api/migration ---

export interface PersonReconciliationItem {
  id: string;
  raw_name: string;
  normalized_name: string;
  reason: string;
  candidate_person_ids_json: string;
  status: string;
  resolved_person_id: string | null;
  resolved_by_person_id: string | null;
  resolved_at: string | null;
  resolution_note: string;
  created_at: string;
}

export const listReconciliationItems = (status = "pending") =>
  apiGet<PersonReconciliationItem[]>(`/api/migration/reconciliation-items?status=${status}`);

export interface ResolveReconciliationPayload {
  action: "link_existing" | "create_new" | "ignore";
  target_person_id?: string;
  new_person_display_name?: string;
  note?: string;
}

export const resolveReconciliationItem = (id: string, payload: ResolveReconciliationPayload) =>
  apiPost<PersonReconciliationItem>(`/api/migration/reconciliation-items/${id}/resolve`, payload);

export interface StagingProjectRecord {
  id: string;
  import_batch_id: string;
  source_system: string;
  external_id: string;
  status: string;
  conflict_reason: string | null;
  candidate_project_ids_json: string;
  pm_name_raw: string | null;
  candidate_person_ids_json: string;
  pm_explicitly_unassigned: boolean;
  resolved_action: string | null;
  resolved_target_project_id: string | null;
  resolution_note: string;
  promoted_project_id: string | null;
  promoted_at: string | null;
  reverted_at: string | null;
  reverted_reason: string;
  created_at: string;
  updated_at: string;
}

export interface ImportBatch {
  id: string;
  source_system: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  started_by_person_id: string | null;
  checksum: string;
  records_seen: number;
  records_ready: number;
  records_conflicted: number;
}

export const listImportBatches = () => apiGet<ImportBatch[]>("/api/migration/import-batches");
export const listStagingRecords = (batchId: string, status?: string) =>
  apiGet<StagingProjectRecord[]>(
    `/api/migration/import-batches/${batchId}/records${status ? `?status=${status}` : ""}`
  );

export interface ResolveConflictPayload {
  action: "create_new" | "link_existing" | "skip" | "proceed_without_pm";
  target_project_id?: string;
  note?: string;
}

export const resolveStagingConflict = (id: string, payload: ResolveConflictPayload) =>
  apiPost<StagingProjectRecord>(`/api/migration/staging-records/${id}/resolve-conflict`, payload);
export const promoteStagingRecord = (id: string) =>
  apiPost<StagingProjectRecord>(`/api/migration/staging-records/${id}/promote`);
export const rollbackStagingRecord = (id: string, reason: string) =>
  apiPost<StagingProjectRecord>(`/api/migration/staging-records/${id}/rollback`, { reason });
export const retryPromotionAfterRollback = (id: string) =>
  apiPost<StagingProjectRecord>(`/api/migration/staging-records/${id}/retry-promotion`);
export const retryPmResolution = (id: string) =>
  apiPost<StagingProjectRecord>(`/api/migration/staging-records/${id}/retry-pm-resolution`);

// --- /api/tasks ---

export type TaskStatus = "todo" | "in_progress" | "blocked" | "done" | "cancelled";
export type TaskPriority = "low" | "medium" | "high" | "urgent";

export const TASK_STATUS_LABELS: Record<TaskStatus, string> = {
  todo: "Por fazer",
  in_progress: "Em curso",
  blocked: "Bloqueada",
  done: "Concluída",
  cancelled: "Cancelada",
};

// Categoria operacional (D-058) — só field/material contam para o attention
// do mapa; o servidor valida sempre o valor (TASK_CATEGORIES).
export type TaskCategory = "workflow" | "field" | "material" | "documentation" | "commercial" | "other";

export const TASK_CATEGORY_LABELS: Record<TaskCategory, string> = {
  workflow: "Workflow",
  field: "Campo",
  material: "Material",
  documentation: "Documentação",
  commercial: "Comercial",
  other: "Outra",
};

export const TASK_PRIORITY_LABELS: Record<TaskPriority, string> = {
  low: "Baixa",
  medium: "Média",
  high: "Alta",
  urgent: "Urgente",
};

// Mesma máquina de estados de app/services/tasks.py:TASK_TRANSITIONS — só
// para desenhar a UI (o servidor é sempre a fonte de verdade; um pedido
// inválido continua a ser recusado mesmo que a UI deixasse passar).
export const TASK_ALLOWED_NEXT_STATUSES: Record<TaskStatus, TaskStatus[]> = {
  todo: ["todo", "in_progress", "blocked", "done", "cancelled"],
  in_progress: ["in_progress", "todo", "blocked", "done", "cancelled"],
  blocked: ["blocked", "todo", "in_progress", "cancelled"],
  done: ["done", "todo", "in_progress"],
  cancelled: ["cancelled", "todo"],
};

export const DEFAULT_TASK_TYPE_LABELS: Record<string, string> = {
  visita_tecnica: "Visita técnica",
  preparacao_instalacao: "Preparação da instalação",
  instalacao: "Instalação",
  comissionamento: "Comissionamento",
  fotos_drive: "Colocar fotos na Drive",
  custom: "Tarefa personalizada",
};

export interface Task {
  id: string;
  project_id: string;
  title: string;
  task_type: string;
  description: string;
  status: TaskStatus;
  priority: TaskPriority;
  category: TaskCategory;
  assigned_to_person_id: string | null;
  due_date: string | null;
  completed_at: string | null;
  notes: string;
  created_by_person_id: string | null;
  created_at: string;
  updated_at: string;
  project_name: string | null;
  assigned_to_display_name: string | null;
  is_overdue: boolean;
  can_edit: boolean;
}

export interface TaskHistoryEntry {
  id: string;
  task_id: string;
  field_name: string;
  old_value: string | null;
  new_value: string | null;
  changed_by_person_id: string | null;
  changed_by_person_name: string | null;
  source: string;
  note: string;
  changed_at: string;
}

export interface TaskFilters {
  project_id?: string;
  status?: TaskStatus;
  assigned_to_person_id?: string;
  overdue_only?: boolean;
  due_before?: string;
  due_after?: string;
  priority?: TaskPriority;
}

export function listTasks(filters: TaskFilters = {}): Promise<Task[]> {
  const params = new URLSearchParams();
  if (filters.project_id) params.set("project_id", filters.project_id);
  if (filters.status) params.set("status", filters.status);
  if (filters.assigned_to_person_id) params.set("assigned_to_person_id", filters.assigned_to_person_id);
  if (filters.overdue_only) params.set("overdue_only", "true");
  if (filters.due_before) params.set("due_before", filters.due_before);
  if (filters.due_after) params.set("due_after", filters.due_after);
  if (filters.priority) params.set("priority", filters.priority);
  const qs = params.toString();
  return apiGet<Task[]>(`/api/tasks${qs ? `?${qs}` : ""}`);
}

export const getTask = (id: string) => apiGet<Task>(`/api/tasks/${id}`);
export const getTaskHistory = (id: string) => apiGet<TaskHistoryEntry[]>(`/api/tasks/${id}/history`);

export interface TaskCreatePayload {
  project_id: string;
  title: string;
  task_type?: string;
  description?: string;
  priority?: TaskPriority;
  category?: TaskCategory;
  assigned_to_person_id?: string | null;
  due_date?: string | null;
  notes?: string;
}

export const createTask = (payload: TaskCreatePayload) => apiPost<Task>("/api/tasks", payload);

export interface TaskUpdatePayload {
  title?: string;
  description?: string;
  status?: TaskStatus;
  priority?: TaskPriority;
  assigned_to_person_id?: string | null;
  due_date?: string | null;
  notes?: string;
}

export const updateTask = (id: string, payload: TaskUpdatePayload) => apiPatch<Task>(`/api/tasks/${id}`, payload);

// --- /api/absences ---

export type AbsenceType = "ferias" | "baixa_medica" | "outro";
export type AbsenceStatus = "aprovada" | "cancelada";

export const ABSENCE_TYPE_LABELS: Record<AbsenceType, string> = {
  ferias: "Férias",
  baixa_medica: "Baixa médica",
  outro: "Outro",
};

export interface Absence {
  id: string;
  person_id: string;
  start_date: string;
  end_date: string;
  type: AbsenceType;
  note: string;
  status: AbsenceStatus;
  created_by_person_id: string | null;
  created_at: string;
  updated_at: string;
  person_display_name: string | null;
  can_cancel: boolean;
}

export function listAbsences(filters: { person_id?: string; status?: string } = {}): Promise<Absence[]> {
  const params = new URLSearchParams();
  if (filters.person_id) params.set("person_id", filters.person_id);
  if (filters.status) params.set("status", filters.status);
  const qs = params.toString();
  return apiGet<Absence[]>(`/api/absences${qs ? `?${qs}` : ""}`);
}

export interface AbsenceCreatePayload {
  person_id: string;
  start_date: string;
  end_date: string;
  type?: AbsenceType;
  note?: string;
}

export const createAbsence = (payload: AbsenceCreatePayload) => apiPost<Absence>("/api/absences", payload);
export const cancelAbsence = (id: string) => apiPatch<Absence>(`/api/absences/${id}`, { status: "cancelada" });

// --- /api/dashboard ---

export interface ProjectMini {
  id: string;
  name: string;
  pm_display_name: string | null;
  start_date: string | null;
  missing_fields: string[];
}

export interface TaskMini {
  id: string;
  title: string;
  task_type: string;
  priority: TaskPriority;
  project_id: string;
  project_name: string;
  assigned_to_display_name: string | null;
  due_date: string | null;
}

export interface AbsenceMini {
  id: string;
  person_id: string;
  person_display_name: string;
  start_date: string;
  end_date: string;
  type: AbsenceType;
}

export interface BirthdayMini {
  person_id: string;
  person_display_name: string;
  birth_date: string;
  days_until: number;
}

export interface WeekDaySummary {
  date: string;
  tasks_due_count: number;
  tasks_completed_count: number;
  people_absent_count: number;
}

export interface DashboardSummary {
  generated_at: string;
  scope: "all" | "own" | "none";
  week_start: string;
  week_end: string;
  active_projects_count: number;
  projects_starting_next_30_days: ProjectMini[];
  overdue_tasks: TaskMini[];
  tasks_due_this_week: TaskMini[];
  pending_technical_visits: TaskMini[];
  pending_commissioning: TaskMini[];
  projects_without_pm: ProjectMini[];
  projects_missing_data: ProjectMini[];
  current_absences: AbsenceMini[];
  upcoming_absences: AbsenceMini[];
  upcoming_birthdays: BirthdayMini[];
  urgent_tasks: TaskMini[];
  projects_photos_pending: ProjectMini[];
  week_overview: WeekDaySummary[];
}

export const getDashboardSummary = () => apiGet<DashboardSummary>("/api/dashboard/summary");

// --- Inventário (MVP de Operações) ---

export interface InventoryItem {
  id: string;
  sku: string;
  name: string;
  unit: string;
  min_stock: string;
  preferred_supplier_id: string | null;
  lead_time_days: number | null;
  is_active: boolean;
  physical_stock: string;
  available_stock: string;
  total_reserved: string;
  below_min_stock: boolean;
}

export const listInventoryItems = () => apiGet<InventoryItem[]>("/api/inventory/items");

export interface InventoryMovement {
  id: string;
  item_id: string;
  movement_type: string;
  quantity: string;
  project_id: string | null;
  location_id: string | null;
  destination_location_id: string | null;
  unit_cost: string | null;
  reference: string;
  idempotency_key: string | null;
  created_by_person_id: string | null;
  created_at: string;
  item_name: string | null;
  project_name: string | null;
}

export function listInventoryMovements(
  filters: { item_id?: string; project_id?: string; movement_type?: string } = {},
): Promise<InventoryMovement[]> {
  const params = new URLSearchParams();
  if (filters.item_id) params.set("item_id", filters.item_id);
  if (filters.project_id) params.set("project_id", filters.project_id);
  if (filters.movement_type) params.set("movement_type", filters.movement_type);
  const qs = params.toString();
  return apiGet<InventoryMovement[]>(`/api/inventory/movements${qs ? `?${qs}` : ""}`);
}

export const createCentralMovement = (payload: {
  item_id: string;
  movement_type: "entrada" | "ajuste";
  quantity: string;
  reference?: string;
  unit_cost?: string;
}) => apiPost<InventoryMovement>("/api/inventory/movements", payload);

export interface ProjectMaterialRequirement {
  id: string;
  project_id: string;
  item_id: string;
  quantity_required: string;
  notes: string;
  source: string;
  created_at: string;
  item_name: string | null;
  item_unit: string | null;
  reserved: string;
  consumed: string;
  missing: string;
  available_stock_sufficient: boolean;
}

export interface ProjectInventorySummary {
  project_id: string;
  requirements: ProjectMaterialRequirement[];
  reservations: InventoryMovement[];
}

export const getProjectInventory = (projectId: string) =>
  apiGet<ProjectInventorySummary>(`/api/projects/${projectId}/inventory`);

export const createMaterialRequirement = (
  projectId: string,
  payload: { item_id: string; quantity_required: string; notes?: string },
) => apiPost<ProjectMaterialRequirement>(`/api/projects/${projectId}/inventory/requirements`, payload);

export const updateMaterialRequirement = (
  projectId: string,
  requirementId: string,
  payload: { quantity_required?: string; notes?: string },
) => apiPatch<ProjectMaterialRequirement>(`/api/projects/${projectId}/inventory/requirements/${requirementId}`, payload);

function projectInventoryOperation(
  projectId: string,
  action: "reserve" | "consume" | "release" | "return",
  payload: { item_id: string; quantity: string; reference?: string },
) {
  return apiPost<InventoryMovement>(`/api/projects/${projectId}/inventory/${action}`, payload);
}

export const reserveProjectMaterial = (projectId: string, payload: { item_id: string; quantity: string; reference?: string }) =>
  projectInventoryOperation(projectId, "reserve", payload);
export const consumeProjectMaterial = (projectId: string, payload: { item_id: string; quantity: string; reference?: string }) =>
  projectInventoryOperation(projectId, "consume", payload);
export const releaseProjectMaterial = (projectId: string, payload: { item_id: string; quantity: string; reference?: string }) =>
  projectInventoryOperation(projectId, "release", payload);
export const returnProjectMaterial = (projectId: string, payload: { item_id: string; quantity: string; reference?: string }) =>
  projectInventoryOperation(projectId, "return", payload);

// --- Metas e indicadores (página única — nunca "Metas"/"Dashboards" separados) ---

export type GoalMetric =
  | "installations"
  | "kwp"
  | "projects_completed"
  | "projects_certified"
  | "power_installed"
  | "power_delivered";

export const GOAL_METRIC_LABELS: Record<GoalMetric, string> = {
  installations: "Instalações concluídas",
  kwp: "Potência instalada (kWp)",
  projects_completed: "Obras concluídas",
  projects_certified: "Obras certificadas",
  power_installed: "Potência instalada",
  power_delivered: "Potência entregue",
};

export interface GoalPeriod {
  id: string;
  period_type: "year" | "quarter" | "semester" | "month";
  year: number;
  quarter: number | null;
  semester: number | null;
  month: number | null;
  metric: GoalMetric;
  target_value: string;
  scope: "company" | "pm";
  pm_person_id: string | null;
  pm_display_name: string | null;
  notes: string;
  realized: string;
  percent: number;
  missing: string;
  expected_pace: string;
  projection: string;
  pace_status: "on_track" | "behind" | "ahead" | "no_target";
}

export interface PortfolioBreakdown {
  not_started: number;
  in_progress: number;
  completed: number;
  kwp_not_started: string;
  kwp_in_progress: string;
  kwp_completed: string;
  certified_count: number;
  pending_certification_count: number;
}

export interface YearlyIndicator {
  year: number;
  installations: string;
  kwp: string;
}

export interface PerformanceSummary {
  goals: GoalPeriod[];
  portfolio: PortfolioBreakdown;
  yearly: YearlyIndicator[];
}

export interface PerformanceFilters {
  year?: number;
  pm_person_id?: string;
  period_type?: "year" | "quarter" | "semester" | "month";
  quarter?: number;
  semester?: number;
  month?: number;
}

function performanceFiltersToParams(filters: PerformanceFilters): string {
  const params = new URLSearchParams();
  if (filters.year) params.set("year", String(filters.year));
  if (filters.pm_person_id) params.set("pm_person_id", filters.pm_person_id);
  if (filters.period_type) params.set("period_type", filters.period_type);
  if (filters.quarter) params.set("quarter", String(filters.quarter));
  if (filters.semester) params.set("semester", String(filters.semester));
  if (filters.month) params.set("month", String(filters.month));
  return params.toString();
}

export function getPerformanceSummary(filters: PerformanceFilters = {}): Promise<PerformanceSummary> {
  const qs = performanceFiltersToParams(filters);
  return apiGet<PerformanceSummary>(`/api/performance/summary${qs ? `?${qs}` : ""}`);
}

export function listGoals(filters: PerformanceFilters = {}): Promise<GoalPeriod[]> {
  const qs = performanceFiltersToParams(filters);
  return apiGet<GoalPeriod[]>(`/api/performance/goals${qs ? `?${qs}` : ""}`);
}

export const createGoal = (payload: {
  period_type: "year" | "quarter" | "semester" | "month";
  year: number;
  quarter?: number;
  semester?: number;
  month?: number;
  metric: GoalMetric;
  target_value: string;
  scope?: "company" | "pm";
  pm_person_id?: string;
  notes?: string;
}) => apiPost<GoalPeriod>("/api/performance/goals", payload);

export const updateGoal = (id: string, payload: { target_value?: string; notes?: string }) =>
  apiPatch<GoalPeriod>(`/api/performance/goals/${id}`, payload);

// --- Importação de notas iniciais ---

export interface FieldImportConflict {
  id: string;
  target_entity: string;
  field_name: string;
  old_value: string | null;
  new_value: string | null;
  resolution: "pending" | "use_new" | "keep_old";
  resolved_by_person_id: string | null;
  resolved_at: string | null;
}

export interface FieldImportRecord {
  id: string;
  target_project_id: string | null;
  is_new_project: boolean;
  match_strategy: string;
  status: string;
  promoted_project_id: string | null;
  candidate_projects: { id: string }[];
  mapped_fields: {
    project?: Record<string, unknown>;
    installation?: Record<string, unknown>;
    licensing?: Record<string, unknown>;
  };
  conflicts: FieldImportConflict[];
}

export interface FieldImportBatch {
  id: string;
  source_type: string;
  source_filename: string;
  form_version: string | null;
  status: "pending_confirmation" | "applied" | "rejected";
  started_by_person_id: string | null;
  started_at: string;
  applied_by_person_id: string | null;
  applied_at: string | null;
  records: FieldImportRecord[];
}

export const previewNotesImport = (file: File) => {
  const formData = new FormData();
  formData.append("file", file);
  return apiUpload<FieldImportBatch>("/api/imports/notes/preview", formData);
};

export const getImportBatch = (batchId: string) => apiGet<FieldImportBatch>(`/api/imports/${batchId}`);

export const resolveImportConflict = (conflictId: string, resolution: "use_new" | "keep_old") =>
  apiPost<FieldImportConflict>(`/api/imports/conflicts/${conflictId}/resolve`, { resolution });

export const applyNotesImport = (batchId: string, targetProjectId?: string) =>
  apiPost<{ project_id: string; project_name: string; created_new_project: boolean }>("/api/imports/notes/apply", {
    batch_id: batchId,
    target_project_id: targetProjectId,
    confirm: true,
  });

// --- Dados satélite do projeto: instalação, licenciamento, comunicação ---

export interface ProjectInstallationData {
  project_id: string;
  client_nif: string | null;
  contact_person_name: string | null;
  contact_person_role: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  address: string | null;
  district: string | null;
  municipality: string | null;
  power_kwp: number | null;
  panel_count: number | null;
  panel_power_wp: number | null;
  inverters: string | null;
  batteries: string | null;
  has_backup: boolean | null;
  ev_chargers: string | null;
  installation_type: string | null;
  injection_type: string | null;
  om_notes: string | null;
  notes: string;
  updated_at: string | null;
}

export interface ProjectLicensingData {
  project_id: string;
  upac_number: string | null;
  dgeg_number: string | null;
  cadastro_number: string | null;
  licensing_status: string | null;
  registration_date: string | null;
  certification_request_date: string | null;
  inspecting_entity: string | null;
  inspection_date: string | null;
  certificate_date: string | null;
  installer: string | null;
  commercializer: string | null;
  annual_production_kwh: number | null;
  comments: string;
  updated_at: string | null;
}

export interface ProjectCommunicationData {
  project_id: string;
  operator: string | null;
  gsm_m2m_number: string | null;
  card_identifier: string | null;
  communication_status: string | null;
  notes: string;
  updated_at: string | null;
}

export const getProjectInstallationData = (projectId: string) =>
  apiGet<ProjectInstallationData>(`/api/projects/${projectId}/installation-data`);
export const updateProjectInstallationData = (projectId: string, changes: Partial<ProjectInstallationData>) =>
  apiPatch<ProjectInstallationData>(`/api/projects/${projectId}/installation-data`, changes);

export const getProjectLicensingData = (projectId: string) =>
  apiGet<ProjectLicensingData>(`/api/projects/${projectId}/licensing-data`);
export const updateProjectLicensingData = (projectId: string, changes: Partial<ProjectLicensingData>) =>
  apiPatch<ProjectLicensingData>(`/api/projects/${projectId}/licensing-data`, changes);

export const getProjectCommunicationData = (projectId: string) =>
  apiGet<ProjectCommunicationData>(`/api/projects/${projectId}/communication-data`);
export const updateProjectCommunicationData = (projectId: string, changes: Partial<ProjectCommunicationData>) =>
  apiPatch<ProjectCommunicationData>(`/api/projects/${projectId}/communication-data`, changes);

// --- Mapa operacional ---

// Estado (green|yellow|red) derivado no servidor — nunca recalculado no
// frontend (ver docs/DECISIONS.md D-058, app/services/map.py).
export type MapAttention = "green" | "yellow" | "red";

export interface MapNextOperationalTask {
  id: string;
  title: string;
  due_date: string | null;
  priority: string;
}

export interface MapProject {
  id: string;
  name: string;
  client_name: string | null;
  pm_person_id: string | null;
  pm_display_name: string | null;
  status: string;
  lat: number | null;
  lon: number | null;
  power_kwp: number | null;
  open_tasks_count: number;
  issues_count: number;
  attention: MapAttention;
  operational_tasks_count: number;
  overdue_operational_tasks_count: number;
  blocked_operational_tasks_count: number;
  urgent_operational_tasks_count: number;
  next_operational_task: MapNextOperationalTask | null;
  // `material_visible=false` (sem inventory.view) => os dois campos
  // abaixo ficam sempre `null` — nunca `false` (D-058).
  material_visible: boolean;
  has_material_on_site: boolean | null;
  material_sku_count: number | null;
}

export interface MapSummary {
  visible_active_projects: number;
  mapped_projects: number;
  unmapped_projects: number;
  map_coverage_percent: number;
  green_projects: number;
  yellow_projects: number;
  red_projects: number;
  operational_clean_percent: number;
  projects_with_material: number;
}

export interface MapSupplier {
  id: string;
  name: string;
  category: string | null;
  contact: string | null;
  email: string | null;
  address: string | null;
  lat: number | null;
  lon: number | null;
  is_preferred: boolean;
  lead_time_days: number | null;
  materials: string;
  is_active: boolean;
}

export interface MapPickupPoint {
  id: string;
  name: string;
  supplier_id: string | null;
  address: string | null;
  lat: number | null;
  lon: number | null;
  schedule: string | null;
  contact: string | null;
  materials: string;
  notes: string;
  is_active: boolean;
}

export interface ProjectIssue {
  id: string;
  project_id: string;
  description: string;
  category: string;
  priority: string;
  status: string;
  assigned_to_person_id: string | null;
  due_date: string | null;
  lat: number | null;
  lon: number | null;
  related_task_id: string | null;
  notes: string;
  visible_on_map: boolean;
  created_by_person_id: string | null;
  created_at: string;
  project_name: string | null;
}

export interface MapData {
  config: { provider_enabled: boolean; tile_url: string; tile_attribution: string };
  projects: MapProject[];
  projects_without_coordinates: MapProject[];
  suppliers: MapSupplier[];
  pickup_points: MapPickupPoint[];
  issues: ProjectIssue[];
  summary: MapSummary;
}

export const getMapData = () => apiGet<MapData>("/api/map/data");

export const listSuppliers = () => apiGet<MapSupplier[]>("/api/suppliers");
export const createSupplier = (payload: Partial<MapSupplier> & { name: string }) =>
  apiPost<MapSupplier>("/api/suppliers", payload);
export const updateSupplier = (id: string, changes: Partial<MapSupplier>) =>
  apiPatch<MapSupplier>(`/api/suppliers/${id}`, changes);

export const listPickupPoints = () => apiGet<MapPickupPoint[]>("/api/pickup-points");
export const createPickupPoint = (payload: Partial<MapPickupPoint> & { name: string }) =>
  apiPost<MapPickupPoint>("/api/pickup-points", payload);
export const updatePickupPoint = (id: string, changes: Partial<MapPickupPoint>) =>
  apiPatch<MapPickupPoint>(`/api/pickup-points/${id}`, changes);

export const listProjectIssues = (projectId: string) =>
  apiGet<ProjectIssue[]>(`/api/projects/${projectId}/issues`);
export const createProjectIssue = (
  projectId: string,
  payload: { description: string; category?: string; priority?: string; lat?: number; lon?: number; notes?: string }
) => apiPost<ProjectIssue>(`/api/projects/${projectId}/issues`, payload);
export const updateProjectIssue = (projectId: string, issueId: string, changes: Partial<ProjectIssue>) =>
  apiPatch<ProjectIssue>(`/api/projects/${projectId}/issues/${issueId}`, changes);
export const convertIssueToTask = (projectId: string, issueId: string, title: string) =>
  apiPost<Task>(`/api/projects/${projectId}/issues/${issueId}/convert-to-task`, { title });

// --- Planeamento (calendário) ---

export interface CalendarEvent {
  id: string;
  visit_id: string | null;
  project_id: string | null;
  task_id: string | null;
  assigned_to_person_id: string | null;
  title: string;
  starts_at: string;
  ends_at: string;
  status: string;
  graph_event_id: string | null;
  created_at: string;
  project_name: string | null;
  task_title: string | null;
  assigned_to_display_name: string | null;
  can_manage: boolean;
}

export interface CalendarEventFilters {
  project_id?: string;
  assigned_to_person_id?: string;
  mine_only?: boolean;
  starts_from?: string;
  starts_to?: string;
}

function calendarFiltersToParams(filters: CalendarEventFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.project_id) params.set("project_id", filters.project_id);
  if (filters.assigned_to_person_id) params.set("assigned_to_person_id", filters.assigned_to_person_id);
  if (filters.mine_only) params.set("mine_only", "true");
  if (filters.starts_from) params.set("starts_from", filters.starts_from);
  if (filters.starts_to) params.set("starts_to", filters.starts_to);
  return params;
}

export function listCalendarEvents(filters: CalendarEventFilters = {}): Promise<CalendarEvent[]> {
  const qs = calendarFiltersToParams(filters).toString();
  return apiGet<CalendarEvent[]>(`/api/planning/events${qs ? `?${qs}` : ""}`);
}

export interface CalendarEventCreatePayload {
  title: string;
  starts_at: string;
  ends_at: string;
  project_id?: string | null;
  task_id?: string | null;
  assigned_to_person_id?: string | null;
}

export const createCalendarEvent = (payload: CalendarEventCreatePayload) =>
  apiPost<CalendarEvent>("/api/planning/events", payload);

export interface CalendarEventUpdatePayload {
  title?: string;
  starts_at?: string;
  ends_at?: string;
  project_id?: string | null;
  task_id?: string | null;
  assigned_to_person_id?: string | null;
  status?: string;
}

export const updateCalendarEvent = (id: string, changes: CalendarEventUpdatePayload) =>
  apiPatch<CalendarEvent>(`/api/planning/events/${id}`, changes);

export const cancelCalendarEvent = (id: string) =>
  apiPost<CalendarEvent>(`/api/planning/events/${id}/cancel`, {});
