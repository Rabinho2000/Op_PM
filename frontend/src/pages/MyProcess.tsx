import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, getMyProcessStages, MyProcessStage } from "../api/client";
import { Alert, Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader } from "../components/ui";
import { formatDatePt } from "../utils/dates";

const STATUS: Record<string, { label: string; tone: "success" | "danger" | "info" | "warning" | "neutral" }> = {
  done: { label: "Concluída", tone: "success" },
  overdue: { label: "Em atraso", tone: "danger" },
  active: { label: "Em curso", tone: "info" },
  upcoming: { label: "Por começar", tone: "neutral" },
  no_date: { label: "Sem data", tone: "neutral" },
  pending: { label: "Por concluir", tone: "warning" },
};

export default function MyProcess() {
  const [stages, setStages] = useState<MyProcessStage[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setStages(null);
    getMyProcessStages()
      .then((value) => !cancelled && setStages(value))
      .catch((e) => !cancelled && setError(e instanceof ApiError ? e.detail : "Não foi possível carregar as suas etapas."));
    return () => { cancelled = true; };
  }, [reload]);

  return (
    <>
      <PageHeader title="As minhas etapas" subtitle="Etapas pendentes atribuídas a si nos projetos visíveis." />
      {error ? <ErrorState message={error} onRetry={() => setReload((n) => n + 1)} /> : !stages ? <LoadingState label="A carregar as suas etapas…" rows={4} /> : stages.length === 0 ? (
        <EmptyState icon="checkCircle" title="Não tem etapas pendentes." text="As etapas concluídas ou atribuídas a outras pessoas não aparecem aqui." />
      ) : (
        <Card title={`${stages.length} etapa${stages.length === 1 ? "" : "s"} pendente${stages.length === 1 ? "" : "s"}`} icon="tasks">
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Projeto</th><th>Etapa</th><th>Estado</th><th>Prazo</th><th>Progresso</th></tr></thead>
              <tbody>{stages.map((stage) => {
                const state = STATUS[stage.status] ?? { label: stage.status, tone: "neutral" as const };
                return <tr key={`${stage.project_id}-${stage.stage_id}`}>
                  <td><Link to={`/projects/${stage.project_id}?tab=processo`}>{stage.project_name}</Link></td>
                  <td>{stage.stage_title}</td>
                  <td><Badge tone={state.tone}>{state.label}</Badge></td>
                  <td>{stage.planned_end ? formatDatePt(stage.planned_end) : "—"}</td>
                  <td>{stage.done_count}/{stage.total_count}</td>
                </tr>;
              })}</tbody>
            </table>
          </div>
        </Card>
      )}
    </>
  );
}
