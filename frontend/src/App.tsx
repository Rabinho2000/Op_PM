import { Navigate, Route, Routes } from "react-router-dom";
import NavBar from "./components/NavBar";
import { getDevUser } from "./api/client";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";
import ProjectDetail from "./pages/ProjectDetail";
import ProjectsList from "./pages/ProjectsList";
import ReconciliationQueue from "./pages/ReconciliationQueue";

// Fase 1: primeira interface web funcional — login (mecanismo de
// desenvolvimento, ver src/pages/Login.tsx), lista de projetos com
// filtros, detalhe/edição autorizada, histórico, e fila de reconciliação
// de PM. Autenticação real via Entra ID fica para quando o tenant/app
// registration estiverem disponíveis (ver docs/OPEN_QUESTIONS.md).
function RequireAuth({ children }: { children: React.ReactNode }) {
  if (!getDevUser()) {
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
      <Route path="/" element={<Navigate to="/projects" replace />} />
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
            <Dashboard />
          </AuthedLayout>
        }
      />
    </Routes>
  );
}
