// Percurso de obra de um projeto (D-052): fases, cronograma das etapas e
// checklist de subtarefas/contactos. Datas, estados e permissões vêm
// calculados do servidor (app/services/workflow.py) — aqui só se mostra e
// se envia a marcação.
import { useState } from "react";
import {
  ApiError,
  ProjectWorkflow as Workflow,
  setWorkflowContactDone,
  setWorkflowSubtaskDone,
  WorkflowStage,
  WorkflowStageStatus,
} from "../api/client";
import { formatDayMonthPt } from "../utils/dates";
import Icon from "./Icon";
import { useToast } from "./Toast";
import { Badge, ProgressBar, Tone } from "./ui";

export const STAGE_STATUS_LABELS: Record<WorkflowStageStatus, string> = {
  concluida: "Concluída",
  em_curso: "Em curso",
  atrasada: "Atrasada",
  a_aguardar: "A aguardar",
  por_iniciar: "Por iniciar",
};

const STAGE_STATUS_TONES: Record<WorkflowStageStatus, Tone> = {
  concluida: "success",
  em_curso: "info",
  atrasada: "danger",
  a_aguardar: "neutral",
  por_iniciar: "neutral",
};

type Filter = "todas" | "pendentes" | "atrasadas";

function dateRange(stage: WorkflowStage): string {
  if (!stage.planned_start || !stage.planned_end) {
    return stage.start_day ? `dia ${stage.start_day}${stage.end_day !== stage.start_day ? `–${stage.end_day}` : ""}` : "";
  }
  if (stage.planned_start === stage.planned_end) return formatDayMonthPt(stage.planned_start);
  return `${formatDayMonthPt(stage.planned_start)} – ${formatDayMonthPt(stage.planned_end)}`;
}

