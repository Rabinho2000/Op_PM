import { ReactNode, useEffect, useMemo, useState } from "react";
import { Link, Navigate, useParams, useSearchParams } from "react-router-dom";
import {
  ApiError,
  getProject,
  getWorksCalendar,
  InstallerAccessInstaller,
  InstallerAccessTeamsResponse,
  listInstallerAccessTeams,
  listInstallerInventory,
  listProjects,
  listTasks,
  Project,
  Task,
} from "../api/client";
import {
  formatSignedTimeBankDuration,
  getTimeBankSummary,
  listTimeBankAdjustments,
  listTimeBankEntries,
} from "../api/timeBank";
import { useSession } from "../session/SessionContext";
import { hasInstallerCapability, INSTALLER_ACCESS_PERMISSIONS } from "../session/installerAccess";
import { formatQuantity } from "../utils/quantities";
import { todayIsoLisbon } from "../utils/dates";
import { Alert, Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader, ProgressBar } from "../components/ui";

function apiErrorMessage(error: unknown): string {
  return error instanceof ApiError ? error.detail : "Não foi possível contactar o servidor.";
}

function useReloadable<T>(loader: () => Promise<T>, fallback: string) {
  const [value, setValue] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setValue(null);
    setError(null);
    loader()
      .then((result) => !cancelled && setValue(result))
      .catch((reason) => !cancelled && setError(apiErrorMessage(reason) || fallback));
    return () => {
      cancelled = true;
    };
  }, [loader, reloadKey, fallback]);
  return { value, error, reload: () => setReloadKey((key) => key + 1) };
}

export function InstallerCapabilityGate({
  capability,
  children,
}: {
  capability: (typeof INSTALLER_ACCESS_PERMISSIONS)[number];
  children: ReactNode;
}) {
  const { me } = useSession();
  return hasInstallerCapability(me, capability) ? <>{children}</> : <Navigate to="/projects" replace />;
}

export function InstallerProjectsPage() {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const loader = useMemo(() => () => listProjects({ q: query.trim() || undefined, is_active: true }), [query]);
  const { value: projects, error, reload } = useReloadable(loader, "Não foi possível carregar os projetos atribuídos.");
  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(search), 250);
    return () => window.clearTimeout(timer);
  }, [search]);

  return (
    <>
      <PageHeader title="Projetos atribuídos" subtitle="Instalações associadas ao seu instalador. Esta vista é apenas de consulta." />
      <div className="toolbar" role="search" aria-label="Pesquisar projetos atribuídos">
        <div className="field field--wide">
          <label htmlFor="installer-project-search">Pesquisar</label>
          <input id="installer-project-search" className="input" type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Nome da obra…" />
        </div>
      </div>
      {error && <div className="card"><ErrorState message={error} onRetry={reload} /></div>}
      {!error && !projects && <div className="card"><LoadingState label="A carregar projetos atribuídos…" /></div>}
      {!error && projects && projects.length === 0 && <div className="card"><EmptyState title="Nenhum projeto atribuído" text="Não há projetos no âmbito do seu instalador para estes filtros." /></div>}
      {!error && projects && projects.length > 0 && (
        <div className="grid grid--cards">
          {projects.map((project) => <InstallerProjectCard key={project.id} project={project} />)}
        </div>
      )}
    </>
  );
}

function InstallerProjectCard({ project }: { project: Project }) {
  return (
    <Card title={<Link to={`/projects/${project.id}`}>{project.name}</Link>} icon="folder" tone="brand">
      <div className="stack stack--sm">
        <div className="cluster cluster--between">
          <Badge tone="neutral">{project.lifecycle_status ?? "Sem estado"}</Badge>
          <span className="small muted">{project.status}</span>
        </div>
        <ProgressBar value={project.workflow_progress_percent ?? 0} label={`Progresso de ${project.name}`} />
        {(project.work_start_date || project.work_end_date) && <div className="small muted">Obra: {project.work_start_date ?? "—"} a {project.work_end_date ?? "—"}</div>}
        {project.installer_team_name && <div className="small muted">Equipa: {project.installer_team_name}</div>}
      </div>
    </Card>
  );
}

