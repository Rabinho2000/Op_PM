import LifecycleMultiSelect from "../components/LifecycleMultiSelect";
import { MouseEvent as ReactMouseEvent, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useSearchParams, useNavigate } from "react-router-dom";
import {
  ApiError,
  applySavedWorksView,
  createSavedWorksView,
  deleteSavedWorksView,
  getWorksPreferences,
  getWorksCalendar,
  Installer,
  listInstallers,
  listPeople,
  listSavedWorksViews,
  Person,
  SavedWorksView,
  updateProjectWorkPlan,
  WorkItem,
  WorkPlanInput,
  WorksCalendar,
  WorksPreferences,
  updateSavedWorksView,
  updateWorksPreferences,
} from "../api/client";
import Icon from "../components/Icon";
import { useLifecycleStatuses, LifecycleBadge } from "../components/LifecycleStatus";
import { Alert, Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader } from "../components/ui";
import { useToast } from "../components/Toast";
import WorksTimeline from "../components/WorksTimeline";
import { todayIsoLisbon } from "../utils/dates";
import { defaultWindow, formatIsoPt, shiftWindow, windowFrom, Zoom, ZOOMS } from "../utils/worksTimeline";
import { useSession } from "../session/SessionContext";
import "./Works.css";

const ZOOM_KEYS = Object.keys(ZOOMS) as Zoom[];
const ISO_RE = /^\d{4}-\d{2}-\d{2}$/;
const VIEW_QUERY_KEYS = ["zoom", "from", "pm", "estado", "inst", "equipa", "idle"] as const;
type ViewState = { zoom: Zoom; from: string | null; pm: string; lifecycle: string[]; installerId: string; teamId: string; showIdle: boolean };
type PreferenceStatus = "loading" | "ready" | "error";
type ScrollSnapshot = { left: number; top: number; timelineLeft: number | null };
const FALLBACK_VIEW: ViewState = { zoom: "months", from: null, pm: "", lifecycle: [], installerId: "", teamId: "", showIdle: false };
const DEFAULT_PREFERENCE: WorksPreferences = { zoom: "month_days", lifecycle_status: [], pm_person_id: null, installer_id: null, team_id: null, show_idle: false };

// Any recognized URL key makes the URL a complete, shareable view. Missing
// keys intentionally use viewFromParams defaults instead of leaking a saved
// preference into a partial link.
function hasViewQuery(params: URLSearchParams): boolean {
  return VIEW_QUERY_KEYS.some((key) => params.has(key));
}

function viewFromParams(params: URLSearchParams): ViewState {
  const rawZoom = params.get("zoom");
  const zoom = ZOOM_KEYS.includes(rawZoom as Zoom) ? (rawZoom as Zoom) : "months";
  const from = params.get("from");
  return {
    zoom,
    from: from && ISO_RE.test(from) ? from : null,
    pm: params.get("pm") ?? "",
    lifecycle: params.getAll("estado"),
    installerId: params.get("inst") ?? "",
    teamId: params.get("equipa") ?? "",
    showIdle: params.get("idle") === "1",
  };
}

function viewFromPreference(preference: WorksPreferences): ViewState {
  return { zoom: preference.zoom, from: null, pm: preference.pm_person_id ?? "", lifecycle: preference.lifecycle_status ?? [], installerId: preference.installer_id ?? "", teamId: preference.team_id ?? "", showIdle: preference.show_idle };
}

function preferenceFromView(view: ViewState): WorksPreferences {
  return { zoom: view.zoom, lifecycle_status: view.lifecycle, pm_person_id: view.pm || null, installer_id: view.installerId || null, team_id: view.teamId || null, show_idle: view.showIdle };
}

