import { ReactNode, useEffect } from "react";
import { Location, Navigate, Outlet, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { clearDevUser, getDevUser, hasActiveSession } from "./api/client";
import Icon from "./components/Icon";
import Layout from "./components/Layout";
import { ToastProvider } from "./components/Toast";
import { ErrorState, LoadingState } from "./components/ui";
import ProjectDetailOverlay from "./components/ProjectDetailOverlay";
import Home from "./pages/Home";
import ImportNotes from "./pages/ImportNotes";
import Inventory from "./pages/Inventory";
import Installers from "./pages/Installers";
import Works from "./pages/Works";
import WorksTeams from "./pages/WorksTeams";
import Suppliers from "./pages/Suppliers";
import Login from "./pages/Login";
import MapPage from "./pages/Map";
import Performance from "./pages/Performance";
import Planning from "./pages/Planning";
import ProjectDetail from "./pages/ProjectDetail";
import ClientReports from "./pages/ClientReports";
import ProjectsList from "./pages/ProjectsList";
import ReconciliationQueue from "./pages/ReconciliationQueue";
import SystemStatus from "./pages/SystemStatus";
import Tasks from "./pages/Tasks";
import Vacations from "./pages/Vacations";
import MyProcess from "./pages/MyProcess";
import SupportOperations from "./pages/SupportOperations";
import IsolatedTimeBank from "./pages/IsolatedTimeBank";
import {
  InstallerCapabilityGate,
  InstallerInventoryPage,
  InstallerProjectDetailPage,
  InstallerProjectsPage,
  InstallerTasksPage,
  InstallerTeamsPage,
  InstallerTimeBankPage,
  InstallerWorksPage,
} from "./pages/InstallerAccessPages";
import { isInstallerCollaborator } from "./session/installerAccess";
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

function AuthedOverlay() {
  return (
    <RequireAuth>
      <SessionProvider>
        <SessionGate>
          <ProjectDetailOverlay />
        </SessionGate>
      </SessionProvider>
    </RequireAuth>
  );
}

function ScopedOrStaff({
  capability,
  scoped,
  staff,
}: {
  capability: Parameters<typeof InstallerCapabilityGate>[0]["capability"];
  scoped: ReactNode;
  staff: ReactNode;
}) {
  const { me } = useSession();
  if (!isInstallerCollaborator(me)) return <>{staff}</>;
  return <InstallerCapabilityGate capability={capability}>{scoped}</InstallerCapabilityGate>;
}

function ProjectsRoute() {
  const { me } = useSession();
  return isInstallerCollaborator(me) ? <InstallerProjectsPage /> : <ProjectsList />;
}

function ProjectDetailRoute() {
  const { me } = useSession();
  return isInstallerCollaborator(me) ? <InstallerCapabilityGate capability="project.view_assigned_installer"><InstallerProjectDetailPage /></InstallerCapabilityGate> : <ProjectDetail />;
}

function HomeRoute() {
  const { me } = useSession();
  return isInstallerCollaborator(me) ? <Navigate to="/projects" replace /> : <Home />;
}

function StaffOnly({ children }: { children: ReactNode }) {
  const { me } = useSession();
  return isInstallerCollaborator(me) ? <Navigate to="/projects" replace /> : <>{children}</>;
}

function AppRoutes() {
  const location = useLocation();
  const backgroundLocation = (location.state as { backgroundLocation?: Location } | null)?.backgroundLocation;

  return (
    <>
      <Routes location={backgroundLocation ?? location}>
        <Route path="/login" element={<Login />} />
        <Route element={<AuthedShell />}>
          <Route path="/" element={<HomeRoute />} />
          <Route path="/projects" element={<ProjectsRoute />} />
          <Route path="/client-reports" element={<StaffOnly><ClientReports /></StaffOnly>} />
          <Route path="/projects/import" element={<StaffOnly><ImportNotes /></StaffOnly>} />
          <Route path="/projects/:projectId" element={<ProjectDetailRoute />} />
          <Route path="/tasks" element={<ScopedOrStaff capability="task.view_assigned_installer" scoped={<InstallerTasksPage />} staff={<Tasks />} />} />
          <Route path="/inventory" element={<ScopedOrStaff capability="inventory.view_assigned_installer" scoped={<InstallerInventoryPage />} staff={<Inventory />} />} />
          <Route path="/suppliers" element={<StaffOnly><Suppliers /></StaffOnly>} />
          <Route path="/installers" element={<StaffOnly><Installers /></StaffOnly>} />
          <Route path="/works" element={<ScopedOrStaff capability="works_calendar.view_assigned_installer" scoped={<InstallerWorksPage />} staff={<Works />} />} />
          <Route path="/works/teams" element={<ScopedOrStaff capability="installer_team.view_assigned_installer" scoped={<InstallerTeamsPage />} staff={<WorksTeams />} />} />
          <Route path="/map" element={<StaffOnly><MapPage /></StaffOnly>} />
          <Route path="/performance" element={<StaffOnly><Performance /></StaffOnly>} />
          <Route path="/planning" element={<StaffOnly><Planning /></StaffOnly>} />
          <Route path="/vacations" element={<StaffOnly><Vacations /></StaffOnly>} />
          <Route path="/my-process" element={<StaffOnly><MyProcess /></StaffOnly>} />
          <Route path="/support" element={<StaffOnly><SupportOperations /></StaffOnly>} />
          <Route path="/time-bank" element={<ScopedOrStaff capability="time_bank.view_own" scoped={<InstallerTimeBankPage />} staff={<IsolatedTimeBank />} />} />
          <Route path="/reconciliation" element={<StaffOnly><ReconciliationQueue /></StaffOnly>} />
          <Route path="/status" element={<StaffOnly><SystemStatus /></StaffOnly>} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      {backgroundLocation && (
        <Routes>
          <Route path="/projects/:projectId" element={<AuthedOverlay />} />
        </Routes>
      )}
    </>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <AppRoutes />
    </ToastProvider>
  );
}
