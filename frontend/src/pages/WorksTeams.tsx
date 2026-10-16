import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ApiError,
  getWorksTeams,
  Installer,
  listInstallers,
  TeamLocationAssignment,
  TeamLocationInstaller,
  TeamsView,
} from "../api/client";
import Icon from "../components/Icon";
import { LifecycleBadge, useLifecycleStatuses } from "../components/LifecycleStatus";
import { Card, EmptyState, ErrorState, LoadingState, PageHeader } from "../components/ui";
import { formatDatePt, todayIsoLisbon } from "../utils/dates";

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const PERIODS = [
  { days: 1, label: "Hoje" },
  { days: 7, label: "Esta semana" },
  { days: 14, label: "2 semanas" },
] as const;
type PeriodDays = (typeof PERIODS)[number]["days"];

function validDate(value: string | null): value is string {
  if (!value || !ISO_DATE.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

function readDays(value: string | null, period: string | null): PeriodDays {
  const candidate = value ?? (period === "week" ? "7" : period === "fortnight" ? "14" : period === "today" ? "1" : null);
  return candidate === "7" || candidate === "14" ? Number(candidate) as PeriodDays : 1;
}

function apiErrorMessage(error: unknown): string {
  return error instanceof ApiError ? error.detail : "Não foi possível contactar o servidor.";
}

function assignmentStatus(assignment: TeamLocationAssignment) {
  return assignment.conflict ? (
    <span className="teams-view__status teams-view__status--conflict" aria-label="Conflito de datas">
      <Icon name="alert" size={15} /> Conflito
    </span>
  ) : (
    <span className="teams-view__status"><Icon name="checkCircle" size={15} /> Afectada</span>
  );
}

function teamStatus(team: NonNullable<TeamLocationInstaller["teams"]>[number]) {
  if (team.status === "ocupada_noutra_obra") {
    return <span className="teams-view__status" aria-label="Ocupada noutra obra"><Icon name="alert" size={15} /> Ocupada noutra obra</span>;
  }
  if (team.status === "ocupada" || (team.assignments?.length ?? 0) > 0) {
    return <span className="teams-view__status"><Icon name="clock" size={15} /> Ocupada</span>;
  }
  return <span className="teams-view__status"><Icon name="checkCircle" size={15} /> Livre</span>;
}

function AssignmentDetails({ assignment, statuses }: { assignment: TeamLocationAssignment; statuses: ReturnType<typeof useLifecycleStatuses> }) {
  return (
    <div className="teams-view__assignment">
      <div>
        <Link to={`/projects/${assignment.project_id}`}><strong>{assignment.project_name}</strong></Link>{" "}
        {assignmentStatus(assignment)}
      </div>
      {assignment.address && <div className="small muted"><Icon name="mapPin" size={14} /> {assignment.address}</div>}
      <div className="small muted">
        {formatDatePt(assignment.start_date)} a {formatDatePt(assignment.end_date)}
        {assignment.pm_display_name ? ` · PM ${assignment.pm_display_name}` : " · sem PM"}
      </div>
      <div className="small"><LifecycleBadge status={assignment.lifecycle_status} statuses={statuses} /></div>
      {assignment.conflict && <div className="small teams-view__status--conflict"><Icon name="alert" size={14} /> Esta janela sobrepõe outra obra da equipa.</div>}
      {assignment.lat !== null && assignment.lon !== null && (
        <Link className="small" to="/map"><Icon name="mapPin" size={14} /> Ver no mapa</Link>
      )}
    </div>
  );
}

function InstallerTeams({ installer, statuses }: { installer: TeamLocationInstaller; statuses: ReturnType<typeof useLifecycleStatuses> }) {
  const teams = installer.teams ?? [];
  return (
    <Card className="teams-view__group" title={installer.name} icon="wrench" tone="brand">
      {teams.length === 0 ? (
        <EmptyState compact title="Sem equipas registadas." />
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table className="teams-view__table">
            <thead><tr><th scope="col">Equipa</th><th scope="col">Estado</th><th scope="col">Obra(s)</th></tr></thead>
            <tbody>
              {teams.map((team) => (
                <tr key={team.id}>
                  <th scope="row">{team.name}</th>
                  <td>{teamStatus(team)}</td>
                  <td>
                    {(team.assignments?.length ?? 0) > 0 ? team.assignments?.map((assignment) => <AssignmentDetails key={assignment.id} assignment={assignment} statuses={statuses} />) : (
                      <span className="muted">{team.status === "ocupada_noutra_obra" ? "Ocupada noutra obra" : "Sem obra nesta janela"}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

export default function WorksTeams() {
  const [params, setParams] = useSearchParams();
  const today = todayIsoLisbon();
  const dateParam = params.get("date");
  const date = validDate(dateParam) ? dateParam : today;
  const days = readDays(params.get("days"), params.get("period"));
  const installerParam = params.get("installer_id") ?? params.get("inst") ?? "";
  const [installers, setInstallers] = useState<Installer[]>([]);
  const [data, setData] = useState<TeamsView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const statuses = useLifecycleStatuses();

  useEffect(() => {
    let cancelled = false;
    listInstallers().then((result) => !cancelled && setInstallers(result)).catch(() => !cancelled && setInstallers([]));
    return () => { cancelled = true; };
  }, []);

  const activeInstallers = useMemo(() => installers.filter((installer) => installer.is_active), [installers]);
  const installerId = useMemo(
    () => installerParam && activeInstallers.some((installer) => installer.id === installerParam) ? installerParam : "",
    [installerParam, activeInstallers]
  );

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    getWorksTeams({ date, days, installer_id: installerId || undefined })
      .then((result) => !cancelled && setData(result))
      .catch((reason) => !cancelled && setError(apiErrorMessage(reason)));
    return () => { cancelled = true; };
  }, [date, days, installerId, reloadKey]);

  function update(patch: { date?: string; days?: PeriodDays; installerId?: string }) {
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      if (patch.date !== undefined) next.set("date", patch.date);
      if (patch.days !== undefined) next.set("days", String(patch.days));
      if (patch.installerId !== undefined) {
        next.delete("inst");
        next.delete("installer_id");
        if (patch.installerId) next.set("inst", patch.installerId);
      }
      return next;
    }, { replace: true });
  }

  return (
    <>
      <PageHeader
        title="Equipas"
        subtitle="Onde está cada equipa e quais estão livres para a próxima obra."
        actions={<Link className="btn btn--ghost" to="/works"><Icon name="calendar" size={16} /> Calendário</Link>}
      />
      <div className="toolbar" role="search" aria-label="Filtros da vista de equipas">
        <div className="field">
          <label htmlFor="teams-date">Data</label>
          <input id="teams-date" className="input" type="date" value={date} onChange={(event) => update({ date: event.target.value })} />
        </div>
        <div className="field">
          <span className="field__label" id="teams-period-label">Período</span>
          <div className="segmented" role="group" aria-labelledby="teams-period-label">
            {PERIODS.map((period) => <button key={period.days} type="button" className={days === period.days ? "is-active" : ""} aria-pressed={days === period.days} onClick={() => update({ days: period.days })}>{period.label}</button>)}
          </div>
        </div>
        <div className="field">
          <label htmlFor="teams-installer">Instalador</label>
          <select id="teams-installer" className="select" value={installerId} onChange={(event) => update({ installerId: event.target.value })}>
            <option value="">Todos os instaladores</option>
            {activeInstallers.map((installer) => <option key={installer.id} value={installer.id}>{installer.name}</option>)}
          </select>
        </div>
        <div className="toolbar__end"><button type="button" className="btn btn--ghost" onClick={() => update({ date: today, days: 1, installerId: "" })}>Hoje</button></div>
      </div>
      {error && <div className="card"><ErrorState message={error} onRetry={() => setReloadKey((key) => key + 1)} /></div>}
      {!error && !data && <div className="card"><LoadingState label="A carregar localização das equipas…" rows={4} /></div>}
      {!error && data && (
        <>
          <p className="small muted" aria-live="polite">{formatDatePt(data.date)} · {data.days === 1 ? "Hoje" : `${data.days} dias`} · {data.installers.reduce((count, installer) => count + (installer.teams?.length ?? 0), 0)} equipas</p>
          {data.installers.length === 0 ? <div className="card"><EmptyState icon="wrench" title="Nenhum instalador ou equipa neste filtro." text="Altere a data ou remova o filtro de instalador." /></div> : data.installers.map((installer) => <InstallerTeams key={installer.id} installer={installer} statuses={statuses} />)}
          <div className="small muted" aria-label="Legenda de estados"><Icon name="checkCircle" size={14} /> Livre · <Icon name="clock" size={14} /> Ocupada · <Icon name="alert" size={14} /> Ocupada noutra obra ou em conflito</div>
        </>
      )}
    </>
  );
}
