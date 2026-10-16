import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  createTeamAssignment,
  deleteTeamAssignment,
  formatApiDetail,
  Installer,
  listInstallers,
  listTeamAssignments,
  Project,
  TeamAssignment,
  TeamAssignmentInput,
  TeamAssignmentUpdate,
  updateTeamAssignment,
} from "../api/client";
import { formatDatePt } from "../utils/dates";
import Icon from "./Icon";
import { Alert, Badge, EmptyState, Modal } from "./ui";

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return formatApiDetail(error.detail) ?? error.message;
  return "Não foi possível contactar o servidor.";
}

function emptyForm(project: Project): TeamAssignmentInput {
  return {
    team_id: "",
    start_date: project.work_start_date ?? "",
    end_date: project.work_end_date ?? "",
    note: "",
  };
}

function assignmentTeamLabel(assignment: TeamAssignment, installers: Installer[]): string {
  if (assignment.team_name) return assignment.team_name;
  for (const installer of installers) {
    const team = installer.teams.find((candidate) => candidate.id === assignment.team_id);
    if (team) return team.name;
  }
  return "Equipa não identificada";
}

export default function TeamAssignments({ project }: { project: Project }) {
  const [assignments, setAssignments] = useState<TeamAssignment[] | null>(null);
  const [installers, setInstallers] = useState<Installer[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<TeamAssignment | "new" | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setAssignments(null);
    Promise.all([listTeamAssignments(project.id), listInstallers()])
      .then(([nextAssignments, nextInstallers]) => {
        if (cancelled) return;
        setAssignments(nextAssignments);
        setInstallers(nextInstallers);
      })
      .catch((reason) => {
        if (!cancelled) setError(errorMessage(reason));
      });
    return () => {
      cancelled = true;
    };
  }, [project.id, reloadKey]);

  const installer = installers.find((candidate) => candidate.id === project.installer_id);
  const activeTeams = useMemo(
    () => (installer?.teams ?? []).filter((team) => team.is_active),
    [installer],
  );

  function teamsFor(assignment: TeamAssignment | null) {
    if (!assignment) return activeTeams;
    return (installer?.teams ?? []).filter((team) => team.is_active || team.id === assignment.team_id);
  }

  async function remove(assignment: TeamAssignment) {
    if (deletingId || !window.confirm(`Remover a afectação da ${assignmentTeamLabel(assignment, installers)}?`)) return;
    setDeletingId(assignment.id);
    setError(null);
    try {
      await deleteTeamAssignment(project.id, assignment.id);
      setAssignments((current) => current?.filter((candidate) => candidate.id !== assignment.id) ?? current);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <section className="team-assignments" aria-labelledby="team-assignments-title">
      <div className="team-assignments__head">
        <h3 id="team-assignments-title">Equipas</h3>
        {project.can_plan_work && project.installer_id && (
          <button type="button" className="btn btn--sm" onClick={() => setEditing("new")}>
            <Icon name="plus" size={14} /> Adicionar equipa
          </button>
        )}
      </div>
      {error && (
        <Alert
          tone="danger"
          title="Não foi possível carregar as equipas"
          action={
            <button type="button" className="btn btn--sm" onClick={() => setReloadKey((key) => key + 1)}>
              Tentar novamente
            </button>
          }
        >
          {error}
        </Alert>
      )}
      {!error && assignments === null && <p className="small muted">A carregar afectações…</p>}
      {!error && assignments && assignments.length === 0 && (
        <EmptyState
          compact
          title="Nenhuma equipa afectada a esta obra."
          text={project.installer_name ? "Adicione uma ou mais equipas e defina a janela de cada uma." : "A obra ainda não tem instalador."}
        />
      )}
      {!error && assignments && assignments.length > 0 && (
        <ul className="team-assignments__list">
          {assignments.map((assignment) => (
            <li key={assignment.id} className="team-assignments__item">
              <div>
                <strong>{assignmentTeamLabel(assignment, installers)}</strong>
                {(assignment.team_leader_name || assignment.team_leader_phone) && (
                  <span className="muted">
                    {assignment.team_leader_name ? ` · chefe ${assignment.team_leader_name}` : ""}
                    {assignment.team_leader_phone ? ` · ${assignment.team_leader_phone}` : ""}
                  </span>
                )}
                <div className="small muted">
                  {formatDatePt(assignment.start_date)} a {formatDatePt(assignment.end_date)}
                </div>
                {assignment.note && <div className="small">{assignment.note}</div>}
                {assignment.warning && (
                  <div className="small team-assignments__warning">
                    <Icon name="alert" size={14} /> {assignment.warning}
                  </div>
                )}
              </div>
              {project.can_plan_work && (
                <div className="team-assignments__actions">
                  {assignment.warning && <Badge tone="warning">Fora da janela da obra</Badge>}
                  <button type="button" className="btn btn--ghost btn--sm" onClick={() => setEditing(assignment)} disabled={deletingId !== null}>
                    Editar
                  </button>
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm danger-text"
                    onClick={() => void remove(assignment)}
                    disabled={deletingId !== null}
                  >
                    {deletingId === assignment.id ? "A remover…" : "Remover"}
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {editing && (
        <AssignmentModal
          project={project}
          assignment={editing === "new" ? null : editing}
          teams={teamsFor(editing === "new" ? null : editing)}
          onClose={() => setEditing(null)}
          onSaved={(saved, wasNew) => {
            setAssignments((current) => {
              if (!current) return [saved];
              return wasNew ? [...current, saved] : current.map((item) => (item.id === saved.id ? saved : item));
            });
            setEditing(null);
          }}
        />
      )}
    </section>
  );
}

function AssignmentModal({
  project,
  assignment,
  teams,
  onClose,
  onSaved,
}: {
  project: Project;
  assignment: TeamAssignment | null;
  teams: Installer["teams"];
  onClose: () => void;
  onSaved: (assignment: TeamAssignment, wasNew: boolean) => void;
}) {
  const initial = assignment ? null : emptyForm(project);
  const [teamId, setTeamId] = useState(assignment?.team_id ?? initial?.team_id ?? "");
  const [startDate, setStartDate] = useState(assignment?.start_date ?? initial?.start_date ?? "");
  const [endDate, setEndDate] = useState(assignment?.end_date ?? initial?.end_date ?? "");
  const [note, setNote] = useState(assignment?.note ?? initial?.note ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!teamId || !startDate || !endDate) {
      setError("Escolha a equipa e preencha as duas datas.");
      return;
    }
    if (endDate < startDate) {
      setError("O fim da afectação não pode ser anterior ao início.");
      return;
    }
    setError(null);
    setSaving(true);
    try {
      const saved = assignment
        ? await updateTeamAssignment(project.id, assignment.id, { team_id: teamId, start_date: startDate, end_date: endDate, note } satisfies TeamAssignmentUpdate)
        : await createTeamAssignment(project.id, { team_id: teamId, start_date: startDate, end_date: endDate, note } satisfies TeamAssignmentInput);
      onSaved(saved, !assignment);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={assignment ? "Editar afectação" : "Adicionar equipa à obra"}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn btn--ghost" onClick={onClose} disabled={saving}>Cancelar</button>
          <button type="submit" form="team-assignment-form" className="btn" disabled={saving || teams.length === 0}>
            {saving ? "A guardar…" : "Guardar"}
          </button>
        </>
      }
    >
      <form id="team-assignment-form" className="stack" onSubmit={submit}>
        {error && <Alert tone="danger">{error}</Alert>}
        <div className="field">
          <label htmlFor="assignment-team">Equipa</label>
          <select id="assignment-team" className="select" value={teamId} onChange={(event) => setTeamId(event.target.value)} required>
            <option value="">— escolher equipa —</option>
            {teams.map((team) => (
              <option key={team.id} value={team.id}>
                {team.name}{team.leader_name ? ` (chefe ${team.leader_name})` : ""}{!team.is_active ? " (inactiva — manter apenas)" : ""}
              </option>
            ))}
          </select>
          {teams.length === 0 && <span className="small muted">O instalador não tem equipas activas disponíveis.</span>}
        </div>
        <div className="grid grid--2">
          <div className="field">
            <label htmlFor="assignment-start">Início</label>
            <input id="assignment-start" className="input" type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="assignment-end">Fim</label>
            <input id="assignment-end" className="input" type="date" value={endDate} min={startDate || undefined} onChange={(event) => setEndDate(event.target.value)} required />
          </div>
        </div>
        <div className="field">
          <label htmlFor="assignment-note">Nota <span className="muted">(opcional)</span></label>
          <textarea id="assignment-note" className="input" rows={3} maxLength={4000} value={note} onChange={(event) => setNote(event.target.value)} />
        </div>
      </form>
    </Modal>
  );
}
