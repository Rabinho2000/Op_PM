import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
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
import {
  createProjectListView,
  deleteProjectListView,
  getProjectListPreferences,
  listProjectListViews,
  ProjectListColumn,
  ProjectListConfig,
  ProjectListFilters,
  ProjectListRowOptions,
  ProjectListView,
  updateProjectListPreferences,
  updateProjectListView,
} from "../api/projectListViews";
import Icon from "../components/Icon";
import CreateProjectModal from "../components/CreateProjectModal";
import ProjectDeletionModal from "../components/ProjectDeletionModal";
import LifecycleMultiSelect from "../components/LifecycleMultiSelect";
import { LifecycleBadge, LifecycleStatusControl, useLifecycleStatuses } from "../components/LifecycleStatus";
import PmInlineSelect from "../components/PmInlineSelect";
import { Badge, EmptyState, ErrorState, LoadingState, PageHeader, ProgressBar } from "../components/ui";
import { useToast } from "../components/Toast";
import { useSession } from "../session/SessionContext";
import { formatDatePt, relativeDayLabel, todayIsoLisbon } from "../utils/dates";
import { PAYMENT_MILESTONE_LABELS, PAYMENT_MILESTONE_ORDER, PROJECT_STATUS_TONES } from "../utils/labels";
import { lifecycleFromParams, lifecycleToParams, lifecycleView, IN_PROGRESS_LIFECYCLE } from "../utils/projectFilters";
import { groupProjectsByLifecycle } from "../utils/projectGrouping";
import {
  DEFAULT_PROJECT_LIST_COLUMNS,
  defaultProjectListConfig,
  defaultProjectListFilters,
  defaultProjectListRowOptions,
  normalizeProjectListConfig,
  PROJECT_LIST_COLUMN_LABELS,
  PROJECT_LIST_SORT_LABELS,
  PROJECT_LIST_COLUMN_ORDER,
  sortProjects,
} from "../utils/projectListConfig";
import "./ProjectsList.css";

type ActiveFilter = ProjectListFilters["active"];
type Filters = ProjectListFilters;

const EMPTY_FILTERS: Filters = defaultProjectListFilters();
const PROJECT_LIST_QUERY_KEYS = ["search", "status", "estado", "pm", "active", "startFrom", "startTo", "sort_by", "sort_direction"] as const;

