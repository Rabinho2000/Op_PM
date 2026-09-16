import { FormEvent, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { getHealth, HealthResponse, setDevUser } from "../api/client";
import { devLoginEnabled, isEntraConfigured, loginWithMicrosoft } from "../auth/msal";
import Icon from "../components/Icon";
import { Alert, Avatar } from "../components/ui";

// Fase 1 (D-031): login real via Microsoft Entra ID com MSAL —
// Authorization Code + PKCE, access token dedicado à API (nunca o ID
// token). Sem tenant configurado (VITE_ENTRA_*), o botão fica desativado
// com uma explicação.
//
// Modo demonstração (D-051): a secção de utilizadores sintéticos só existe
// quando `devLoginEnabled` (build de desenvolvimento/demo) E o backend
// confirma em /health que aceita o login de desenvolvimento (só
// local/test). Em staging/produção nunca aparece — e o backend recusa o
// cabeçalho X-Dev-User-Email de qualquer forma.

export const DEMO_USERS = [
  {
    email: "chefe.sintetico@example.invalid",
    name: "Chefe Sintético",
    role: "Chefe de Operações",
    description: "Vê e gere toda a operação, tarefas e férias da equipa.",
  },
  {
    email: "pm.um.sintetico@example.invalid",
    name: "PM Sintético Um",
    role: "Project Manager",
    description: "Vê apenas os seus projetos; edita notas e as suas tarefas.",
  },
  {
    email: "admin.sintetico@example.invalid",
    name: "Admin Sintético",
    role: "Administrador",
    description: "Todas as permissões, incluindo reconciliação de PM.",
  },
  {
    email: "comercial.sintetico@example.invalid",
    name: "Comercial Sintético",
    role: "Comercial",
    description: "Consulta projetos e tarefas, sem editar.",
  },
  {
    email: "financeiro.sintetico@example.invalid",
    name: "Financeiro Sintético",
    role: "Financeiro",
    description: "Consulta projetos e tarefas, sem editar.",
  },
];

export default function Login() {
  const [email, setEmail] = useState("");
  const [msalError, setMsalError] = useState<string | null>(null);
  const [redirecting, setRedirecting] = useState(false);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState(false);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const sessionExpired = searchParams.get("sessionExpired") === "1";
  const demoUnavailable = searchParams.get("demoUnavailable") === "1";

  useEffect(() => {
    document.title = "Entrar · Op_PM";
    if (!devLoginEnabled) return;
    getHealth()
      .then(setHealth)
      .catch(() => setHealthError(true));
  }, []);

  // Só depois de o servidor confirmar — nunca por omissão.
  const serverAcceptsDemo = health?.dev_login_available === true;
  const showDemo = devLoginEnabled && serverAcceptsDemo;

  function enterAs(address: string) {
    setDevUser(address.trim());
    navigate("/");
  }

  function handleDevSubmit(e: FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    enterAs(email);
  }

  async function handleMicrosoftLogin() {
    setMsalError(null);
    setRedirecting(true);
    try {
      await loginWithMicrosoft();
    } catch (err) {
      setRedirecting(false);
      setMsalError(err instanceof Error ? err.message : "Falha desconhecida ao iniciar o login Microsoft.");
    }
  }

  return (
    <div className="login">
      <section className="login__brand" aria-label="Apresentação">
        <div>
          <span className="brand-mark" style={{ width: 48, height: 48, borderRadius: 12 }}>
            <Icon name="sun" size={28} />
          </span>
          <h1>Op_PM</h1>
          <p>
            Plataforma de gestão de operações: projetos, tarefas, visitas técnicas, comissionamentos e a disponibilidade da
            equipa — num só lugar.
          </p>
          <ul className="login__features">
            <li>
              <Icon name="dashboard" /> Painel com os indicadores da semana
            </li>
            <li>
              <Icon name="folder" /> Estado e progresso de cada projeto
            </li>
            <li>
              <Icon name="columns" /> Tarefas em lista ou Kanban, com prazos e prioridades
            </li>
            <li>
              <Icon name="calendar" /> Férias, ausências e aniversários da equipa
            </li>
          </ul>
        </div>
        <p className="small" style={{ margin: 0 }}>
          Acesso reservado a colaboradores. Permissões aplicadas pelo servidor em cada pedido.
        </p>
      </section>

      <main className="login__panel">
        <div className="login__card">
          <h2>Iniciar sessão</h2>
          <p className="muted" style={{ marginTop: 0 }}>
            Use a sua conta Microsoft da organização.
          </p>

          {sessionExpired && <Alert tone="warning">A sua sessão expirou. Inicie sessão novamente.</Alert>}
          {demoUnavailable && (
            <Alert tone="danger">O modo demonstração não está disponível neste servidor. Use a conta Microsoft.</Alert>
          )}

          <button
            type="button"
            className="btn btn--primary btn--block"
            style={{ minHeight: 46 }}
            onClick={handleMicrosoftLogin}
            disabled={!isEntraConfigured || redirecting}
          >
            <Icon name="microsoft" />
            {redirecting ? "A redirecionar para a Microsoft…" : "Entrar com Microsoft"}
          </button>
          {!isEntraConfigured && (
            <p className="small muted" style={{ marginTop: 8 }}>
              O login Microsoft ainda não está configurado nesta instalação (faltam <code>VITE_ENTRA_CLIENT_ID</code>,{" "}
              <code>VITE_ENTRA_TENANT_ID</code> e <code>VITE_ENTRA_API_SCOPE</code>). Não é necessário para a
              demonstração.
            </p>
          )}
          {msalError && (
            <p className="small text-danger" role="alert" style={{ marginTop: 8 }}>
              {msalError}
            </p>
          )}

          {devLoginEnabled && !showDemo && (
            <p className="small muted" style={{ marginTop: 24 }} role="status">
              {healthError
                ? "Não foi possível contactar o servidor — o modo demonstração fica indisponível até o backend responder."
                : health
                  ? "Este servidor não aceita o modo demonstração."
                  : "A verificar se o servidor aceita o modo demonstração…"}
            </p>
          )}

          {showDemo && (
            <section aria-labelledby="demo-title">
              <div className="divider">ou</div>
              <Alert tone="warning" title="Modo demonstração (apenas local)">
                Utilizadores e dados 100% sintéticos. Este acesso só funciona com o servidor em <code>APP_ENV=local</code>{" "}
                e nunca está disponível em staging ou produção.
              </Alert>
              <h3 id="demo-title" style={{ fontSize: "0.95rem", margin: "0 0 10px" }}>
                Entrar como utilizador de demonstração
              </h3>
              <div className="stack">
                {DEMO_USERS.map((u) => (
                  <button key={u.email} type="button" className="user-pick" onClick={() => enterAs(u.email)}>
                    <Avatar name={u.name} />
                    <span>
                      <span className="user-pick__name" style={{ display: "block" }}>
                        {u.role}
                      </span>
                      <span className="user-pick__desc">{u.description}</span>
                    </span>
                    <Icon name="chevronRight" className="user-pick__arrow" />
                  </button>
                ))}
              </div>

              <details style={{ marginTop: 16 }}>
                <summary className="small" style={{ cursor: "pointer" }}>
                  Entrar com outro email sintético
                </summary>
                <form onSubmit={handleDevSubmit} style={{ display: "flex", gap: 8, marginTop: 10 }}>
                  <label htmlFor="email" className="sr-only">
                    Email do utilizador de demonstração
                  </label>
                  <input
                    id="email"
                    className="input"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="nome@example.invalid"
                  />
                  <button type="submit" className="btn">
                    Entrar
                  </button>
                </form>
              </details>
            </section>
          )}
        </div>
      </main>
    </div>
  );
}
