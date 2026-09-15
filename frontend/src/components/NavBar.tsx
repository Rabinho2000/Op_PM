import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getSessionDisplayName, logoutCurrentSession } from "../api/client";

export default function NavBar() {
  const navigate = useNavigate();
  const [loggingOut, setLoggingOut] = useState(false);
  const displayName = getSessionDisplayName();

  async function handleLogout() {
    setLoggingOut(true);
    try {
      // Para uma sessão Microsoft real isto navega para fora da app
      // (logoutRedirect); para o login de desenvolvimento, limpa e
      // regressa ao ecrã de login localmente.
      await logoutCurrentSession();
      navigate("/login");
    } finally {
      setLoggingOut(false);
    }
  }

  return (
    <nav
      style={{
        display: "flex",
        alignItems: "center",
        gap: "1rem",
        padding: "0.75rem 1.25rem",
        borderBottom: "1px solid #ddd",
        fontFamily: "system-ui, sans-serif",
        fontSize: "0.95rem",
      }}
    >
      <strong>Op_PM</strong>
      <Link to="/">Painel</Link>
      <Link to="/projects">Projetos</Link>
      <Link to="/tasks">Tarefas</Link>
      <Link to="/vacations">Férias</Link>
      <Link to="/reconciliation">Reconciliação de PM</Link>
      <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "0.75rem" }}>
        <span style={{ color: "#666" }}>{displayName}</span>
        <button onClick={handleLogout} disabled={loggingOut} style={{ padding: "0.25rem 0.75rem" }}>
          {loggingOut ? "A sair…" : "Sair"}
        </button>
      </div>
    </nav>
  );
}
