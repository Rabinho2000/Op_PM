import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { setDevUser } from "../api/client";

// Fase 1: autenticação real via Microsoft Entra ID ainda não pode ser
// ligada aqui — precisa de um tenant/app registration reais que este
// repositório não tem (ver docs/OPEN_QUESTIONS.md, pergunta 1). O backend
// já valida tokens Entra ID de verdade quando AUTH_ENABLED=true
// (app/security/entra_auth.py) — só falta a app registration para o MSAL.js
// falar com um tenant real. Entretanto, este ecrã usa o mecanismo de
// desenvolvimento (X-Dev-User-Email), que o backend só aceita em
// local/test — nunca funciona em staging/produção.
export default function Login() {
  const [email, setEmail] = useState("");
  const navigate = useNavigate();

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setDevUser(email.trim());
    navigate("/projects");
  }

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", maxWidth: 420, margin: "4rem auto", padding: "0 1rem" }}>
      <h1>Op_PM</h1>

      <div
        style={{
          background: "#fff8e1",
          border: "1px solid #e0c46a",
          borderRadius: 6,
          padding: "0.75rem 1rem",
          fontSize: "0.9rem",
          marginBottom: "1.5rem",
        }}
      >
        <strong>Login com Microsoft — pendente.</strong> A validação real de
        token Entra ID já está implementada no backend, mas falta a
        configuração do tenant/app registration (ver{" "}
        <code>docs/OPEN_QUESTIONS.md</code>, pergunta 1). Por agora, entrar
        como um dos utilizadores sintéticos de desenvolvimento abaixo.
      </div>

      <form onSubmit={handleSubmit}>
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
          Entrar
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
    </div>
  );
}
