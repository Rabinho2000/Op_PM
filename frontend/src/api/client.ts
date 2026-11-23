// Cliente da API. Fase 1 (D-031): login real via Microsoft Entra ID
// (MSAL, ver src/auth/msal.ts) já está implementado — quando há uma conta
// MSAL ativa, todo o pedido leva `Authorization: Bearer <access token da
// API>`. O mecanismo de desenvolvimento (X-Dev-User-Email) continua a
// existir só para local/test (ver src/auth/msal.ts:devLoginEnabled e
// app/security/current_user.py no backend) e nunca é enviado ao mesmo
// tempo que um Bearer token — os dois caminhos são mutuamente exclusivos,
// tal como no backend. Nenhuma chave/segredo de integração (Claude, Graph,
// ClickUp, Financial, Entra) é colocada aqui: essas só existem no backend.
import type { Perm } from "../generated/permissions";
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

// O FastAPI devolve `detail` como texto, ou como lista de erros de validação
// (`[{ msg: "Value error, Email inválido." }]`): normaliza para uma frase legível.
export function formatApiDetail(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : null))
      .filter((m): m is string => Boolean(m))
      .map((m) => m.replace(/^Value error, /, ""));
    return messages.length > 0 ? messages.join(" ") : null;
  }
  return null;
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
      detail = formatApiDetail(body.detail) ?? detail;
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

export const apiGet = <T>(path: string) => request<T>(path);
export const apiPatch = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
export const apiPut = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PUT", body: JSON.stringify(body) });
export const apiPost = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined });
export const apiDelete = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "DELETE", ...(body !== undefined ? { body: JSON.stringify(body) } : {}) });
export const apiUpload = <T>(path: string, formData: FormData) => requestUpload<T>(path, formData);

export { ApiError };

export const NETWORK_ERROR_MESSAGE = "Não foi possível contactar o servidor.";

/** Mensagem de erro para o utilizador: o `detail` da API ou, se o pedido nem chegou lá, o texto de reserva. */
export function errorMessage(err: unknown, fallback: string = NETWORK_ERROR_MESSAGE): string {
  return err instanceof ApiError ? err.detail : fallback;
}

// --- /health, /me ---

export interface HealthResponse {
  status: string;
  app_env: string;
  database_dialect: string;
  integrations: Record<string, boolean>;
  demo_mode?: boolean;
  demo_real_data?: boolean;
  dev_login_available?: boolean;
}

export interface MeResponse {
  user_id: string;
  email: string;
  person_id: string;
  display_name?: string;
  roles: string[];
  role_labels?: string[];
  // Códigos do catálogo do backend (src/generated/permissions.ts); um código novo
  // do servidor que o cliente ainda não conhece só falha a comparação, nunca a execução.
  permissions: Perm[];
}

export const getHealth = () => apiGet<HealthResponse>("/health");
export const getMe = () => apiGet<MeResponse>("/me");

export interface MyProcessStage {
  project_id: string;
  project_name: string;
  stage_id: string;
  stage_code: string;
  stage_title: string;
  responsible_rule: string | null;
  status: string;
  planned_start: string | null;
  planned_end: string | null;
  done_count: number;
  total_count: number;
}

export const getMyProcessStages = () => apiGet<MyProcessStage[]>("/api/me/process-stages");

export interface SupportDelegation {
  pm_person_id: string;
  pm_display_name: string;
  support_person_id: string;
  support_display_name: string;
}

export const listSupportDelegations = () => apiGet<SupportDelegation[]>("/api/support-delegations");
export const saveSupportDelegation = (body: { pm_person_id: string; support_person_id: string }) =>
  request<SupportDelegation>("/api/support-delegations", { method: "PUT", body: JSON.stringify(body) });
export const deleteSupportDelegation = (pmPersonId: string) =>
  request<void>(`/api/support-delegations/${pmPersonId}`, { method: "DELETE" });

// --- /api/people ---

export interface Person {
  id: string;
  display_name: string;
  email?: string | null;
  is_active: boolean;
}

export const listPeople = () => apiGet<Person[]>("/api/people");

export interface EligibleProjectManager {
  id: string;
  display_name: string;
}

export const listEligibleProjectManagers = () => apiGet<EligibleProjectManager[]>("/api/projects/eligible-managers");

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
  // Estado do ciclo de vida (D-069) — código estável; a lista vem de getLifecycleStatuses().
  lifecycle_status: string | null;
  // Obra (D-071): instalador, equipa e datas.
  installer_id: string | null;
  installer_team_id: string | null;
  work_start_date: string | null;
  work_end_date: string | null;
  // Datas derivadas do modelo do processo e ainda não confirmadas por ninguém.
  work_dates_estimated: boolean;
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
  deleted_at: string | null;
  deleted_by_person_id: string | null;
  entered_at: string | null;
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
  can_view_project_scope: boolean;
  can_change_status: boolean;
  can_plan_work: boolean;
  has_project_photo: boolean;
  can_edit_project_photo: boolean;
  can_delete: boolean;
  can_restore: boolean;
  installer_name: string | null;
  installer_team_name: string | null;
  installer_team_leader_name: string | null;
  // Licenciamento (D-105): flags efetivas calculadas no servidor (permissão + âmbito do projeto).
  // O frontend não as deduz de /api/me nem de editable_fields.
  can_edit_credentials: boolean;
  can_reveal_credentials: boolean;
  can_edit_sim_cards: boolean;
  can_reveal_sim_secrets: boolean;
  can_edit_surplus_contracts: boolean;
  payments?: ProjectPayments | null;
  can_edit_payments?: boolean;
}

export type PaymentMilestoneCode = "adjudicacao" | "entrada_obra" | "fim_obra" | "certificado_final";
export type ProjectPayments = Record<PaymentMilestoneCode, boolean>;

export interface ProjectPaymentMilestone {
  milestone: PaymentMilestoneCode;
  label: string;
  received: boolean;
  marked_at: string | null;
  marked_by: string | null;
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
  lifecycle_status?: string[];
  start_from?: string;
  start_to?: string;
}

export interface ProjectCreateInput {
  name: string;
  client_name?: string;
  client_contact?: string;
  client_email?: string;
  address?: string;
  lat?: number;
  lon?: number;
  power_kwp?: number;
  power_raw?: string;
  pm_person_id?: string;
  start_date?: string;
  lifecycle_status?: string | null;
  role?: string;
  equipment_notes?: string;
  injection_notes?: string;
  om_notes?: string;
  commercial_assumptions?: string;
  award_year_raw?: string;
  notes?: string;
}

export interface ProjectNameCandidate {
  id: string;
  name: string;
}

export const createProject = (body: ProjectCreateInput) => apiPost<Project>("/api/projects", body);
export const checkProjectName = (name: string) =>
  apiGet<ProjectNameCandidate[]>(`/api/projects/check-name?name=${encodeURIComponent(name)}`);

export function listProjects(filters: ProjectFilters = {}): Promise<Project[]> {
  const params = new URLSearchParams();
  if (filters.pm_person_id) params.set("pm_person_id", filters.pm_person_id);
  if (filters.is_active !== undefined) params.set("is_active", String(filters.is_active));
  if (filters.q) params.set("q", filters.q);
  if (filters.status) params.set("status", filters.status);
  for (const s of filters.lifecycle_status ?? []) params.append("lifecycle_status", s);
  if (filters.start_from) params.set("start_from", filters.start_from);
  if (filters.start_to) params.set("start_to", filters.start_to);
  const qs = params.toString();
  return apiGet<Project[]>(`/api/projects${qs ? `?${qs}` : ""}`);
}

export const getProject = (id: string) => apiGet<Project>(`/api/projects/${id}`);
export const updateProject = (id: string, changes: Partial<Project>) =>
  apiPatch<Project>(`/api/projects/${id}`, changes);
export const getProjectHistory = (id: string) => apiGet<ProjectHistoryEntry[]>(`/api/projects/${id}/history`);
export const getProjectPayments = (id: string) =>
  apiGet<ProjectPaymentMilestone[]>(`/api/projects/${id}/payments`);
export const updateProjectPayment = (id: string, milestone: PaymentMilestoneCode, received: boolean) =>
  apiPut<ProjectPaymentMilestone>(`/api/projects/${id}/payments/${milestone}`, { received });
