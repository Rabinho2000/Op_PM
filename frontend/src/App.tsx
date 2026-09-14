import Dashboard from "./pages/Dashboard";

// Fase 0: sem router nem ecrã de login real — só a casca que prova que o
// frontend fala com o backend. O login real (Microsoft Entra ID) e a
// navegação entre módulos ficam para as fases seguintes do roadmap
// (ver docs/PLAN.md).
export default function App() {
  return <Dashboard />;
}
