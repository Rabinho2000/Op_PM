import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  getProjectProcess,
  ProcessRead,
  ProcessResponsible,
  ProcessStage,
  setProcessContactDone,
  setProcessSubtaskDone,
} from "../api/client";
import { formatDatePt } from "../utils/dates";
import Icon from "./Icon";
import { Alert, Badge, Card, EmptyState, ErrorState, LoadingState, ProgressBar } from "./ui";
import type { Tone } from "./ui";

const STATUS_LABELS: Record<string, string> = {
  done: "Concluída",
  overdue: "Em atraso",
  active: "Em curso",
  upcoming: "Por começar",
  no_date: "Sem data",
};

const STATUS_TONES: Record<string, Tone> = {
  done: "success",
  overdue: "danger",
  active: "info",
  upcoming: "neutral",
  no_date: "neutral",
};

const CONTACT_LABELS: Record<string, string> = { contacto: "Contacto", update: "Update" };

export function responsibleText(r: ProcessResponsible): string {
  if (r.names.length > 0) return `${r.label}: ${r.names.join(", ")}`;
  return r.unresolved ? `${r.label} — por atribuir` : r.label;
}

// Separador "Processo" do projeto (D-073): fases → etapas → subtarefas, com o
// responsável resolvido para ESTE projeto, prazos calculados a partir do arranque e
// o progresso. Marcar só é oferecido quando o servidor indica `can_update`.
export default function ProjectProcess({ projectId }: { projectId: string }) {
  const [process, setProcess] = useState<ProcessRead | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    getProjectProcess(projectId)
      .then((p) => {
        if (cancelled) return;
        setProcess(p);
        // Abre por omissão as etapas por fazer que estão em curso ou em atraso.
        setOpen((prev) => {
          if (Object.keys(prev).length > 0) return prev;
          const initial: Record<string, boolean> = {};
          for (const phase of p.phases) for (const s of phase.stages) initial[s.code] = s.status === "active" || s.status === "overdue";
          return initial;
        });
      })
      .catch((e) => !cancelled && setError(e instanceof ApiError ? e.detail : "Não foi possível carregar o processo."));
    return () => {
      cancelled = true;
    };
  }, [projectId, reloadKey]);

  const run = useCallback(async (key: string, action: () => Promise<ProcessRead>) => {
    setPending(key);
    setActionError(null);
    try {
      setProcess(await action());
    } catch (e) {
      setActionError(e instanceof ApiError ? e.detail : "Não foi possível guardar.");
    } finally {
      setPending(null);
    }
  }, []);

  if (error) return <ErrorState message={error} onRetry={() => setReloadKey((k) => k + 1)} />;
  if (!process) return <LoadingState label="A carregar o processo…" rows={4} />;
  if (!process.has_catalog) {
    return (
      <Card title="Processo" icon="tasks">
        <EmptyState compact icon="tasks" title="O processo ainda não foi carregado." text="Peça a um administrador para carregar o catálogo do processo." />
      </Card>
    );
  }

  const { summary } = process;
  return (
    <div className="process">
      <Card title="Progresso do processo" icon="tasks">
        <ProgressBar value={summary.percent} label="Progresso do processo" large />
        <p className="small muted" style={{ marginTop: 8 }}>
          {summary.done} de {summary.total} subtarefas · {summary.stages_done} de {summary.stages_total} etapas concluídas
        </p>
        <div className="badges" style={{ marginTop: 8 }}>
          {summary.overdue_stages > 0 && <Badge tone="danger">{summary.overdue_stages} em atraso</Badge>}
          {summary.overdue_contacts > 0 && <Badge tone="warning">{summary.overdue_contacts} contactos por fazer</Badge>}
        </div>
        {process.start_date === null && (
          <div style={{ marginTop: 12 }}>
            <Alert tone="warning">
              Este projeto não tem data de início: os prazos das etapas não podem ser calculados.
            </Alert>
          </div>
        )}
        {!process.can_update && (
          <p className="small muted" style={{ marginTop: 8 }}>
            Só consulta: não tem permissão para marcar o progresso deste projeto.
          </p>
        )}
        {actionError && (
          <div style={{ marginTop: 12 }}>
            <Alert tone="danger">{actionError}</Alert>
          </div>
        )}
      </Card>

      {process.phases.map((phase) => (
        <section key={phase.id} className="process__phase" aria-label={phase.name}>
          <h3 className="process__phase-title">
            <span className="process__dot" style={{ background: phase.color }} aria-hidden="true" />
            {phase.name}
            <span className="muted small"> · {phase.done_count}/{phase.total_count}</span>
          </h3>
          {phase.stages.map((stage) => (
            <StageCard
              key={stage.id}
              stage={stage}
              expanded={Boolean(open[stage.code])}
              onToggle={() => setOpen((o) => ({ ...o, [stage.code]: !o[stage.code] }))}
              canUpdate={process.can_update}
              pending={pending}
              onSubtask={(subtaskId, done) => run(`s:${subtaskId}`, () => setProcessSubtaskDone(projectId, subtaskId, done))}
              onContact={(done) => run(`c:${stage.id}`, () => setProcessContactDone(projectId, stage.id, done))}
            />
          ))}
        </section>
      ))}
    </div>
  );
}