export async function getProjectPhotoBlob(id: string): Promise<Blob> {
  const res = await fetch(`${API_BASE_URL}/api/projects/${id}/photo`, { headers: await authHeaders() });
  if (!res.ok) {
    await handleResponse<void>(res);
    throw new Error("Não foi possível carregar a fotografia.");
  }
  return res.blob();
}
export const uploadProjectPhoto = (id: string, file: File) => {
  const formData = new FormData();
  formData.append("file", file);
  return requestUpload<{ has_project_photo: boolean; content_type: string }>(`/api/projects/${id}/photo`, formData);
};
export const deleteProjectPhoto = (id: string) => apiDelete<void>(`/api/projects/${id}/photo`);
export const deleteProject = (id: string, reason: string) =>
  apiDelete<void>(`/api/projects/${id}`, { reason });
export const listDeletedProjects = () => apiGet<Project[]>("/api/projects/deleted");
export const restoreProject = (id: string) => apiPost<Project>(`/api/projects/${id}/restore`);

// --- Instaladores, equipas e plano de obra (D-071) ---
export interface InstallerTeam {
  id: string;
  name: string;
  leader_name: string | null;
  leader_phone: string | null;
  is_active: boolean;
  project_count: number;
}

export interface Installer {
  id: string;
  name: string;
  is_active: boolean;
  teams: InstallerTeam[];
  project_count: number;
}

export interface WorkPlanInput {
  installer_id?: string | null;
  installer_team_id?: string | null;
  work_start_date?: string | null;
  work_end_date?: string | null;
  // Só `false`: confirma as datas atuais (estimadas) sem as alterar.
  work_dates_estimated?: false;
}

export const listInstallers = () => apiGet<Installer[]>("/api/installers");

// Canal mínimo de consulta para instaladores colaboradores. Nunca substitui os
// endpoints de staff: o servidor aplica o âmbito da membership em cada pedido.
export interface InstallerAccessTeam {
  id: string;
  installer_id: string;
  name: string;
  is_active: boolean;
}

export interface InstallerAccessInstaller {
  id: string;
  name: string;
  is_active: boolean;
  teams: InstallerAccessTeam[];
}

export interface InstallerAccessTeamsEnvelope {
  teams: InstallerAccessTeam[];
  installers: Array<{ id: string; name: string; is_active: boolean }>;
  scoped: boolean;
}

export type InstallerAccessTeamsResponse = InstallerAccessInstaller[] | InstallerAccessTeamsEnvelope;

export const listInstallerAccessTeams = () =>
  apiGet<InstallerAccessTeamsResponse>("/api/installer-access/teams");

export interface InstallerInventoryLocation {
  id?: string;
  label: string;
}

export interface InstallerInventoryRow {
  project_id: string;
  project_name?: string;
  article_name: string;
  unit: string;
  required_quantity: string | number;
  reserved_quantity: string | number;
  consumed_quantity: string | number;
  delivered_quantity: string | number;
  locations: InstallerInventoryLocation[];
}

export interface InstallerInventoryPage {
  items: InstallerInventoryRow[];
  total: number;
  limit: number;
  offset: number;
}

export const listInstallerInventory = (filters: { projectId?: string; limit?: number; offset?: number } = {}) => {
  const params = new URLSearchParams();
  if (filters.projectId) params.set("project_id", filters.projectId);
  params.set("limit", String(filters.limit ?? 100));
  params.set("offset", String(filters.offset ?? 0));
  return apiGet<InstallerInventoryPage>(`/api/installer-access/inventory?${params.toString()}`);
};

export const createInstaller = (name: string) => apiPost<Installer>("/api/installers", { name });
export const updateInstaller = (id: string, changes: { name?: string; is_active?: boolean }) =>
  apiPatch<Installer>(`/api/installers/${id}`, changes);
export const createInstallerTeam = (
  installerId: string,
  payload: { name: string; leader_name?: string | null; leader_phone?: string | null }
) => apiPost<Installer>(`/api/installers/${installerId}/teams`, payload);
export const updateInstallerTeam = (
  installerId: string,
  teamId: string,
  changes: { name?: string; leader_name?: string | null; leader_phone?: string | null; is_active?: boolean }
) => apiPatch<Installer>(`/api/installers/${installerId}/teams/${teamId}`, changes);
export const updateProjectWorkPlan = (id: string, plan: WorkPlanInput) =>
  apiPatch<Project>(`/api/projects/${id}/work-plan`, plan);

export interface TeamAssignment {
  id: string;
  project_id: string;
  installer_id: string;
  team_id: string;
  start_date: string;
  end_date: string;
  note: string;
  created_by_person_id: string | null;
  team_name?: string | null;
  installer_name?: string | null;
  team_leader_name?: string | null;
  team_leader_phone?: string | null;
  warning?: string | null;
}

export interface TeamAssignmentInput {
  team_id: string;
  start_date: string;
  end_date: string;
  note?: string;
}

export interface TeamAssignmentUpdate {
  team_id?: string;
  start_date?: string;
  end_date?: string;
  note?: string;
}

export const listTeamAssignments = (projectId: string) =>
  apiGet<TeamAssignment[]>(`/api/projects/${projectId}/team-assignments`);
export const createTeamAssignment = (projectId: string, payload: TeamAssignmentInput) =>
  apiPost<TeamAssignment>(`/api/projects/${projectId}/team-assignments`, payload);
export const updateTeamAssignment = (projectId: string, assignmentId: string, changes: TeamAssignmentUpdate) =>
  apiPatch<TeamAssignment>(`/api/projects/${projectId}/team-assignments/${assignmentId}`, changes);
export const deleteTeamAssignment = (projectId: string, assignmentId: string) =>
  apiDelete<void>(`/api/projects/${projectId}/team-assignments/${assignmentId}`);

// --- Processo do projeto (D-073) ---
export interface ProcessSubtask {
  id: string;
  code: string;
  title: string;
  done: boolean;
  done_at: string | null;
  done_by_display_name: string | null;
  // "ui" (marcado na aplicação) ou "legacy" (importado do legado, sem data nem autor).
  source: string;
}

export interface ProcessResponsible {
  rule: string | null;
  // Texto genérico da regra ("PM do projeto", "Subempreiteiro"…).
  label: string;
  names: string[];
  // A regra precisa de um dado que este projeto ainda não tem (PM, instalador, chefe de equipa).
  unresolved: boolean;
  // Há uma pessoa de suporte delegada para o PM deste projeto.
  delegated: boolean;
}

export interface ProcessContact {
  day: number;
  kind: string;
  note: string;
  planned_date: string | null;
  done: boolean;
  done_at: string | null;
  overdue: boolean;
  source: string;
}

export interface ProcessStage {
  id: string;
  code: string;
  title: string;
  note: string;
  responsible: ProcessResponsible;
  depends_on_code: string | null;
  start_day: number | null;
  end_day: number | null;
  planned_start: string | null;
  planned_end: string | null;
  completed_at: string | null;
  // done | overdue | active | upcoming | no_date
  status: string;
  can_update?: boolean;
  done_count: number;
  total_count: number;
  contact: ProcessContact | null;
  subtasks: ProcessSubtask[];
}

export interface ProcessPhase {
  id: string;
  code: string;
  name: string;
  color: string;
  done_count: number;
  total_count: number;
  stages: ProcessStage[];
}

export interface ProcessRead {
  project_id: string;
  start_date: string | null;
  has_catalog: boolean;
  can_update: boolean;
  phases: ProcessPhase[];
  summary: {
    done: number;
    total: number;
    percent: number;
    stages_done: number;
    stages_total: number;
    overdue_stages: number;
    overdue_contacts: number;
  };
}

export const getProjectProcess = (projectId: string) => apiGet<ProcessRead>(`/api/projects/${projectId}/process`);
export const setProcessSubtaskDone = (projectId: string, subtaskId: string, done: boolean) =>
  apiPatch<ProcessRead>(`/api/projects/${projectId}/process/subtasks/${subtaskId}`, { done });
export const setProcessStageSubtasksDone = (projectId: string, stageId: string, done: boolean) =>
  apiPatch<ProcessRead>(`/api/projects/${projectId}/process/stages/${stageId}/subtasks`, { done });
export const setProcessContactDone = (projectId: string, stageId: string, done: boolean) =>
  apiPatch<ProcessRead>(`/api/projects/${projectId}/process/stages/${stageId}/contact`, { done });

