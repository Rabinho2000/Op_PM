// Planeamento (calendário): continua local nesta fase — sem Microsoft
// Graph, sem envio de email (D-010). O servidor já decide quem pode
// editar cada evento (`can_manage`, ver app/services/planning.py); esta
// página só filtra/apresenta e nunca infere permissões sozinha.
import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  cancelCalendarEvent,
  CalendarEvent,
  createCalendarEvent,
  listCalendarEvents,
  listPeople,
  listProjects,
  listTasks,
  Person,
  Project,
  Task,
  updateCalendarEvent,
} from "../api/client";
import Icon from "../components/Icon";
import { useToast } from "../components/Toast";
import { Alert, Badge, Card, EmptyState, ErrorState, LoadingState, Modal, PageHeader, Tone } from "../components/ui";
import { todayIsoLisbon } from "../utils/dates";

type ViewMode = "list" | "week" | "month";
type Scope = "all" | "mine" | "pm" | "project" | "responsible";

const EVENT_STATUS_TONES: Record<string, Tone> = {
  rascunho: "neutral",
  aprovado: "brand",
  publicado: "success",
  cancelado: "danger",
};

const LISBON_DATETIME_PARTS = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Europe/Lisbon",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

const LISBON_TIME_ONLY = new Intl.DateTimeFormat("pt-PT", {
  timeZone: "Europe/Lisbon",
  hour: "2-digit",
  minute: "2-digit",
});

function lisbonDateOf(isoDateTime: string): string {
  return todayIsoLisbon(new Date(isoDateTime));
}

function toDatetimeLocalValue(isoDateTime: string): string {
  const date = new Date(isoDateTime);
  if (Number.isNaN(date.getTime())) return "";
  const parts = LISBON_DATETIME_PARTS.formatToParts(date);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "00";
  return `${get("year")}-${get("month")}-${get("day")}T${get("hour")}:${get("minute")}`;
}

function formatTimePt(isoDateTime: string): string {
  const date = new Date(isoDateTime);
  if (Number.isNaN(date.getTime())) return "—";
  return LISBON_TIME_ONLY.format(date);
}

function parseIsoDate(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

function isoOfDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function addDays(iso: string, days: number): string {
  const date = parseIsoDate(iso);
  date.setUTCDate(date.getUTCDate() + days);
  return isoOfDate(date);
}

function addMonths(iso: string, months: number): string {
  const date = parseIsoDate(iso);
  date.setUTCMonth(date.getUTCMonth() + months, 1);
  return isoOfDate(date);
}

function startOfMonth(iso: string): string {
  const date = parseIsoDate(iso);
  date.setUTCDate(1);
  return isoOfDate(date);
}

function daysInMonth(iso: string): number {
  const date = parseIsoDate(iso);
  return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 0)).getUTCDate();
}

// 0 = segunda … 6 = domingo (semana começa à segunda, convenção PT).
function mondayFirstWeekday(iso: string): number {
  return (parseIsoDate(iso).getUTCDay() + 6) % 7;
}

function startOfWeek(iso: string): string {
  return addDays(iso, -mondayFirstWeekday(iso));
}

function formatDayHeaderPt(iso: string): string {
  const date = parseIsoDate(iso);
  return date.toLocaleDateString("pt-PT", { timeZone: "UTC", weekday: "short", day: "2-digit", month: "2-digit" });
}

function formatMonthTitlePt(iso: string): string {
  const date = parseIsoDate(iso);
  return date.toLocaleDateString("pt-PT", { timeZone: "UTC", month: "long", year: "numeric" });
}

interface ViewRange {
  startIso: string;
  endIso: string;
  days: string[];
}