function StageCard({
  stage,
  expanded,
  onToggle,
  canUpdate,
  pending,
  onSubtask,
  onContact,
}: {
  stage: ProcessStage;
  expanded: boolean;
  onToggle: () => void;
  canUpdate: boolean;
  pending: string | null;
  onSubtask: (subtaskId: string, done: boolean) => void;
  onContact: (done: boolean) => void;
}) {
  const bodyId = `stage-${stage.code}`;
  const r = stage.responsible;
  return (
    <div className={`process__stage process__stage--${stage.status}`}>
      <button type="button" className="process__stage-head" aria-expanded={expanded} aria-controls={bodyId} onClick={onToggle}>
        <span className={`process__chevron ${expanded ? "process__chevron--open" : ""}`} aria-hidden="true">
          <Icon name="chevronRight" size={16} />
        </span>
        <span className="process__stage-title">{stage.title}</span>
        <span className="process__stage-meta">
          <Badge tone={STATUS_TONES[stage.status] ?? "neutral"}>{STATUS_LABELS[stage.status] ?? stage.status}</Badge>
          <span className="small muted">
            {stage.done_count}/{stage.total_count}
          </span>
        </span>
      </button>
      <div className="process__stage-sub small muted">
        <span className={r.unresolved ? "text-danger" : undefined}>{responsibleText(r)}</span>
        {r.delegated && <> · <Badge tone="info">delegado</Badge></>}
        {stage.planned_start && stage.planned_end && (
          <>
            {" "}
            · {formatDatePt(stage.planned_start)} a {formatDatePt(stage.planned_end)}
          </>
        )}
      </div>
      {expanded && (
        <div id={bodyId} className="process__stage-body">
          {stage.note && <p className="small muted">{stage.note}</p>}
          {stage.contact && (
            <label className={`process__contact ${stage.contact.overdue ? "process__contact--overdue" : ""}`}>
              <input
                type="checkbox"
                checked={stage.contact.done}
                disabled={!canUpdate || pending === `c:${stage.id}`}
                onChange={(e) => canUpdate && onContact(e.target.checked)}
              />
              <span>
                <strong>{CONTACT_LABELS[stage.contact.kind] ?? stage.contact.kind}</strong>
                {stage.contact.planned_date && <> até {formatDatePt(stage.contact.planned_date)}</>}
                {stage.contact.overdue && <Badge tone="danger">por fazer</Badge>}
                {stage.contact.note && <span className="muted"> — {stage.contact.note}</span>}
              </span>
            </label>
          )}
          <ul className="process__subtasks">
            {stage.subtasks.map((t) => (
              <li key={t.id}>
                <label>
                  <input
                    type="checkbox"
                    checked={t.done}
                    disabled={!canUpdate || pending === `s:${t.id}`}
                    onChange={(e) => canUpdate && onSubtask(t.id, e.target.checked)}
                  />
                  <span className={t.done ? "process__done" : undefined}>{t.title}</span>
                </label>
                {t.done && (t.done_by_display_name || t.done_at) && (
                  <span className="small muted">
                    {t.done_by_display_name ?? ""}
                    {t.done_at ? ` · ${formatDatePt(t.done_at.slice(0, 10))}` : ""}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
