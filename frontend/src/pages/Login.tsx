import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { setDevUser } from "../api/client";
import { devLoginEnabled, isEntraConfigured, loginWithMicrosoft } from "../auth/msal";

// Fase 1 (D-031): login real via Microsoft Entra ID com MSAL —
// Authorization Code + PKCE, access token dedicado à API (nunca o ID
// token), renovação silenciosa e logout (ver src/auth/msal.ts,
// src/api/client.ts). Sem um tenant/app registration reais configurados
// (VITE_ENTRA_CLIENT_ID/VITE_ENTRA_TENANT_ID/VITE_ENTRA_API_SCOPE — ver
// docs/OPEN_QUESTIONS.md, pergunta 1), o botão fica desativado com uma
// explicação, nunca tenta autenticar com credenciais inventadas.
//
// O login de desenvolvimento (X-Dev-User-Email) fica claramente separado
// abaixo e só é renderizado quando devLoginEnabled é true — por omissão,
// ligado em `vite dev`/testes, desligado num build de produção.
export default function Login() {
  const [email, setEmail] = useState("");
  const [msalError, setMsalError] = useState<string | null>(null);
  const [redirecting, setRedirecting] = useState(false);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const sessionExpired = searchParams.get("sessionExpired") === "1";

  function handleDevSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setDevUser(email.trim());
    navigate("/projects");
  }

  async function handleMicrosoftLogin() {
    setMsalError(null);
    setRedirecting(true);
    try {
      // loginRedirect navega para fora da app (Authorization Code + PKCE);
      // o regresso é tratado em src/auth/msal.ts:ensureMsalReady, chamado
      // em main.tsx antes da app voltar a renderizar.
      await loginWithMicrosoft();
    } catch (err) {
      setRedirecting(false);
      setMsalError(err instanceof Error ? err.message : "Falha desconhecida ao iniciar o login Microsoft.");
    }
  }

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", maxWidth: 420, margin: "4rem auto", padding: "0 1rem" }}>
      <h1>Op_PM</h1>

      {sessionExpired && (
        <div
          style={{
            background: "#fdecea",
            border: "1px solid #e0a29a",
            borderRadius: 6,
            padding: "0.75rem 1rem",
            fontSize: "0.9rem",
            marginBottom: "1.5rem",
          }}
        >
          A sua sessão expirou. Inicie sessão novamente.
        </div>
      )}

      <section style={{ marginBottom: "2rem" }}>
        <button
          type="button"
          onClick={handleMicrosoftLogin}
          disabled={!isEntraConfigured || redirecting}
          style={{
            width: "100%",
            padding: "0.65rem 1rem",
            fontSize: "1rem",
            cursor: isEntraConfigured ? "pointer" : "not-allowed",
          }}
        >
          {redirecting ? "A redirecionar para a Microsoft…" : "Entrar com Microsoft"}
        </button>
        {!isEntraConfigured && (
          <p style={{ fontSize: "0.85rem", color: "#666", marginTop: "0.5rem" }}>
            Login Microsoft ainda não configurado nesta instalação — faltam{" "}
            <code>VITE_ENTRA_CLIENT_ID</code>, <code>VITE_ENTRA_TENANT_ID</code> e{" "}
            <code>VITE_ENTRA_API_SCOPE</code> (ver <code>frontend/.env.example</code> e{" "}
            <code>docs/OPEN_QUESTIONS.md</code>, pergunta 1). O backend já valida tokens
            Entra ID reais quando isto estiver disponível.
          </p>
        )}
        {msalError && (
          <p style={{ fontSize: "0.85rem", color: "#b3261e", marginTop: "0.5rem" }}>{msalError}</p>
        )}
      </section>

      {devLoginEnabled && (
        <section
          style={{
            borderTop: "1px dashed #ccc",
            paddingTop: "1.25rem",
          }}
        >
          <div
            style={{
              background: "#fff8e1",
              border: "1px solid #e0c46a",
              borderRadius: 6,
              padding: "0.75rem 1rem",
              fontSize: "0.85rem",
              marginBottom: "1rem",
            }}
          >
            <strong>Apenas desenvolvimento/testes.</strong> O backend só aceita este
            mecanismo com <code>AUTH_ENABLED=false</code> em <code>local</code>/<code>test</code> —
            nunca disponível em staging/produção.
          </div>

          <form onSubmit={handleDevSubmit}>
            <label htmlFor="email" style={{ display: "block", marginBottom: "0.25rem" }}>
              Email (utilizador de desenvolvimento)
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="chefe.sintetico@example.invalid"
              style={{ width: "100%", padding: "0.5rem", boxSizing: "border-box", marginBottom: "0.75rem" }}
            />
            <button type="submit" style={{ padding: "0.5rem 1rem" }}>
              Entrar (desenvolvimento)
            </button>
          </form>

          <p style={{ fontSize: "0.85rem", color: "#666", marginTop: "1.5rem" }}>
            Utilizadores sintéticos do seed (ver <code>backend/app/migration/seed_dev.py</code>):
          </p>
          <ul style={{ fontSize: "0.85rem", color: "#666" }}>
            <li>chefe.sintetico@example.invalid — Chefe de Operações</li>
            <li>pm.um.sintetico@example.invalid — Project Manager</li>
            <li>comercial.sintetico@example.invalid — Comercial (só leitura)</li>
            <li>financeiro.sintetico@example.invalid — Financeiro</li>
            <li>admin.sintetico@example.invalid — Administrador</li>
          </ul>
        </section>
      )}
    </div>
  );
}
