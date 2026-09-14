/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_DEV_USER_EMAIL?: string;
  // Login real Microsoft Entra ID (MSAL, Authorization Code + PKCE) — ver
  // src/auth/msal.ts. Todos opcionais: sem eles, o botão "Entrar com
  // Microsoft" fica visivelmente desativado, nunca falha silenciosamente.
  readonly VITE_ENTRA_CLIENT_ID?: string;
  readonly VITE_ENTRA_TENANT_ID?: string;
  // Âmbito do access token pedido para a API (nunca o ID token) — ex.
  // "api://<client-id-da-api>/access_as_user". Tem de corresponder ao
  // ENTRA_REQUIRED_SCOPE configurado no backend, se este exigir um scp
  // específico (ver backend/app/config.py).
  readonly VITE_ENTRA_API_SCOPE?: string;
  readonly VITE_ENTRA_REDIRECT_URI?: string;
  // Por omissão: ligado em `vite dev`/testes, desligado num build de
  // produção — só um "true"/"false" explícito aqui substitui essa
  // omissão (ver src/auth/msal.ts:devLoginEnabled).
  readonly VITE_ENABLE_DEV_LOGIN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
