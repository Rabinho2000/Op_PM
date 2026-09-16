import { useEffect, useState } from "react";
import { getHealth, HealthResponse } from "../api/client";
import { Badge, Card, ErrorState, LoadingState, PageHeader } from "../components/ui";
import { useSession } from "../session/SessionContext";

// Diagnóstico técnico (antiga página inicial da Fase 1): estado do backend,
// integrações e utilizador atual.
const INTEGRATION_LABELS: Record<string, string> = {
  graph_enabled: "Microsoft Graph (email/calendário)",
  clickup_enabled: "ClickUp",
  financial_enabled: "Financial",
  claude_enabled: "Claude",
};

export default function SystemStatus() {
  const { me } = useSession();
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setError(null);
    getHealth()
      .then(setHealth)
      .catch(() => setError("Não foi possível contactar o servidor."));
  }

  useEffect(load, []);

  return (
    <>
      <PageHeader
        title="Estado do sistema"
        subtitle="Diagnóstico técnico: servidor, integrações e o seu utilizador. Sem dados de produção nem integrações reais ativas."
      />
      <div className="grid grid--2">
        <Card title="Servidor" icon="activity">
          {error && <ErrorState message={error} onRetry={load} />}
          {!error && !health && <LoadingState />}
          {health && (
            <dl className="kv">
              <dt>Estado</dt>
              <dd>
                <Badge tone={health.status === "ok" ? "success" : "danger"} dot>
                  {health.status === "ok" ? "Operacional" : health.status}
                </Badge>
              </dd>
              <dt>Ambiente</dt>
              <dd>{health.app_env}</dd>
              <dt>Base de dados</dt>
              <dd>{health.database_dialect}</dd>
              <dt>Modo demonstração</dt>
              <dd>{health.demo_mode ? "Ativo (dados sintéticos)" : "Inativo"}</dd>
            </dl>
          )}
        </Card>
        <Card title="Integrações externas" icon="link" tone="neutral">
          {health ? (
            <ul className="list">
              {Object.entries(health.integrations).map(([key, enabled]) => (
                <li key={key} className="list__item" style={{ paddingLeft: 0, paddingRight: 0 }}>
                  <span className="list__main">{INTEGRATION_LABELS[key] ?? key}</span>
                  <Badge tone={enabled ? "success" : "neutral"}>{enabled ? "Ativa" : "Não ativada"}</Badge>
                </li>
              ))}
            </ul>
          ) : (
            !error && <LoadingState />
          )}
        </Card>
        <Card title="O seu utilizador" icon="user">
          {me && (
            <dl className="kv">
              <dt>Nome</dt>
              <dd>{me.display_name ?? "—"}</dd>
              <dt>Email</dt>
              <dd>{me.email}</dd>
              <dt>Papéis</dt>
              <dd>{(me.role_labels ?? me.roles).join(", ") || "(nenhum)"}</dd>
            </dl>
          )}
        </Card>
        <Card title="Permissões efetivas" icon="lock" tone="neutral">
          {me && (
            <div className="badges">
              {me.permissions.length === 0 && <span className="muted">(nenhuma)</span>}
              {me.permissions.map((p) => (
                <Badge key={p}>{p}</Badge>
              ))}
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
