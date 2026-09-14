// Cliente mínimo da API. Fase 0: sem login real (Entra ID por implementar),
// por isso usa o cabeçalho de desenvolvimento X-Dev-User-Email — o mesmo
// mecanismo que o backend documenta em app/security/current_user.py.
// Nunca coloca aqui nenhuma chave/segredo de integração (Claude, Graph,
// ClickUp, Financial): essas só existem no backend.

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const DEV_USER_EMAIL = import.meta.env.VITE_DEV_USER_EMAIL ?? "chefe.sintetico@example.invalid";

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

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "X-Dev-User-Email": DEV_USER_EMAIL },
  });
  if (!res.ok) {
    throw new Error(`Pedido a ${path} falhou com estado ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export function getHealth(): Promise<HealthResponse> {
  return apiGet<HealthResponse>("/health");
}

export function getMe(): Promise<MeResponse> {
  return apiGet<MeResponse>("/me");
}
