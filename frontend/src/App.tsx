import { ReactNode, useEffect } from "react";
import { Navigate, Outlet, Route, Routes, useNavigate } from "react-router-dom";
import { clearDevUser, getDevUser, hasActiveSession } from "./api/client";
import Icon from "./components/Icon";
import Layout from "./components/Layout";
import { ToastProvider } from "./components/Toast";
import { ErrorState, LoadingState } from "./components/ui";
import Home from "./pages/Home";
import Inventory from "./pages/Inventory";
import Login from "./pages/Login";
import Performance from "./pages/Performance";
import ProjectDetail from "./pages/ProjectDetail";
import ProjectsList from "./pages/ProjectsList";
import ReconciliationQueue from "./pages/ReconciliationQueue";
import SystemStatus from "./pages/SystemStatus";
import Tasks from "./pages/Tasks";
import Vacations from "./pages/Vacations";
import { SessionProvider, useSession } from "./session/SessionContext";

// Fase 1: login (real via Microsoft Entra ID quando configurado, ou o
// mecanismo de desenvolvimento em local/test — ver src/pages/Login.tsx e
// src/auth/msal.ts). Fase 1.5: "/" é o painel de operações.
// D-051: layout com sidebar (src/components/Layout.tsx), sessão partilhada
// (src/session/SessionContext.tsx) e notificações.
function RequireAuth({ children }: { children: ReactNode }) {
  if (!hasActiveSession()) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

function SessionGate({ children }: { children: ReactNode }) {
  const { me, health, loading, error, reload } = useSession();
  const navigate = useNavigate();
  const usingDevLogin = getDevUser() !== null;
  // Defesa em profundidade: se o servidor diz que não aceita o login de
  // desenvolvimento (staging/produção), a sessão de demonstração é
  // descartada — o backend já recusaria qualquer pedido de qualquer forma.
  const devLoginRejected = usingDevLogin && health !== null && health.dev_login_available === false;

  useEffect(() => {
    if (devLoginRejected) {
      clearDevUser();
      navigate("/login?demoUnavailable=1", { replace: true });
    }
  }, [devLoginRejected, navigate]);

  if (loading) {
    return (
      <div className="login__panel" style={{ minHeight: "100%" }}>
        <LoadingState label="A preparar a sessão…" />
      </div>
    );
  }
  if (!me) {
    return (
      <div className="login__panel" style={{ minHeight: "100%" }}>
        <div className="card login__card">
          <ErrorState
            message={
              error ??
              "Não foi possível identificar o utilizador. Confirme que o servidor está a correr e volte a entrar."
            }
            onRetry={reload}
          />
          <div style={{ padding: "0 20px 20px", textAlign: "center" }}>
            <button
              type="button"
              className="btn"
              onClick={() => {
                clearDevUser();
                navigate("/login");
              }}
            >
              <Icon name="arrowLeft" size={16} /> Voltar ao início de sessão
            </button>
          </div>
        </div>
      </div>
    );
  }
  return <>{children}</>;
}

// Rota de layout: a sessão (/me, /health) é carregada uma vez e mantém-se
// ao navegar entre páginas autenticadas.
function AuthedShell() {
  return (
    <RequireAuth>
      <SessionProvider>
        <SessionGate>
          <Layout>
            <Outlet />
          </Layout>
        </SessionGate>
      </SessionProvider>
    </RequireAuth>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<AuthedShell />}>
          <Route path="/" element={<Home />} />
          <Route path="/projects" element={<ProjectsList />} />
          <Route path="/projects/:projectId" element={<ProjectDetail />} />
          <Route path="/tasks" element={<Tasks />} />
          <Route path="/inventory" element={<Inventory />} />
          <Route path="/performance" element={<Performance />} />
          <Route path="/vacations" element={<Vacations />} />
          <Route path="/reconciliation" element={<ReconciliationQueue />} />
          <Route path="/status" element={<SystemStatus />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </ToastProvider>
  );
}
