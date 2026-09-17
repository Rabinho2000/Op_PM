// Metas e indicadores — página única (nunca "Metas" e "Dashboards"
// separados, ver docs/PLAN_OPERATIONS_MVP.md secção 8). Todo o cálculo de
// progresso/percentagem/projeção vem do servidor (D-041) — esta página só
// apresenta.
import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  ApiError,
  createGoal,
  GOAL_METRIC_LABELS,
  GoalMetric,
  GoalPeriod,
  getPerformanceSummary,
  PerformanceSummary,
} from "../api/client";
import Icon from "../components/Icon";
import { useToast } from "../components/Toast";
import { Alert, Badge, Card, EmptyState, ErrorState, LoadingState, Modal, PageHeader, ProgressBar, Tone } from "../components/ui";
import { useSession } from "../session/SessionContext";

const PACE_TONE: Record<GoalPeriod["pace_status"], Tone> = {
  ahead: "success",
  on_track: "brand",
  behind: "danger",
  no_target: "neutral",
};

const PACE_LABEL: Record<GoalPeriod["pace_status"], string> = {
  ahead: "Acima do ritmo esperado",
  on_track: "No ritmo esperado",
  behind: "Abaixo do ritmo esperado",
  no_target: "Sem objetivo definido",
};

function CreateGoalModal({ year, onClose, onDone }: { year: number; onClose: () => void; onDone: () => void }) {
  const [form, setForm] = useState({
    period_type: "year" as GoalPeriod["period_type"],
    metric: "installations" as GoalMetric,
    target_value: "",
    scope: "company" as "company" | "pm",
    quarter: "1",
    notes: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!form.target_value) {
      setError("Indique o valor do objetivo.");
      return;
    }
    setSaving(true);
    try {
      await createGoal({
        period_type: form.period_type,
        year,
        quarter: form.period_type === "quarter" ? Number(form.quarter) : undefined,
        metric: form.metric,
        target_value: form.target_value,
        scope: form.scope,
        notes: form.notes,
      });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Não foi possível criar a meta.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={`Nova meta — ${year}`}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancelar
          </button>
          <button type="submit" form="goal-form" className="btn btn--primary" disabled={saving}>
            {saving ? "A criar…" : "Criar meta"}
          </button>
        </>
      }
    >
      <form id="goal-form" className="form-grid" onSubmit={handleSubmit}>
        {error && (
          <div className="span-2">
            <Alert tone="danger">{error}</Alert>
          </div>
        )}
        <div className="field span-2">
          <label htmlFor="g-metric">Métrica</label>
          <select
            id="g-metric"
            className="select"
            value={form.metric}
            onChange={(e) => setForm({ ...form, metric: e.target.value as GoalMetric })}
          >
            {(Object.keys(GOAL_METRIC_LABELS) as GoalMetric[]).map((m) => (
              <option key={m} value={m}>
                {GOAL_METRIC_LABELS[m]}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="g-period">Período</label>
          <select
            id="g-period"
            className="select"
            value={form.period_type}
            onChange={(e) => setForm({ ...form, period_type: e.target.value as GoalPeriod["period_type"] })}
          >
            <option value="year">Anual</option>
            <option value="quarter">Trimestral</option>
          </select>
        </div>
        {form.period_type === "quarter" && (
          <div className="field">
            <label htmlFor="g-quarter">Trimestre</label>
            <select id="g-quarter" className="select" value={form.quarter} onChange={(e) => setForm({ ...form, quarter: e.target.value })}>
              <option value="1">T1</option>
              <option value="2">T2</option>
              <option value="3">T3</option>
              <option value="4">T4</option>
            </select>
          </div>
        )}
        <div className="field span-2">
          <label htmlFor="g-target">Valor do objetivo</label>
          <input
            id="g-target"
            className="input"
            type="number"
            step="0.001"
            value={form.target_value}
            onChange={(e) => setForm({ ...form, target_value: e.target.value })}
          />
        </div>
        <div className="field span-2">
          <label htmlFor="g-notes">Notas</label>
          <textarea id="g-notes" className="textarea" rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
        </div>
      </form>
    </Modal>
  );
}

export default function Performance() {
  const { can } = useSession();
  const { notify } = useToast();
  const [year, setYear] = useState(new Date().getFullYear());
  const [summary, setSummary] = useState<PerformanceSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const canManageGoals = can("performance.manage_goals");

  const load = useCallback(() => {
    setError(null);
    getPerformanceSummary({ year })
      .then(setSummary)
      .catch((e) => setError(e instanceof ApiError ? e.detail : "Não foi possível contactar o servidor."));
  }, [year]);

  useEffect(load, [load]);

  return (
    <>
      <PageHeader
        title="Metas e indicadores"
        subtitle="Objetivos e progresso da operação, num único sítio — sem separar «Metas» de «Dashboards»."
        actions={
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <select className="select" value={year} onChange={(e) => setYear(Number(e.target.value))} aria-label="Ano">
              {Array.from({ length: 5 }, (_, i) => new Date().getFullYear() - i).map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
            {canManageGoals && (
              <button type="button" className="btn btn--primary" onClick={() => setCreating(true)}>
                <Icon name="plus" size={16} /> Nova meta
              </button>
            )}
          </div>
        }
      />

      {error && (
        <div className="card">
          <ErrorState message={error} onRetry={load} />
        </div>
      )}

      {!error && (
        <>
          <Card title={`Metas de ${year}`} icon="flag" flush>
            {summary === null ? (
              <LoadingState rows={3} />
            ) : summary.goals.length === 0 ? (
              <EmptyState icon="flag" title="Sem metas definidas para este ano." />
            ) : (
              <ul className="list">
                {summary.goals.map((g) => (
                  <li key={g.id} className="list__item" style={{ flexDirection: "column", alignItems: "stretch", gap: 6 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                      <span className="list__title">
                        {GOAL_METRIC_LABELS[g.metric]}
                        {g.scope === "pm" && g.pm_display_name && <span className="muted"> · {g.pm_display_name}</span>}
                        {g.period_type === "quarter" && <span className="muted"> · T{g.quarter}</span>}
                      </span>
                      <Badge tone={PACE_TONE[g.pace_status]}>{PACE_LABEL[g.pace_status]}</Badge>
                    </div>
                    <ProgressBar value={g.percent} label={`${GOAL_METRIC_LABELS[g.metric]}: ${g.percent}%`} />
                    <div className="small muted">
                      Realizado: {g.realized} de {g.target_value} · Falta: {g.missing} · Projeção ao fim do período: {g.projection}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <div className="section-gap grid">
            <Card title="Portefólio por estado" icon="folder" tone="violet" flush>
              {summary === null ? (
                <LoadingState rows={3} />
              ) : (
                <ul className="list">
                  <li className="list__item">
                    <span className="list__title">Em preparação (não iniciado)</span>
                    <Badge tone="neutral">{summary.portfolio.not_started}</Badge>
                  </li>
                  <li className="list__item">
                    <span className="list__title">Em construção (em curso)</span>
                    <Badge tone="violet">{summary.portfolio.in_progress}</Badge>
                  </li>
                  <li className="list__item">
                    <span className="list__title">Entregues (concluído)</span>
                    <Badge tone="success">{summary.portfolio.completed}</Badge>
                  </li>
                  <li className="list__item">
                    <span className="list__title">Certificadas</span>
                    <Badge tone="success">{summary.portfolio.certified_count}</Badge>
                  </li>
                  <li className="list__item">
                    <span className="list__title">Entregues, pendentes de certificação</span>
                    <Badge tone="warning">{summary.portfolio.pending_certification_count}</Badge>
                  </li>
                </ul>
              )}
            </Card>

            <Card title="Instalações e kWp por ano" icon="activity" tone="violet" flush>
              {summary === null ? (
                <LoadingState rows={3} />
              ) : (
                <div className="table-wrap">
                  <table className="table">
                    <caption className="sr-only">Instalações e potência instalada por ano</caption>
                    <thead>
                      <tr>
                        <th scope="col">Ano</th>
                        <th scope="col">Instalações concluídas</th>
                        <th scope="col">kWp</th>
                      </tr>
                    </thead>
                    <tbody>
                      {summary.yearly.map((y) => (
                        <tr key={y.year}>
                          <td>{y.year}</td>
                          <td>{y.installations}</td>
                          <td>{y.kwp}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          </div>
        </>
      )}

      {creating && (
        <CreateGoalModal
          year={year}
          onClose={() => setCreating(false)}
          onDone={() => {
            setCreating(false);
            notify("Meta criada.", "success");
            load();
          }}
        />
      )}
    </>
  );
}