// --- Calendário de obras (D-072) ---
export interface WorkItem {
  project_id: string;
  name: string;
  client_name: string | null;
  pm_person_id: string | null;
  pm_display_name: string | null;
  lifecycle_status: string | null;
  installer_id: string | null;
  installer_name: string | null;
  installer_team_id: string | null;
  installer_team_name: string | null;
  work_start_date: string;
  work_end_date: string;
  work_dates_estimated: boolean;
  // A mesma equipa tem outra obra sobreposta (só entre preparação e construção).
  conflict: boolean;
  assignment_id?: string | null;
  assignment_start_date?: string | null;
  assignment_end_date?: string | null;
  assignment_start?: string | null;
  assignment_end?: string | null;
  team_id?: string | null;
  team_name?: string | null;
  team_leader_name?: string | null;
  // O utilizador pode alterar o plano desta obra (arrastar no calendário).
  can_plan_work?: boolean;
}

export interface UnscheduledProject {
  project_id: string;
  name: string;
  pm_display_name: string | null;
  lifecycle_status: string | null;
  installer_name: string | null;
  installer_team_name: string | null;
  work_start_date: string | null;
  work_end_date: string | null;
}

export interface WorksCalendar {
  start: string;
  end: string;
  works: WorkItem[];
  unscheduled: UnscheduledProject[];
  summary: { works: number; conflicts: number; estimated: number; unscheduled: number };
}

export interface WorksFilters {
  from: string;
  to: string;
  pm_person_id?: string;
  lifecycle_status?: string[];
  installer_ids?: string[];
  /** Legacy single-installer input; serialized using the canonical repeated installer_ids parameter. */
  installer_id?: string;
  team_id?: string;
}

export type WorksZoom = "weeks" | "months" | "quarters" | "month_days";

export interface WorksPreferences {
  zoom: WorksZoom;
  lifecycle_status: string[];
  pm_person_id: string | null;
  installer_ids?: string[];
  /** Present in old API responses and as a compatibility alias in current responses. */
  installer_id?: string | null;
  team_id: string | null;
  show_idle: boolean;
}

export const getWorksPreferences = () => apiGet<WorksPreferences>("/api/me/works-preferences");
export const updateWorksPreferences = (changes: WorksPreferences) =>
  apiPatch<WorksPreferences>("/api/me/works-preferences", changes);

export interface SavedWorksView {
  id: string;
  name: string;
  zoom: WorksZoom;
  lifecycle_status: string[];
  pm_person_id: string | null;
  installer_ids?: string[];
  /** Present in old API responses and as a compatibility alias in current responses. */
  installer_id?: string | null;
  team_id: string | null;
  show_idle: boolean;
  created_at: string;
  updated_at: string;
}

export type SavedWorksViewInput = Omit<SavedWorksView, "id" | "created_at" | "updated_at">;

export const listSavedWorksViews = () => apiGet<SavedWorksView[]>("/api/me/works-saved-views");
export const createSavedWorksView = (payload: SavedWorksViewInput) =>
  apiPost<SavedWorksView>("/api/me/works-saved-views", payload);
export const updateSavedWorksView = (id: string, changes: Partial<SavedWorksViewInput>) =>
  apiPatch<SavedWorksView>(`/api/me/works-saved-views/${id}`, changes);
export const deleteSavedWorksView = (id: string) =>
  apiDelete<void>(`/api/me/works-saved-views/${id}`);
export const applySavedWorksView = (id: string) =>
  apiPost<WorksPreferences>(`/api/me/works-saved-views/${id}/apply`);

export function getWorksCalendar(filters: WorksFilters): Promise<WorksCalendar> {
  const params = new URLSearchParams({ from: filters.from, to: filters.to });
  if (filters.pm_person_id) params.set("pm_person_id", filters.pm_person_id);
  for (const id of filters.installer_ids ?? (filters.installer_id ? [filters.installer_id] : [])) params.append("installer_ids", id);
  if (filters.team_id) params.set("team_id", filters.team_id);
  for (const s of filters.lifecycle_status ?? []) params.append("lifecycle_status", s);
  return apiGet<WorksCalendar>(`/api/works/calendar?${params.toString()}`);
}

export interface TeamLocationAssignment {
  id: string;
  project_id: string;
  project_name: string;
  address: string | null;
  lat: number | null;
  lon: number | null;
  pm_person_id: string | null;
  pm_display_name: string | null;
  lifecycle_status: string | null;
  start_date: string;
  end_date: string;
  note: string;
  conflict?: boolean;
}

export type TeamLocationStatus = "livre" | "ocupada" | "ocupada_noutra_obra" | string;

export interface TeamLocationTeam {
  id: string;
  installer_id: string;
  name: string;
  assignments?: TeamLocationAssignment[];
  status?: TeamLocationStatus;
  free?: boolean;
}

export interface TeamLocationInstaller {
  id: string;
  name: string;
  teams?: TeamLocationTeam[];
}

export interface TeamsView {
  date: string;
  days: number;
  installers: TeamLocationInstaller[];
}

export interface WorksTeamsFilters {
  date: string;
  days: number;
  installer_ids?: string[];
  /** Legacy single-installer input; serialized using the canonical repeated installer_ids parameter. */
  installer_id?: string;
}

export function getWorksTeams(filters: WorksTeamsFilters): Promise<TeamsView> {
  const params = new URLSearchParams({ date: filters.date, days: String(filters.days) });
  for (const id of filters.installer_ids ?? (filters.installer_id ? [filters.installer_id] : [])) params.append("installer_ids", id);
  return apiGet<TeamsView>(`/api/works/teams?${params.toString()}`);
}

// --- Estado do ciclo de vida do projeto (D-069) ---
export interface LifecycleStatus {
  code: string;
  label: string;
  // Posição na sequência normal (1..5); null para "On hold pelo cliente".
  flow_position: number | null;
}

export interface ProjectStatusChangeResult {
  project: Project;
  // Aviso (nunca bloqueio) quando a mudança salta estados da sequência normal.
  warning: string | null;
}

let lifecycleStatusesPromise: Promise<LifecycleStatus[]> | null = null;
// A lista é fixa durante a sessão: um único pedido, partilhado por toda a UI.
export function getLifecycleStatuses(): Promise<LifecycleStatus[]> {
  if (!lifecycleStatusesPromise) {
    lifecycleStatusesPromise = apiGet<LifecycleStatus[]>("/api/projects/lifecycle-statuses").catch((e) => {
      lifecycleStatusesPromise = null;
      throw e;
    });
  }
  return lifecycleStatusesPromise;
}

export const changeProjectStatus = (id: string, lifecycle_status: string, note = "") =>
  apiPatch<ProjectStatusChangeResult>(`/api/projects/${id}/status`, { lifecycle_status, note });

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
export type AbsenceStatus = "pendente" | "aprovada" | "rejeitada" | "cancelada";

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
  decided_by_person_id: string | null;
  decided_by_display_name: string | null;
  decided_at: string | null;
  decision_note: string;
  cancelled_by_person_id: string | null;
  cancelled_by_display_name: string | null;
  cancelled_at: string | null;
  created_at: string;
  updated_at: string;
  person_display_name: string | null;
  overlapping_absences: AbsenceOverlap[];
  overlapping_absences_count: number;
  overlapping_projects: WorkOverlap[];
  overlapping_projects_count: number;
  can_approve: boolean;
  can_reject: boolean;
  can_cancel: boolean;
}

export interface AbsenceOverlap {
  id: string;
  start_date: string;
  end_date: string;
  type: AbsenceType;
  status: AbsenceStatus;
}

