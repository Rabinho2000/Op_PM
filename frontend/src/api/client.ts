// Cliente da API. Fase 1 (D-031): login real via Microsoft Entra ID
// (MSAL, ver src/auth/msal.ts) já está implementado — quando há uma conta
// MSAL ativa, todo o pedido leva `Authorization: Bearer <access token da
// API>`. O mecanismo de desenvolvimento (X-Dev-User-Email) continua a
// existir só para local/test (ver src/auth/msal.ts:devLoginEnabled e
// app/security/current_user.py no backend) e nunca é enviado ao mesmo
// tempo que um Bearer token — os dois caminhos são mutuamente exclusivos,
// tal como no backend. Nenhuma chave/segredo de integração (Claude, Graph,
// ClickUp, Financial, Entra) é colocada aqui: essas só existem no backend.
import { SessionExpiredError, getActiveMsalAccount, getApiAccessToken, logoutFromMicrosoft } from "../auth/msal";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const DEV_USER_STORAGE_KEY = "op_pm_dev_user_email";

export function getDevUser(): string | null {
  try {
    return localStorage.getItem(DEV_USER_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setDevUser(email: string): void {
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };

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

  const res = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });

  if (res.status === 401 && usingMsal) {
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

const apiGet = <T>(path: string) => request<T>(path);
const apiPatch = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
const apiPost = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined });

export { ApiError };

// --- /health, /me ---

export interface HealthResponse {
  status: string;
  app_env: string;
  database_dialect: string;
  integrations: Record<string, boolean>;
}

export interface MeResponse {
  user_id: string;
  email: string;
  person_id: string;
  roles: string[];
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
}

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
}

export function listProjects(filters: ProjectFilters = {}): Promise<Project[]> {
  const params = new URLSearchParams();
  if (filters.pm_person_id) params.set("pm_person_id", filters.pm_person_id);
  if (filters.is_active !== undefined) params.set("is_active", String(filters.is_active));
  if (filters.q) params.set("q", filters.q);
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
export const retryPmResolution = (id: string) =>
  apiPost<StagingProjectRecord>(`/api/migration/staging-records/${id}/retry-pm-resolution`);
