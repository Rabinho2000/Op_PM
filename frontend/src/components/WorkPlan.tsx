import { FormEvent, useEffect, useState } from "react";
import { ApiError, Installer, listInstallers, Project, updateProjectWorkPlan } from "../api/client";
import { formatDatePt } from "../utils/dates";
import Icon from "./Icon";
import { useToast } from "./Toast";
import { Alert, Badge, Card, Modal } from "./ui";

// Cartão "Obra" do projeto: instalador, equipa (com o chefe) e datas. Só é
// editável quando o servidor indica `can_plan_work`; o PATCH continua validado
// no backend (permissão, âmbito, equipa do instalador, datas).
export default function WorkPlanCard({ project, onChanged }: { project: Project; onChanged: (p: Project) => void }) {
  const [open, setOpen] = useState(false);
  const hasPlan = project.installer_id !== null || project.work_start_date !== null || project.work_end_date !== null;

  return (
    <>
      <Card
        title="Obra"
        icon="wrench"
        actions={
          project.can_plan_work && (
            <button type="button" className="btn btn--sm" onClick={() => setOpen(true)}>
              {hasPlan ? "Editar plano" : "Planear obra"}
            </button>
          )
        }
      >
        <dl className="kv">
          <dt>Instalador</dt>
          <dd>{project.installer_name ?? <span className="muted">Por atribuir</span>}</dd>
          <dt>Equipa</dt>
          <dd>
            {project.installer_team_name ? (
              <>
                {project.installer_team_name}
                {project.installer_team_leader_name && <span className="muted"> · chefe {project.installer_team_leader_name}</span>}
              </>
            ) : (
              <span className="muted">{project.installer_name ? "Sem equipa atribuída" : "—"}</span>
            )}
          </dd>
          <dt>Início da obra</dt>
          <dd>{project.work_start_date ? formatDatePt(project.work_start_date) : <span className="muted">Por definir</span>}</dd>
          <dt>Fim da obra</dt>
          <dd>
            {project.work_end_date ? formatDatePt(project.work_end_date) : <span className="muted">Por definir</span>}
            {project.work_dates_estimated && (
              <span style={{ marginLeft: 8 }}>
                <Badge tone="warning">Datas estimadas</Badge>
              </span>
            )}
          </dd>
        </dl>
        {project.work_dates_estimated && (
          <p className="small muted" style={{ marginTop: 8 }}>
            Estimadas a partir do modelo do processo (não refletem a realidade). Edite o plano para as confirmar.
          </p>
        )}
      </Card>
      {open && (
        <WorkPlanModal
          project={project}
          onClose={() => setOpen(false)}
          onSaved={(p) => {
            onChanged(p);
            setOpen(false);
          }}
        />
      )}
    </>
  );
}

function WorkPlanModal({
  project,
  onClose,
  onSaved,
}: {
  project: Project;
  onClose: () => void;
  onSaved: (p: Project) => void;
}) {
  const { notify } = useToast();
  const [installers, setInstallers] = useState<Installer[] | null>(null);
  const [installerId, setInstallerId] = useState(project.installer_id ?? "");
  const [teamId, setTeamId] = useState(project.installer_team_id ?? "");
  const [start, setStart] = useState(project.work_start_date ?? "");
  const [end, setEnd] = useState(project.work_end_date ?? "");
  const [confirmDates, setConfirmDates] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    listInstallers()
      .then(setInstallers)
      .catch(() => setError("Não foi possível carregar os instaladores."));
  }, []);

  // Só se oferecem os ativos, mais o que já está atribuído (para não o perder de vista).
  const installerOptions = (installers ?? []).filter((i) => i.is_active || i.id === project.installer_id);
  const selected = (installers ?? []).find((i) => i.id === installerId);
  const teamOptions = (selected?.teams ?? []).filter((t) => t.is_active || t.id === project.installer_team_id);

  function chooseInstaller(id: string) {
    setInstallerId(id);
    setTeamId(""); // a equipa é do instalador anterior
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (start && end && end < start) {
      setError("O fim da obra não pode ser anterior ao início.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await updateProjectWorkPlan(project.id, {
        installer_id: installerId || null,
        installer_team_id: installerId && teamId ? teamId : null,
        work_start_date: start || null,
        work_end_date: end || null,
        ...(project.work_dates_estimated && confirmDates ? { work_dates_estimated: false as const } : {}),
      });
      notify("Plano da obra atualizado.");
      onSaved(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Não foi possível guardar o plano da obra.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title="Plano da obra"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancelar
          </button>
          <button type="submit" form="workplan-form" className="btn btn--primary" disabled={saving || installers === null}>
            {saving ? "A guardar…" : "Guardar plano"}
          </button>
        </>
      }
    >
      <form id="workplan-form" className="form-grid" onSubmit={handleSubmit} noValidate>
        {error && (
          <div className="span-2">
            <Alert tone="danger">{error}</Alert>
          </div>
        )}
        <div className="field">
          <label htmlFor="wp-installer">Instalador</label>
          <select id="wp-installer" className="select" value={installerId} onChange={(e) => chooseInstaller(e.target.value)}>
            <option value="">— sem instalador —</option>
            {installerOptions.map((i) => (
              <option key={i.id} value={i.id}>
                {i.name}
                {i.is_active ? "" : " (inativo)"}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="wp-team">Equipa</label>
          <select id="wp-team" className="select" value={teamId} disabled={!installerId} onChange={(e) => setTeamId(e.target.value)}>
            <option value="">{installerId && teamOptions.length === 0 ? "— este instalador não tem equipas —" : "— sem equipa —"}</option>
            {teamOptions.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
                {t.leader_name ? ` (chefe ${t.leader_name})` : ""}
                {t.is_active ? "" : " (inativa)"}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="wp-start">Início da obra</label>
          <input id="wp-start" className="input" type="date" value={start} onChange={(e) => setStart(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="wp-end">Fim da obra</label>
          <input id="wp-end" className="input" type="date" value={end} min={start || undefined} onChange={(e) => setEnd(e.target.value)} />
        </div>
        {project.work_dates_estimated && (
          <div className="span-2">
            <Alert tone="warning">
              <Icon name="info" size={14} /> As datas atuais são estimadas. Alterá-las confirma-as; se estiverem corretas,
              marque a caixa abaixo.
            </Alert>
            <label style={{ display: "inline-flex", alignItems: "center", gap: 8, marginTop: 8, fontWeight: 500 }}>
              <input type="checkbox" checked={confirmDates} onChange={(e) => setConfirmDates(e.target.checked)} />
              Confirmar as datas como corretas
            </label>
          </div>
        )}
      </form>
    </Modal>
  );
}
