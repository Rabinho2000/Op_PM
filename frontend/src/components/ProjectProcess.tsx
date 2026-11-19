import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import {
  getProjectProcess,
  ProcessRead,
  ProcessResponsible,
  ProcessStage,
  setProcessContactDone,
  setProcessStageSubtasksDone,
  setProcessSubtaskDone,
  errorMessage,
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
  pending: "Por concluir",
};

const STATUS_TONES: Record<string, Tone> = {
  done: "success",
  overdue: "danger",
  active: "info",
  upcoming: "neutral",
  no_date: "neutral",
  pending: "warning",
};

const CONTACT_LABELS: Record<string, string> = { contacto: "Contacto", update: "Update" };

function phaseSwatchStyle(color: string | null | undefined): CSSProperties | undefined {
  const safeColor = color?.trim();
  if (!safeColor || !/^#(?:[\da-f]{3,4}|[\da-f]{6}|[\da-f]{8})$/i.test(safeColor)) return undefined;
  return { "--phase-color": safeColor } as CSSProperties;
}

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
  const [closedOnly, setClosedOnly] = useState(false);
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
      .catch((e) => !cancelled && setError(errorMessage(e, "Não foi possível carregar o processo.")));
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
      setActionError(errorMessage(e, "Não foi possível guardar."));
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
  const visiblePhases = process.phases
    .map((phase) => ({ ...phase, stages: closedOnly ? phase.stages.filter((stage) => stage.status === "done") : phase.stages }))
    .filter((phase) => phase.stages.length > 0);
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
        <label className="process__closed-filter" style={{ display: "inline-flex", gap: 8, marginTop: 12 }}>
          <input type="checkbox" checked={closedOnly} onChange={(event) => setClosedOnly(event.target.checked)} />
          <span>Etapas fechadas</span>
        </label>
      </Card>

      {visiblePhases.map((phase) => (
        <section key={phase.id} className="process__phase" aria-label={phase.name}>
          <h3 className="process__phase-title">
            <span className="process__phase-swatch" style={phaseSwatchStyle(phase.color)} aria-hidden="true" />
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
              onStageSubtasks={(done) => run(`stage:${stage.id}`, () => setProcessStageSubtasksDone(projectId, stage.id, done))}
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
  onStageSubtasks,
  onContact,
}: {
  stage: ProcessStage;
  expanded: boolean;
  onToggle: () => void;
  canUpdate: boolean;
  pending: string | null;
  onSubtask: (subtaskId: string, done: boolean) => void;
  onStageSubtasks: (done: boolean) => void;
  onContact: (done: boolean) => void;
}) {
  const bodyId = `stage-${stage.code}`;
  const stageActionKey = `stage:${stage.id}`;
  const stageCanUpdate = stage.can_update ?? canUpdate;
  const allDone = stage.total_count > 0 && stage.done_count === stage.total_count;
  const partiallyDone = stage.done_count > 0 && !allDone;
  const stageCheckboxRef = useRef<HTMLInputElement>(null);
  const r = stage.responsible;

  useEffect(() => {
    if (stageCheckboxRef.current) stageCheckboxRef.current.indeterminate = partiallyDone;
  }, [partiallyDone, pending, stage.done_count, stage.id]);

  return (
    <div className={`process__stage process__stage--${stage.status}`}>
      <button type="button" className="process__stage-head" aria-expanded={expanded} aria-controls={bodyId} onClick={onToggle}>
        <span className={`process__chevron ${expanded ? "process__chevron--open" : ""}`} aria-hidden="true">
          <Icon name="chevronRight" size={16} />
        </span>
        <span className="process__stage-title">{stage.title}</span>
        <span className="process__stage-meta">
          <Badge tone={STATUS_TONES[stage.status] ?? "neutral"}>{STATUS_LABELS[stage.status] ?? stage.status}</Badge>
          {stage.status === "done" && stage.completed_at && <span className="small muted">Concluída em {formatDatePt(stage.completed_at.slice(0, 10))}</span>}
          <span className="small muted">
            {stage.done_count}/{stage.total_count}
          </span>
        </span>
      </button>
      <div className="process__stage-sub small muted">
        {stage.total_count > 0 && (
          <label className="process__stage-bulk">
            <input
              ref={stageCheckboxRef}
              type="checkbox"
              checked={allDone}
              aria-label={`Marcar todas as subtarefas de ${stage.title}`}
              disabled={!stageCanUpdate || pending === stageActionKey}
              onChange={(e) => stageCanUpdate && onStageSubtasks(e.target.checked)}
            />
            <span>Concluir etapa</span>
          </label>
        )}
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
                disabled={!stageCanUpdate || pending === `c:${stage.id}` || pending === stageActionKey}
                onChange={(e) => stageCanUpdate && onContact(e.target.checked)}
              />
              <span>
                <strong>{CONTACT_LABELS[stage.contact.kind] ?? stage.contact.kind}</strong>
                {stage.contact.planned_date && <> até {formatDatePt(stage.contact.planned_date)}</>}
                {stage.contact.overdue && <Badge tone="danger">por fazer</Badge>}
                {stage.contact.done && stage.contact.source === "legacy" && <span className="small muted"> (importado do legado)</span>}
                {stage.contact.done && stage.contact.source === "inferred" && <span className="small muted"> (concluído por regra)</span>}
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
                    disabled={!stageCanUpdate || pending === `s:${t.id}` || pending === stageActionKey}
                    onChange={(e) => stageCanUpdate && onSubtask(t.id, e.target.checked)}
                  />
                  <span className={t.done ? "process__done" : undefined}>{t.title}</span>
                </label>
                {t.done && t.source === "legacy" && <span className="small muted">importado do legado</span>}
                {t.done && t.source === "inferred" && (
                  <span className="small muted">concluída por regra (projeto entregue)</span>
                )}
                {t.done && t.source === "ui" && (t.done_by_display_name || t.done_at) && (
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