export interface WorkOverlap {
  id: string;
  name: string;
  lifecycle_status: string | null;
  work_start_date: string;
  work_end_date: string;
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
export const approveAbsence = (id: string) => apiPost<Absence>(`/api/absences/${id}/approve`);
export const rejectAbsence = (id: string, note: string) => apiPost<Absence>(`/api/absences/${id}/reject`, { note });
export const cancelAbsence = (id: string) => apiPost<Absence>(`/api/absences/${id}/cancel`);

// --- /api/holidays ---

export type HolidayScope = "nacional" | "municipal" | "empresa";

export interface Holiday {
  id: string;
  date: string;
  name: string;
  scope: HolidayScope;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface HolidayCreatePayload {
  date: string;
  name: string;
  scope: HolidayScope;
}

export function listHolidays(from?: string, to?: string, includeInactive = false): Promise<Holiday[]> {
  const params = new URLSearchParams();
  if (from) params.set("from", from);
  if (to) params.set("to", to);
  if (includeInactive) params.set("include_inactive", "true");
  const query = params.toString();
  return apiGet<Holiday[]>(`/api/holidays${query ? `?${query}` : ""}`);
}

export const createHoliday = (payload: HolidayCreatePayload) => apiPost<Holiday>("/api/holidays", payload);
export const updateHoliday = (id: string, payload: Partial<HolidayCreatePayload> & { is_active?: boolean }) =>
  apiPatch<Holiday>(`/api/holidays/${id}`, payload);
export const deleteHoliday = (id: string) => apiDelete<Holiday>(`/api/holidays/${id}`);

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
  scope: "all" | "own" | "delegated" | "none";
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
  pending_absences_count: number | null;
}

export interface DashboardWorkProject {
  id: string;
  name: string;
  expected_start_date: string | null;
  pm_display_name: string | null;
  installer_display_name: string | null;
  team_display_name: string | null;
  next_task_title: string | null;
  next_task_due_date: string | null;
}

export interface DashboardWorks {
  construction: DashboardWorkProject[];
  preparation: DashboardWorkProject[];
}

export const getDashboardSummary = () => apiGet<DashboardSummary>("/api/dashboard/summary");
export const getDashboardWorks = () => apiGet<DashboardWorks>("/api/dashboard/works");

// --- Inventário (MVP de Operações) ---

export type InventoryOwner = "solcor" | "verde_milenar";
export type InventoryLocationType = "central" | "project" | "vehicle" | "supplier" | "office";

export const INVENTORY_OWNER_STORAGE_KEY = "op_pm_inventory_owner";

export function getStoredInventoryOwner(): InventoryOwner {
  try {
    const stored = localStorage.getItem(INVENTORY_OWNER_STORAGE_KEY);
    return stored === "verde_milenar" ? "verde_milenar" : "solcor";
  } catch {
    return "solcor";
  }
}

export interface InventoryLocationStock {
  location_id: string | null;
  location_name: string;
  physical_stock: string;
}

export interface InventoryItem {
  id: string;
  sku: string;
  name: string;
  unit: string;
  category: string | null;
  manufacturer?: string | null;
  model?: string | null;
  subcategory?: string | null;
  power_w?: string | null;
  cross_section_mm2?: string | null;
  section_label?: string | null;
  has_photo?: boolean;
  min_stock: string;
  preferred_supplier_id: string | null;
  lead_time_days: number | null;
  is_active: boolean;
  physical_stock: string;
  available_stock: string;
  total_reserved: string;
  below_min_stock: boolean;
  location_stocks?: InventoryLocationStock[];
}

export const listInventoryCategories = () => apiGet<string[]>("/api/inventory/categories");

export interface InventoryCategoryImageInfo {
  name: string;
  has_custom_image: boolean;
  image_version: string | null;
}

export interface InventoryCategoryImageUploadResult extends InventoryCategoryImageInfo {
  content_type: string;
}

export const listInventoryCategoryDetails = () =>
  apiGet<InventoryCategoryImageInfo[]>("/api/inventory/categories/details");

export type InventoryItemDocumentKind = "datasheet" | "manual" | "guia" | "outro";

export interface InventoryItemDocument {
  id: string;
  item_id: string;
  kind: InventoryItemDocumentKind;
  title: string;
  filename: string;
  content_type: string;
  size: number;
  created_by_person_id: string;
  created_at: string;
}

async function getAuthenticatedBlob(path: string): Promise<Blob> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: await authHeaders(),
    cache: "no-store",
  });
  if (!res.ok) {
    await handleResponse<void>(res);
    throw new Error("Não foi possível carregar a imagem.");
  }
  return res.blob();
}

export const getInventoryItemPhotoBlob = (itemId: string) =>
  getAuthenticatedBlob(`/api/inventory/items/${encodeURIComponent(itemId)}/photo`);

export const listInventoryItemDocuments = (itemId: string) =>
  apiGet<InventoryItemDocument[]>(`/api/inventory/items/${encodeURIComponent(itemId)}/documents`);

export const getInventoryItemDocumentBlob = (itemId: string, documentId: string) =>
  getAuthenticatedBlob(
    `/api/inventory/items/${encodeURIComponent(itemId)}/documents/${encodeURIComponent(documentId)}/download`,
  );

export const uploadInventoryItemDocument = (
  itemId: string,
  kind: InventoryItemDocumentKind,
  title: string,
  file: File,
) => {
  const formData = new FormData();
  formData.append("kind", kind);
  formData.append("title", title);
  formData.append("file", file);
  return apiUpload<InventoryItemDocument>(
    `/api/inventory/items/${encodeURIComponent(itemId)}/documents`, formData,
  );
};

export const deleteInventoryItemDocument = (itemId: string, documentId: string) =>
  apiDelete<void>(
    `/api/inventory/items/${encodeURIComponent(itemId)}/documents/${encodeURIComponent(documentId)}`,
  );

export const uploadInventoryItemPhoto = (itemId: string, file: File) => {
  const formData = new FormData();
  formData.append("file", file);
  return apiUpload<{ has_photo: boolean; content_type: string }>(
    `/api/inventory/items/${encodeURIComponent(itemId)}/photo`, formData,
  );
};

export const deleteInventoryItemPhoto = (itemId: string) =>
  apiDelete<void>(`/api/inventory/items/${encodeURIComponent(itemId)}/photo`);

export const getInventoryCategoryImageBlob = (category: string, imageVersion?: string | null) => {
  const versionQuery = imageVersion ? `?version=${encodeURIComponent(imageVersion)}` : "";
  return getAuthenticatedBlob(
    `/api/inventory/categories/${encodeURIComponent(category)}/image${versionQuery}`,
  );
};

export const uploadInventoryCategoryImage = (category: string, file: File) => {
  const formData = new FormData();
  formData.append("file", file);
  return apiUpload<InventoryCategoryImageUploadResult>(
    `/api/inventory/categories/${encodeURIComponent(category)}/image`, formData,
  );
};

export const deleteInventoryCategoryImage = (category: string) =>
  apiDelete<void>(`/api/inventory/categories/${encodeURIComponent(category)}/image`);

export const listInventoryItems = (owner: InventoryOwner = "solcor") =>
  apiGet<InventoryItem[]>(`/api/inventory/items?owner=${owner}`);

export interface InventoryLocation {
  id: string;
  code: string;
  name: string;
  location_type: InventoryLocationType;
  project_id: string | null;
  owner: InventoryOwner;
  is_active: boolean;
}

export interface InventoryCatalogHistoryEntry {
  id: string;
  entity_type: "item" | "location";
  entity_id: string;
  action: "create" | "edit" | "deactivate";
  changes: Record<string, unknown>;
  changed_by_person_id: string | null;
  changed_by_person_name: string | null;
  changed_at: string;
}

export const listInventoryLocations = (owner: InventoryOwner = "solcor") =>
  apiGet<InventoryLocation[]>(`/api/inventory/locations?owner=${owner}`);

export const listInventoryCatalogHistory = (filters: { entity_id?: string; entity_type?: "item" | "location" } = {}) => {
  const params = new URLSearchParams();
  if (filters.entity_id) params.set("entity_id", filters.entity_id);
  if (filters.entity_type) params.set("entity_type", filters.entity_type);
  const query = params.toString();
  return apiGet<InventoryCatalogHistoryEntry[]>(`/api/inventory/catalog-history${query ? `?${query}` : ""}`);
};

export interface InventoryItemCreate {
  sku: string;
  name: string;
  unit?: string;
  category?: string | null;
  manufacturer?: string | null;
  model?: string | null;
  subcategory?: string | null;
  power_w?: string | null;
  cross_section_mm2?: string | null;
  min_stock?: string;
  preferred_supplier_id?: string | null;
  lead_time_days?: number | null;
}

export interface InventoryItemUpdate {
  sku?: string;
  name?: string;
  unit?: string;
  category?: string | null;
  manufacturer?: string | null;
  model?: string | null;
  subcategory?: string | null;
  power_w?: string | null;
  cross_section_mm2?: string | null;
  min_stock?: string;
  preferred_supplier_id?: string | null;
  lead_time_days?: number | null;
  is_active?: boolean;
}

export const createInventoryItem = (payload: InventoryItemCreate) =>
  apiPost<InventoryItem>("/api/inventory/items", payload);

export const updateInventoryItem = (id: string, payload: InventoryItemUpdate) =>
  apiPatch<InventoryItem>(`/api/inventory/items/${id}`, payload);

export const reactivateInventoryItem = (id: string) =>
  apiPatch<InventoryItem>(`/api/inventory/items/${id}`, { is_active: true });

