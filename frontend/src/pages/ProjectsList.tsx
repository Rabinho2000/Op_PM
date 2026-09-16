import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  listPeople,
  listProjects,
  Person,
  Project,
  PROJECT_STATUS_LABELS,
  ProjectFilters,
  ProjectStatus,
} from "../api/client";
import Icon from "../components/Icon";
import { Avatar, Badge, EmptyState, ErrorState, LoadingState, PageHeader, ProgressBar } from "../components/ui";
import { formatDatePt, relativeDayLabel, todayIsoLisbon } from "../utils/dates";
import { PROJECT_STATUS_TONES } from "../utils/labels";

type ActiveFilter = "active" | "inactive" | "all";

interface Filters {
  search: string;
  status: ProjectStatus | "";
  pm: string;
  active: ActiveFilter;
  startFrom: string;
  startTo: string;
}

const EMPTY_FILTERS: Filters = { search: "", status: "", pm: "", active: "active", startFrom: "", startTo: "" };

// Todos os filtros são aplicados pelo servidor (GET /api/projects) — a
// visibilidade (PM só vê os seus) também.
export function toApiFilters(f: Filters): ProjectFilters {
  return {
    q: f.search.trim() || undefined,
    status: f.status || undefined,
    pm_person_id: f.pm || undefined,
    is_active: f.active === "all" ? undefined : f.active === "active",
    start_from: f.startFrom || undefined,
    start_to: f.startTo || undefined,
  };
}

function missingLabels(p: Project): string[] {
  return [
    !p.has_pm && "sem PM",
    !p.has_email && "sem email",
    !p.has_contact && "sem contacto",
    !p.has_coordinates && "sem coordenadas",
  ].filter((x): x is string => Boolean(x));
}

