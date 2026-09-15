import { Navigate, Route, Routes } from "react-router-dom";
import NavBar from "./components/NavBar";
import { hasActiveSession } from "./api/client";
import Home from "./pages/Home";
import Login from "./pages/Login";
import ProjectDetail from "./pages/ProjectDetail";
import ProjectsList from "./pages/ProjectsList";
import ReconciliationQueue from "./pages/ReconciliationQueue";
import SystemStatus from "./pages/SystemStatus";
import Tasks from "./pages/Tasks";
import Vacations from "./pages/Vacations";

// Fase 1: interface web funcional — login (real via Microsoft Entra ID
// quando configurado, ou o mecanismo de desenvolvimento em local/test —
// ver src/pages/Login.tsx e src/auth/msal.ts), lista de projetos com
// filtros, detalhe/edição autorizada, histórico, e fila de reconciliação
// de PM.
//
// Fase 1.5 (MVP dashboard/workflow): "/" passou a ser o painel de
// operações real (src/pages/Home.tsx), com Tarefas e Férias como páginas
// próprias — ver docs/PLAN.md.
function RequireAuth({ children }: { children: React.ReactNode }) {
  if (!hasActiveSession()) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

function AuthedLayout({ children }: { children: React.ReactNode }) {
  return (
    <RequireAuth>
      <NavBar />
      {children}
    </RequireAuth>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <AuthedLayout>
            <Home />
          </AuthedLayout>
        }
      />
      <Route
        path="/projects"
        element={
          <AuthedLayout>
            <ProjectsList />
          </AuthedLayout>
        }
      />
      <Route
        path="/projects/:projectId"
        element={
          <AuthedLayout>
            <ProjectDetail />
          </AuthedLayout>
        }
      />
      <Route
        path="/tasks"
        element={
          <AuthedLayout>
            <Tasks />
          </AuthedLayout>
        }
      />
      <Route
        path="/vacations"
        element={
          <AuthedLayout>
            <Vacations />
          </AuthedLayout>
        }
      />
      <Route
        path="/reconciliation"
        element={
          <AuthedLayout>
            <ReconciliationQueue />
          </AuthedLayout>
        }
      />
      <Route
        path="/status"
        element={
          <AuthedLayout>
            <SystemStatus />
          </AuthedLayout>
        }
      />
    </Routes>
  );
}