export const deactivateInventoryItem = (id: string) =>
  apiPost<InventoryItem>(`/api/inventory/items/${id}/deactivate`);

export interface InventoryLocationCreate {
  code: string;
  name: string;
  location_type: InventoryLocationType;
  project_id?: string | null;
  owner?: InventoryOwner;
}

export interface InventoryLocationUpdate {
  code?: string;
  name?: string;
  location_type?: InventoryLocationType;
  project_id?: string | null;
  owner?: InventoryOwner | null;
  is_active?: boolean;
}

export const createInventoryLocation = (payload: InventoryLocationCreate) =>
  apiPost<InventoryLocation>("/api/inventory/locations", payload);

export const updateInventoryLocation = (id: string, payload: InventoryLocationUpdate) =>
  apiPatch<InventoryLocation>(`/api/inventory/locations/${id}`, payload);

export const deactivateInventoryLocation = (id: string) =>
  apiPost<InventoryLocation>(`/api/inventory/locations/${id}/deactivate`);

export interface OpeningStockCreate {
  item_id: string;
  quantity: string;
  reference: string;
  idempotency_key: string;
  location_id?: string | null;
}

export const createOpeningStock = (payload: OpeningStockCreate, owner: InventoryOwner = "solcor") =>
  apiPost<InventoryMovement>(`/api/inventory/opening-stock?owner=${owner}`, payload);

// --- Pedidos de material a fornecedores (D-067) ---
// A máquina de estados vive no servidor: `allowed_actions` diz o que ESTE
// utilizador pode fazer AGORA (estado ∩ permissões ∩ âmbito) e a UI só mostra
// essas ações — nunca reconstrói a regra. O sistema nunca envia email: "enviar"
// regista que uma pessoa autorizada o fez fora do sistema.
export type MaterialRequestStatus =
  | "rascunho"
  | "pedido_enviado"
  | "orcamento_recebido"
  | "aprovado"
  | "adjudicado"
  | "cancelado";

export type MaterialRequestAction = "send" | "record_quote" | "approve" | "adjudicate" | "cancel";

export const MATERIAL_REQUEST_STATUS_LABELS: Record<MaterialRequestStatus, string> = {
  rascunho: "Rascunho",
  pedido_enviado: "Pedido enviado",
  orcamento_recebido: "Orçamento recebido",
  aprovado: "Aprovado",
  adjudicado: "Adjudicado",
  cancelado: "Cancelado",
};

export const MATERIAL_REQUEST_ACTION_LABELS: Record<MaterialRequestAction, string> = {
  send: "Marcar como enviado",
  record_quote: "Registar orçamento",
  approve: "Aprovar orçamento",
  adjudicate: "Adjudicar",
  cancel: "Cancelar pedido",
};

export interface MaterialRequestLine {
  id: string;
  item_id: string | null;
  description: string;
  quantity: string;
  unit: string | null;
  unit_price: string | null;
  line_total: string | null;
}

export interface MaterialRequestHistoryEntry {
  action: string;
  from_status: string | null;
  to_status: string;
  changed_by_display_name: string | null;
  note: string;
  changed_at: string;
}

export interface MaterialRequest {
  id: string;
  project_id: string;
  project_name: string | null;
  supplier_id: string | null;
  supplier_name: string | null;
  status: MaterialRequestStatus;
  notes: string;
  created_by_display_name: string | null;
  approved_by_display_name: string | null;
  created_at: string;
  updated_at: string;
  lines: MaterialRequestLine[];
  // `null` enquanto houver linhas sem preço — nunca um total parcial.
  total: string | null;
  allowed_actions: MaterialRequestAction[];
  history: MaterialRequestHistoryEntry[];
}

export interface MaterialRequestLineInput {
  item_id?: string | null;
  description?: string;
  quantity: string;
}

export const listMaterialRequests = (
  filters: { project_id?: string; supplier_id?: string; status?: string } = {},
) => {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  const query = params.toString();
  return apiGet<MaterialRequest[]>(`/api/material-requests${query ? `?${query}` : ""}`);
};

export const getMaterialRequest = (id: string) => apiGet<MaterialRequest>(`/api/material-requests/${id}`);

export const createMaterialRequest = (payload: {
  project_id: string;
  supplier_id?: string | null;
  notes?: string;
  lines: MaterialRequestLineInput[];
}) => apiPost<MaterialRequest>("/api/material-requests", payload);

export const applyMaterialRequestAction = (
  id: string,
  payload: { action: MaterialRequestAction; note?: string; prices?: { line_id: string; unit_price: string }[] },
) => apiPost<MaterialRequest>(`/api/material-requests/${id}/actions`, payload);

// Texto para uma pessoa rever, copiar e enviar — o sistema nunca o envia.
export interface MaterialRequestEmailDraft {
  to: string | null;
  subject: string;
  body: string;
}

export const getMaterialRequestEmailDraft = (id: string) =>
  apiGet<MaterialRequestEmailDraft>(`/api/material-requests/${id}/email-draft`);

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
  reversal_of_movement_id: string | null;
  created_by_person_id: string | null;
  created_at: string;
  item_name: string | null;
  project_name: string | null;
}

export interface InventoryMovementCreate {
  item_id: string;
  movement_type: string;
  quantity: string;
  location_id?: string | null;
  destination_location_id?: string | null;
  reference?: string;
  unit_cost?: string | null;
  idempotency_key?: string | null;
}

export function listInventoryMovements(
  filters: { item_id?: string; project_id?: string; movement_type?: string; owner?: InventoryOwner } = {},
): Promise<InventoryMovement[]> {
  const params = new URLSearchParams();
  if (filters.item_id) params.set("item_id", filters.item_id);
  if (filters.project_id) params.set("project_id", filters.project_id);
  if (filters.movement_type) params.set("movement_type", filters.movement_type);
  params.set("owner", filters.owner ?? "solcor");
  return apiGet<InventoryMovement[]>(`/api/inventory/movements?${params.toString()}`);
}

export const createCentralMovement = (payload: InventoryMovementCreate) =>
  apiPost<InventoryMovement>("/api/inventory/movements", payload);

export interface ProjectMaterialRequirement {
  id: string;
  project_id: string;
  item_id: string;
  quantity_required: string;
  notes: string;
  source: string;
  created_by_person_id: string | null;
  created_at: string;
  updated_at: string;
  item_name: string | null;
  item_unit: string | null;
  reserved: string;
  consumed: string;
  missing: string;
  available_stock_sufficient: boolean;
}

export interface ProjectOnSite {
  item_id: string;
  item_name: string | null;
  item_unit: string | null;
  quantity: string;
}

export interface ProjectInventorySummary {
  project_id: string;
  requirements: ProjectMaterialRequirement[];
  reservations: InventoryMovement[];
  on_site: ProjectOnSite[];
}

export const getProjectInventory = (projectId: string, owner: InventoryOwner = "solcor") =>
  apiGet<ProjectInventorySummary>(`/api/projects/${projectId}/inventory?owner=${owner}`);

export interface ProjectMaterialRequirementCreate {
  item_id: string;
  quantity_required: string;
  notes?: string;
}

export interface ProjectMaterialRequirementUpdate {
  quantity_required?: string;
  notes?: string;
}

export const createMaterialRequirement = (
  projectId: string,
  payload: ProjectMaterialRequirementCreate,
  owner: InventoryOwner = "solcor",
) => apiPost<ProjectMaterialRequirement>(`/api/projects/${projectId}/inventory/requirements?owner=${owner}`, payload);

export const updateMaterialRequirement = (
  projectId: string,
  requirementId: string,
  payload: ProjectMaterialRequirementUpdate,
) => apiPatch<ProjectMaterialRequirement>(`/api/projects/${projectId}/inventory/requirements/${requirementId}`, payload);

export interface ProjectInventoryOperationCreate {
  item_id: string;
  quantity: string;
  reference?: string;
  idempotency_key?: string | null;
  owner?: InventoryOwner;
}

function projectInventoryOperation(
  projectId: string,
  action: "reserve" | "consume" | "release" | "return" | "deliver" | "collect",
  payload: ProjectInventoryOperationCreate,
) {
  return apiPost<InventoryMovement>(`/api/projects/${projectId}/inventory/${action}`, {
    ...payload,
    owner: payload.owner ?? "solcor",
  });
}

export const reserveProjectMaterial = (projectId: string, payload: ProjectInventoryOperationCreate) =>
  projectInventoryOperation(projectId, "reserve", payload);