export function InstallerProjectDetailPage() {
  const { projectId = "" } = useParams();
  const { me } = useSession();
  const [project, setProject] = useState<Project | null>(null);
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const canTasks = hasInstallerCapability(me, "task.view_assigned_installer");

  useEffect(() => {
    let cancelled = false;
    setProject(null);
    setTasks(null);
    setError(null);
    getProject(projectId)
      .then((result) => {
        if (cancelled) return;
        setProject(result);
        if (canTasks) listTasks({ project_id: projectId }).then((items) => !cancelled && setTasks(items)).catch(() => !cancelled && setTasks([]));
      })
      .catch((reason) => !cancelled && setError(reason instanceof ApiError && reason.status === 404 ? "Projeto não encontrado ou fora do seu âmbito." : apiErrorMessage(reason)));
    return () => {
      cancelled = true;
    };
  }, [projectId, canTasks, reloadKey]);

  if (error) return <div className="card"><ErrorState message={error} onRetry={() => setReloadKey((key) => key + 1)} /></div>;
  if (!project) return <div className="card"><LoadingState label="A carregar o projeto…" /></div>;

  return (
    <>
      <PageHeader title={project.name} subtitle="Detalhe do projeto atribuído — consulta sem edição." actions={<Link className="btn btn--ghost" to="/projects">Voltar aos projetos</Link>} />
      <div className="grid grid--2">
        <Card title="Resumo" icon="folder">
          <div className="stack stack--sm">
            <div><strong>Estado:</strong> {project.lifecycle_status ?? "—"}</div>
            <div><strong>Progresso:</strong> <ProgressBar value={project.workflow_progress_percent ?? 0} /></div>
            {project.work_start_date && <div><strong>Obra:</strong> {project.work_start_date} a {project.work_end_date ?? "—"}</div>}
            {project.installer_team_name && <div><strong>Equipa:</strong> {project.installer_team_name}</div>}
          </div>
        </Card>
        {canTasks && <Card title="Tarefas" icon="tasks">
          {tasks === null ? <LoadingState label="A carregar tarefas…" rows={2} /> : tasks.length === 0 ? <EmptyState compact title="Sem tarefas visíveis." /> : <div className="stack stack--sm">{tasks.map((task) => <div key={task.id} className="card__row"><strong>{task.title}</strong><span className="small muted">{task.status}{task.due_date ? ` · ${task.due_date}` : ""}</span></div>)}</div>}
        </Card>}
      </div>
    </>
  );
}

