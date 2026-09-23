// Plano de deslocação (D-066): a rota otimizada e, para cada instalação, o que
// há para fazer. Só leitura — não cria tarefas, visitas nem movimentos. Uma
// secção `null` (sem permissão) diz-se como tal, nunca como "nada a fazer".
import type { ReactNode } from "react";
import type { TripPlan, TripStop } from "../api/client";
import { formatDatePt, formatDateTimePt } from "../utils/dates";
import { buildTripSummaryText } from "../utils/tripPlan";
import Icon from "./Icon";
import { Badge, Modal } from "./ui";

const PRIORITY_LABELS: Record<string, string> = { low: "baixa", medium: "média", high: "alta", urgent: "urgente" };

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div style={{ marginTop: 6 }}>
      <div className="small muted">{title}</div>
      {children}
    </div>
  );
}

function Hidden({ what }: { what: string }) {
  return <div className="small muted">Sem permissão para ver {what}.</div>;
}

function StopJobs({ stop }: { stop: TripStop }) {
  const jobs = stop.jobs;
  if (!jobs) {
    return stop.info ? <div className="small muted">Materiais: {stop.info}</div> : null;
  }
  return (
    <>
      <Section title="Tarefas operacionais">
        {jobs.tasks === null ? (
          <Hidden what="as tarefas" />
        ) : jobs.tasks.length === 0 ? (
          <div className="small">Nenhuma tarefa operacional aberta.</div>
        ) : (
          <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
            {jobs.tasks.map((t) => (
              <li key={t.id}>
                {t.title}
                {t.is_overdue && <Badge tone="danger">atrasada</Badge>}
                {t.due_date && ` — prazo ${formatDatePt(t.due_date)}`} ({PRIORITY_LABELS[t.priority] ?? t.priority})
              </li>
            ))}
          </ul>
        )}
      </Section>
      <Section title="Pendências">
        {jobs.issues === null ? (
          <Hidden what="as pendências" />
        ) : jobs.issues.length === 0 ? (
          <div className="small">Nenhuma pendência aberta.</div>
        ) : (
          <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
            {jobs.issues.map((i) => (
              <li key={i.id}>
                {i.description} ({PRIORITY_LABELS[i.priority] ?? i.priority})
              </li>
            ))}
          </ul>
        )}
      </Section>
      <Section title="Material a recolher">
        {jobs.collect === null ? (
          <Hidden what="o inventário" />
        ) : jobs.collect.length === 0 ? (
          <div className="small">Sem material no local.</div>
        ) : (
          <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
            {jobs.collect.map((c) => (
              <li key={c.item_id}>
                {c.quantity} {c.item_unit} — {c.item_name}
              </li>
            ))}
          </ul>
        )}
      </Section>
      {jobs.next_visit && (
        <Section title="Visita já agendada">
          <div className="small">
            {jobs.next_visit.title} — {formatDateTimePt(jobs.next_visit.starts_at)}
          </div>
        </Section>
      )}
    </>
  );
}

export default function TripPlanModal({
  plan,
  onClose,
  onOpenRoute,
  onCopied,
}: {
  plan: TripPlan;
  onClose: () => void;
  onOpenRoute: () => void;
  onCopied: (ok: boolean) => void;
}) {
  const s = plan.summary;

  async function copySummary() {
    try {
      await navigator.clipboard.writeText(buildTripSummaryText(plan));
      onCopied(true);
    } catch {
      onCopied(false);
    }
  }

  return (
    <Modal
      title="Plano da deslocação"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={copySummary}>
            Copiar resumo
          </button>
          <button type="button" className="btn btn--primary" onClick={onOpenRoute}>
            <Icon name="mapPin" size={14} /> Abrir rota
          </button>
        </>
      }
    >
      <div aria-label="Resumo da deslocação">
        <p style={{ margin: "0 0 6px" }}>
          <strong>{plan.total_km} km</strong> em linha reta
          {plan.saved_km > 0 ? ` — menos ${plan.saved_km} km do que a ordem escolhida.` : "."}{" "}
          {plan.method === "exact" ? "Ordem ótima." : "Boa ordem, mas não garantidamente a ótima."}
        </p>
        <p className="small" style={{ margin: 0 }}>
          {s.projects} instalação(ões)
          {s.suppliers > 0 && ` · ${s.suppliers} fornecedor(es)`}
          {s.pickup_points > 0 && ` · ${s.pickup_points} ponto(s) de recolha`}
          {s.operational_tasks !== null &&
            ` · ${s.operational_tasks} tarefa(s) operacional(is)${s.overdue_tasks ? ` (${s.overdue_tasks} atrasada(s))` : ""}`}
          {s.issues !== null && ` · ${s.issues} pendência(s)`}
          {s.items_to_collect !== null && ` · ${s.items_to_collect} material(is) a recolher`}
        </p>
        <p className="small muted" style={{ margin: "4px 0 10px" }}>
          Distâncias em linha reta (aproximação) — não são quilómetros de condução.
        </p>
      </div>
      <ol style={{ margin: 0, paddingLeft: 18 }}>
        {plan.stops.map((stop, index) => (
          <li key={`${stop.kind}:${stop.id}`} style={{ marginBottom: 10 }}>
            <strong>{stop.name}</strong>
            <span className="small muted">{index === 0 ? " (partida)" : ` — +${stop.leg_km} km`}</span>
            <StopJobs stop={stop} />
          </li>
        ))}
        {plan.return_leg_km !== null && (
          <li className="small muted">Regresso à partida — +{plan.return_leg_km} km</li>
        )}
      </ol>
    </Modal>
  );
}
