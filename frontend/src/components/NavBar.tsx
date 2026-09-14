import { Link, useNavigate } from "react-router-dom";
import { clearDevUser, getDevUser } from "../api/client";

export default function NavBar() {
  const navigate = useNavigate();
  const email = getDevUser();

  function handleLogout() {
    clearDevUser();
    navigate("/login");
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
      <Link to="/projects">Projetos</Link>
      <Link to="/reconciliation">Reconciliação de PM</Link>
      <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "0.75rem" }}>
        <span style={{ color: "#666" }}>{email}</span>
        <button onClick={handleLogout} style={{ padding: "0.25rem 0.75rem" }}>
          Sair
        </button>
      </div>
    </nav>
  );
}