function getViewRange(view: ViewMode, anchorIso: string): ViewRange {
  if (view === "week") {
    const startIso = startOfWeek(anchorIso);
    const days = Array.from({ length: 7 }, (_, i) => addDays(startIso, i));
    return { startIso, endIso: days[6], days };
  }
  if (view === "month") {
    const monthStart = startOfMonth(anchorIso);
    const gridStart = startOfWeek(monthStart);
    const monthEnd = addDays(monthStart, daysInMonth(anchorIso) - 1);
    const gridEnd = addDays(startOfWeek(monthEnd), 6);
    const totalDays = Math.round((parseIsoDate(gridEnd).getTime() - parseIsoDate(gridStart).getTime()) / 86_400_000) + 1;
    const days = Array.from({ length: totalDays }, (_, i) => addDays(gridStart, i));
    return { startIso: gridStart, endIso: gridEnd, days };
  }
  const startIso = anchorIso;
  const endIso = addDays(anchorIso, 13);
  const days = Array.from({ length: 14 }, (_, i) => addDays(startIso, i));
  return { startIso, endIso, days };
}

function eventsOverlap(aStart: string, aEnd: string, bStart: string, bEnd: string): boolean {
  return new Date(aStart) < new Date(bEnd) && new Date(bStart) < new Date(aEnd);
}

function findConflicts(
  events: CalendarEvent[],
  candidate: { id?: string; assigned_to_person_id: string; starts_at: string; ends_at: string }
): CalendarEvent[] {
  return events.filter(
    (e) =>
      e.id !== candidate.id &&
      e.status !== "cancelado" &&
      e.assigned_to_person_id === candidate.assigned_to_person_id &&
      eventsOverlap(candidate.starts_at, candidate.ends_at, e.starts_at, e.ends_at)
  );
}

