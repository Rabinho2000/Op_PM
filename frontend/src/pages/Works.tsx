import LifecycleMultiSelect from "../components/LifecycleMultiSelect";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ApiError,
  getWorksCalendar,
  Installer,
  listInstallers,
  listPeople,
  Person,
  WorksCalendar,
} from "../api/client";
import Icon from "../components/Icon";
import { useLifecycleStatuses, LifecycleBadge } from "../components/LifecycleStatus";
import { Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader } from "../components/ui";
import WorksTimeline from "../components/WorksTimeline";
import { todayIsoLisbon } from "../utils/dates";
import { defaultWindow, formatIsoPt, shiftWindow, windowFrom, Zoom, ZOOMS } from "../utils/worksTimeline";

const ZOOM_KEYS = Object.keys(ZOOMS) as Zoom[];
const ISO_RE = /^\d{4}-\d{2}-\d{2}$/;

// Calendário de obras por instalador e equipa (D-072). Todo o estado (janela,
// zoom, filtros) vive no URL: a vista é partilhável e sobrevive a um refresh.
export default function Works() {
  const [params, setParams] = useSearchParams();
  const today = todayIsoLisbon();
  const statuses = useLifecycleStatuses();

  const zoomParam = params.get("zoom");
  const zoom: Zoom = ZOOM_KEYS.includes(zoomParam as Zoom) ? (zoomParam as Zoom) : "months";
  const fromParam = params.get("from");
  const win = useMemo(
    () => (fromParam && ISO_RE.test(fromParam) ? windowFrom(zoom, fromParam) : defaultWindow(zoom, today)),
    [zoom, fromParam, today]
  );
  const pm = params.get("pm") ?? "";
  const lifecycle = params.getAll("estado");
  const installerId = params.get("inst") ?? "";
  const teamId = params.get("equipa") ?? "";
  const showIdle = params.get("idle") === "1";

  const [installers, setInstallers] = useState<Installer[]>([]);
  const [people, setPeople] = useState<Person[]>([]);
  const [data, setData] = useState<WorksCalendar | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  function update(patch: Record<string, string | string[] | null>) {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const [key, value] of Object.entries(patch)) {
          next.delete(key);
          if (Array.isArray(value)) value.forEach((v) => next.append(key, v));
          else if (value) next.set(key, value);
        }
        return next;
      },
      { replace: true }
    );
  }

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
    let cancelled = false;
    setError(null);
    setData(null);
    getWorksCalendar({
      from: win.from,
      to: win.to,
      pm_person_id: pm || undefined,
      lifecycle_status: lifecycle.length > 0 ? lifecycle : undefined,
      installer_id: installerId || undefined,
      team_id: teamId || undefined,
    })
      .then((r) => !cancelled && setData(r))
      .catch((e) => !cancelled && setError(e instanceof ApiError ? e.detail : "Não foi possível contactar o servidor."));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [win.from, win.to, pm, lifecycleKey, installerId, teamId, reloadKey]);

  const teamOptions = useMemo(() => {
    const scope = installerId ? installers.filter((i) => i.id === installerId) : installers;
    return scope.flatMap((i) => i.teams.map((t) => ({ id: t.id, label: installerId ? t.name : `${i.name} — ${t.name}` })));
  }, [installers, installerId]);

  const hasFilters = Boolean(pm || lifecycle.length > 0 || installerId || teamId);
  const clearFilters = () => update({ pm: null, estado: null, inst: null, equipa: null });

  return (
    <>
      <PageHeader
        title="Calendário de obras"
        subtitle="As obras ao longo do tempo, por instalador e equipa."
      />

      <div className="toolbar" role="search" aria-label="Filtros do calendário de obras">
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
        </div>
      </div>

      {error && (
        <div className="card">
          <ErrorState message={error} onRetry={() => setReloadKey((k) => k + 1)} />
        </div>
      )}
      {!error && data === null && (
        <div className="card">
          <LoadingState label="A carregar obras…" rows={4} />
        </div>
      )}

      {!error && data && (
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
                      <Link to={`/projects/${p.project_id}`}>{p.name}</Link>
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
    </>
  );
}
