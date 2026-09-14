// Login real Microsoft Entra ID — Fase 1, item 3 do hardening (D-031).
//
// Usa @azure/msal-browser diretamente (sem @azure/msal-react, para manter
// a mesma forma simples de módulo singleton já usada em api/client.ts,
// sem introduzir Context/Provider só para isto). O MSAL browser SÓ suporta
// Authorization Code + PKCE para aplicações públicas SPA desde a v2 — não
// há flag de "implicit flow" para desativar aqui, é sempre PKCE.
//
// Nunca usa o ID token como autorização: acquireToken*({ scopes: apiScopes })
// devolve um access token dedicado ao recurso da API (result.accessToken),
// que é o único valor que sai deste módulo para o resto da app.
//
// Sem VITE_ENTRA_CLIENT_ID/VITE_ENTRA_TENANT_ID/VITE_ENTRA_API_SCOPE
// configurados (nenhum tenant real disponível neste repositório — ver
// docs/OPEN_QUESTIONS.md, pergunta 1), `isEntraConfigured` fica false e o
// ecrã de login mostra o botão "Entrar com Microsoft" desativado, nunca
// tenta autenticar com credenciais inventadas.
import {
  AccountInfo,
  AuthenticationResult,
  Configuration,
  EventType,
  InteractionRequiredAuthError,
  PublicClientApplication,
} from "@azure/msal-browser";

export const ENTRA_CLIENT_ID = import.meta.env.VITE_ENTRA_CLIENT_ID ?? "";
export const ENTRA_TENANT_ID = import.meta.env.VITE_ENTRA_TENANT_ID ?? "";
export const ENTRA_API_SCOPE = import.meta.env.VITE_ENTRA_API_SCOPE ?? "";

export const isEntraConfigured = Boolean(ENTRA_CLIENT_ID && ENTRA_TENANT_ID && ENTRA_API_SCOPE);

// Âmbito pedido para o access token da API — nunca inclui "openid"/
// "profile" aqui (esses produzem/afetam o ID token, irrelevante para
// autorizar pedidos à API).
export const apiScopes: string[] = ENTRA_API_SCOPE ? [ENTRA_API_SCOPE] : [];

// Login de desenvolvimento (X-Dev-User-Email): ligado por omissão em
// `vite dev`/testes (import.meta.env.DEV), desligado por omissão num
// build de produção — espelha a mesma filosofia de "hardening por
// omissão fora de local/test" do backend (Settings._enforce_hardening_in_non_local_envs).
// Um valor explícito de VITE_ENABLE_DEV_LOGIN substitui sempre essa
// omissão (útil para testar um build de produção apontado a um backend
// local/test).
export const devLoginEnabled: boolean = (() => {
  const explicit = import.meta.env.VITE_ENABLE_DEV_LOGIN;
  if (explicit === "true") return true;
  if (explicit === "false") return false;
  return Boolean(import.meta.env.DEV);
})();

const msalConfig: Configuration = {
  auth: {
    clientId: ENTRA_CLIENT_ID || "00000000-0000-0000-0000-000000000000",
    authority: ENTRA_TENANT_ID
      ? `https://login.microsoftonline.com/${ENTRA_TENANT_ID}`
      : "https://login.microsoftonline.com/organizations",
    redirectUri: import.meta.env.VITE_ENTRA_REDIRECT_URI || window.location.origin,
    postLogoutRedirectUri: (import.meta.env.VITE_ENTRA_REDIRECT_URI || window.location.origin) + "/login",
  },
  cache: {
    // sessionStorage, não localStorage: os tokens não sobrevivem ao fecho
    // do separador nem são partilhados entre separadores — reduz a
    // janela de exposição a um XSS persistente. O MSAL só faz refresh
    // silencioso dentro da mesma sessão de separador; reabrir a app noutro
    // separador pede novo login (aceitável para esta fase — nunca discutido
    // como requisito UX).
    cacheLocation: "sessionStorage",
  },
};

export const msalInstance = new PublicClientApplication(msalConfig);

// initialize() é obrigatório antes de qualquer outra chamada (MSAL v3+).
// handleRedirectOnLoad() trata a navegação de volta do loginRedirect
// (extrai o código de autorização, troca-o por tokens via PKCE) — tem de
// ser chamado uma vez, antes da app renderizar (ver main.tsx).
let readyPromise: Promise<void> | null = null;

export function ensureMsalReady(): Promise<void> {
  if (!readyPromise) {
    readyPromise = msalInstance.initialize().then(async () => {
      const result: AuthenticationResult | null = await msalInstance.handleRedirectPromise();
      if (result?.account) {
        msalInstance.setActiveAccount(result.account);
      } else if (!msalInstance.getActiveAccount()) {
        const accounts = msalInstance.getAllAccounts();
        if (accounts.length > 0) msalInstance.setActiveAccount(accounts[0]);
      }
    });
  }
  return readyPromise;
}

msalInstance.addEventCallback((event) => {
  if (
    (event.eventType === EventType.LOGIN_SUCCESS || event.eventType === EventType.ACQUIRE_TOKEN_SUCCESS) &&
    (event.payload as AuthenticationResult)?.account
  ) {
    msalInstance.setActiveAccount((event.payload as AuthenticationResult).account);
  }
});

export function getActiveMsalAccount(): AccountInfo | null {
  return msalInstance.getActiveAccount();
}

// Authorization Code + PKCE — loginRedirect é o único fluxo interativo do
// MSAL browser para SPAs (nunca implicit flow). Pede logo o âmbito da API
// no login, para o primeiro acquireTokenSilent já ter consentimento.
export function loginWithMicrosoft(): Promise<void> {
  return msalInstance.loginRedirect({ scopes: apiScopes.length > 0 ? apiScopes : ["User.Read"] });
}

export function logoutFromMicrosoft(): Promise<void> {
  const account = getActiveMsalAccount() ?? undefined;
  return msalInstance.logoutRedirect({ account });
}

export class SessionExpiredError extends Error {
  constructor() {
    super("Sessão Microsoft expirada — é necessário iniciar sessão novamente.");
  }
}

// Access token para a API (nunca o ID token) — tenta sempre renovação
// silenciosa primeiro (o "silent refresh" pedido no hardening); só
// interrompe a app com um redirect quando o MSAL confirma que precisa
// mesmo de interação (InteractionRequiredAuthError: refresh token expirado
// ou revogado, MFA adicional exigido, etc.) — nesse caso a sessão é
// tratada como expirada, nunca como "sem token, seguir pedido na mesma".
export async function getApiAccessToken(): Promise<string | null> {
  const account = getActiveMsalAccount();
  if (!account || apiScopes.length === 0) return null;
  try {
    const result = await msalInstance.acquireTokenSilent({ scopes: apiScopes, account });
    return result.accessToken;
  } catch (err) {
    if (err instanceof InteractionRequiredAuthError) {
      throw new SessionExpiredError();
    }
    throw err;
  }
}