function EventModal({
  event,
  defaultDate,
  projects,
  people,
  allEvents,
  onClose,
  onSaved,
}: {
  event: CalendarEvent | null;
  defaultDate: string | null;
  projects: Project[];
  people: Person[];
  allEvents: CalendarEvent[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    title: event?.title ?? "",
    project_id: event?.project_id ?? "",
    task_id: event?.task_id ?? "",
    assigned_to_person_id: event?.assigned_to_person_id ?? "",
    starts_at: event ? toDatetimeLocalValue(event.starts_at) : defaultDate ? `${defaultDate}T09:00` : "",
    ends_at: event ? toDatetimeLocalValue(event.ends_at) : defaultDate ? `${defaultDate}T10:00` : "",
  });
  const [tasks, setTasks] = useState<Task[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [conflictAcknowledged, setConflictAcknowledged] = useState(false);

  useEffect(() => {
    if (!form.project_id) {
      setTasks([]);
      return;
    }
    let cancelled = false;
    listTasks({ project_id: form.project_id })
      .then((t) => !cancelled && setTasks(t))
      .catch(() => !cancelled && setTasks([]));
    return () => {
      cancelled = true;
    };
  }, [form.project_id]);

  const conflicts = useMemo(() => {
    if (!form.assigned_to_person_id || !form.starts_at || !form.ends_at) return [];
    const startsIso = `${form.starts_at}:00`;
    const endsIso = `${form.ends_at}:00`;
    return findConflicts(allEvents, {
      id: event?.id,
      assigned_to_person_id: form.assigned_to_person_id,
      starts_at: startsIso,
      ends_at: endsIso,
    });
  }, [allEvents, event?.id, form.assigned_to_person_id, form.starts_at, form.ends_at]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!form.title.trim()) {
      setError("Indique o título do evento.");
      return;
    }
    if (!form.starts_at || !form.ends_at) {
      setError("Indique o início e o fim do evento.");
      return;
    }
    if (form.ends_at <= form.starts_at) {
      setError("A hora de fim tem de ser depois da hora de início.");
      return;
    }
    if (conflicts.length > 0 && !conflictAcknowledged) {
      setError("Existe uma sobreposição de horário para este responsável — confirme para continuar.");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        title: form.title.trim(),
        starts_at: `${form.starts_at}:00`,
        ends_at: `${form.ends_at}:00`,
        project_id: form.project_id || null,
        task_id: form.task_id || null,
        assigned_to_person_id: form.assigned_to_person_id || null,
      };
      if (event) {
        await updateCalendarEvent(event.id, payload);
      } else {
        await createCalendarEvent(payload);
      }
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Não foi possível guardar o evento.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={event ? "Reagendar evento" : "Novo evento"}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancelar
          </button>
          <button type="submit" form="event-form" className="btn btn--primary" disabled={saving}>
            {saving ? "A guardar…" : conflicts.length > 0 ? "Guardar mesmo assim" : "Guardar"}
          </button>
        </>
      }
    >
      {error && <Alert tone="danger">{error}</Alert>}
      {conflicts.length > 0 && (
        <Alert tone="warning">
          <strong>Sobreposição de horário</strong> para este responsável:
          <ul style={{ margin: "6px 0 8px", paddingLeft: 18 }}>
            {conflicts.map((c) => (
              <li key={c.id}>
                {c.title} ({formatTimePt(c.starts_at)}–{formatTimePt(c.ends_at)})
              </li>
            ))}
          </ul>
          <label className="checkbox small">
            <input
              type="checkbox"
              checked={conflictAcknowledged}
              onChange={(e) => setConflictAcknowledged(e.target.checked)}
            />
            Confirmo que quero continuar mesmo com esta sobreposição.
          </label>
        </Alert>
      )}
      <form id="event-form" className="form-grid" onSubmit={handleSubmit}>
        <div className="field span-2">
          <label htmlFor="e-title">Título *</label>
          <input id="e-title" className="input" value={form.title} onChange={(ev) => setForm({ ...form, title: ev.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="e-starts">Início *</label>
          <input
            id="e-starts"
            className="input"
            type="datetime-local"
            value={form.starts_at}
            onChange={(ev) => setForm({ ...form, starts_at: ev.target.value })}
          />
        </div>
        <div className="field">
          <label htmlFor="e-ends">Fim *</label>
          <input
            id="e-ends"
            className="input"
            type="datetime-local"
            value={form.ends_at}
            onChange={(ev) => setForm({ ...form, ends_at: ev.target.value })}
          />
        </div>
        <div className="field span-2">
          <label htmlFor="e-project">Projeto</label>
          <select
            id="e-project"
            className="select"
            value={form.project_id}
            onChange={(ev) => setForm({ ...form, project_id: ev.target.value, task_id: "" })}
          >
            <option value="">— nenhum —</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        {form.project_id && (
          <div className="field span-2">
            <label htmlFor="e-task">Tarefa associada</label>
            <select id="e-task" className="select" value={form.task_id} onChange={(ev) => setForm({ ...form, task_id: ev.target.value })}>
              <option value="">— nenhuma —</option>
              {tasks.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.title}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="field span-2">
          <label htmlFor="e-assignee">Responsável</label>
          <select
            id="e-assignee"
            className="select"
            value={form.assigned_to_person_id}
            onChange={(ev) => setForm({ ...form, assigned_to_person_id: ev.target.value })}
          >
            <option value="">— ninguém —</option>
            {people.map((p) => (
              <option key={p.id} value={p.id}>
                {p.display_name}
              </option>
            ))}
          </select>
        </div>
      </form>
    </Modal>
  );
}

function EventChip({ event, onClick }: { event: CalendarEvent; onClick: () => void }) {
  return (
    <button type="button" className="planning-chip" onClick={onClick}>
      <span className="planning-chip__time">{formatTimePt(event.starts_at)}</span>
      <span className="planning-chip__title">{event.title}</span>
    </button>
  );
}

export default function Planning() {
  const { notify } = useToast();
  const [view, setView] = useState<ViewMode>("week");
  const [anchorIso, setAnchorIso] = useState(() => todayIsoLisbon());
  const [scope, setScope] = useState<Scope>("all");
  const [scopePmId, setScopePmId] = useState("");
  const [scopeProjectId, setScopeProjectId] = useState("");
  const [scopeResponsibleId, setScopeResponsibleId] = useState("");

  const [events, setEvents] = useState<CalendarEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [people, setPeople] = useState<Person[]>([]);
  const [detailEvent, setDetailEvent] = useState<CalendarEvent | null>(null);
  const [editingEvent, setEditingEvent] = useState<CalendarEvent | null>(null);
  const [creatingForDate, setCreatingForDate] = useState<string | null>(null);

  const range = useMemo(() => getViewRange(view, anchorIso), [view, anchorIso]);

  useEffect(() => {
    listProjects({ is_active: true }).then(setProjects).catch(() => setProjects([]));
    listPeople().then(setPeople).catch(() => setPeople([]));
  }, []);

  const projectPmMap = useMemo(() => {
    const map = new Map<string, string | null>();
    for (const p of projects) map.set(p.id, p.pm_person_id);
    return map;
  }, [projects]);

  const pmOptions = useMemo(() => {
    const seen = new Map<string, string>();
    for (const p of projects) {
      if (p.pm_person_id && p.pm_display_name) seen.set(p.pm_person_id, p.pm_display_name);
    }
    return Array.from(seen.entries());
  }, [projects]);

  function load() {
    setError(null);
    listCalendarEvents({
      starts_from: `${range.startIso}T00:00:00`,
      starts_to: `${range.endIso}T23:59:59`,
      mine_only: scope === "mine",
      project_id: scope === "project" && scopeProjectId ? scopeProjectId : undefined,
      assigned_to_person_id: scope === "responsible" && scopeResponsibleId ? scopeResponsibleId : undefined,
    })
      .then(setEvents)
      .catch((e) => setError(e instanceof ApiError ? e.detail : "Não foi possível contactar o servidor."));
  }

  useEffect(load, [range.startIso, range.endIso, scope, scopeProjectId, scopeResponsibleId]);

  const filteredEvents = useMemo(() => {
    if (!events) return [];
    if (scope === "pm" && scopePmId) {
      return events.filter((e) => e.project_id && projectPmMap.get(e.project_id) === scopePmId);
    }
    return events;
  }, [events, scope, scopePmId, projectPmMap]);

  const eventsByDay = useMemo(() => {
    const map = new Map<string, CalendarEvent[]>();
    for (const e of filteredEvents) {
      const day = lisbonDateOf(e.starts_at);
      const bucket = map.get(day) ?? [];
      bucket.push(e);
      map.set(day, bucket);
    }
    for (const bucket of map.values()) bucket.sort((a, b) => a.starts_at.localeCompare(b.starts_at));
    return map;
  }, [filteredEvents]);

  async function handleCancel(event: CalendarEvent) {
    try {
      await cancelCalendarEvent(event.id);
      notify("Evento cancelado.", "success");
      setDetailEvent(null);
      load();
    } catch (err) {
      notify(err instanceof ApiError ? err.detail : "Não foi possível cancelar o evento.", "error");
    }
  }

  function navigate(delta: number) {
    if (view === "week") setAnchorIso(addDays(anchorIso, delta * 7));
    else if (view === "month") setAnchorIso(addMonths(anchorIso, delta));
    else setAnchorIso(addDays(anchorIso, delta * 14));
  }

  const rangeTitle = view === "month" ? formatMonthTitlePt(anchorIso) : `${formatDayHeaderPt(range.startIso)} – ${formatDayHeaderPt(range.endIso)}`;

  if (error) {
    return (
      <>
        <PageHeader title="Planeamento" />
        <div className="card">
          <ErrorState message={error} onRetry={load} />
        </div>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Planeamento"
        subtitle="Calendário de visitas, comissionamentos e outras marcações — local, sem sincronização externa."
        actions={
          <button type="button" className="btn btn--primary btn--sm" onClick={() => setCreatingForDate(anchorIso)}>
            <Icon name="plus" size={14} /> Novo evento
          </button>
        }
      />

      <form className="toolbar" role="search" aria-label="Filtros de planeamento" onSubmit={(e) => e.preventDefault()}>
        <div className="field">
          <label htmlFor="pl-view">Vista</label>
          <select id="pl-view" className="select" value={view} onChange={(e) => setView(e.target.value as ViewMode)}>
            <option value="week">Semana</option>
            <option value="month">Mês</option>
            <option value="list">Lista</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="pl-scope">Ver</label>
          <select id="pl-scope" className="select" value={scope} onChange={(e) => setScope(e.target.value as Scope)}>
            <option value="all">Todos</option>
            <option value="mine">Meus</option>
            <option value="pm">Por PM</option>
            <option value="project">Por projeto</option>
            <option value="responsible">Por responsável</option>
          </select>
        </div>
        {scope === "pm" && (
          <div className="field">
            <label htmlFor="pl-pm">PM</label>
            <select id="pl-pm" className="select" value={scopePmId} onChange={(e) => setScopePmId(e.target.value)}>
              <option value="">Escolha um PM</option>
              {pmOptions.map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
            </select>
          </div>
        )}
        {scope === "project" && (
          <div className="field">
            <label htmlFor="pl-project">Projeto</label>
            <select id="pl-project" className="select" value={scopeProjectId} onChange={(e) => setScopeProjectId(e.target.value)}>
              <option value="">Escolha um projeto</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
        )}
        {scope === "responsible" && (
          <div className="field">
            <label htmlFor="pl-responsible">Responsável</label>
            <select
              id="pl-responsible"
              className="select"
              value={scopeResponsibleId}
              onChange={(e) => setScopeResponsibleId(e.target.value)}
            >
              <option value="">Escolha uma pessoa</option>
              {people.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.display_name}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="field">
          <span>Período</span>
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <button type="button" className="btn btn--sm" onClick={() => navigate(-1)} aria-label="Período anterior">
              <Icon name="chevronLeft" size={14} />
            </button>
            <button type="button" className="btn btn--sm" onClick={() => setAnchorIso(todayIsoLisbon())}>
              Hoje
            </button>
            <button type="button" className="btn btn--sm" onClick={() => navigate(1)} aria-label="Período seguinte">
              <Icon name="chevronRight" size={14} />
            </button>
          </div>
        </div>
      </form>

      <Card title={rangeTitle} icon="calendar" flush>
        {events === null ? (
          <LoadingState rows={6} />
        ) : filteredEvents.length === 0 ? (
          <EmptyState compact icon="calendar" title="Sem eventos neste período com estes filtros." />
        ) : view === "list" ? (
          <ul className="list">
            {range.days
              .filter((day) => (eventsByDay.get(day) ?? []).length > 0)
              .map((day) => (
                <li key={day} className="list__item" style={{ flexDirection: "column", alignItems: "stretch", gap: 6 }}>
                  <div className="list__title">{formatDayHeaderPt(day)}</div>
                  {(eventsByDay.get(day) ?? []).map((e) => (
                    <button
                      key={e.id}
                      type="button"
                      className="list__main"
                      style={{ background: "none", border: 0, padding: "4px 0", textAlign: "left", cursor: "pointer" }}
                      onClick={() => setDetailEvent(e)}
                    >
                      <span className="list__title">
                        {formatTimePt(e.starts_at)}–{formatTimePt(e.ends_at)} · {e.title}
                      </span>
                      <div className="list__meta">
                        {e.project_name ?? "sem projeto"}
                        {e.assigned_to_display_name ? ` · ${e.assigned_to_display_name}` : ""}
                      </div>
                    </button>
                  ))}
                </li>
              ))}
          </ul>
        ) : view === "week" ? (
          <div className="planning-week">
            {range.days.map((day) => (
              <div key={day} className="planning-week__day">
                <div className="planning-week__header">
                  <span>{formatDayHeaderPt(day)}</span>
                  <button type="button" className="planning-week__add" aria-label={`Novo evento em ${day}`} onClick={() => setCreatingForDate(day)}>
                    <Icon name="plus" size={12} />
                  </button>
                </div>
                <div className="planning-week__events">
                  {(eventsByDay.get(day) ?? []).map((e) => (
                    <EventChip key={e.id} event={e} onClick={() => setDetailEvent(e)} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="planning-month">
            {range.days.map((day) => {
              const dayEvents = eventsByDay.get(day) ?? [];
              const inMonth = day.slice(0, 7) === anchorIso.slice(0, 7);
              return (
                <div key={day} className={`planning-month__day${inMonth ? "" : " planning-month__day--muted"}`}>
                  <div className="planning-month__header">
                    <span>{Number(day.slice(8, 10))}</span>
                    <button type="button" className="planning-week__add" aria-label={`Novo evento em ${day}`} onClick={() => setCreatingForDate(day)}>
                      <Icon name="plus" size={12} />
                    </button>
                  </div>
                  {dayEvents.slice(0, 3).map((e) => (
                    <EventChip key={e.id} event={e} onClick={() => setDetailEvent(e)} />
                  ))}
                  {dayEvents.length > 3 && <div className="planning-month__more">+{dayEvents.length - 3} mais</div>}
                </div>
              );
            })}
          </div>
        )}
      </Card>

      {detailEvent && (
        <Modal
          title={detailEvent.title}
          onClose={() => setDetailEvent(null)}
          footer={
            detailEvent.can_manage && detailEvent.status !== "cancelado" ? (
              <>
                <button type="button" className="btn btn--danger" onClick={() => handleCancel(detailEvent)}>
                  Cancelar evento
                </button>
                <button
                  type="button"
                  className="btn btn--primary"
                  onClick={() => {
                    setEditingEvent(detailEvent);
                    setDetailEvent(null);
                  }}
                >
                  Reagendar
                </button>
              </>
            ) : undefined
          }
        >
          <dl className="kv">
            <dt>Estado</dt>
            <dd>
              <Badge tone={EVENT_STATUS_TONES[detailEvent.status] ?? "neutral"}>{detailEvent.status}</Badge>
            </dd>
            <dt>Início</dt>
            <dd>
              {formatDayHeaderPt(lisbonDateOf(detailEvent.starts_at))} · {formatTimePt(detailEvent.starts_at)}
            </dd>
            <dt>Fim</dt>
            <dd>
              {formatDayHeaderPt(lisbonDateOf(detailEvent.ends_at))} · {formatTimePt(detailEvent.ends_at)}
            </dd>
            {detailEvent.project_id && (
              <>
                <dt>Projeto</dt>
                <dd>
                  <Link to={`/projects/${detailEvent.project_id}`}>{detailEvent.project_name}</Link>
                </dd>
              </>
            )}
            {detailEvent.task_title && (
              <>
                <dt>Tarefa</dt>
                <dd>{detailEvent.task_title}</dd>
              </>
            )}
            <dt>Responsável</dt>
            <dd>{detailEvent.assigned_to_display_name ?? "—"}</dd>
          </dl>
        </Modal>
      )}

      {(creatingForDate !== null || editingEvent) && (
        <EventModal
          event={editingEvent}
          defaultDate={creatingForDate}
          projects={projects}
          people={people}
          allEvents={events ?? []}
          onClose={() => {
            setCreatingForDate(null);
            setEditingEvent(null);
          }}
          onSaved={() => {
            notify(editingEvent ? "Evento atualizado." : "Evento criado.", "success");
            setCreatingForDate(null);
            setEditingEvent(null);
            load();
          }}
        />
      )}
    </>
  );
}