export const consumeProjectMaterial = (projectId: string, payload: ProjectInventoryOperationCreate) =>
  projectInventoryOperation(projectId, "consume", payload);
export const releaseProjectMaterial = (projectId: string, payload: ProjectInventoryOperationCreate) =>
  projectInventoryOperation(projectId, "release", payload);
export const returnProjectMaterial = (projectId: string, payload: ProjectInventoryOperationCreate) =>
  projectInventoryOperation(projectId, "return", payload);
// Entrega/recolha (D-064): localização física do material. Não alteram o
// stock central nem a reserva; recolher não pode exceder o que está no local.
export const deliverProjectMaterial = (projectId: string, payload: ProjectInventoryOperationCreate) =>
  projectInventoryOperation(projectId, "deliver", payload);
export const collectProjectMaterial = (projectId: string, payload: ProjectInventoryOperationCreate) =>
  projectInventoryOperation(projectId, "collect", payload);

export const reverseProjectMovement = (projectId: string, movementId: string, reason?: string) =>
  apiPost<InventoryMovement>(
    `/api/projects/${projectId}/inventory/movements/${movementId}/reverse`,
    { reason: reason || "Anulação manual" },
  );

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

export interface CompletedTaskItem {
  id: string;
  title: string;
  project_id: string;
  project_name: string;
  completed_at: string;
}

export interface CompletedTasksWeeklyPm {
  pm_person_id: string | null;
  pm_display_name: string | null;
  task_count: number;
  subtask_count: number;
  tasks: CompletedTaskItem[];
}

export interface CompletedTasksWeekly {
  iso_year: number;
  iso_week: number;
  week_start: string;
  week_end: string;
  pms: CompletedTasksWeeklyPm[];
}

export interface CompletedTasksWeeklyFilters {
  from?: string;
  to?: string;
}

function completedTasksWeeklyFiltersToParams(filters: CompletedTasksWeeklyFilters): string {
  const params = new URLSearchParams();
  if (filters.from) params.set("from", filters.from);
  if (filters.to) params.set("to", filters.to);
  return params.toString();
}

export function getCompletedTasksWeekly(filters: CompletedTasksWeeklyFilters = {}): Promise<CompletedTasksWeekly[]> {
  const qs = completedTasksWeeklyFiltersToParams(filters);
  return apiGet<CompletedTasksWeekly[]>(`/api/performance/completed-tasks-weekly${qs ? `?${qs}` : ""}`);
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

// Estado derivado no servidor (ver docs/PLANO_LICENCIAMENTO_SIM.md §1). Nunca recalculado no cliente.
export type LicensingState =
  | "sem_registo"
  | "cadastrado"
  | "certificacao_pedida"
  | "inspecionado"
  | "certificado_provisorio"
  | "certificado_definitivo";

export interface ProjectLicensingData {
  project_id: string;
  upac_number: string | null;
  upac_registration_date: string | null;
  dgeg_number: string | null;
  cadastro_number: string | null;
  licensing_status: string | null;
  registration_date: string | null;
  certification_request_date: string | null;
  inspecting_entity: string | null;
  inspection_date: string | null;
  provisional_certificate_date: string | null;
  certificate_date: string | null;
  installer: string | null;
  commercializer: string | null;
  annual_production_kwh: number | null;
  comments: string;
  licensing_state: LicensingState;
  updated_at: string | null;
}

export interface ProjectCommunicationData {
  project_id: string;
  communication_status: string | null;
  whereversim_login: string | null;
  notes: string;
  updated_at: string | null;
}

// Credenciais de portais: a leitura nunca traz password (só `has_password`).
export type PortalCode = "dgeg_login_geral" | "mastervantagem" | "outro";

export interface PortalCredential {
  id: string;
  project_id: string;
  portal: string;
  username: string;
  email: string | null;
  has_password: boolean;
  updated_at: string | null;
}

export interface PortalCredentialReveal {
  id: string;
  portal: string;
  username: string;
  password: string;
}

export interface PortalCredentialCreate {
  portal: PortalCode;
  username: string;
  email?: string | null;
  // Omitido = sem password.
  password?: string;
}

export interface PortalCredentialUpdate {
  portal?: PortalCode;
  username?: string;
  // Omitido = manter; null = limpar.
  email?: string | null;
  // Omitido = manter; string não vazia = substituir; null = remover a password.
  password?: string | null;
}

// Cartões SIM (0..n por projeto). A leitura nunca traz PIN/PUK: só `has_pin`/`has_puk`.
export type SimPurpose = "comunicacoes" | "dados_moveis" | "outro";

export interface SimCard {
  id: string;
  project_id: string;
  purpose: SimPurpose;
  operator: string | null;
  phone_number: string | null;
  iccid: string | null;
  verified_on_portal: boolean | null;
  verified_date: string | null;
  notes: string;
  has_pin: boolean;
  has_puk: boolean;
  updated_at: string | null;
}

export interface SimCardCreate {
  purpose: SimPurpose;
  operator?: string | null;
  phone_number?: string | null;
  iccid?: string | null;
  verified_on_portal?: boolean | null;
  verified_date?: string | null;
  notes?: string | null;
  // Omitido = sem PIN/PUK. String vazia ou null com o campo explícito = sem valor.
  pin?: string | null;
  puk?: string | null;
}

// PATCH: campos omitidos mantêm-se. `pin`/`puk` omitidos = mantêm; `null`/"" = removem.
export type SimCardUpdate = Partial<SimCardCreate>;

export interface SimCardReveal {
  id: string;
  pin: string | null;
  puk: string | null;
}

// Contratos de venda de excedente.
export interface SurplusContract {
  id: string;
  project_id: string;
  commercializer: string | null;
  contract_type: string | null;
  contract_sent_date: string | null;
  signed_received_date: string | null;
  sent_to_commercializer_date: string | null;
  status: string | null;
  duration_months: number | null;
  start_date: string | null;
  end_date: string | null;
  notes: string;
  updated_at: string | null;
}

export interface SurplusContractInput {
  commercializer: string | null;
  contract_type: string | null;
  contract_sent_date: string | null;
  signed_received_date: string | null;
  sent_to_commercializer_date: string | null;
  status: string | null;
  duration_months: number | null;
  start_date: string | null;
  end_date: string | null;
  notes: string | null;
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

// --- Ficha de segurança da obra ---
export type SafetySheetRoofType =
  | "telha_ceramica"
  | "chapa_sandwich"
  | "chapa_simples_fibrocimento"
  | "laje_terraco"
  | "solo"
  | "outro";
export type SafetySheetAccessMethod = "escada" | "andaime" | "plataforma_elevatoria" | "outro";
export type SafetySheetRisk =
  | "queda_altura"
  | "eletrico_dc_ac"
  | "fragil_claraboias"
  | "condicoes_meteorologicas"
  | "outro";
export type SafetySheetMeasure =
  | "linha_vida"
  | "arnes"
  | "capacete"
  | "luvas_dieleticas"
  | "calcado"
  | "guarda_corpos"
  | "outro";

export interface SafetySheetWorker {
  person_id: string | null;
  name: string;
  installer_id: string | null;
  team_id: string | null;
}

export interface SafetySheetRead {
  project_id: string;
  version: number;
  roof_type: SafetySheetRoofType | null;
  roof_other: string | null;
  approximate_height_m: number | null;
  access_method: SafetySheetAccessMethod | null;
  access_other: string | null;
  risks: SafetySheetRisk[];
  risk_other: string | null;
  safety_measures: SafetySheetMeasure[];
  measure_other: string | null;
  workers: SafetySheetWorker[];
  safety_responsible: string | null;
  emergency_contacts: string | null;
  observations: string | null;
  work_start_date: string | null;
  work_end_date: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface SafetySheetPrefillRead {
  project_id: string;
  workers: SafetySheetWorker[];
}

export interface SafetySheetUpdate {
  expected_version: number;
  roof_type: SafetySheetRoofType | null;
  roof_other: string | null;
  approximate_height_m: number | null;
  access_method: SafetySheetAccessMethod | null;
  access_other: string | null;
  risks: SafetySheetRisk[];
  risk_other: string | null;
  safety_measures: SafetySheetMeasure[];
  measure_other: string | null;
  workers: SafetySheetWorker[];
  safety_responsible: string | null;
  emergency_contacts: string | null;
  observations: string | null;
  work_start_date: string | null;
  work_end_date: string | null;
}

export const getSafetySheet = (projectId: string) =>
  apiGet<SafetySheetRead>(`/api/projects/${projectId}/safety-sheet`);
export const updateSafetySheet = (projectId: string, body: SafetySheetUpdate) =>
  apiPut<SafetySheetRead>(`/api/projects/${projectId}/safety-sheet`, body);
export const prefillSafetySheetWorkers = (projectId: string) =>
  apiGet<SafetySheetPrefillRead>(`/api/projects/${projectId}/safety-sheet/workers-prefill`);

async function requestHtml(path: string): Promise<string> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { Accept: "text/html", ...(await authHeaders()) },
  });
  if (res.status === 401 && getActiveMsalAccount() !== null) redirectToExpiredSession();
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = formatApiDetail(body.detail) ?? detail;
    } catch {
      // Resposta não-JSON: mantém o statusText.
    }
    throw new ApiError(res.status, detail);
  }
  return res.text();
}

