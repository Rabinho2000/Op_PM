// Fecho de hardening da Fase 1 (D-033): o login de desenvolvimento
// (X-Dev-User-Email) nunca pode escapar para um build de produção, mesmo
// que `localStorage` ainda tenha um valor de uma sessão de desenvolvimento
// anterior. `devLoginEnabled` (src/auth/msal.ts) já é computado a partir de
// `import.meta.env` no carregamento do módulo — por isso cada teste
// controla esse valor com `vi.stubEnv` ANTES de importar `client.ts`
// (`vi.resetModules()` garante um módulo novo, nunca a instância já
// avaliada por um teste anterior).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const DEV_USER_STORAGE_KEY = "op_pm_dev_user_email";

async function importClientWithDevLogin(enabled: boolean) {
  vi.resetModules();
  vi.stubEnv("VITE_ENABLE_DEV_LOGIN", enabled ? "true" : "false");
  return import("./client");
}

describe("login de desenvolvimento — gate por devLoginEnabled (D-033)", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("com devLoginEnabled=true: grava, lê, e hasActiveSession reflete o login de desenvolvimento", async () => {
    const client = await importClientWithDevLogin(true);
    expect(client.getDevUser()).toBeNull();
    expect(client.hasActiveSession()).toBe(false);

    client.setDevUser("chefe.sintetico@example.invalid");

    expect(client.getDevUser()).toBe("chefe.sintetico@example.invalid");
    expect(client.hasActiveSession()).toBe(true);
    expect(localStorage.getItem(DEV_USER_STORAGE_KEY)).toBe("chefe.sintetico@example.invalid");
  });

  it("com devLoginEnabled=false: setDevUser nunca grava, getDevUser nunca lê, hasActiveSession fica false", async () => {
    const client = await importClientWithDevLogin(false);

    client.setDevUser("chefe.sintetico@example.invalid");

    expect(client.getDevUser()).toBeNull();
    expect(client.hasActiveSession()).toBe(false);
    // Nunca escreveu no localStorage — não é só a leitura que fica bloqueada.
    expect(localStorage.getItem(DEV_USER_STORAGE_KEY)).toBeNull();
  });

  it("com devLoginEnabled=false: um valor antigo já em localStorage (de uma sessão de dev anterior) é limpo ao carregar o módulo", async () => {
    // Simula o cenário real: alguém fez login de desenvolvimento com
    // VITE_ENABLE_DEV_LOGIN=true, e depois a mesma app (mesmo browser) é
    // recarregada já com um build/configuração de produção
    // (VITE_ENABLE_DEV_LOGIN=false) — o valor antigo nunca deve sobreviver.
    localStorage.setItem(DEV_USER_STORAGE_KEY, "login.antigo@example.invalid");

    const client = await importClientWithDevLogin(false);

    expect(client.getDevUser()).toBeNull();
    expect(localStorage.getItem(DEV_USER_STORAGE_KEY)).toBeNull();
  });

  it("com devLoginEnabled=false: o pedido HTTP nunca envia X-Dev-User-Email, mesmo com localStorage manipulado depois de importar o módulo", async () => {
    const client = await importClientWithDevLogin(false);

    // Escreve diretamente no localStorage, contornando setDevUser — o
    // pedido continua sem o cabeçalho, porque getDevUser() (usado dentro
    // de request()) também recusa ler fora de devLoginEnabled.
    localStorage.setItem(DEV_USER_STORAGE_KEY, "tentativa.manual@example.invalid");

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ status: "ok" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await client.getHealth();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Dev-User-Email"]).toBeUndefined();
  });
});