// Calendário de obras por instalador e equipa (D-072). Todo o estado (janela,
// zoom, filtros) vive no URL: a vista é partilhável e sobrevive a um refresh.
export default function Works() {
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const { me } = useSession();
  const today = todayIsoLisbon();
  const statuses = useLifecycleStatuses();
  const { notify } = useToast();
  const accountKey = me?.user_id ?? me?.email ?? "anonymous";
  const [view, setView] = useState<ViewState>(() => (hasViewQuery(params) ? viewFromParams(params) : FALLBACK_VIEW));
  const [viewReady, setViewReady] = useState(() => hasViewQuery(params));
  const [preferenceStatus, setPreferenceStatus] = useState<PreferenceStatus>(() => (hasViewQuery(params) ? "ready" : "loading"));
  const [preferenceError, setPreferenceError] = useState<string | null>(null);
  const [preferenceSaveError, setPreferenceSaveError] = useState<string | null>(null);
  const [preferenceSaving, setPreferenceSaving] = useState(false);
  const [preferenceSaved, setPreferenceSaved] = useState(false);
  const [savedViews, setSavedViews] = useState<SavedWorksView[]>([]);
  const [savedViewsLoading, setSavedViewsLoading] = useState(true);
  const [savedViewsError, setSavedViewsError] = useState<string | null>(null);
  const [savedViewsActionError, setSavedViewsActionError] = useState<string | null>(null);
  const [savedViewsSaving, setSavedViewsSaving] = useState(false);
  const [savedViewsApplyingId, setSavedViewsApplyingId] = useState<string | null>(null);
  const [savedViewsManagingId, setSavedViewsManagingId] = useState<string | null>(null);
  const [selectedSavedViewId, setSelectedSavedViewId] = useState("");
  const userInteracted = useRef(false);
  const preferenceAccountRef = useRef<string | null>(null);
  const preferenceAccountKeyRef = useRef(accountKey);
  preferenceAccountKeyRef.current = accountKey;
  const preferenceRequestRef = useRef(0);
  const paramsRef = useRef(params);
  paramsRef.current = params;
  const paramSignature = params.toString();
  const lastWrittenParams = useRef(paramSignature);
  const zoom = view.zoom;
  const fromParam = view.from;
  const win = useMemo(() => (fromParam ? windowFrom(zoom, fromParam) : defaultWindow(zoom, today)), [zoom, fromParam, today]);
  const pm = view.pm;
  const lifecycle = view.lifecycle;
  const installerId = view.installerId;
  const teamId = view.teamId;
  const showIdle = view.showIdle;

  const [installers, setInstallers] = useState<Installer[]>([]);
  const [people, setPeople] = useState<Person[]>([]);
  const [data, setData] = useState<WorksCalendar | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const worksRootRef = useRef<HTMLDivElement>(null);
  const scrollRestoreRef = useRef<ScrollSnapshot | null>(null);
  const scrollUserIntentRef = useRef(false);

  useEffect(() => {
    const refresh = () => {
      const timeline = worksRootRef.current?.querySelector<HTMLElement>(".works__scroll");
      scrollRestoreRef.current = {
        left: window.scrollX,
        top: window.scrollY,
        timelineLeft: timeline?.scrollLeft ?? null,
      };
      scrollUserIntentRef.current = false;
      setReloadKey((key) => key + 1);
    };
    window.addEventListener("op:works-project-refresh", refresh);
    return () => window.removeEventListener("op:works-project-refresh", refresh);
  }, []);

  // Mark real user input while a refresh is pending. A browser may emit a
  // scroll event when the old document is temporarily clamped; that event is
  // deliberately not treated as intent, so the captured position can still
  // be restored after the rows return.
  useEffect(() => {
    const markUserIntent = () => {
      if (scrollRestoreRef.current) scrollUserIntentRef.current = true;
    };
    window.addEventListener("wheel", markUserIntent, { passive: true });
    window.addEventListener("touchstart", markUserIntent, { passive: true });
    window.addEventListener("pointerdown", markUserIntent, { passive: true });
    window.addEventListener("keydown", markUserIntent);
    return () => {
      window.removeEventListener("wheel", markUserIntent);
      window.removeEventListener("touchstart", markUserIntent);
      window.removeEventListener("pointerdown", markUserIntent);
      window.removeEventListener("keydown", markUserIntent);
    };
  }, []);

  function update(patch: Record<string, string | string[] | null>) {
    userInteracted.current = true;
    const next = { ...view };
    if ("zoom" in patch) next.zoom = (patch.zoom as Zoom | null) ?? "months";
    if ("from" in patch) next.from = patch.from as string | null;
    if ("pm" in patch) next.pm = (patch.pm as string | null) ?? "";
    if ("estado" in patch) next.lifecycle = Array.isArray(patch.estado) ? patch.estado : [];
    if ("inst" in patch) next.installerId = (patch.inst as string | null) ?? "";
    if ("equipa" in patch) next.teamId = (patch.equipa as string | null) ?? "";
    if ("idle" in patch) next.showIdle = patch.idle === "1";
    setView(next);
    setViewReady(true);
    setPreferenceSaved(false);

    // Keep every view key in the shareable URL so a filter change never
    // silently discards the selected zoom or another active filter.
    const nextParams = new URLSearchParams(params);
    for (const key of VIEW_QUERY_KEYS) nextParams.delete(key);
    nextParams.set("zoom", next.zoom);
    if (next.from) nextParams.set("from", next.from);
    if (next.pm) nextParams.set("pm", next.pm);
    next.lifecycle.forEach((value) => nextParams.append("estado", value));
    if (next.installerId) nextParams.set("inst", next.installerId);
    if (next.teamId) nextParams.set("equipa", next.teamId);
    if (next.showIdle) nextParams.set("idle", "1");
    lastWrittenParams.current = nextParams.toString();
    setParams(nextParams, { replace: true });
  }

  useEffect(() => {
    if (paramSignature === lastWrittenParams.current) return;
    lastWrittenParams.current = paramSignature;
    setView(viewFromParams(params));
    userInteracted.current = true;
    setViewReady(true);
  }, [paramSignature, params]);

  const loadPreferences = useCallback(async () => {
    const currentParams = paramsRef.current;
    const explicitUrl = hasViewQuery(currentParams);
    const requestAccountKey = accountKey;
    const requestId = ++preferenceRequestRef.current;
    const isCurrentRequest = () =>
      preferenceRequestRef.current === requestId && preferenceAccountKeyRef.current === requestAccountKey;
    const accountChanged = preferenceAccountRef.current !== accountKey;
    if (accountChanged) {
      preferenceAccountRef.current = accountKey;
      userInteracted.current = false;
    }
    if (!explicitUrl) {
      if (accountChanged) {
        setView(FALLBACK_VIEW);
        setViewReady(false);
      }
    } else {
      setView(viewFromParams(currentParams));
      setViewReady(true);
    }
    setPreferenceStatus("loading");
    setPreferenceError(null);
    try {
      const saved = await getWorksPreferences();
      if (!isCurrentRequest()) return;
      if (!explicitUrl && !userInteracted.current) setView(viewFromPreference(saved));
      setViewReady(true);
      setPreferenceStatus("ready");
    } catch (e) {
      if (!isCurrentRequest()) return;
      setViewReady(true);
      setPreferenceStatus("error");
      setPreferenceError(e instanceof ApiError ? e.detail : "Não foi possível carregar a vista guardada; a usar a vista local.");
    }
  }, [accountKey]);

  useEffect(() => {
    void loadPreferences();
  }, [loadPreferences]);

  useEffect(() => {
    let cancelled = false;
    setSavedViews([]);
    setSelectedSavedViewId("");
    setSavedViewsLoading(true);
    setSavedViewsError(null);
    listSavedWorksViews()
      .then((views) => {
        if (cancelled) return;
        setSavedViews(views);
      })
      .catch((e) => {
        if (cancelled) return;
        setSavedViewsError(e instanceof ApiError ? e.detail : "Não foi possível carregar as vistas guardadas.");
      })
      .finally(() => {
        if (!cancelled) setSavedViewsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [accountKey]);

  useEffect(() => {
    listInstallers()
      .then(setInstallers)
      .catch(() => setInstallers([]));
    listPeople()
      .then(setPeople)
      .catch(() => setPeople([]));
  }, []);

  const lifecycleKey = lifecycle.join(",");
  useEffect(() => {
    if (!viewReady) return undefined;
    let cancelled = false;
    setError(null);
    if (data === null) {
      setLoading(true);
      setRefreshing(false);
    } else {
      setRefreshing(true);
    }
    getWorksCalendar({
      from: win.from,
      to: win.to,
      pm_person_id: pm || undefined,
      lifecycle_status: lifecycle.length > 0 ? lifecycle : undefined,
      installer_id: installerId || undefined,
      team_id: teamId || undefined,
    })
      .then((r) => {
        if (cancelled) return;
        setData(r);
        setLoading(false);
        setRefreshing(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setLoading(false);
        setRefreshing(false);
        setError(e instanceof ApiError ? e.detail : "Não foi possível contactar o servidor.");
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewReady, win.from, win.to, pm, lifecycleKey, installerId, teamId, reloadKey]);

  useLayoutEffect(() => {
    const snapshot = scrollRestoreRef.current;
    if (!snapshot || data === null) return;
    scrollRestoreRef.current = null;
    const userMoved = scrollUserIntentRef.current;
    scrollUserIntentRef.current = false;
    if (userMoved) return;

    if (window.scrollX !== snapshot.left || window.scrollY !== snapshot.top) {
      window.scrollTo({ left: snapshot.left, top: snapshot.top, behavior: "auto" });
    }
    if (snapshot.timelineLeft !== null) {
      const timeline = worksRootRef.current?.querySelector<HTMLElement>(".works__scroll");
      if (timeline && timeline.scrollLeft !== snapshot.timelineLeft) timeline.scrollLeft = snapshot.timelineLeft;
    }
  }, [data]);

  // Arrastar/redimensionar uma obra: grava logo e oferece "Anular", que repõe os valores
  // anteriores (o servidor confirma as datas ao gravar, por isso a anulação também as confirma).
  async function changePlan(work: WorkItem, changes: WorkPlanInput) {
    const undo: WorkPlanInput = {};
    if ("work_start_date" in changes) {
      undo.work_start_date = work.work_start_date;
      undo.work_end_date = work.work_end_date;
    }
    if ("installer_id" in changes) {
      undo.installer_id = work.installer_id;
      undo.installer_team_id = work.installer_team_id;
    }
    try {
      await updateProjectWorkPlan(work.project_id, changes);
      setReloadKey((k) => k + 1);
      notify(`Obra «${work.name}» atualizada.`, "success", {
        label: "Anular",
        onClick: () => {
          updateProjectWorkPlan(work.project_id, undo)
            .then(() => notify("Alteração anulada."))
            .catch((e) => notify(e instanceof ApiError ? e.detail : "Não foi possível anular.", "error"))
            .finally(() => setReloadKey((k) => k + 1));
        },
      });
    } catch (e) {
      notify(e instanceof ApiError ? e.detail : "Não foi possível gravar a alteração.", "error");
      setReloadKey((k) => k + 1);
    }
  }

  async function handleSavePreferences() {
    setPreferenceSaving(true);
    setPreferenceSaveError(null);
    setPreferenceSaved(false);
    try {
      await updateWorksPreferences(preferenceFromView(view));
      setPreferenceSaved(true);
      notify("Vista guardada.", "success");
    } catch (e) {
      setPreferenceSaveError(e instanceof ApiError ? e.detail : "Não foi possível guardar a vista. Tente novamente.");
    } finally {
      setPreferenceSaving(false);
    }
  }

  async function handleResetPreferences() {
    setPreferenceSaving(true);
    setPreferenceSaveError(null);
    setPreferenceSaved(false);
    try {
      const saved = await updateWorksPreferences(DEFAULT_PREFERENCE);
      setView(viewFromPreference(saved));
      setViewReady(true);
      const nextParams = new URLSearchParams(params);
      for (const key of VIEW_QUERY_KEYS) nextParams.delete(key);
      lastWrittenParams.current = nextParams.toString();
      setParams(nextParams, { replace: true });
      setPreferenceSaved(true);
      notify("Vista reposta.", "success");
    } catch (e) {
      setPreferenceSaveError(e instanceof ApiError ? e.detail : "Não foi possível repor a vista. Tente novamente.");
    } finally {
      setPreferenceSaving(false);
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
      const savedView = await createSavedWorksView({ name, ...preferenceFromView(view) });
      setSavedViews((current) => [...current, savedView]);
      setSelectedSavedViewId(savedView.id);
      notify("Vista nomeada guardada.", "success");
    } catch (e) {
      setSavedViewsActionError(e instanceof ApiError ? e.detail : "Não foi possível guardar a vista nomeada.");
    } finally {
      setSavedViewsSaving(false);
    }
  }

  async function handleApplySavedView() {
    const savedView = savedViews.find((candidate) => candidate.id === selectedSavedViewId);
    if (!savedView) return;
    setSavedViewsActionError(null);
    setSavedViewsApplyingId(savedView.id);
    try {
      const applied = await applySavedWorksView(savedView.id);
      update({
        zoom: applied.zoom,
        pm: applied.pm_person_id,
        estado: applied.lifecycle_status,
        inst: applied.installer_id,
        equipa: applied.team_id,
        idle: applied.show_idle ? "1" : null,
      });
      setReloadKey((key) => key + 1);
      notify("Vista aplicada.", "success");
    } catch (e) {
      setSavedViewsActionError(e instanceof ApiError ? e.detail : "Não foi possível aplicar a vista nomeada.");
    } finally {
      setSavedViewsApplyingId(null);
    }
  }

  async function handleRenameSavedView() {
    const savedView = savedViews.find((candidate) => candidate.id === selectedSavedViewId);
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
      const updated = await updateSavedWorksView(savedView.id, { name });
      setSavedViews((current) => current.map((candidate) => (candidate.id === updated.id ? updated : candidate)));
      notify("Vista renomeada.", "success");
    } catch (e) {
      setSavedViewsActionError(e instanceof ApiError ? e.detail : "Não foi possível renomear a vista.");
    } finally {
      setSavedViewsManagingId(null);
    }
  }

  async function handleDeleteSavedView() {
    const savedView = savedViews.find((candidate) => candidate.id === selectedSavedViewId);
    if (!savedView || !window.confirm(`Eliminar a vista «${savedView.name}»?`)) return;
    setSavedViewsActionError(null);
    setSavedViewsManagingId(savedView.id);
    try {
      await deleteSavedWorksView(savedView.id);
      setSavedViews((current) => current.filter((candidate) => candidate.id !== savedView.id));
      setSelectedSavedViewId("");
      notify("Vista eliminada.", "success");
    } catch (e) {
      setSavedViewsActionError(e instanceof ApiError ? e.detail : "Não foi possível eliminar a vista.");
    } finally {
      setSavedViewsManagingId(null);
    }
  }

  const teamOptions = useMemo(() => {
    const scope = installerId ? installers.filter((i) => i.id === installerId) : installers;
    return scope.flatMap((i) => i.teams.map((t) => ({ id: t.id, label: installerId ? t.name : `${i.name} — ${t.name}` })));
  }, [installers, installerId]);

  const hasFilters = Boolean(pm || lifecycle.length > 0 || installerId || teamId);
  const clearFilters = () => update({ pm: null, estado: null, inst: null, equipa: null });
  const openProjectOverlay = (projectId: string) => navigate(`/projects/${projectId}`, { state: { backgroundLocation: location } });
  const handleProjectLinkClick = (projectId: string, event: ReactMouseEvent<HTMLAnchorElement>) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    openProjectOverlay(projectId);
  };

  return (
    <div ref={worksRootRef} className="works-page">
      <PageHeader
        title="Calendário de obras"
        subtitle="As obras ao longo do tempo, por instalador e equipa. Arraste uma barra para a mover (ou mude de linha para mudar de instalador/equipa) e as pontas para ajustar as datas."
        actions={<Link className="btn btn--ghost" to="/works/teams"><Icon name="wrench" size={16} /> Ver equipas</Link>}
      />

      {(preferenceError || preferenceSaveError) && (
        <div className="works__preference-alert">
          {preferenceError && <Alert tone="warning" title="Vista guardada indisponível" action={<button type="button" className="btn btn--sm" onClick={() => void loadPreferences()}>Tentar novamente</button>}>{preferenceError}</Alert>}
          {preferenceSaveError && <Alert tone="warning" title="Vista não guardada" action={<button type="button" className="btn btn--sm" onClick={handleSavePreferences} disabled={preferenceSaving}>Tentar guardar</button>}>{preferenceSaveError}</Alert>}
        </div>
      )}

      <div className="toolbar" role="search" aria-label="Filtros do calendário de obras">
        <div className="field">
          <label htmlFor="w-saved-view">Vistas guardadas</label>
          <select
            id="w-saved-view"
            className="select"
            value={selectedSavedViewId}
            onChange={(e) => setSelectedSavedViewId(e.target.value)}
            disabled={savedViewsLoading}
          >
            <option value="">{savedViewsLoading ? "A carregar…" : "Selecionar vista guardada"}</option>
            {savedViews.map((savedView) => (
              <option key={savedView.id} value={savedView.id}>
                {savedView.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="btn btn--sm btn--ghost"
            onClick={() => void handleApplySavedView()}
            disabled={!selectedSavedViewId || savedViewsApplyingId !== null}
          >
            {savedViewsApplyingId ? "A aplicar…" : "Aplicar vista"}
          </button>
          {selectedSavedViewId && (
            <>
              <button
                type="button"
                className="btn btn--sm btn--ghost"
                onClick={() => void handleRenameSavedView()}
                disabled={savedViewsManagingId !== null || savedViewsApplyingId !== null}
              >
                {savedViewsManagingId === selectedSavedViewId ? "A renomear…" : "Renomear vista"}
              </button>
              <button
                type="button"
                className="btn btn--sm btn--ghost"
                onClick={() => void handleDeleteSavedView()}
                disabled={savedViewsManagingId !== null || savedViewsApplyingId !== null}
              >
                {savedViewsManagingId === selectedSavedViewId ? "A gerir…" : "Eliminar vista"}
              </button>
            </>
          )}
          {savedViewsError && <span className="small text-danger" role="alert">{savedViewsError}</span>}
        </div>
        <div className="field">
          <span className="field__label" id="w-zoom-label">
            Escala
          </span>
          <div className="segmented" role="group" aria-labelledby="w-zoom-label">
            {ZOOM_KEYS.map((z) => (
              <button
                key={z}
                type="button"
                className={z === zoom ? "is-active" : ""}
                aria-pressed={z === zoom}
                onClick={() => update({ zoom: z === "months" ? null : z, from: null })}
              >
                {ZOOMS[z].label}
              </button>
            ))}
          </div>
        </div>
        <div className="field">
          <span className="field__label" id="w-nav-label">
            Período
          </span>
          <div className="segmented" role="group" aria-labelledby="w-nav-label">
            <button type="button" aria-label="Período anterior" onClick={() => update({ from: shiftWindow(zoom, win.from, -1).from })}>
              <Icon name="chevronLeft" size={16} />
            </button>
            <button type="button" onClick={() => update({ from: null })}>
              Hoje
            </button>
            <button type="button" aria-label="Período seguinte" onClick={() => update({ from: shiftWindow(zoom, win.from, 1).from })}>
              <Icon name="chevronRight" size={16} />
            </button>
          </div>
        </div>
        <div className="field">
          <label htmlFor="w-pm">PM</label>
          <select id="w-pm" className="select" value={pm} onChange={(e) => update({ pm: e.target.value || null })}>
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
          <label htmlFor="w-inst">Instalador</label>
          <select
            id="w-inst"
            className="select"
            value={installerId}
            onChange={(e) => update({ inst: e.target.value || null, equipa: null })}
          >
            <option value="">Todos os instaladores</option>
            {installers.map((i) => (
              <option key={i.id} value={i.id}>
                {i.name}
                {i.is_active ? "" : " (inativo)"}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="w-team">Equipa</label>
          <select id="w-team" className="select" value={teamId} onChange={(e) => update({ equipa: e.target.value || null })}>
            <option value="">Todas as equipas</option>
            {teamOptions.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
        <LifecycleMultiSelect id="w-estado" label="Estado da obra" value={lifecycle} onChange={(next) => update({ estado: next })} statuses={statuses} />
        <div className="toolbar__end">
          <label style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: "0.85rem" }}>
            <input type="checkbox" checked={showIdle} onChange={(e) => update({ idle: e.target.checked ? "1" : null })} />
            Mostrar equipas sem obras
          </label>
          {hasFilters && (
            <button type="button" className="btn btn--ghost" onClick={clearFilters}>
              <Icon name="x" size={16} /> Limpar filtros
            </button>
          )}
          <button type="button" className="btn btn--sm btn--ghost" onClick={() => void handleCreateSavedView()} disabled={savedViewsSaving}>
            {savedViewsSaving ? "A guardar…" : "Guardar vista atual como…"}
          </button>
          <button type="button" className="btn btn--sm" onClick={handleSavePreferences} disabled={preferenceSaving || preferenceStatus === "loading"}>
            {preferenceSaving ? "A guardar…" : preferenceSaved ? "Vista fixada" : "Fixar vista"}
          </button>
          <button type="button" className="btn btn--sm btn--ghost" onClick={() => void handleResetPreferences()} disabled={preferenceSaving}>
            Repor vista
          </button>
          {savedViewsActionError && <span className="small text-danger" role="alert">{savedViewsActionError}</span>}
        </div>
      </div>

      {refreshing && data && (
        <div role="status" aria-label="A atualizar obras…" aria-live="polite" className="small muted">
          A atualizar obras…
        </div>
      )}
      {error && (
        <div className="card">
          <ErrorState message={error} onRetry={() => setReloadKey((k) => k + 1)} />
          {data && <p className="small muted">A mostrar a última versão confirmada enquanto tenta novamente.</p>}
        </div>
      )}
      {data === null && loading && !error && (
        <div className="card">
          <LoadingState label="A carregar obras…" rows={4} />
        </div>
      )}

      {data && (
        <>
          <p className="small muted" aria-live="polite" style={{ margin: "0 0 8px" }}>
            {formatIsoPt(win.from)} a {formatIsoPt(win.to)} · {data.summary.works} obra{data.summary.works === 1 ? "" : "s"}
            {data.summary.conflicts > 0 && <> · <strong className="text-danger">{data.summary.conflicts} em conflito</strong></>}
            {data.summary.estimated > 0 && <> · {data.summary.estimated} com datas estimadas</>}
            {data.summary.unscheduled > 0 && <> · {data.summary.unscheduled} por planear</>}
          </p>

          {data.works.length === 0 && !showIdle ? (
            <div className="card">
              <EmptyState
                icon="calendar"
                title="Nenhuma obra neste período"
                text={
                  hasFilters
                    ? "Nenhuma obra corresponde aos filtros escolhidos neste período."
                    : "Não há obras com datas neste período. Mude de período ou de escala."
                }
                action={
                  hasFilters ? (
                    <button type="button" className="btn btn--sm" onClick={clearFilters}>
                      Limpar filtros
                    </button>
                  ) : undefined
                }
              />
            </div>
          ) : (
            <div className="card" style={{ overflow: "hidden" }}>
              <WorksTimeline
                works={data.works}
                installers={installers}
                window={win}
                zoom={zoom}
                today={today}
                statuses={statuses}
                showIdle={showIdle}
                onPlanChange={changePlan}
                onOpenProject={(projectId) => openProjectOverlay(projectId)}
              />
            </div>
          )}

          <ul className="works__legend" aria-label="Legenda">
            <li>
              <span className="works__swatch works__swatch--estimated" /> Datas estimadas (ainda por confirmar)
            </li>
            <li>
              <span className="works__swatch works__swatch--conflict" /> A equipa tem outra obra sobreposta
            </li>
            <li>
              <span className="works__swatch works__swatch--today" /> Hoje
            </li>
          </ul>

          <Card title={`Por planear (${data.summary.unscheduled})`} icon="calendar" tone="warning">
            {data.unscheduled.length === 0 ? (
              <EmptyState compact title="Todas as obras em curso têm datas." />
            ) : (
              <>
                <p className="small muted" style={{ marginBottom: 8 }}>
                  Projetos ativos sem as duas datas da obra — não aparecem no calendário.
                </p>
                <ul className="works__unscheduled">
                  {data.unscheduled.map((p) => (
                    <li key={p.project_id}>
                      <Link to={`/projects/${p.project_id}`} onClick={(event) => handleProjectLinkClick(p.project_id, event)}>{p.name}</Link>
                      <span className="muted">
                        {p.pm_display_name ? ` · ${p.pm_display_name}` : " · sem PM"}
                        {p.installer_name ? ` · ${p.installer_name}${p.installer_team_name ? ` / ${p.installer_team_name}` : ""}` : ""}
                      </span>{" "}
                      <LifecycleBadge status={p.lifecycle_status} statuses={statuses} />
                      {(p.work_start_date || p.work_end_date) && (
                        <Badge tone="warning">
                          só {p.work_start_date ? `início ${formatIsoPt(p.work_start_date)}` : `fim ${formatIsoPt(p.work_end_date as string)}`}
                        </Badge>
                      )}
                    </li>
                  ))}
                </ul>
                {data.summary.unscheduled > data.unscheduled.length && (
                  <p className="small muted">A mostrar {data.unscheduled.length} de {data.summary.unscheduled}.</p>
                )}
              </>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