export default function ProjectsList() {
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    listPeople()
      .then((all) => setPeople(all))
      .catch(() => setPeople([]));
  }, []);

  useEffect(() => {
    const handle = window.setTimeout(() => setDebouncedSearch(filters.search), 250);
    return () => window.clearTimeout(handle);
  }, [filters.search]);

  const { status, pm, active, startFrom, startTo } = filters;
  useEffect(() => {
    let cancelled = false;
    setError(null);
    setProjects(null);
    listProjects(toApiFilters({ search: debouncedSearch, status, pm, active, startFrom, startTo }))
      .then((result) => !cancelled && setProjects(result))
      .catch((e) => !cancelled && setError(e instanceof ApiError ? e.detail : "Não foi possível contactar o servidor."));
    return () => {
      cancelled = true;
    };
  }, [debouncedSearch, status, pm, active, startFrom, startTo, reloadKey]);

  const set = <K extends keyof Filters>(key: K, value: Filters[K]) => setFilters((f) => ({ ...f, [key]: value }));
  const hasFilters = JSON.stringify(filters) !== JSON.stringify(EMPTY_FILTERS);
  const today = todayIsoLisbon();

  return (
    <>
      <PageHeader
        title="Projetos"
        subtitle="Estado, progresso e próximos passos de cada instalação."
      />

      <form className="toolbar" role="search" aria-label="Filtros de projetos" onSubmit={(e) => e.preventDefault()}>
        <div className="field field--wide">
          <label htmlFor="f-search">Pesquisar</label>
          <div className="search">
            <Icon name="search" size={16} />
            <input
              id="f-search"
              className="input"
              type="search"
              placeholder="Projeto, cliente ou contacto…"
              value={filters.search}
              onChange={(e) => set("search", e.target.value)}
            />
          </div>
        </div>
        <div className="field">
          <label htmlFor="f-status">Estado</label>
          <select
            id="f-status"
            className="select"
            value={filters.status}
            onChange={(e) => set("status", e.target.value as ProjectStatus | "")}
          >
            <option value="">Todos os estados</option>
            {(Object.keys(PROJECT_STATUS_LABELS) as ProjectStatus[]).map((s) => (
              <option key={s} value={s}>
                {PROJECT_STATUS_LABELS[s]}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="f-pm">PM</label>
          <select id="f-pm" className="select" value={filters.pm} onChange={(e) => set("pm", e.target.value)}>
            <option value="">Todos os PM</option>
            {people.map((p) => (
              <option key={p.id} value={p.id}>
                {p.display_name}
                {p.is_active ? "" : " (inativo)"}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="f-from">Início a partir de</label>
          <input
            id="f-from"
            className="input"
            type="date"
            value={filters.startFrom}
            onChange={(e) => set("startFrom", e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="f-to">Início até</label>
          <input id="f-to" className="input" type="date" value={filters.startTo} onChange={(e) => set("startTo", e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="f-active">Situação</label>
          <select
            id="f-active"
            className="select"
            value={filters.active}
            onChange={(e) => set("active", e.target.value as ActiveFilter)}
          >
            <option value="active">Ativos</option>
            <option value="inactive">Inativos</option>
            <option value="all">Todos</option>
          </select>
        </div>
        {hasFilters && (
          <div className="toolbar__end">
            <button type="button" className="btn btn--ghost" onClick={() => setFilters(EMPTY_FILTERS)}>
              <Icon name="x" size={16} /> Limpar filtros
            </button>
          </div>
        )}
      </form>

      <div className="card">
        {error && <ErrorState message={error} onRetry={() => setReloadKey((k) => k + 1)} />}
        {!error && projects === null && <LoadingState label="A carregar projetos…" rows={5} />}
        {!error && projects?.length === 0 && (
          <EmptyState
            icon="folder"
            title="Nenhum projeto encontrado"
            text={
              hasFilters
                ? "Nenhum projeto corresponde aos filtros escolhidos."
                : "Não há projetos visíveis para o seu perfil."
            }
            action={
              hasFilters ? (
                <button type="button" className="btn btn--sm" onClick={() => setFilters(EMPTY_FILTERS)}>
                  Limpar filtros
                </button>
              ) : undefined
            }
          />
        )}
        {!error && projects && projects.length > 0 && (
          <>
            <div className="card__header" style={{ paddingBottom: 12 }}>
              <span className="small muted" aria-live="polite">
                {projects.length} projeto{projects.length === 1 ? "" : "s"}
              </span>
            </div>
            <div className="table-wrap">
              <table className="table">
                <caption className="sr-only">Lista de projetos</caption>
                <thead>
                  <tr>
                    <th scope="col" className="col-main">Projeto</th>
                    <th scope="col">PM</th>
                    <th scope="col">Estado</th>
                    <th scope="col">Progresso</th>
                    <th scope="col">Próxima tarefa</th>
                    <th scope="col">Atrasadas</th>
                    <th scope="col">Avisos</th>
                  </tr>
                </thead>
                <tbody>
                  {projects.map((p) => {
                    const missing = missingLabels(p);
                    const dueOverdue = p.next_task_due_date !== null && p.next_task_due_date < today;
                    return (
                      <tr key={p.id} className={p.overdue_tasks_count > 0 ? "row--danger" : undefined}>
                        <td>
                          <Link to={`/projects/${p.id}`} className="cell-title">
                            {p.name}
                          </Link>
                          <span className="cell-sub">
                            {p.client_name ?? "Cliente por identificar"}
                            {p.start_date && ` · início ${formatDatePt(p.start_date)}`}
                          </span>
                        </td>
                        <td className="nowrap">
                          {p.pm_display_name ? (
                            <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                              <Avatar name={p.pm_display_name} small />
                              {p.pm_display_name}
                            </span>
                          ) : (
                            <Badge tone="warning">Sem PM</Badge>
                          )}
                        </td>
                        <td>
                          <Badge tone={PROJECT_STATUS_TONES[p.status]} dot>
                            {PROJECT_STATUS_LABELS[p.status]}
                          </Badge>
                          {!p.is_active && (
                            <div style={{ marginTop: 4 }}>
                              <Badge>Inativo</Badge>
                            </div>
                          )}
                        </td>
                        <td style={{ minWidth: 150 }}>
                          <ProgressBar value={p.workflow_progress_percent} label={`Progresso de ${p.name}`} />
                        </td>
                        <td>
                          {p.next_task_title ? (
                            <>
                              <span>{p.next_task_title}</span>
                              <span className={`cell-sub ${dueOverdue ? "text-danger" : ""}`}>
                                {p.next_task_due_date
                                  ? `prazo ${formatDatePt(p.next_task_due_date)} (${relativeDayLabel(p.next_task_due_date, today)})`
                                  : "sem prazo definido"}
                              </span>
                            </>
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                        <td>
                          {p.overdue_tasks_count > 0 ? (
                            <Badge tone="danger">{p.overdue_tasks_count}</Badge>
                          ) : (
                            <span className="muted">0</span>
                          )}
                        </td>
                        <td>
                          <div className="badges">
                            {p.photos_pending_warning && (
                              <Badge tone="warning">
                                <Icon name="camera" size={12} /> Fotos pendentes
                              </Badge>
                            )}
                            {missing.map((m) => (
                              <Badge key={m} tone="neutral">
                                {m}
                              </Badge>
                            ))}
                            {!p.photos_pending_warning && missing.length === 0 && <span className="muted">—</span>}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </>
  );
}