export default function ProjectWorkflow({
  projectId,
  workflow,
  onChange,
}: {
  projectId: string;
  workflow: Workflow;
  onChange: (updated: Workflow) => void;
}) {
  const { notify } = useToast();
  const [open, setOpen] = useState<Set<string>>(() => {
    const current = workflow.stages.find((s) => s.number === workflow.current_stage_number);
    return new Set(current ? [current.code] : []);
  });
  const [busy, setBusy] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("todas");

  const phaseByCode = new Map(workflow.phases.map((p) => [p.code, p]));
  const totalDays = Math.max(workflow.total_days, 1);

  function toggleOpen(code: string) {
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  }

  async function run(key: string, action: () => Promise<Workflow>) {
    setBusy(key);
    try {
      onChange(await action());
    } catch (e) {
      notify(e instanceof ApiError ? e.detail : "Não foi possível guardar.", "error");
    } finally {
      setBusy(null);
    }
  }

  const stages = workflow.stages.filter((s) => {
    if (filter === "pendentes") return s.status !== "concluida";
    if (filter === "atrasadas") return s.status === "atrasada" || s.contact_overdue;
    return true;
  });

  return (
    <div className="wf">
      <div className="card wf__summary">
        <div className="wf__summary-main">
          <div className="small muted">Percurso de obra</div>
          <ProgressBar value={workflow.progress_percent} large label="Progresso do percurso de obra" />
          <div className="small muted">
            {workflow.done_count} de {workflow.total_count} subtarefas
            {workflow.planned_end && <> · fim previsto {formatDayMonthPt(workflow.planned_end)}</>}
            {!workflow.start_date && <> · sem data de início — prazos por calcular</>}
          </div>
        </div>
        <div className="badges">
          {workflow.current_stage_number !== null ? (
            <Badge tone="brand">Etapa atual: {workflow.current_stage_number}</Badge>
          ) : (
            <Badge tone="success">Percurso concluído</Badge>
          )}
          {workflow.overdue_stages_count > 0 && (
            <Badge tone="danger">
              {workflow.overdue_stages_count} etapa{workflow.overdue_stages_count > 1 ? "s" : ""} em atraso
            </Badge>
          )}
          {workflow.pending_contacts_count > 0 && (
            <Badge tone="warning">
              <Icon name="phone" size={12} /> {workflow.pending_contacts_count} contacto
              {workflow.pending_contacts_count > 1 ? "s" : ""} por fazer
            </Badge>
          )}
          {!workflow.can_edit && <Badge>Só leitura</Badge>}
        </div>
      </div>

      <div className="wf__phases" aria-label="Fases">
        {workflow.phases.map((p) => {
          const pct = p.total_count ? Math.round((100 * p.done_count) / p.total_count) : 0;
          return (
            <div
              key={p.code}
              className={`wf__phase ${p.code === workflow.current_phase_code ? "wf__phase--current" : ""}`}
              style={{ ["--ph" as string]: p.color }}
            >
              <span className="wf__phase-name">{p.name}</span>
              <span className="wf__phase-bar">
                <span style={{ width: `${pct}%` }} />
              </span>
              <span className="wf__phase-count">
                {p.done_count}/{p.total_count}
              </span>
            </div>
          );
        })}
      </div>

      <div className="wf__toolbar">
        <div className="segmented" role="group" aria-label="Filtrar etapas">
          {(
            [
              ["todas", "Todas"],
              ["pendentes", "Por concluir"],
              ["atrasadas", "Em atraso"],
            ] as [Filter, string][]
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              aria-pressed={filter === key}
              onClick={() => setFilter(key)}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="small muted">Prazos em dias úteis desde o início do projeto</span>
      </div>

      <ol className="wf__stages">
        {stages.length === 0 && <li className="muted small wf__empty">Nenhuma etapa neste filtro.</li>}
        {stages.map((stage) => {
          const phase = phaseByCode.get(stage.phase_code);
          const isOpen = open.has(stage.code);
          const left = ((stage.start_day ?? 1) - 1) / totalDays;
          const width = ((stage.end_day ?? stage.start_day ?? 1) - (stage.start_day ?? 1) + 1) / totalDays;
          const contactDay = stage.contact_type && stage.start_day ? stage.contact_date : null;
          return (
            <li
              key={stage.code}
              className={`wf__stage wf__stage--${stage.status}`}
              style={{ ["--ph" as string]: phase?.color ?? "#888" }}
            >
              <button
                type="button"
                className="wf__stage-head"
                aria-expanded={isOpen}
                aria-controls={`wf-${stage.code}`}
                onClick={() => toggleOpen(stage.code)}
              >
                <span className="wf__num" aria-hidden="true">
                  {stage.status === "concluida" ? <Icon name="check" size={14} /> : stage.number}
                </span>
                <span className="wf__title">
                  <span className="wf__title-text">
                    <span className="sr-only">Etapa {stage.number}: </span>
                    {stage.title}
                  </span>
                  <span className="wf__meta">
                    {phase?.name}
                    {stage.responsible_label && <> · {stage.responsible_label}</>}
                    {dateRange(stage) && <> · {dateRange(stage)}</>}
                  </span>
                </span>
                <span className="wf__timeline" aria-hidden="true">
                  <span className="wf__bar" style={{ left: `${left * 100}%`, width: `${Math.max(width * 100, 1.5)}%` }}>
                    <span
                      className="wf__bar-fill"
                      style={{ width: `${stage.total_count ? (100 * stage.done_count) / stage.total_count : 0}%` }}
                    />
                  </span>
                </span>
                <span className="wf__right">
                  {stage.contact_type && (
                    <span
                      className={`wf__contact-dot ${stage.contact_done ? "done" : stage.contact_overdue ? "late" : ""}`}
                      title={stage.contact_done ? "Contacto feito" : "Contacto com o cliente por fazer"}
                    >
                      <Icon name={stage.contact_type === "contacto" ? "phone" : "mail"} size={12} />
                    </span>
                  )}
                  <span className="wf__count">
                    {stage.done_count}/{stage.total_count}
                  </span>
                  <Badge tone={STAGE_STATUS_TONES[stage.status]}>{STAGE_STATUS_LABELS[stage.status]}</Badge>
                  <Icon name="chevronRight" size={16} />
                </span>
              </button>

              {isOpen && (
                <div className="wf__body" id={`wf-${stage.code}`}>
                  {(stage.note || (stage.status === "a_aguardar" && stage.depends_on_number)) && (
                    <p className="small muted wf__note">
                      {stage.status === "a_aguardar" && stage.depends_on_number && (
                        <>A aguardar a conclusão da etapa {stage.depends_on_number}. </>
                      )}
                      {stage.note}
                    </p>
                  )}

                  {stage.contact_type && (
                    <label className={`wf__check wf__check--contact ${stage.contact_overdue ? "late" : ""}`}>
                      <input
                        type="checkbox"
                        checked={stage.contact_done}
                        disabled={!workflow.can_edit || busy !== null}
                        onChange={(e) =>
                          run(`${stage.code}:contact`, () =>
                            setWorkflowContactDone(projectId, stage.code, e.target.checked)
                          )
                        }
                      />
                      <Icon name={stage.contact_type === "contacto" ? "phone" : "mail"} size={14} />
                      <span>
                        <strong>{stage.contact_type === "contacto" ? "Contacto com o cliente" : "Atualização ao cliente"}</strong>
                        {contactDay && <> · {formatDayMonthPt(contactDay)}</>}
                        {stage.contact_note && <> — {stage.contact_note}</>}
                        {stage.contact_overdue && <span className="wf__late"> · em atraso</span>}
                      </span>
                    </label>
                  )}

                  <ul className="wf__subtasks">
                    {stage.subtasks.map((sub) => (
                      <li key={sub.code}>
                        <label className={`wf__check ${sub.done ? "done" : ""}`}>
                          <input
                            type="checkbox"
                            checked={sub.done}
                            disabled={!workflow.can_edit || busy !== null}
                            onChange={(e) =>
                              run(sub.code, () => setWorkflowSubtaskDone(projectId, sub.code, e.target.checked))
                            }
                          />
                          {sub.is_client_contact && <Icon name="phone" size={13} />}
                          <span>{sub.title}</span>
                        </label>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
