import { useState } from "react";
import { ApiError, ProcessRead, setProcessSubtaskDone } from "../api/client";
import { formatDatePt } from "../utils/dates";
import { responsibleText } from "./ProjectProcess";
import { Alert, Badge, Card, EmptyState } from "./ui";
import type { Tone } from "./ui";

const STATUS_LABELS: Record<string, string> = { overdue: "Em atraso", active: "Em curso", upcoming: "Por começar", no_date: "Sem data", pending: "Por concluir", done: "Concluída" };
const STATUS_TONES: Record<string, Tone> = { overdue: "danger", active: "info", upcoming: "neutral", no_date: "neutral", pending: "warning", done: "success" };

/** Subtarefas do processo por concluir — as "tarefas fixas" do projeto (D-078). */
export function pendingProcessTasks(process: ProcessRead | null): number {
  return process?.has_catalog ? process.summary.total - process.summary.done : 0;
}

// Tarefas fixas do projeto (as subtarefas do processo) no separador "Tarefas": por omissão só as
// por concluir, agrupadas por etapa; o servidor decide se se pode marcar (`can_update`).
export default function ProcessOpenTasks({
  projectId,
  process,
  onChange,
}: {
  projectId: string;
  process: ProcessRead | null;
  onChange: (p: ProcessRead) => void;
}) {
  const [showDone, setShowDone] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!process || !process.has_catalog) return null;

  const toggle = async (subtaskId: string, done: boolean) => {
    setPending(subtaskId);
    setError(null);
    try {
      onChange(await setProcessSubtaskDone(projectId, subtaskId, done));
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Não foi possível guardar.");
    } finally {
      setPending(null);
    }
  };

  const stages = process.phases
    .flatMap((ph) => ph.stages)
    .map((s) => ({ stage: s, subtasks: s.subtasks.filter((t) => showDone || !t.done) }))
    .filter((g) => g.subtasks.length > 0);
  const { done, total } = process.summary;

  return (
    <Card
      title="Tarefas do processo"
      icon="tasks"
      actions={
        <label className="small">
          <input type="checkbox" checked={showDone} onChange={(e) => setShowDone(e.target.checked)} /> Mostrar concluídas
        </label>
      }
    >
      <p className="small muted">
        {total - done} por concluir de {total} · o processo completo está no separador Processo.
      </p>
      {error && <Alert tone="danger">{error}</Alert>}
      {stages.length === 0 && <EmptyState compact icon="tasks" title="Todas as tarefas do processo estão concluídas." />}
      {stages.map(({ stage, subtasks }) => (
        <section key={stage.id} aria-label={stage.title} style={{ marginTop: 12 }}>
          <h3 className="process__phase-title" style={{ fontSize: "1rem" }}>
            {stage.title} <Badge tone={STATUS_TONES[stage.status] ?? "neutral"}>{STATUS_LABELS[stage.status] ?? stage.status}</Badge>
          </h3>
          <div className="small muted">
            {responsibleText(stage.responsible)}
            {stage.planned_end && <> · até {formatDatePt(stage.planned_end)}</>}
          </div>
          <ul className="process__subtasks">
            {subtasks.map((t) => (
              <li key={t.id}>
                <label>
                  <input
                    type="checkbox"
                    checked={t.done}
                    disabled={!process.can_update || pending === t.id}
                    onChange={(e) => process.can_update && toggle(t.id, e.target.checked)}
                  />
                  <span className={t.done ? "process__done" : undefined}>{t.title}</span>
                </label>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </Card>
  );
}