export const getSafetySheetPrintHtml = (projectId: string) =>
  requestHtml(`/api/projects/${projectId}/safety-sheet/print`);

export const listProjectCredentials = (projectId: string) =>
  apiGet<PortalCredential[]>(`/api/projects/${projectId}/credentials`);
export const createProjectCredential = (projectId: string, body: PortalCredentialCreate) =>
  apiPost<PortalCredential>(`/api/projects/${projectId}/credentials`, body);
export const updateProjectCredential = (projectId: string, credentialId: string, body: PortalCredentialUpdate) =>
  apiPatch<PortalCredential>(`/api/projects/${projectId}/credentials/${credentialId}`, body);
export const deleteProjectCredential = (projectId: string, credentialId: string) =>
  apiDelete<void>(`/api/projects/${projectId}/credentials/${credentialId}`);
export const revealProjectCredential = (projectId: string, credentialId: string) =>
  apiPost<PortalCredentialReveal>(`/api/projects/${projectId}/credentials/${credentialId}/reveal`);

export const listProjectSimCards = (projectId: string) =>
  apiGet<SimCard[]>(`/api/projects/${projectId}/sim-cards`);
export const createProjectSimCard = (projectId: string, body: SimCardCreate) =>
  apiPost<SimCard>(`/api/projects/${projectId}/sim-cards`, body);
export const updateProjectSimCard = (projectId: string, simId: string, body: SimCardUpdate) =>
  apiPatch<SimCard>(`/api/projects/${projectId}/sim-cards/${simId}`, body);
export const deleteProjectSimCard = (projectId: string, simId: string) =>
  apiDelete<void>(`/api/projects/${projectId}/sim-cards/${simId}`);
export const revealProjectSimCard = (projectId: string, simId: string) =>
  apiPost<SimCardReveal>(`/api/projects/${projectId}/sim-cards/${simId}/reveal`);

export const listSurplusContracts = (projectId: string) =>
  apiGet<SurplusContract[]>(`/api/projects/${projectId}/surplus-contracts`);
export const createSurplusContract = (projectId: string, body: Partial<SurplusContractInput>) =>
  apiPost<SurplusContract>(`/api/projects/${projectId}/surplus-contracts`, body);
export const updateSurplusContract = (projectId: string, contractId: string, body: Partial<SurplusContractInput>) =>
  apiPatch<SurplusContract>(`/api/projects/${projectId}/surplus-contracts/${contractId}`, body);
export const deleteSurplusContract = (projectId: string, contractId: string) =>
  apiDelete<void>(`/api/projects/${projectId}/surplus-contracts/${contractId}`);

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
  lifecycle_status: string | null;
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
  // Visitas futuras (calendário). `visits_visible=false` (sem calendar.view)
  // => os dois campos ficam `null`, nunca "0 visitas". Não afetam attention.
  visits_visible: boolean;
  upcoming_visits_count: number | null;
  next_visit: MapNextVisit | null;
}

export interface MapNextVisit {
  id: string;
  title: string;
  starts_at: string;
  ends_at: string;
  assigned_to_display_name: string | null;
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

// Otimização da ordem de paragens (D-065). Distância em LINHA RETA (grande
// círculo) — aproximação, nunca quilómetros de condução. A primeira paragem é
// o ponto de partida; o servidor resolve coordenadas e visibilidade.
export type RouteStopKind = "project" | "supplier" | "pickup";

export interface RouteStop {
  kind: RouteStopKind;
  id: string;
  name: string;
  lat: number;
  lon: number;
  leg_km: number;
  cumulative_km: number;
}

export interface RouteOptimization {
  stops: RouteStop[];
  return_leg_km: number | null;
  round_trip: boolean;
  total_km: number;
  requested_order_km: number;
  saved_km: number;
  method: "exact" | "heuristic";
  distance_model: "great_circle";
}

export const optimizeRoute = (stops: { kind: RouteStopKind; id: string }[], roundTrip: boolean) =>
  apiPost<RouteOptimization>("/api/map/optimize-route", { stops, round_trip: roundTrip });

// Plano de deslocação (D-066): a rota otimizada mais o que há para fazer em
// cada instalação. Só leitura. Cada secção é `null` quando o utilizador não
// tem a permissão para a ver — nunca uma lista vazia (que diria "nada a fazer").
export interface TripTask {
  id: string;
  title: string;
  category: string;
  priority: string;
  status: string;
  due_date: string | null;
  is_overdue: boolean;
}

export interface TripIssue {
  id: string;
  description: string;
  category: string;
  priority: string;
  due_date: string | null;
}

export interface TripCollect {
  item_id: string;
  item_name: string | null;
  item_unit: string | null;
  quantity: string;
}

export interface TripStopJobs {
  tasks: TripTask[] | null;
  issues: TripIssue[] | null;
  collect: TripCollect[] | null;
  next_visit: MapNextVisit | null;
}

export interface TripStop extends RouteStop {
  info: string | null;
  jobs: TripStopJobs | null;
}

export interface TripSummary {
  projects: number;
  suppliers: number;
  pickup_points: number;
  operational_tasks: number | null;
  overdue_tasks: number | null;
  issues: number | null;
  items_to_collect: number | null;
}

export interface TripPlan extends Omit<RouteOptimization, "stops"> {
  stops: TripStop[];
  summary: TripSummary;
  visibility: { tasks: boolean; issues: boolean; material: boolean; visits: boolean };
}

export const planTrip = (stops: { kind: RouteStopKind; id: string }[], roundTrip: boolean) =>
  apiPost<TripPlan>("/api/map/trip-plan", { stops, round_trip: roundTrip });

// --- Fornecedores (D-070) ---
export interface SupplierContact {
  id?: string;
  name: string;
  department: string | null;
  phone: string | null;
  email: string | null;
}

export interface Supplier extends MapSupplier {
  phone: string | null;
  website: string | null;
  // Ligação ao mapa (localização exata) e contactos (pessoas/departamentos) — D-090.
  maps_url: string | null;
  contacts: SupplierContact[];
  notes: string;
  // Vários tipos por fornecedor, por ordem alfabética.
  material_types: string[];
  company_codes: SupplierCompanyCode[];
}

export type SupplierCompanyCode = "solcor" | "verde_milenar";

export interface SupplierInput {
  name: string;
  category: string | null;
  contact: string | null;
  phone: string | null;
  email: string | null;
  website: string | null;
  address: string | null;
  maps_url: string | null;
  contacts: SupplierContact[];
  lat: number | null;
  lon: number | null;
  is_preferred: boolean;
  lead_time_days: number | null;
  materials: string;
  notes: string;
  material_types: string[];
  company_codes: SupplierCompanyCode[];
  is_active: boolean;
}

export interface SupplierMaterialType {
  id: string;
  name: string;
  // Fornecedores ativos com este tipo.
  active_suppliers: number;
}

export interface SupplierFilters {
  q?: string;
  material_type?: string;
  is_active?: boolean;
  company_code?: SupplierCompanyCode | "unclassified";
}

export function listSuppliers(filters: SupplierFilters = {}): Promise<Supplier[]> {
  const params = new URLSearchParams();
  if (filters.q) params.set("q", filters.q);
  if (filters.material_type) params.set("material_type", filters.material_type);
  if (filters.is_active !== undefined) params.set("is_active", String(filters.is_active));
  if (filters.company_code) params.set("company_code", filters.company_code);
  const qs = params.toString();
  return apiGet<Supplier[]>(`/api/suppliers${qs ? `?${qs}` : ""}`);
}
export const listSupplierMaterialTypes = () => apiGet<SupplierMaterialType[]>("/api/suppliers/material-types");
export const createSupplier = (payload: Partial<SupplierInput> & { name: string }) =>
  apiPost<Supplier>("/api/suppliers", payload);
export const updateSupplier = (id: string, changes: Partial<SupplierInput>) =>
  apiPatch<Supplier>(`/api/suppliers/${id}`, changes);

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

export type PlanningView = "month" | "week" | "list";

export interface CalendarEventCategory {
  code: string;
  label: string;
  color: string;
}

export interface CalendarEvent {
  id: string;
  visit_id: string | null;
  project_id: string | null;
  task_id: string | null;
  assigned_to_person_id: string | null;
  assigned_to_person_ids?: string[];
  title: string;
  category?: string;
  starts_at: string;
  ends_at: string;
  status: string;
  graph_event_id: string | null;
  created_at: string;
  project_name: string | null;
  project_url?: string | null;
  project_context_hidden?: boolean;
  task_title: string | null;
  assigned_to_display_name: string | null;
  assigned_to_display_names?: string[];
  process_stage_id?: string | null;
  process_stage_code?: string | null;
  process_stage_title?: string | null;
  process_subtask_id?: string | null;
  process_subtask_code?: string | null;
  process_subtask_title?: string | null;
  responsible_person_ids?: string[];
  responsible_display_names?: string[];
  source?: "manual" | "process";
  source_id?: string | null;
  category_label?: string | null;
  category_color?: string | null;
  can_manage: boolean;
  recurrence_series_id?: string | null;
  recurrence_rule?: "weekly" | null;
  recurrence_index?: number | null;
  recurrence_count?: number | null;
  recurrence_until?: string | null;
}

export interface CalendarEventFilters {
  project_id?: string;
  assigned_to_person_id?: string;
  mine_only?: boolean;
  category?: string;
  starts_from?: string;
  starts_to?: string;
}

function calendarFiltersToParams(filters: CalendarEventFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.project_id) params.set("project_id", filters.project_id);
  if (filters.assigned_to_person_id) params.set("assigned_to_person_id", filters.assigned_to_person_id);
  if (filters.mine_only) params.set("mine_only", "true");
  if (filters.category) params.set("category", filters.category);
  if (filters.starts_from) params.set("starts_from", filters.starts_from);
  if (filters.starts_to) params.set("starts_to", filters.starts_to);
  return params;
}

