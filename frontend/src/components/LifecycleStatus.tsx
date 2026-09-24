import { FormEvent, useEffect, useState } from "react";
import {
  ApiError,
  changeProjectStatus,
  getLifecycleStatuses,
  LifecycleStatus,
  Project,
} from "../api/client";
import { LIFECYCLE_STATUS_TONES } from "../utils/labels";
import { useToast } from "./Toast";
import { Alert, Badge, Modal } from "./ui";

// A lista de estados vem do servidor (GET /api/projects/lifecycle-statuses) —
// nunca é duplicada aqui. Enquanto carrega, o rótulo cai para o código.
export function useLifecycleStatuses(): LifecycleStatus[] {
  const [statuses, setStatuses] = useState<LifecycleStatus[]>([]);
  useEffect(() => {
    let cancelled = false;
    getLifecycleStatuses()
      .then((s) => !cancelled && setStatuses(s))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);
  return statuses;
}

export function LifecycleBadge({ status, statuses }: { status: string | null; statuses: LifecycleStatus[] }) {
  if (!status) return <Badge tone="neutral">Sem estado</Badge>;
  const label = statuses.find((s) => s.code === status)?.label ?? status;
  return (
    <Badge tone={LIFECYCLE_STATUS_TONES[status] ?? "neutral"} dot>
      {label}
    </Badge>
  );
}

// Só é oferecido quando o servidor indica `can_change_status`; o PATCH continua
// validado no backend (permissão + âmbito).
export function LifecycleStatusControl({
  project,
  statuses,
  onChanged,
}: {
  project: Project;
  statuses: LifecycleStatus[];
  onChanged: (project: Project) => void;
}) {
  const { notify } = useToast();
  const [open, setOpen] = useState(false);
  const [choice, setChoice] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function openDialog() {
    setChoice(project.lifecycle_status ?? "");
    setNote("");
    setError(null);
    setOpen(true);
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!choice || choice === project.lifecycle_status) {
      setError("Escolha um estado diferente do atual.");
      return;
    }
    setSaving(true);
    setError(null);
    changeProjectStatus(project.id, choice, note.trim())
      .then((result) => {
        onChanged(result.project);
        notify(result.warning ?? "Estado do projeto atualizado.", result.warning ? "info" : "success");
        setOpen(false);
      })
      .catch((err) => setError(err instanceof ApiError ? err.detail : "Não foi possível alterar o estado."))
      .finally(() => setSaving(false));
  }

  return (
    <>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <LifecycleBadge status={project.lifecycle_status} statuses={statuses} />
        {project.can_change_status && (
          <button type="button" className="btn btn--sm" onClick={openDialog}>
            Alterar estado
          </button>
        )}
      </span>
      {open && (
        <Modal
          title="Alterar estado do projeto"
          onClose={() => setOpen(false)}
          footer={
            <>
              <button type="button" className="btn" onClick={() => setOpen(false)}>
                Cancelar
              </button>
              <button type="submit" form="lifecycle-form" className="btn btn--primary" disabled={saving}>
                {saving ? "A guardar…" : "Guardar estado"}
              </button>
            </>
          }
        >
          <form id="lifecycle-form" className="form-grid" onSubmit={handleSubmit}>
            {error && (
              <div className="span-2">
                <Alert tone="danger">{error}</Alert>
              </div>
            )}
            <div className="field span-2">
              <label htmlFor="lc-status">Novo estado *</label>
              <select id="lc-status" className="select" value={choice} onChange={(e) => setChoice(e.target.value)}>
                <option value="">— escolher estado —</option>
                {statuses.map((s) => (
                  <option key={s.code} value={s.code}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field span-2">
              <label htmlFor="lc-note">Nota (opcional)</label>
              <textarea
                id="lc-note"
                className="textarea"
                rows={3}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Ex.: cliente pediu para adiar a obra."
              />
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