// Todos os filtros são aplicados pelo servidor (GET /api/projects) — a
// visibilidade (PM só vê os seus) também.
export function toApiFilters(f: Filters): ProjectFilters {
  return {
    q: f.search.trim() || undefined,
    status: f.status || undefined,
    lifecycle_status: f.lifecycle.length > 0 ? f.lifecycle : undefined,
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

function projectCountLabel(count: number): string {
  return `${count} ${count === 1 ? "projeto" : "projetos"}`;
}

function errorDetail(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

function hasProjectListQuery(params: URLSearchParams): boolean {
  return PROJECT_LIST_QUERY_KEYS.some((key) => params.has(key));
}

function parseStatus(value: string | null): ProjectStatus | "" {
  return value && Object.prototype.hasOwnProperty.call(PROJECT_STATUS_LABELS, value) ? (value as ProjectStatus) : "";
}

function configFromUrl(params: URLSearchParams): ProjectListConfig {
  const fallback = defaultProjectListConfig();
  const rawActive = params.get("active");
  const active: ActiveFilter = rawActive === "inactive" || rawActive === "all" ? rawActive : "active";
  const rawSort = params.get("sort_by");
  const sortBy = rawSort === "start_date" || rawSort === "power_kwp" || rawSort === "created_at" ? rawSort : "name";
  const sortDirection = params.get("sort_direction") === "desc" ? "desc" : "asc";
  return {
    ...fallback,
    filters: {
      ...fallback.filters,
      search: params.get("search") ?? "",
      status: parseStatus(params.get("status")),
      lifecycle: params.has("estado") ? lifecycleFromParams(params.getAll("estado")) : [...IN_PROGRESS_LIFECYCLE],
      pm: params.get("pm") ?? "",
      active,
      startFrom: params.get("startFrom") ?? "",
      startTo: params.get("startTo") ?? "",
    },
    sort_by: sortBy,
    sort_direction: sortDirection,
  };
}

function paramsForConfig(params: URLSearchParams, config: ProjectListConfig): URLSearchParams {
  const next = new URLSearchParams(params);
  for (const key of PROJECT_LIST_QUERY_KEYS) next.delete(key);
  if (config.filters.search) next.set("search", config.filters.search);
  if (config.filters.status) next.set("status", config.filters.status);
  lifecycleToParams(config.filters.lifecycle).forEach((value) => next.append("estado", value));
  if (config.filters.pm) next.set("pm", config.filters.pm);
  if (config.filters.active !== "active") next.set("active", config.filters.active);
  if (config.filters.startFrom) next.set("startFrom", config.filters.startFrom);
  if (config.filters.startTo) next.set("startTo", config.filters.startTo);
  if (config.sort_by !== "name") next.set("sort_by", config.sort_by);
  if (config.sort_direction !== "asc") next.set("sort_direction", config.sort_direction);
  return next;
}

function ColumnConfigurator({
  columns,
  availableColumns,
  rowOptions,
  onChange,
  onRowOptionsChange,
  onRestore,
}: {
  columns: ProjectListColumn[];
  availableColumns: ProjectListColumn[];
  rowOptions: ProjectListRowOptions;
  onChange: (columns: ProjectListColumn[]) => void;
  onRowOptionsChange: (options: ProjectListRowOptions) => void;
  onRestore: () => void;
}) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const close = () => {
    setOpen(false);
    triggerRef.current?.focus();
  };

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) close();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const toggleColumn = (column: ProjectListColumn, checked: boolean) => {
    if (checked) onChange(columns.includes(column) ? columns : [...columns, column]);
    else if (columns.length > 1) onChange(columns.filter((current) => current !== column));
  };

  const moveColumn = (column: ProjectListColumn, offset: -1 | 1) => {
    const index = columns.indexOf(column);
    const target = index + offset;
    if (index < 0 || target < 0 || target >= columns.length) return;
    const next = [...columns];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  };

  return (
    <div ref={containerRef} className="projects-list__column-menu">
      <button
        ref={triggerRef}
        type="button"
        className="btn btn--sm btn--ghost"
        aria-expanded={open}
        aria-controls="project-list-column-dialog"
        onClick={() => setOpen((current) => !current)}
      >
        Personalizar lista
      </button>
      {open && (
        <div id="project-list-column-dialog" className="projects-list__column-dialog" role="dialog" aria-label="Personalizar lista">
          <div className="projects-list__column-dialog-header">
            <strong>Colunas visíveis</strong>
            <button type="button" className="btn btn--sm btn--ghost" onClick={close}>
              Fechar personalização da lista
            </button>
          </div>
          <div className="projects-list__column-options">
            {availableColumns.map((column) => {
              const index = columns.indexOf(column);
              const visible = index >= 0;
              const label = PROJECT_LIST_COLUMN_LABELS[column];
              return (
                <div key={column} className="projects-list__column-option">
                  <label className="checkbox">
                    <input
                      type="checkbox"
                      aria-label={`Mostrar ${label}`}
                      checked={visible}
                      disabled={visible && columns.length === 1}
                      onChange={(event) => toggleColumn(column, event.target.checked)}
                    />
                    {label}
                    {visible && columns.length === 1 && <span className="small muted">mínimo 1</span>}
                  </label>
                  {visible && (
                    <span className="projects-list__column-order">
                      <button
                        type="button"
                        className="btn btn--sm btn--ghost"
                        aria-label={`Subir coluna ${label}`}
                        disabled={index === 0}
                        onClick={() => moveColumn(column, -1)}
                      >
                        ↑
                      </button>
                      <button
                        type="button"
                        className="btn btn--sm btn--ghost"
                        aria-label={`Descer coluna ${label}`}
                        disabled={index === columns.length - 1}
                        onClick={() => moveColumn(column, 1)}
                      >
                        ↓
                      </button>
                    </span>
                  )}
                </div>
              );
            })}
          </div>
          <button type="button" className="btn btn--sm btn--ghost" onClick={onRestore}>
            Restaurar colunas padrão
          </button>
          <fieldset className="projects-list__row-options">
            <legend>Opções da linha</legend>
            <label className="checkbox">
              <input
                type="checkbox"
                aria-label="Mostrar ações na linha"
                checked={rowOptions.show_row_actions}
                onChange={(event) => onRowOptionsChange({ ...rowOptions, show_row_actions: event.target.checked })}
              />
              Mostrar ações na linha
            </label>
            <label className="checkbox">
              <input
                type="checkbox"
                aria-label="Mostrar etiquetas de aviso"
                checked={rowOptions.show_warning_tags}
                onChange={(event) => onRowOptionsChange({ ...rowOptions, show_warning_tags: event.target.checked })}
              />
              Mostrar etiquetas de aviso
            </label>
            <label className="checkbox">
              <input
                type="checkbox"
                aria-label="Controlos editáveis inline"
                checked={rowOptions.inline_controls}
                onChange={(event) => onRowOptionsChange({ ...rowOptions, inline_controls: event.target.checked })}
              />
              Controlos editáveis inline (PM e estado)
            </label>
          </fieldset>
          <button
            type="button"
            className="btn btn--sm btn--ghost"
            onClick={() => onRowOptionsChange(defaultProjectListRowOptions())}
          >
            Restaurar opções da linha padrão
          </button>
        </div>
      )}
    </div>
  );
}

function renderProjectCell(
  column: ProjectListColumn,
  project: Project,
  groupStatus: string | null,
  people: Person[],
  statuses: ReturnType<typeof useLifecycleStatuses>,
  today: string,
  onChanged: (updated: Project) => void,
  onDelete: (project: Project) => void,
  origin: { pathname: string; search: string; hash: string },
  rowOptions: ProjectListRowOptions,
) {
  const missing = missingLabels(project);
  const dueOverdue = project.next_task_due_date !== null && project.next_task_due_date < today;
  switch (column) {
    case "project":
      return (
        <>
          <Link
            to={`/projects/${project.id}`}
            state={{ from: { pathname: origin.pathname, search: origin.search, hash: origin.hash } }}
            className="cell-title"
          >
            {project.name}
          </Link>
          <span className="cell-sub">
            {project.client_name ?? "Cliente por identificar"}
            {project.start_date && ` · início ${formatDatePt(project.start_date)}`}
            {project.installer_name && ` · ${project.installer_name}${project.installer_team_name ? ` / ${project.installer_team_name}` : ""}`}
          </span>
          {rowOptions.show_row_actions && project.can_delete === true && (
            <div style={{ marginTop: 6 }}>
              <button type="button" className="btn btn--sm btn--danger" onClick={() => onDelete(project)}>
                Apagar projeto
              </button>
            </div>
          )}
        </>
      );
    case "pm":
      return rowOptions.inline_controls ? (
        <PmInlineSelect project={project} people={people} onChanged={onChanged} />
      ) : <span>{project.pm_display_name ?? "Sem PM"}</span>;
    case "lifecycle":
      return rowOptions.inline_controls ? (
        <>
          <LifecycleStatusControl project={project} statuses={statuses} onChanged={onChanged} />
          {!project.is_active && (
            <div style={{ marginTop: 4 }}>
              <Badge>Inativo</Badge>
            </div>
          )}
        </>
      ) : (
        <>
          <span>{project.lifecycle_status ? statuses.find((status) => status.code === project.lifecycle_status)?.label ?? project.lifecycle_status : "Sem estado"}</span>
          {!project.is_active && <span className="cell-sub">Inativo</span>}
        </>
      );
    case "progress":
      return (
        <>
          <div style={{ marginBottom: 4 }}>
            <Badge tone={PROJECT_STATUS_TONES[project.status]}>{PROJECT_STATUS_LABELS[project.status]}</Badge>
          </div>
          <ProgressBar value={project.workflow_progress_percent} label={`Progresso de ${project.name}`} />
        </>
      );
    case "next_task":
      return project.next_task_title ? (
        <>
          <span>{project.next_task_title}</span>
          <span className={`cell-sub ${dueOverdue ? "text-danger" : ""}`}>
            {project.next_task_due_date
              ? `prazo ${formatDatePt(project.next_task_due_date)} (${relativeDayLabel(project.next_task_due_date, today)})`
              : "sem prazo definido"}
          </span>
        </>
      ) : (
        <span className="muted">—</span>
      );
    case "overdue":
      return project.overdue_tasks_count > 0 ? <Badge tone="danger">{project.overdue_tasks_count}</Badge> : <span className="muted">0</span>;
    case "warnings":
      if (!rowOptions.show_warning_tags) return <span className="muted">—</span>;
      return (
        <div className="badges">
          {project.photos_pending_warning && (
            <Badge tone="warning">
              <Icon name="camera" size={12} /> Fotos pendentes
            </Badge>
          )}
          {missing.map((missingLabel) => (
            <Badge key={missingLabel} tone="neutral">
              {missingLabel}
            </Badge>
          ))}
          {!project.photos_pending_warning && missing.length === 0 && <span className="muted">—</span>}
        </div>
      );
    case "payments":
      return (
        <span className="payment-indicators">
          {PAYMENT_MILESTONE_ORDER.map((milestone) => {
            const received = project.payments?.[milestone] ?? false;
            const label = PAYMENT_MILESTONE_LABELS[milestone];
            const state = received ? "recebido" : "não recebido";
            return (
              <span
                key={milestone}
                className={`payment-indicators__item${received ? " payment-indicators__item--received" : ""}`}
                role="img"
                title={`${label}: ${state}`}
                aria-label={`${label}: ${state}`}
              >
                {received ? "✓" : "○"}
              </span>
            );
          })}
        </span>
      );
    case "installer":
      return project.installer_name ? (
        <>
          <span>{project.installer_name}</span>
          {project.installer_team_name && <span className="cell-sub">{project.installer_team_name}</span>}
        </>
      ) : (
        <span className="muted">—</span>
      );
    case "start_date":
      return project.start_date ? formatDatePt(project.start_date) : <span className="muted">—</span>;
    case "power_kwp":
      return project.power_kwp === null ? <span className="muted">—</span> : `${project.power_kwp} kWp`;
    case "client":
      return project.client_name?.trim() ? project.client_name : <span className="muted">—</span>;
    case "address":
      return project.address?.trim() ? project.address : <span className="muted">—</span>;
    case "contact": {
      const contact = project.client_contact?.trim();
      const email = project.client_email?.trim();
      if (!contact && !email) return <span className="muted">—</span>;
      return (
        <>
          {contact && <span>{contact}</span>}
          {email && <span className="cell-sub">{email}</span>}
        </>
      );
    }
    case "notes":
      return project.notes?.trim() ? (
        <span className="projects-list__notes" title={project.notes} aria-label={project.notes} tabIndex={0}>
          {project.notes}
        </span>
      ) : <span className="muted">—</span>;
  }
}

export default function ProjectsList() {
  const { can, me } = useSession();
  const canViewPayments = can("payment.view");
  const location = useLocation();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const paramsRef = useRef(params);
  paramsRef.current = params;
  const accountKey = me?.user_id ?? me?.email ?? "anonymous";
  const accountKeyRef = useRef(accountKey);
  accountKeyRef.current = accountKey;
  const initialUrlView = hasProjectListQuery(params);
  const [config, setConfig] = useState<ProjectListConfig>(() => (initialUrlView ? configFromUrl(params) : defaultProjectListConfig()));
  const configRef = useRef(config);
  configRef.current = config;
  const [viewReady, setViewReady] = useState(initialUrlView);
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [deletingProject, setDeletingProject] = useState<Project | null>(null);
  const [creatingProject, setCreatingProject] = useState(false);
  const [people, setPeople] = useState<Person[]>([]);
  const lifecycleStatuses = useLifecycleStatuses();
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(() => new Set());
  const { notify } = useToast();
  const [preferenceStatus, setPreferenceStatus] = useState<"loading" | "ready" | "error">(initialUrlView ? "ready" : "loading");
  const [preferenceError, setPreferenceError] = useState<string | null>(null);
  const [preferenceSaveError, setPreferenceSaveError] = useState<string | null>(null);
  const [preferenceSaving, setPreferenceSaving] = useState(false);
  const [preferenceSaved, setPreferenceSaved] = useState(false);
  const [preferenceReloadKey, setPreferenceReloadKey] = useState(0);
  const [savedViews, setSavedViews] = useState<ProjectListView[]>([]);
  const [savedViewsLoading, setSavedViewsLoading] = useState(true);
  const [savedViewsError, setSavedViewsError] = useState<string | null>(null);
  const [savedViewsActionError, setSavedViewsActionError] = useState<string | null>(null);
  const [savedViewsSaving, setSavedViewsSaving] = useState(false);
  const [savedViewsManagingId, setSavedViewsManagingId] = useState<string | null>(null);
  const [selectedSavedViewId, setSelectedSavedViewId] = useState("");
  const [savedViewsReloadKey, setSavedViewsReloadKey] = useState(0);
  const userInteracted = useRef(false);
  const preferenceAccountRef = useRef<string | null>(null);
  const preferenceRequestRef = useRef(0);
  const lastWrittenParams = useRef(params.toString());
  const lastObservedParams = useRef(params.toString());

  useEffect(() => {
    listPeople()
      .then((all) => setPeople(all))
      .catch(() => setPeople([]));
  }, []);

  useEffect(() => {
    const handle = window.setTimeout(() => setDebouncedSearch(config.filters.search), 250);
    return () => window.clearTimeout(handle);
  }, [config.filters.search]);

  useEffect(() => {
    const signature = params.toString();
    if (signature === lastObservedParams.current) return;
    lastObservedParams.current = signature;
    if (signature === lastWrittenParams.current) return;
    userInteracted.current = true;
    setConfig(hasProjectListQuery(params) ? configFromUrl(params) : defaultProjectListConfig());
    setViewReady(true);
    setPreferenceSaved(false);
  }, [params]);

  useEffect(() => {
    let cancelled = false;
    const requestId = ++preferenceRequestRef.current;
    const requestAccountKey = accountKey;
    const currentParams = paramsRef.current;
    const explicitUrl = hasProjectListQuery(currentParams);
    const accountChanged = preferenceAccountRef.current !== accountKey;
    if (accountChanged) {
      preferenceAccountRef.current = accountKey;
      userInteracted.current = false;
      if (explicitUrl) {
        setConfig(configFromUrl(currentParams));
        setViewReady(true);
      } else {
        setConfig(defaultProjectListConfig());
        setViewReady(false);
      }
    }
    setPreferenceStatus("loading");
    setPreferenceError(null);
    getProjectListPreferences()
      .then((response) => {
        if (cancelled || requestId !== preferenceRequestRef.current || accountKeyRef.current !== requestAccountKey) return;
        if (!explicitUrl && !userInteracted.current) setConfig(normalizeProjectListConfig(response.config));
        setViewReady(true);
        setPreferenceStatus("ready");
      })
      .catch((reason) => {
        if (cancelled || requestId !== preferenceRequestRef.current || accountKeyRef.current !== requestAccountKey) return;
        setViewReady(true);
        setPreferenceStatus("error");
        setPreferenceError(errorDetail(reason, "Não foi possível carregar a preferência de abertura."));
      });
    return () => {
      cancelled = true;
    };
  }, [accountKey, preferenceReloadKey]);

  useEffect(() => {
    let cancelled = false;
    setSavedViews([]);
    setSelectedSavedViewId("");
    setSavedViewsLoading(true);
    setSavedViewsError(null);
    listProjectListViews()
      .then((views) => {
        if (!cancelled) setSavedViews(views);
      })
      .catch((reason) => {
        if (!cancelled) setSavedViewsError(errorDetail(reason, "Não foi possível carregar as vistas pessoais."));
      })
      .finally(() => {
        if (!cancelled) setSavedViewsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [accountKey, savedViewsReloadKey]);

  const filters = config.filters;
  const { status, pm, active, startFrom, startTo } = filters;
  const lifecycle = filters.lifecycle;
  const lifecycleKey = lifecycle.join(",");
  const accountReady = preferenceAccountRef.current === accountKey;
  useEffect(() => {
    if (!viewReady || !accountReady) return undefined;
    const requestAccountKey = accountKey;
    let cancelled = false;
    setError(null);
    setProjects(null);
    listProjects(toApiFilters({ search: debouncedSearch, status, lifecycle, pm, active, startFrom, startTo }))
      .then((result) => !cancelled && accountKeyRef.current === requestAccountKey && setProjects(result))
      .catch((reason) => !cancelled && accountKeyRef.current === requestAccountKey && setError(errorDetail(reason, "Não foi possível contactar o servidor.")));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewReady, accountReady, debouncedSearch, status, lifecycleKey, pm, active, startFrom, startTo, reloadKey]);

  const commitConfig = (next: ProjectListConfig | ((current: ProjectListConfig) => ProjectListConfig)) => {
    const normalized = normalizeProjectListConfig(typeof next === "function" ? next(configRef.current) : next);
    configRef.current = normalized;
    userInteracted.current = true;
    setConfig(normalized);
    setViewReady(true);
    setPreferenceSaved(false);
    const nextParams = paramsForConfig(paramsRef.current, normalized);
    lastWrittenParams.current = nextParams.toString();
    setParams(nextParams, { replace: true });
  };

  const updateFilters = (patch: Partial<Filters>) =>
    commitConfig((current) => ({ ...current, filters: { ...current.filters, ...patch } }));

  const lifecycleViewState = lifecycleView(lifecycle);
  const filteredColumns = config.columns.filter((column) => column !== "payments" || canViewPayments);
  const visibleColumns = filteredColumns.length > 0 ? filteredColumns : ["project" as const];
  const availableColumns = PROJECT_LIST_COLUMN_ORDER.filter((column) => column !== "payments" || canViewPayments);
  const defaultFilters = defaultProjectListFilters();
  const hasFilters =
    JSON.stringify({ ...filters, lifecycle: [] }) !== JSON.stringify({ ...defaultFilters, lifecycle: [] }) || lifecycleViewState !== "in_progress";
  const resetFilters = () => updateFilters(defaultFilters);
  const today = todayIsoLisbon();
  const groups = useMemo(
    () => groupProjectsByLifecycle(projects ?? [], lifecycleStatuses).map((group) => ({ ...group, projects: sortProjects(group.projects, config.sort_by, config.sort_direction) })),
    [projects, lifecycleStatuses, config.sort_by, config.sort_direction]
  );
  const allGroupsExpanded = groups.length > 0 && groups.every((group) => !collapsedGroups.has(group.key));
  const toggleGroup = (key: string) =>
    setCollapsedGroups((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const toggleAllGroups = () =>
    setCollapsedGroups(allGroupsExpanded ? new Set(groups.map((group) => group.key)) : new Set());

  async function handleSavePreferences() {
    const actionAccountKey = accountKey;
    setPreferenceSaving(true);
    setPreferenceSaveError(null);
    setPreferenceSaved(false);
    try {
      await updateProjectListPreferences(normalizeProjectListConfig(configRef.current));
      if (accountKeyRef.current === actionAccountKey) {
        setPreferenceSaved(true);
        notify("Preferência de abertura guardada.", "success");
      }
    } catch (reason) {
      if (accountKeyRef.current === actionAccountKey) setPreferenceSaveError(errorDetail(reason, "Não foi possível guardar a preferência de abertura."));
    } finally {
      if (accountKeyRef.current === actionAccountKey) setPreferenceSaving(false);
    }
  }

  async function handleCreateSavedView() {
    const enteredName = window.prompt("Nome da vista:");
    const name = enteredName?.trim();
    if (!name) {
      if (enteredName !== null) setSavedViewsActionError("Introduza um nome para guardar a vista.");
      return;
    }
    setSavedViewsActionError(null);
    setSavedViewsSaving(true);
    try {
      const savedView = await createProjectListView({ name, config: normalizeProjectListConfig(configRef.current) });
      setSavedViews((current) => [...current, savedView]);
      setSelectedSavedViewId(savedView.id);
      notify("Vista pessoal guardada.", "success");
    } catch (reason) {
      setSavedViewsActionError(errorDetail(reason, "Não foi possível guardar a vista pessoal."));
    } finally {
      setSavedViewsSaving(false);
    }
  }

  function selectedSavedView(): ProjectListView | undefined {
    return savedViews.find((candidate) => candidate.id === selectedSavedViewId);
  }

  function handleApplySavedView() {
    const savedView = selectedSavedView();
    if (!savedView) return;
    setSavedViewsActionError(null);
    commitConfig(normalizeProjectListConfig(savedView.config));
    notify("Vista aplicada.", "success");
  }

  async function handleUpdateSavedView() {
    const savedView = selectedSavedView();
    if (!savedView) return;
    setSavedViewsActionError(null);
    setSavedViewsManagingId(savedView.id);
    try {
      const updated = await updateProjectListView(savedView.id, { config: normalizeProjectListConfig(configRef.current) });
      setSavedViews((current) => current.map((candidate) => (candidate.id === updated.id ? updated : candidate)));
      notify("Vista pessoal atualizada.", "success");
    } catch (reason) {
      setSavedViewsActionError(errorDetail(reason, "Não foi possível atualizar a vista pessoal."));
    } finally {
      setSavedViewsManagingId(null);
    }
  }

  async function handleRenameSavedView() {
    const savedView = selectedSavedView();
    if (!savedView) return;
    const enteredName = window.prompt("Novo nome da vista:", savedView.name);
    const name = enteredName?.trim();
    if (!name) {
      if (enteredName !== null) setSavedViewsActionError("Introduza um nome para a vista.");
      return;
    }
    setSavedViewsActionError(null);
    setSavedViewsManagingId(savedView.id);
    try {
      const updated = await updateProjectListView(savedView.id, { name });
      setSavedViews((current) => current.map((candidate) => (candidate.id === updated.id ? updated : candidate)));
      notify("Vista pessoal renomeada.", "success");
    } catch (reason) {
      setSavedViewsActionError(errorDetail(reason, "Não foi possível renomear a vista pessoal."));
    } finally {
      setSavedViewsManagingId(null);
    }
  }

  async function handleDeleteSavedView() {
    const savedView = selectedSavedView();
    if (!savedView || !window.confirm(`Eliminar a vista «${savedView.name}»?`)) return;
    setSavedViewsActionError(null);
    setSavedViewsManagingId(savedView.id);
    try {
      await deleteProjectListView(savedView.id);
      setSavedViews((current) => current.filter((candidate) => candidate.id !== savedView.id));
      setSelectedSavedViewId("");
      notify("Vista pessoal eliminada.", "success");
    } catch (reason) {
      setSavedViewsActionError(errorDetail(reason, "Não foi possível eliminar a vista pessoal."));
    } finally {
      setSavedViewsManagingId(null);
    }
  }

  return (
    <div className="projects-page">
      <PageHeader
        title="Projetos"
        subtitle="Estado, progresso e próximos passos de cada instalação."
        actions={
          <>
            {can("project.edit_all") && (
              <button type="button" className="btn" onClick={() => setCreatingProject(true)}>
                Novo projeto
              </button>
            )}
            {can("project.restore") && <Link to="/projects/deleted" className="btn">Projetos apagados</Link>}
            {can("import.notes") && (
              <Link to="/projects/import" className="btn btn--primary">
                <Icon name="database" size={16} /> Novo projeto — importar notas
              </Link>
            )}
          </>
        }
      />

      {preferenceError && (
        <div className="projects-list__preference-alert" role="alert">
          <span>Preferência de abertura indisponível: {preferenceError}</span>
          <button type="button" className="btn btn--sm btn--ghost" onClick={() => setPreferenceReloadKey((key) => key + 1)}>
            Tentar carregar preferência
          </button>
        </div>
      )}
      {preferenceSaveError && (
        <div className="projects-list__preference-alert" role="alert">
          <span>{preferenceSaveError}</span>
          <button type="button" className="btn btn--sm btn--ghost" onClick={handleSavePreferences} disabled={preferenceSaving}>
            Tentar guardar
          </button>
        </div>
      )}

      <form className="toolbar" role="search" aria-label="Filtros de projetos" onSubmit={(event) => event.preventDefault()}>
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
              onChange={(event) => updateFilters({ search: event.target.value })}
            />
          </div>
        </div>
        <div className="field">
          <label htmlFor="f-status">Tarefas</label>
          <select id="f-status" className="select" value={filters.status} onChange={(event) => updateFilters({ status: event.target.value as ProjectStatus | "" })}>
            <option value="">Todas</option>
            {(Object.keys(PROJECT_STATUS_LABELS) as ProjectStatus[]).map((statusKey) => (
              <option key={statusKey} value={statusKey}>
                {PROJECT_STATUS_LABELS[statusKey]}
              </option>
            ))}
          </select>
        </div>
        <LifecycleMultiSelect
          id="f-lifecycle"
          label="Estado do projeto"
          value={lifecycle}
          onChange={(next) => updateFilters({ lifecycle: next })}
          statuses={lifecycleStatuses}
        />
        <div className="field">
          <label htmlFor="f-pm">PM</label>
          <select id="f-pm" className="select" value={filters.pm} onChange={(event) => updateFilters({ pm: event.target.value })}>
            <option value="">Todos os PM</option>
            {people.map((person) => (
              <option key={person.id} value={person.id}>
                {person.display_name}
                {person.is_active ? "" : " (inativo)"}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="f-from">Início a partir de</label>
          <input id="f-from" className="input" type="date" value={filters.startFrom} onChange={(event) => updateFilters({ startFrom: event.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="f-to">Início até</label>
          <input id="f-to" className="input" type="date" value={filters.startTo} onChange={(event) => updateFilters({ startTo: event.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="f-active">Situação</label>
          <select id="f-active" className="select" value={filters.active} onChange={(event) => updateFilters({ active: event.target.value as ActiveFilter })}>
            <option value="active">Ativos</option>
            <option value="inactive">Inativos</option>
            <option value="all">Todos</option>
          </select>
        </div>
        {hasFilters && (
          <div className="toolbar__end">
            <button type="button" className="btn btn--ghost" onClick={resetFilters}>
              <Icon name="x" size={16} /> Limpar filtros
            </button>
          </div>
        )}
      </form>

      <div className="projects-list__settings" role="toolbar" aria-label="Configuração da lista de projetos">
        <ColumnConfigurator
          columns={config.columns}
          availableColumns={availableColumns}
          rowOptions={config.row_options}
          onChange={(columns) => commitConfig((current) => ({ ...current, columns }))}
          onRowOptionsChange={(row_options) => commitConfig((current) => ({ ...current, row_options }))}
          onRestore={() => commitConfig((current) => ({ ...current, columns: [...DEFAULT_PROJECT_LIST_COLUMNS] }))}
        />
        <div className="field">
          <label htmlFor="project-list-sort">Ordenar por</label>
          <select
            id="project-list-sort"
            className="select"
            value={config.sort_by}
            onChange={(event) => commitConfig((current) => ({ ...current, sort_by: event.target.value as ProjectListConfig["sort_by"] }))}
          >
            {Object.entries(PROJECT_LIST_SORT_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="project-list-sort-direction">Direção</label>
          <select
            id="project-list-sort-direction"
            className="select"
            value={config.sort_direction}
            onChange={(event) => commitConfig((current) => ({ ...current, sort_direction: event.target.value as ProjectListConfig["sort_direction"] }))}
          >
            <option value="asc">Ascendente</option>
            <option value="desc">Descendente</option>
          </select>
        </div>
        <div className="field projects-list__saved-view-field">
          <label htmlFor="project-list-saved-view">Vistas pessoais</label>
          <select
            id="project-list-saved-view"
            className="select"
            value={selectedSavedViewId}
            onChange={(event) => setSelectedSavedViewId(event.target.value)}
            disabled={savedViewsLoading}
          >
            <option value="">{savedViewsLoading ? "A carregar…" : "Selecionar vista pessoal"}</option>
            {savedViews.map((savedView) => (
              <option key={savedView.id} value={savedView.id}>
                {savedView.name}
              </option>
            ))}
          </select>
        </div>
        <div className="projects-list__view-actions">
          <button type="button" className="btn btn--sm btn--ghost" onClick={handleApplySavedView} disabled={!selectedSavedViewId || savedViewsManagingId !== null}>
            Aplicar vista
          </button>
          <button type="button" className="btn btn--sm btn--ghost" onClick={() => void handleCreateSavedView()} disabled={savedViewsSaving}>
            {savedViewsSaving ? "A guardar…" : "Guardar vista atual como…"}
          </button>
          <button type="button" className="btn btn--sm" onClick={() => void handleSavePreferences()} disabled={preferenceSaving || preferenceStatus === "loading"}>
            {preferenceSaving ? "A guardar…" : "Guardar preferência de abertura"}
          </button>
          {selectedSavedViewId && (
            <>
              <button type="button" className="btn btn--sm btn--ghost" onClick={() => void handleUpdateSavedView()} disabled={savedViewsManagingId !== null}>
                {savedViewsManagingId === selectedSavedViewId ? "A atualizar…" : "Atualizar vista"}
              </button>
              <button type="button" className="btn btn--sm btn--ghost" onClick={() => void handleRenameSavedView()} disabled={savedViewsManagingId !== null}>
                {savedViewsManagingId === selectedSavedViewId ? "A gerir…" : "Renomear vista"}
              </button>
              <button type="button" className="btn btn--sm btn--ghost" onClick={() => void handleDeleteSavedView()} disabled={savedViewsManagingId !== null}>
                {savedViewsManagingId === selectedSavedViewId ? "A gerir…" : "Eliminar vista"}
              </button>
            </>
          )}
        </div>
        {savedViewsError && (
          <span className="small text-danger" role="alert">
            {savedViewsError} <button type="button" className="btn btn--sm btn--ghost" onClick={() => setSavedViewsReloadKey((key) => key + 1)}>Tentar carregar vistas</button>
          </span>
        )}
        {savedViewsActionError && <span className="small text-danger" role="alert">{savedViewsActionError}</span>}
      </div>
      {preferenceSaved && <p className="small text-success" role="status">Preferência de abertura guardada.</p>}

      <div className="card projects-page__results">
        {error && <ErrorState message={error} onRetry={() => setReloadKey((key) => key + 1)} />}
        {!error && projects === null && <LoadingState label="A carregar projetos…" rows={5} />}
        {!error && projects?.length === 0 && (
          <EmptyState
            icon="folder"
            title="Nenhum projeto encontrado"
            text={hasFilters ? "Nenhum projeto corresponde aos filtros escolhidos." : "Não há projetos visíveis para o seu perfil."}
            action={
              hasFilters ? (
                <button type="button" className="btn btn--sm" onClick={resetFilters}>
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
                {lifecycleViewState === "in_progress" && " em curso"}
              </span>
              {lifecycleViewState === "in_progress" && (
                <span className="small muted" style={{ marginLeft: 8 }}>
                  (os já entregues e certificados estão escondidos){" "}
                  <button type="button" className="btn btn--sm btn--ghost" onClick={() => updateFilters({ lifecycle: [] })}>
                    Mostrar todos
                  </button>
                </span>
              )}
            </div>
            <div className="projects-list__group-toolbar" role="toolbar" aria-label="Grupos de projetos">
              <span className="projects-list__group-toolbar-label">Agrupado por estado do projeto</span>
              <button
                type="button"
                className="btn btn--sm btn--ghost"
                aria-expanded={allGroupsExpanded}
                aria-controls={groups.map((_, index) => `projects-group-${index}`).join(" ")}
                onClick={toggleAllGroups}
              >
                {allGroupsExpanded ? "Recolher todos" : "Expandir todos"}
              </button>
            </div>
            <div
              className="table-wrap projects-list__table-wrap"
              role="region"
              aria-label="Lista de projetos"
              tabIndex={0}
            >
              <p className="projects-list__scroll-hint">Deslize horizontalmente para consultar todas as colunas.</p>
              <table className="table">
                <caption className="sr-only">Lista de projetos</caption>
                <thead>
                  <tr>
                    {visibleColumns.map((column) => (
                      <th
                        key={column}
                        scope="col"
                        className={column === "project" ? "col-main" : undefined}
                        title={column === "payments" ? "FT Adj | EO | FO | Ct" : undefined}
                      >
                        {PROJECT_LIST_COLUMN_LABELS[column]}
                      </th>
                    ))}
                  </tr>
                </thead>
                {groups.map((group, groupIndex) => {
                  const expanded = !collapsedGroups.has(group.key);
                  const groupId = `projects-group-${groupIndex}`;
                  const groupCount = projectCountLabel(group.projects.length);
                  return (
                    <Fragment key={group.key}>
                      <tbody className={`projects-list__group ${expanded ? "" : "projects-list__group--collapsed"}`}>
                        <tr className="projects-list__group-row">
                          <th scope="rowgroup" colSpan={visibleColumns.length}>
                            <button
                              type="button"
                              className="projects-list__group-toggle"
                              aria-expanded={expanded}
                              aria-controls={groupId}
                              aria-label={`${expanded ? "Recolher" : "Expandir"} grupo ${group.label} (${groupCount})`}
                              onClick={() => toggleGroup(group.key)}
                            >
                              <span className="projects-list__group-chevron" aria-hidden="true">
                                {expanded ? "▾" : "▸"}
                              </span>
                              <LifecycleBadge status={group.status} statuses={lifecycleStatuses} />
                              <span className="projects-list__group-count">{group.projects.length}</span>
                            </button>
                          </th>
                        </tr>
                      </tbody>
                      <tbody id={groupId} className="projects-list__group-body" hidden={!expanded}>
                        {group.projects.map((project) => (
                          <tr key={project.id} className={project.overdue_tasks_count > 0 ? "row--danger" : undefined}>
                            {visibleColumns.map((column) => (
                              <td key={column} className={column === "pm" ? "nowrap" : undefined} style={column === "progress" ? { minWidth: 150 } : undefined}>
                                {renderProjectCell(
                                  column,
                                  project,
                                  group.status,
                                  people,
                                  lifecycleStatuses,
                                  today,
                                  (updated) => setProjects((current) => current && current.map((row) => (row.id === updated.id ? updated : row))),
                                  setDeletingProject,
                                  location,
                                  config.row_options,
                                )}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </Fragment>
                  );
                })}
              </table>
            </div>
          </>
        )}
      </div>
      {deletingProject && (
        <ProjectDeletionModal
          project={deletingProject}
          onClose={() => setDeletingProject(null)}
          onDeleted={() => {
            setDeletingProject(null);
            setProjects((current) => current?.filter((project) => project.id !== deletingProject.id) ?? current);
            setReloadKey((key) => key + 1);
            notify("Projeto apagado.", "success");
          }}
        />
      )}
      {creatingProject && (
        <CreateProjectModal
          statuses={lifecycleStatuses}
          onClose={() => setCreatingProject(false)}
          onCreated={(projectId) => {
            setCreatingProject(false);
            navigate(`/projects/${projectId}`, {
              state: { from: { pathname: location.pathname, search: location.search, hash: location.hash } },
            });
          }}
        />
      )}
    </div>
  );
}