function isoAfter(date: string, days: number): string {
  const value = new Date(`${date}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() + days);
  return value.toISOString().slice(0, 10);
}

export function InstallerWorksPage() {
  const [from, setFrom] = useState(todayIsoLisbon());
  const [to, setTo] = useState(() => isoAfter(todayIsoLisbon(), 30));
  const loader = useMemo(() => () => getWorksCalendar({ from, to }), [from, to]);
  const { value: data, error, reload } = useReloadable(loader, "Não foi possível carregar o calendário de obras.");
  return (
    <>
      <PageHeader title="Calendário de obras" subtitle="Obras atribuídas ao seu instalador. A agenda é apenas de consulta." />
      <div className="toolbar">
        <div className="field"><label htmlFor="installer-works-from">De</label><input id="installer-works-from" className="input" type="date" value={from} onChange={(event) => setFrom(event.target.value)} /></div>
        <div className="field"><label htmlFor="installer-works-to">Até</label><input id="installer-works-to" className="input" type="date" value={to} onChange={(event) => setTo(event.target.value)} /></div>
      </div>
      {error && <div className="card"><ErrorState message={error} onRetry={reload} /></div>}
      {!error && !data && <div className="card"><LoadingState label="A carregar obras…" /></div>}
      {!error && data && <>
        <Alert tone="info">Modo consulta: não é possível arrastar, redimensionar, guardar vistas ou alterar preferências.</Alert>
        <div className="grid grid--stats"><Card title="Obras" icon="columns"><strong>{data.summary.works}</strong></Card><Card title="Conflitos" icon="alert"><strong>{data.summary.conflicts}</strong></Card><Card title="Por calendarizar" icon="calendar"><strong>{data.summary.unscheduled}</strong></Card></div>
        {data.works.length === 0 ? <div className="card"><EmptyState title="Nenhuma obra no período" /></div> : <div className="grid grid--cards">{data.works.map((work) => <Card key={`${work.project_id}-${work.work_start_date}`} title={<Link to={`/projects/${work.project_id}`}>{work.name}</Link>} icon="columns"><div className="stack stack--sm"><div>{work.work_start_date ?? "—"} a {work.work_end_date ?? "—"}</div><div className="small muted">{work.installer_team_name ?? work.installer_name ?? "Equipa atribuída"}{work.conflict ? " · conflito de datas" : ""}</div></div></Card>)}</div>}
      </>}
    </>
  );
}

function normaliseTeams(response: InstallerAccessTeamsResponse): InstallerAccessInstaller[] {
  if (Array.isArray(response)) return response;
  const byInstaller = new Map<string, InstallerAccessInstaller>();
  for (const installer of response.installers) byInstaller.set(installer.id, { ...installer, teams: [] });
  for (const team of response.teams) {
    const installer = byInstaller.get(team.installer_id);
    if (installer) installer.teams.push(team);
  }
  return [...byInstaller.values()];
}

export function InstallerTeamsPage() {
  const loader = useMemo(() => () => listInstallerAccessTeams(), []);
  const { value, error, reload } = useReloadable(loader, "Não foi possível carregar as equipas associadas.");
  const installers = value ? normaliseTeams(value) : [];
  return (
    <>
      <PageHeader title="Equipas" subtitle="Instaladores e equipas ligados às obras no seu âmbito." />
      {error && <div className="card"><ErrorState message={error} onRetry={reload} /></div>}
      {!error && !value && <div className="card"><LoadingState label="A carregar equipas…" /></div>}
      {!error && value && installers.length === 0 && <div className="card"><EmptyState title="Nenhuma equipa associada" /></div>}
      {!error && value && installers.map((installer) => <Card key={installer.id} title={installer.name} icon="wrench"><div className="stack stack--sm">{installer.teams.length === 0 ? <span className="muted">Sem equipas registadas.</span> : installer.teams.map((team) => <div key={team.id} className="cluster cluster--between"><span>{team.name}</span><Badge tone={team.is_active ? "success" : "neutral"}>{team.is_active ? "Ativa" : "Inativa"}</Badge></div>)}</div></Card>)}
    </>
  );
}

export function InstallerInventoryPage() {
  const [params, setParams] = useSearchParams();
  const projectId = params.get("project_id") || undefined;
  const [offset, setOffset] = useState(0);
  const limit = 100;
  const loader = useMemo(() => () => listInstallerInventory({ projectId, limit, offset }), [projectId, offset]);
  const { value, error, reload } = useReloadable(loader, "Não foi possível carregar o inventário atribuído.");
  const next = value ? offset + limit < value.total : false;
  function setProject(value: string) {
    setOffset(0);
    setParams((previous) => {
      const nextParams = new URLSearchParams(previous);
      if (value) nextParams.set("project_id", value); else nextParams.delete("project_id");
      return nextParams;
    }, { replace: true });
  }
  return (
    <>
      <PageHeader title="Inventário por projeto" subtitle="Quantidades e localizações do inventário associado. Sem stock central, preços ou movimentos globais." />
      {projectId && <div className="toolbar"><div className="field"><label htmlFor="installer-inventory-project">Projeto</label><input id="installer-inventory-project" className="input" value={projectId} onChange={(event) => setProject(event.target.value)} /></div></div>}
      {error && <div className="card"><ErrorState message={error} onRetry={reload} /></div>}
      {!error && !value && <div className="card"><LoadingState label="A carregar inventário…" /></div>}
      {!error && value && value.items.length === 0 && <div className="card"><EmptyState title="Sem inventário associado" /></div>}
      {!error && value && value.items.length > 0 && <Card title={`${value.total} artigo(s) no âmbito`} icon="database" className="installer-inventory-card"><div style={{ overflowX: "auto", maxWidth: "100%" }}><table><thead><tr><th>Projeto</th><th>Artigo</th><th>Unidade</th><th>Necessário</th><th>Reservado</th><th>Consumido</th><th>Entregue</th><th>Localização</th></tr></thead><tbody>{value.items.map((item, index) => <tr key={`${item.project_id}-${item.article_name}-${index}`}><td>{item.project_name ?? item.project_id}</td><td>{item.article_name}</td><td>{item.unit}</td><td>{formatQuantity(item.required_quantity, item.unit)}</td><td>{formatQuantity(item.reserved_quantity, item.unit)}</td><td>{formatQuantity(item.consumed_quantity, item.unit)}</td><td>{formatQuantity(item.delivered_quantity, item.unit)}</td><td>{item.locations.length ? item.locations.map((location) => location.label).join(", ") : "—"}</td></tr>)}</tbody></table></div><div className="cluster cluster--between" style={{ marginTop: 16 }}><span className="small muted">{offset + 1}–{Math.min(offset + limit, value.total)} de {value.total}</span><span className="cluster"><button type="button" className="btn btn--ghost" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>Anterior</button><button type="button" className="btn btn--ghost" disabled={!next} onClick={() => setOffset(offset + limit)}>Seguinte</button></span></div></Card>}
    </>
  );
}

export function InstallerTimeBankPage() {
  const loader = useMemo(() => () => getTimeBankSummary({ year: Number(todayIsoLisbon().slice(0, 4)) }), []);
  const { value: summary, error: summaryError, reload } = useReloadable(loader, "Não foi possível carregar o seu Banco de Horas.");
  const [entries, setEntries] = useState<Awaited<ReturnType<typeof listTimeBankEntries>> | null>(null);
  const [adjustments, setAdjustments] = useState<Awaited<ReturnType<typeof listTimeBankAdjustments>> | null>(null);
  const [ledgerError, setLedgerError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setEntries(null); setAdjustments(null); setLedgerError(null);
    listTimeBankEntries({ limit: 100 }).then((value) => !cancelled && setEntries(value)).catch((reason) => !cancelled && setLedgerError(apiErrorMessage(reason)));
    listTimeBankAdjustments({ limit: 100 }).then((value) => !cancelled && setAdjustments(value)).catch((reason) => !cancelled && setLedgerError(apiErrorMessage(reason)));
    return () => { cancelled = true; };
  }, []);
  const person = summary?.people[0];
  return (
    <>
      <PageHeader title="Banco de Horas" subtitle="O seu saldo e histórico. Esta vista não permite criar, ajustar, importar ou anular movimentos." />
      {(summaryError || ledgerError) && <div className="card"><ErrorState message={summaryError ?? ledgerError ?? "Não foi possível carregar o Banco de Horas."} onRetry={reload} /></div>}
      {!summaryError && !summary && <div className="card"><LoadingState label="A carregar o seu Banco de Horas…" /></div>}
      {summary && <>
        <div className="grid grid--stats"><Card title="Saldo" icon="clock"><strong>{formatSignedTimeBankDuration(person?.balance_seconds)}</strong></Card><Card title="Período" icon="calendar"><strong>{formatSignedTimeBankDuration(person?.period_seconds)}</strong></Card><Card title="A rever" icon="alert"><strong>{person?.needs_review_count ?? 0}</strong></Card></div>
        <Card title="Histórico" icon="clock">{entries === null || adjustments === null ? <LoadingState label="A carregar histórico…" rows={2} /> : entries.items.length === 0 && adjustments.items.length === 0 ? <EmptyState compact title="Sem movimentos registados." /> : <div className="stack stack--sm">{entries.items.map((entry) => <div key={entry.id} className="card__row"><span>{entry.work_date}</span><strong>{formatSignedTimeBankDuration(entry.balance_seconds)}</strong><span className="small muted">{entry.calculation_mode}</span></div>)}{adjustments.items.map((adjustment) => <div key={adjustment.id} className="card__row"><span>{adjustment.effective_date}</span><strong>{formatSignedTimeBankDuration(adjustment.delta_seconds)}</strong><span className="small muted">{adjustment.kind}</span></div>)}</div>}</Card>
      </>}
    </>
  );
}

export function InstallerTasksPage() {
  const loader = useMemo(() => () => listTasks(), []);
  const { value: tasks, error, reload } = useReloadable(loader, "Não foi possível carregar as tarefas atribuídas.");
  return <><PageHeader title="Tarefas" subtitle="Tarefas dos projetos no seu âmbito. Consulta sem alterações." />{error && <div className="card"><ErrorState message={error} onRetry={reload} /></div>}{!error && !tasks && <div className="card"><LoadingState label="A carregar tarefas…" /></div>}{!error && tasks && (tasks.length === 0 ? <div className="card"><EmptyState title="Nenhuma tarefa visível" /></div> : <Card title={`${tasks.length} tarefa(s)`} icon="tasks"><div className="stack stack--sm">{tasks.map((task) => <div key={task.id} className="card__row"><div><strong>{task.title}</strong><div className="small muted">{task.project_name ?? task.project_id}{task.due_date ? ` · ${task.due_date}` : ""}</div></div><Badge tone={task.status === "done" ? "success" : task.status === "blocked" ? "danger" : "neutral"}>{task.status}</Badge></div>)}</div></Card>)}</>;
}
