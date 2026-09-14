import { useEffect, useState } from "react";
import { getHealth, getMe, HealthResponse, MeResponse } from "../api/client";

export default function Dashboard() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [me, setMe] = useState<MeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getHealth().then(setHealth).catch((e) => setError(String(e)));
    getMe().then(setMe).catch((e) => setError(String(e)));
  }, []);

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", padding: "2rem", maxWidth: 720 }}>
      <h1>Op_PM — Fase 0</h1>
      <p style={{ color: "#666" }}>
        Fundação técnica apenas. Sem integrações reais ativas (ClickUp, Microsoft Graph,
        Financial, Claude), sem login real (Entra ID por implementar) e sem dados de produção.
      </p>

      {error && <p style={{ color: "crimson" }}>Erro a contactar a API: {error}</p>}

      <section style={{ marginTop: "1.5rem" }}>
        <h2>Estado do backend</h2>
        {health ? (
          <ul>
            <li>Estado: {health.status}</li>
            <li>Ambiente: {health.app_env}</li>
            <li>Base de dados: {health.database_dialect}</li>
            <li>
              Integrações ativas:{" "}
              {Object.entries(health.integrations).filter(([, v]) => v).length === 0
                ? "nenhuma (esperado nesta fase)"
                : Object.entries(health.integrations)
                    .filter(([, v]) => v)
                    .map(([k]) => k)
                    .join(", ")}
            </li>
          </ul>
        ) : (
          !error && <p>A contactar o backend…</p>
        )}
      </section>

      <section style={{ marginTop: "1.5rem" }}>
        <h2>Utilizador de desenvolvimento</h2>
        {me ? (
          <ul>
            <li>Email: {me.email}</li>
            <li>Papéis: {me.roles.join(", ") || "(nenhum)"}</li>
            <li>Permissões: {me.permissions.join(", ") || "(nenhuma)"}</li>
          </ul>
        ) : (
          !error && <p>A carregar…</p>
        )}
      </section>
    </div>
  );
}
