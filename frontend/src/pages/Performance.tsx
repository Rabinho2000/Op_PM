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
  listPeople,
  Person,
  PerformanceSummary,
  updateGoal,
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

type PeriodType = GoalPeriod["period_type"];

function CreateGoalModal({
  year,
  people,
  onClose,
  onDone,
}: {
  year: number;
  people: Person[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [form, setForm] = useState({
    period_type: "year" as PeriodType,
    metric: "installations" as GoalMetric,
    target_value: "",
    scope: "company" as "company" | "pm",
    pm_person_id: "",
    quarter: "1",
    semester: "1",
    month: "1",
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
    if (form.scope === "pm" && !form.pm_person_id) {
      setError("Escolha o PM para uma meta individual.");
      return;
    }
    setSaving(true);
    try {
      await createGoal({
        period_type: form.period_type,
        year,
        quarter: form.period_type === "quarter" ? Number(form.quarter) : undefined,
        semester: form.period_type === "semester" ? Number(form.semester) : undefined,
        month: form.period_type === "month" ? Number(form.month) : undefined,
        metric: form.metric,
        target_value: form.target_value,
        scope: form.scope,
        pm_person_id: form.scope === "pm" ? form.pm_person_id : undefined,
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
            onChange={(e) => setForm({ ...form, period_type: e.target.value as PeriodType })}
          >
            <option value="year">Anual</option>
            <option value="semester">Semestral</option>
            <option value="quarter">Trimestral</option>
            <option value="month">Mensal</option>
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
        {form.period_type === "semester" && (
          <div className="field">
            <label htmlFor="g-semester">Semestre</label>
            <select id="g-semester" className="select" value={form.semester} onChange={(e) => setForm({ ...form, semester: e.target.value })}>
              <option value="1">S1</option>
              <option value="2">S2</option>
            </select>
          </div>
        )}
        {form.period_type === "month" && (
          <div className="field">
            <label htmlFor="g-month">Mês</label>
            <select id="g-month" className="select" value={form.month} onChange={(e) => setForm({ ...form, month: e.target.value })}>
              {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="field">
          <label htmlFor="g-scope">Âmbito</label>
          <select
            id="g-scope"
            className="select"
            value={form.scope}
            onChange={(e) => setForm({ ...form, scope: e.target.value as "company" | "pm" })}
          >
            <option value="company">Empresa inteira</option>
            <option value="pm">Um PM</option>
          </select>
        </div>
        {form.scope === "pm" && (
          <div className="field">
            <label htmlFor="g-pm">PM</label>
            <select id="g-pm" className="select" value={form.pm_person_id} onChange={(e) => setForm({ ...form, pm_person_id: e.target.value })}>
              <option value="">— escolher —</option>
              {people.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.display_name}
                </option>
              ))}
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

function EditGoalModal({ goal, onClose, onDone }: { goal: GoalPeriod; onClose: () => void; onDone: () => void }) {
  const [targetValue, setTargetValue] = useState(goal.target_value);
  const [notes, setNotes] = useState(goal.notes);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      await updateGoal(goal.id, { target_value: targetValue, notes });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Não foi possível guardar a meta.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={`Editar meta — ${GOAL_METRIC_LABELS[goal.metric]}`}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancelar
          </button>
          <button type="submit" form="goal-edit-form" className="btn btn--primary" disabled={saving}>
            {saving ? "A guardar…" : "Guardar"}
          </button>
        </>
      }
    >
      <form id="goal-edit-form" className="form-grid" onSubmit={handleSubmit}>
        {error && (
          <div className="span-2">
            <Alert tone="danger">{error}</Alert>
          </div>
        )}
        <div className="field span-2">
          <label htmlFor="ge-target">Valor do objetivo</label>
          <input
            id="ge-target"
            className="input"
            type="number"
            step="0.001"
            value={targetValue}
            onChange={(e) => setTargetValue(e.target.value)}
          />
        </div>
        <div className="field span-2">
          <label htmlFor="ge-notes">Notas</label>
          <textarea id="ge-notes" className="textarea" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </div>
      </form>
    </Modal>
  );
}

export default function Performance() {
  const { can } = useSession();
  const { notify } = useToast();
  const [year, setYear] = useState(new Date().getFullYear());
  const [periodType, setPeriodType] = useState<PeriodType>("year");
  const [quarter, setQuarter] = useState(1);
  const [semester, setSemester] = useState(1);
  const [month, setMonth] = useState(1);
  const [pmFilter, setPmFilter] = useState("");
  const [people, setPeople] = useState<Person[]>([]);
  const [summary, setSummary] = useState<PerformanceSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [editingGoal, setEditingGoal] = useState<GoalPeriod | null>(null);

  const canManageGoals = can("performance.manage_goals");

  const load = useCallback(() => {
    setError(null);
    getPerformanceSummary({
      year,
      pm_person_id: pmFilter || undefined,
      period_type: periodType === "year" ? undefined : periodType,
      quarter: periodType === "quarter" ? quarter : undefined,
      semester: periodType === "semester" ? semester : undefined,
      month: periodType === "month" ? month : undefined,
    })
      .then(setSummary)
      .catch((e) => setError(e instanceof ApiError ? e.detail : "Não foi possível contactar o servidor."));
  }, [year, periodType, quarter, semester, month, pmFilter]);

  useEffect(load, [load]);
  useEffect(() => {
    listPeople()
      .then(setPeople)
      .catch(() => setPeople([]));
  }, []);

  return (
    <>
      <PageHeader
        title="Metas e indicadores"
        subtitle="Objetivos e progresso da operação, num único sítio — sem separar «Metas» de «Dashboards»."
        actions={
          canManageGoals && (
            <button type="button" className="btn btn--primary" onClick={() => setCreating(true)}>
              <Icon name="plus" size={16} /> Nova meta
            </button>
          )
        }
      />

      <form className="toolbar" role="search" aria-label="Filtros de metas" onSubmit={(e) => e.preventDefault()}>
        <div className="field">
          <label htmlFor="f-year">Ano</label>
          <select id="f-year" className="select" value={year} onChange={(e) => setYear(Number(e.target.value))}>
            {Array.from({ length: 5 }, (_, i) => new Date().getFullYear() - i).map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="f-period">Período</label>
          <select id="f-period" className="select" value={periodType} onChange={(e) => setPeriodType(e.target.value as PeriodType)}>
            <option value="year">Ano inteiro</option>
            <option value="semester">Semestre</option>
            <option value="quarter">Trimestre</option>
            <option value="month">Mês</option>
          </select>
        </div>
        {periodType === "quarter" && (
          <div className="field">
            <label htmlFor="f-quarter">Trimestre</label>
            <select id="f-quarter" className="select" value={quarter} onChange={(e) => setQuarter(Number(e.target.value))}>
              {[1, 2, 3, 4].map((q) => (
                <option key={q} value={q}>
                  T{q}
                </option>
              ))}
            </select>
          </div>
        )}
        {periodType === "semester" && (
          <div className="field">
            <label htmlFor="f-semester">Semestre</label>
            <select id="f-semester" className="select" value={semester} onChange={(e) => setSemester(Number(e.target.value))}>
              {[1, 2].map((s) => (
                <option key={s} value={s}>
                  S{s}
                </option>
              ))}
            </select>
          </div>
        )}
        {periodType === "month" && (
          <div className="field">
            <label htmlFor="f-month">Mês</label>
            <select id="f-month" className="select" value={month} onChange={(e) => setMonth(Number(e.target.value))}>
              {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="field">
          <label htmlFor="f-pm">PM</label>
          <select id="f-pm" className="select" value={pmFilter} onChange={(e) => setPmFilter(e.target.value)}>
            <option value="">Todos os PM (e empresa)</option>
            {people.map((p) => (
              <option key={p.id} value={p.id}>
                {p.display_name}
              </option>
            ))}
          </select>
        </div>
      </form>

      {error && (
        <div className="card">
          <ErrorState message={error} onRetry={load} />
        </div>
      )}

      {!error && (
        <>
          <Card title="Metas do período selecionado" icon="flag" flush>
            {summary === null ? (
              <LoadingState rows={3} />
            ) : summary.goals.length === 0 ? (
              <EmptyState icon="flag" title="Sem metas definidas para este período." />
            ) : (
              <ul className="list">
                {summary.goals.map((g) => (
                  <li key={g.id} className="list__item" style={{ flexDirection: "column", alignItems: "stretch", gap: 6 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                      <span className="list__title">
                        {GOAL_METRIC_LABELS[g.metric]}
                        {g.scope === "pm" && g.pm_display_name && <span className="muted"> · {g.pm_display_name}</span>}
                        {g.period_type === "quarter" && <span className="muted"> · T{g.quarter}</span>}
                        {g.period_type === "semester" && <span className="muted"> · S{g.semester}</span>}
                        {g.period_type === "month" && <span className="muted"> · mês {g.month}</span>}
                      </span>
                      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <Badge tone={PACE_TONE[g.pace_status]}>{PACE_LABEL[g.pace_status]}</Badge>
                        {canManageGoals && (
                          <button type="button" className="btn btn--sm btn--ghost" onClick={() => setEditingGoal(g)}>
                            <Icon name="wrench" size={14} /> Editar
                          </button>
                        )}
                      </div>
                    </div>
                    <ProgressBar value={g.percent} label={`${GOAL_METRIC_LABELS[g.metric]}: ${g.percent}%`} />
                    <div className="small muted">
                      Realizado: {g.realized} de {g.target_value} · Falta: {g.missing} · Projeção ao fim do período: {g.projection}
                      {g.notes && <> · Notas: {g.notes}</>}
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
          people={people}
          onClose={() => setCreating(false)}
          onDone={() => {
            setCreating(false);
            notify("Meta criada.", "success");
            load();
          }}
        />
      )}

      {editingGoal && (
        <EditGoalModal
          goal={editingGoal}
          onClose={() => setEditingGoal(null)}
          onDone={() => {
            setEditingGoal(null);
            notify("Meta atualizada.", "success");
            load();
          }}
        />
      )}
    </>
  );
}