export function listCalendarEvents(filters: CalendarEventFilters = {}): Promise<CalendarEvent[]> {
  const qs = calendarFiltersToParams(filters).toString();
  return apiGet<CalendarEvent[]>(`/api/planning/events${qs ? `?${qs}` : ""}`);
}

export function listProcessCalendarEvents(filters: CalendarEventFilters = {}): Promise<CalendarEvent[]> {
  const qs = calendarFiltersToParams(filters).toString();
  return apiGet<CalendarEvent[]>(`/api/planning/process-events${qs ? `?${qs}` : ""}`);
}

export const listPlanningEventCategories = () => apiGet<CalendarEventCategory[]>("/api/planning/event-categories");
// Short aliases keep the planning surface discoverable for consumers that do
// not use the longer feature-qualified names.
export const listEventCategories = listPlanningEventCategories;

export interface PlanningPreferences {
  view: PlanningView;
  hide_weekends: boolean;
}

export const getPlanningPreferences = () => apiGet<PlanningPreferences>("/api/me/planning-preferences");
export const updatePlanningPreferences = (changes: Partial<PlanningPreferences>) =>
  apiPatch<PlanningPreferences>("/api/me/planning-preferences", changes);

export interface PlanningProcessSubtaskOption {
  id: string;
  code: string;
  title: string;
  planned_start: null;
  planned_end: null;
}

export interface PlanningProcessOption {
  project_id: string;
  stage_id: string;
  stage_code: string;
  stage_title: string;
  planned_start: string | null;
  planned_end: string | null;
  responsible_person_ids: string[];
  responsible_display_names: string[];
  subtasks: PlanningProcessSubtaskOption[];
}

export const getPlanningProcessOptions = (projectId: string) =>
  apiGet<PlanningProcessOption[]>(`/api/planning/process-options/${projectId}`);

export interface CalendarEventCreatePayload {
  title: string;
  starts_at: string;
  ends_at: string;
  project_id?: string | null;
  task_id?: string | null;
  assigned_to_person_id?: string | null;
  assigned_to_person_ids?: string[];
  category?: string;
  process_stage_id?: string | null;
  process_subtask_id?: string | null;
  recurrence?: "weekly";
  recurrence_until?: string;
  idempotency_key?: string;
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
  assigned_to_person_ids?: string[];
  category?: string;
  process_stage_id?: string | null;
  process_subtask_id?: string | null;
  status?: string;
}

export type CalendarEventMutationScope = "occurrence" | "series";

export const updateCalendarEvent = (
  id: string,
  changes: CalendarEventUpdatePayload,
  scope: CalendarEventMutationScope = "occurrence",
) => apiPatch<CalendarEvent>(`/api/planning/events/${id}?scope=${scope}`, changes);

export const cancelCalendarEvent = (
  id: string,
  scope: CalendarEventMutationScope = "occurrence",
) => apiPost<CalendarEvent>(`/api/planning/events/${id}/cancel?scope=${scope}`, {});

// --- Relatório semanal ao cliente ---

export type ClientReportDeliveryMode = "local" | "graph" | string;
export type ClientReportSendStatus =
  | "sent"
  | "outbox_local"
  | "failed"
  | "skipped"
  | "pending_review"
  | "discarded"
  | "expired"
  | "pending"
  | string;

export interface ClientReportConfig {
  enabled?: boolean;
  review_before_send?: boolean;
  weekday?: number;
  send_time?: string;
  to_emails?: string[];
  cc_emails?: string[];
  weekly_note?: string;
}

export interface ClientReportSend {
  id: string;
  iso_week?: string;
  status: ClientReportSendStatus;
  trigger?: string;
  subject?: string;
  to_emails?: string[];
  cc_emails?: string[];
  sent_at?: string | null;
  created_at?: string;
  error?: string | null;
}

export interface ClientReportResponse extends ClientReportConfig {
  config?: ClientReportConfig | null;
  can_manage?: boolean;
  delivery_mode?: ClientReportDeliveryMode;
  preview_available?: boolean;
  next_send_at?: string | null;
  warnings?: string[];
  last_sends?: ClientReportSend[];
}

export interface ClientReportPreview {
  subject: string;
  body_html: string;
  from_email?: string | null;
  to: string[];
  cc: string[];
}

export interface ClientReportUpdate extends ClientReportConfig {
  enabled: boolean;
  review_before_send: boolean;
  weekday: number;
  send_time: string;
  to_emails: string[];
  cc_emails: string[];
  weekly_note: string;
}

export interface ClientReportListItem {
  project_id: string;
  project_name: string;
  client_name?: string | null;
  pm?: string | null;
  lifecycle_status?: string | null;
  status_label?: string | null;
  enabled: boolean;
  next_send_at?: string | null;
  last_send?: ClientReportSend | null;
  pending_review_count?: number;
  to_emails?: string[];
  cc_emails?: string[];
}

export const getClientReport = (projectId: string) =>
  apiGet<ClientReportResponse>(`/api/projects/${encodeURIComponent(projectId)}/client-report`);

export const updateClientReport = (projectId: string, changes: ClientReportUpdate) =>
  apiPut<ClientReportResponse>(`/api/projects/${encodeURIComponent(projectId)}/client-report`, changes);

export const previewClientReport = (projectId: string) =>
  apiGet<ClientReportPreview>(`/api/projects/${encodeURIComponent(projectId)}/client-report/preview`);

export const sendClientReportNow = (projectId: string) =>
  apiPost<ClientReportSend>(`/api/projects/${encodeURIComponent(projectId)}/client-report/send-now`);

export const approveClientReportSend = (sendId: string) =>
  apiPost<ClientReportSend>(`/api/client-report-sends/${encodeURIComponent(sendId)}/approve`);

export const discardClientReportSend = (sendId: string) =>
  apiPost<ClientReportSend>(`/api/client-report-sends/${encodeURIComponent(sendId)}/discard`);

export interface ClientReportListFilters {
  status?: string;
  pm_person_id?: string;
}

export const listClientReports = (filters: ClientReportListFilters = {}) => {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.pm_person_id) params.set("pm_person_id", filters.pm_person_id);
  const query = params.toString();
  return apiGet<ClientReportListItem[]>(`/api/client-reports${query ? `?${query}` : ""}`);
};
