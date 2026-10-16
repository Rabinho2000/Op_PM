// Planeamento (calendário): dados manuais e projeções read-only do Processo.
// O servidor é a fonte de verdade para visibilidade, permissões, categorias e
// responsáveis; esta página só compõe a vista e envia referências válidas.
import { CSSProperties, FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  CalendarEvent,
  CalendarEventCategory,
  cancelCalendarEvent,
  createCalendarEvent,
  getPlanningPreferences,
  getPlanningProcessOptions,
  listCalendarEvents,
  listPeople,
  listPlanningEventCategories,
  listProcessCalendarEvents,
  listProjects,
  listTasks,
  Person,
  PlanningProcessOption,
  Project,
  Task,
  updateCalendarEvent,
  updatePlanningPreferences,
} from "../api/client";
import Icon from "../components/Icon";
import { useToast } from "../components/Toast";
import { Alert, Avatar, Badge, Card, EmptyState, ErrorState, LoadingState, Modal, PageHeader, Tone } from "../components/ui";
import { lisbonWallClockToIso, todayIsoLisbon } from "../utils/dates";
import "./Planning.css";

type ViewMode = "list" | "week" | "month";
type Scope = "all" | "mine" | "pm" | "project" | "responsible" | "team";
type StatusFilter = "active" | "cancelled" | "all";

const EVENT_STATUS_TONES: Record<string, Tone> = {
  rascunho: "neutral",
  aprovado: "brand",
  publicado: "success",
  cancelado: "danger",
  projected: "violet",
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

const NATURAL_PROJECT_COLLATOR = new Intl.Collator("pt-PT", { numeric: true, sensitivity: "base" });
const PERSON_COLLATOR = new Intl.Collator("pt-PT", { sensitivity: "base" });

export function normalizePlanningSearch(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase("pt-PT")
    .trim();
}

export function sortProjectsNaturally(projects: Project[]): Project[] {
  return [...projects].sort((a, b) => NATURAL_PROJECT_COLLATOR.compare(a.name, b.name) || a.id.localeCompare(b.id));
}

function sortedPeople(people: Person[]): Person[] {
  return [...people].filter((person) => person.is_active).sort((a, b) => PERSON_COLLATOR.compare(a.display_name, b.display_name) || a.id.localeCompare(b.id));
}

function lisbonDateOf(isoDateTime: string): string {
  const date = new Date(isoDateTime);
  if (Number.isNaN(date.getTime())) return isoDateTime.slice(0, 10);
  return todayIsoLisbon(date);
}

function toDatetimeLocalValue(isoDateTime: string): string {
  const date = new Date(isoDateTime);
  if (Number.isNaN(date.getTime())) return "";
  const parts = LISBON_DATETIME_PARTS.formatToParts(date);
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? "00";
  return `${get("year")}-${get("month")}-${get("day")}T${get("hour")}:${get("minute")}`;
}

function formatTimePt(isoDateTime: string): string {
  const date = new Date(isoDateTime);
  if (Number.isNaN(date.getTime())) return "—";
  return LISBON_TIME_ONLY.format(date);
}

function parseIsoDate(iso: string): Date {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day));
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
  return date.toLocaleDateString("pt-PT", { timeZone: "UTC", weekday: "long", day: "2-digit", month: "2-digit" });
}

function formatMonthTitlePt(iso: string): string {
  const date = parseIsoDate(iso);
  return date.toLocaleDateString("pt-PT", { timeZone: "UTC", month: "long", year: "numeric" });
}

function isWeekend(iso: string): boolean {
  const weekday = parseIsoDate(iso).getUTCDay();
  return weekday === 0 || weekday === 6;
}

interface ViewRange {
  startIso: string;
  endIso: string;
  days: string[];
}

export function getPlanningViewRange(view: ViewMode, anchorIso: string): ViewRange {
  if (view === "week") {
    const startIso = startOfWeek(anchorIso);
    const days = Array.from({ length: 7 }, (_, index) => addDays(startIso, index));
    return { startIso, endIso: days[6], days };
  }
  if (view === "month") {
    const monthStart = startOfMonth(anchorIso);
    const gridStart = startOfWeek(monthStart);
    const monthEnd = addDays(monthStart, daysInMonth(anchorIso) - 1);
    const gridEnd = addDays(startOfWeek(monthEnd), 6);
    const totalDays = Math.round((parseIsoDate(gridEnd).getTime() - parseIsoDate(gridStart).getTime()) / 86_400_000) + 1;
    const days = Array.from({ length: totalDays }, (_, index) => addDays(gridStart, index));
    return { startIso: gridStart, endIso: gridEnd, days };
  }
  const startIso = anchorIso;
  const endIso = addDays(anchorIso, 13);
  const days = Array.from({ length: 14 }, (_, index) => addDays(startIso, index));
  return { startIso, endIso, days };
}

export function eventsOverlap(aStart: string, aEnd: string, bStart: string, bEnd: string): boolean {
  const startsA = new Date(aStart).getTime();
  const endsA = new Date(aEnd).getTime();
  const startsB = new Date(bStart).getTime();
  const endsB = new Date(bEnd).getTime();
  if ([startsA, endsA, startsB, endsB].some((value) => Number.isNaN(value))) return false;
  return startsA < endsB && startsB < endsA;
}

function dedupeIds(ids: (string | null | undefined)[]): string[] {
  return ids.filter((id, index, all): id is string => Boolean(id) && all.indexOf(id) === index);
}

export function eventParticipantIds(event: CalendarEvent): string[] {
  return dedupeIds([
    ...(event.assigned_to_person_ids ?? []),
    event.assigned_to_person_id,
    ...(event.responsible_person_ids ?? []),
  ]);
}

export function findPlanningConflicts(
  events: CalendarEvent[],
  candidate: {
    id?: string;
    assigned_to_person_id?: string | null;
    assigned_to_person_ids?: string[];
    starts_at: string;
    ends_at: string;
  },
): CalendarEvent[] {
  const candidatePeople = new Set(
    dedupeIds([...(candidate.assigned_to_person_ids ?? []), candidate.assigned_to_person_id])
  );
  if (candidatePeople.size === 0) return [];
  return events.filter((event) => {
    if (event.id === candidate.id || event.status === "cancelado") return false;
    const sharesPerson = eventParticipantIds(event).some((personId) => candidatePeople.has(personId));
    return sharesPerson && eventsOverlap(candidate.starts_at, candidate.ends_at, event.starts_at, event.ends_at);
  });
}

function canonicalInstant(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toISOString();
}

function processReferenceKey(event: CalendarEvent): string | null {
  if (!event.project_id || (!event.process_stage_id && !event.process_subtask_id)) return null;
  return [
    event.project_id,
    event.process_stage_id ?? "",
    event.process_subtask_id ?? "",
    canonicalInstant(event.starts_at),
    canonicalInstant(event.ends_at),
  ].join("|");
}

export function mergePlanningEvents(manualEvents: CalendarEvent[], processEvents: CalendarEvent[]): CalendarEvent[] {
  const result: CalendarEvent[] = [];
  const keys = new Set<string>();
  for (const event of manualEvents) {
    const key = processReferenceKey(event);
    if (key) keys.add(key);
    result.push(event);
  }
  for (const event of processEvents) {
    const key = processReferenceKey(event);
    if (key && keys.has(key)) continue;
    if (key) keys.add(key);
    result.push(event);
  }
  return result.sort((a, b) => a.starts_at.localeCompare(b.starts_at) || a.id.localeCompare(b.id));
}

function eventCategoryMeta(event: CalendarEvent, categories: CalendarEventCategory[]): { label: string; color: string } {
  const category = categories.find((item) => item.code === event.category);
  return {
    label: event.category_label ?? category?.label ?? event.category ?? "Evento",
    color: event.category_color ?? category?.color ?? "var(--planning-category-fallback)",
  };
}

function projectUrlFor(event: CalendarEvent): string | null {
  if (event.project_url) return event.project_url;
  return event.project_id ? `/projects/${event.project_id}` : null;
}

function PlanningProjectCombobox({
  id,
  label,
  projects,
  value,
  onChange,
  placeholder,
}: {
  id: string;
  label: string;
  projects: Project[];
  value: string;
  onChange: (projectId: string) => void;
  placeholder: string;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const selectedProject = projects.find((project) => project.id === value);
  const [query, setQuery] = useState(selectedProject?.name ?? "");
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const listboxId = `${id}-options`;

  useEffect(() => {
    if (!open) setQuery(selectedProject?.name ?? "");
  }, [open, selectedProject?.id, selectedProject?.name]);

  const visibleProjects = useMemo(() => {
    const ordered = sortProjectsNaturally(projects);
    const normalized = normalizePlanningSearch(query);
    const matching = normalized.length === 0
      ? ordered
      : ordered.filter((project) => normalizePlanningSearch(project.name).includes(normalized));
    if (selectedProject && !matching.some((project) => project.id === selectedProject.id)) {
      return [selectedProject, ...matching];
    }
    return matching;
  }, [projects, query, selectedProject]);

  useEffect(() => {
    setActiveIndex((index) => Math.min(index, Math.max(visibleProjects.length - 1, 0)));
  }, [visibleProjects.length]);

  useEffect(() => {
    if (!open) return undefined;
    const handleOutsideMouseDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
        if (selectedProject) setQuery(selectedProject.name);
      }
    };
    document.addEventListener("mousedown", handleOutsideMouseDown);
    return () => document.removeEventListener("mousedown", handleOutsideMouseDown);
  }, [open, selectedProject]);

  function selectProject(project: Project) {
    onChange(project.id);
    setQuery(project.name);
    setOpen(false);
    setActiveIndex(0);
  }

  function clearSelection() {
    onChange("");
    setQuery("");
    setOpen(false);
    setActiveIndex(0);
  }

  return (
    <div className="planning-combobox" ref={rootRef}>
      <label htmlFor={id}>{label}</label>
      <div className="planning-combobox__control">
        <input
          id={id}
          className="input planning-combobox__input"
          role="combobox"
          aria-autocomplete="list"
          aria-controls={listboxId}
          aria-expanded={open}
          aria-activedescendant={open && visibleProjects[activeIndex] ? `${id}-option-${visibleProjects[activeIndex].id}` : undefined}
          placeholder={placeholder}
          value={query}
          data-selected-id={value}
          onFocus={() => setOpen(true)}
          onClick={() => setOpen(true)}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
            setActiveIndex(0);
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setOpen(true);
              setActiveIndex((index) => Math.min(index + 1, Math.max(visibleProjects.length - 1, 0)));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setOpen(true);
              setActiveIndex((index) => Math.max(index - 1, 0));
            } else if (event.key === "Enter" && open && visibleProjects[activeIndex]) {
              event.preventDefault();
              selectProject(visibleProjects[activeIndex]);
            } else if (event.key === "Escape") {
              event.preventDefault();
              setOpen(false);
              setQuery(selectedProject?.name ?? "");
            }
          }}
        />
        {(value || query) && (
          <button type="button" className="planning-combobox__clear" aria-label={`Limpar ${label}`} onClick={clearSelection}>
            <Icon name="x" size={14} />
          </button>
        )}
      </div>
      {open && (
        <div className="planning-combobox__menu" id={listboxId} role="listbox" aria-label={`Resultados de ${label}`}>
          {visibleProjects.length === 0 ? (
            <div className="planning-combobox__empty">Nenhum projeto encontrado.</div>
          ) : (
            visibleProjects.map((project, index) => (
              <div
                id={`${id}-option-${project.id}`}
                key={project.id}
                role="option"
                aria-selected={project.id === value}
                className={`planning-combobox__option${index === activeIndex ? " planning-combobox__option--active" : ""}`}
                onMouseDown={(event) => {
                  event.preventDefault();
                  selectProject(project);
                }}
              >
                <span>{project.name}</span>
                {project.id === value && <span className="planning-combobox__selected">Selecionado</span>}
              </div>
            ))
          )}
        </div>
      )}
      <input type="hidden" name={`${id}-value`} value={value} readOnly aria-hidden="true" />
    </div>
  );
}

function ParticipantPicker({
  people,
  selectedIds,
  onChange,
}: {
  people: Person[];
  selectedIds: string[];
  onChange: (ids: string[]) => void;
}) {
  const options = sortedPeople(people);
  return (
    <fieldset className="planning-participant-picker">
      <legend>Responsáveis</legend>
      <div className="planning-participant-picker__grid">
        {options.map((person) => {
          const checkboxId = `event-person-${person.id}`;
          const checked = selectedIds.includes(person.id);
          return (
            <label key={person.id} htmlFor={checkboxId} className="planning-person-option">
              <input
                id={checkboxId}
                type="checkbox"
                aria-label={person.display_name}
                checked={checked}
                onChange={(event) => {
                  const next = event.target.checked
                    ? [...selectedIds, person.id]
                    : selectedIds.filter((id) => id !== person.id);
                  onChange(dedupeIds(next));
                }}
              />
              <Avatar name={person.display_name} small />
              <span>{person.display_name}</span>
            </label>
          );
        })}
      </div>
      {options.length === 0 && <span className="muted">Sem pessoas disponíveis neste âmbito.</span>}
    </fieldset>
  );
}

function ParticipantSummary({ event, people }: { event: CalendarEvent; people: Person[] }) {
  let names = event.assigned_to_display_names?.length ? event.assigned_to_display_names : [];
  if (names.length === 0 && event.assigned_to_display_name) names = [event.assigned_to_display_name];
  if (names.length === 0) {
    names = eventParticipantIds(event).map((id) => people.find((person) => person.id === id)?.display_name ?? "Pessoa desconhecida");
  }
  if (names.length === 0) return <span className="muted">—</span>;
  return (
    <span className="planning-participants" aria-label={`Responsáveis: ${names.join(", ")}`}>
      {names.map((name, index) => (
        <span className="planning-participant" key={`${name}-${index}`}>
          <Avatar name={name} small />
          <span>{name}</span>
        </span>
      ))}
    </span>
  );
}

interface EventFormState {
  title: string;
  project_id: string;
  task_id: string;
  assigned_to_person_id: string;
  assigned_to_person_ids: string[];
  category: string;
  process_stage_id: string;
  process_subtask_id: string;
  starts_at: string;
  ends_at: string;
}

function initialEventForm(event: CalendarEvent | null, defaultDate: string | null, categories: CalendarEventCategory[]): EventFormState {
  const assignedIds = event
    ? dedupeIds([...(event.assigned_to_person_ids ?? []), event.assigned_to_person_id])
    : [];
  return {
    title: event?.title ?? "",
    project_id: event?.project_id ?? "",
    task_id: event?.task_id ?? "",
    assigned_to_person_id: assignedIds[0] ?? "",
    assigned_to_person_ids: assignedIds,
    category: event?.category ?? categories[0]?.code ?? "other",
    process_stage_id: event?.process_stage_id ?? "",
    process_subtask_id: event?.process_subtask_id ?? "",
    starts_at: event ? toDatetimeLocalValue(event.starts_at) : defaultDate ? `${defaultDate}T09:00` : "",
    ends_at: event ? toDatetimeLocalValue(event.ends_at) : defaultDate ? `${defaultDate}T10:00` : "",
  };
}

function EventModal({
  event,
  defaultDate,
  projects,
  people,
  categories,
  allEvents,
  onClose,
  onSaved,
}: {
  event: CalendarEvent | null;
  defaultDate: string | null;
  projects: Project[];
  people: Person[];
  categories: CalendarEventCategory[];
  allEvents: CalendarEvent[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<EventFormState>(() => initialEventForm(event, defaultDate, categories));
  const [tasks, setTasks] = useState<Task[]>([]);
  const [processOptions, setProcessOptions] = useState<PlanningProcessOption[]>([]);
  const [tasksLoading, setTasksLoading] = useState(false);
  const [processLoading, setProcessLoading] = useState(false);
  const [tasksError, setTasksError] = useState<string | null>(null);
  const [processError, setProcessError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [conflictAcknowledged, setConflictAcknowledged] = useState(false);

  useEffect(() => {
    const projectId = form.project_id;
    let cancelled = false;
    setTasksError(null);
    setProcessError(null);
    if (!projectId) {
      setTasks([]);
      setProcessOptions([]);
      setTasksLoading(false);
      setProcessLoading(false);
      return () => {
        cancelled = true;
      };
    }

    setTasksLoading(true);
    setProcessLoading(true);
    Promise.allSettled([listTasks({ project_id: projectId }), getPlanningProcessOptions(projectId)]).then(([taskResult, processResult]) => {
      if (cancelled) return;
      if (taskResult.status === "fulfilled") setTasks(taskResult.value);
      else {
        setTasks([]);
        setTasksError(taskResult.reason instanceof ApiError ? taskResult.reason.detail : "Não foi possível carregar as tarefas do projeto.");
      }
      if (processResult.status === "fulfilled") setProcessOptions(processResult.value);
      else {
        setProcessOptions([]);
        setProcessError(processResult.reason instanceof ApiError ? processResult.reason.detail : "Não foi possível carregar as opções do Processo.");
      }
      setTasksLoading(false);
      setProcessLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [form.project_id]);

  const selectedStage = processOptions.find((option) => option.stage_id === form.process_stage_id);
  const conflicts = useMemo(() => {
    if (!form.starts_at || !form.ends_at) return [];
    try {
      return findPlanningConflicts(allEvents, {
        id: event?.id,
        assigned_to_person_id: form.assigned_to_person_id || null,
        assigned_to_person_ids: form.assigned_to_person_ids,
        starts_at: lisbonWallClockToIso(form.starts_at),
        ends_at: lisbonWallClockToIso(form.ends_at),
      });
    } catch {
      return [];
    }
  }, [allEvents, event?.id, form.assigned_to_person_id, form.assigned_to_person_ids, form.starts_at, form.ends_at]);

  useEffect(() => {
    setConflictAcknowledged(false);
  }, [form.assigned_to_person_id, form.assigned_to_person_ids, form.starts_at, form.ends_at]);

  function updateAssignedPeople(ids: string[]) {
    const unique = dedupeIds(ids);
    setForm((current) => ({ ...current, assigned_to_person_ids: unique, assigned_to_person_id: unique[0] ?? "" }));
  }

  function selectProject(projectId: string) {
    setForm((current) => ({
      ...current,
      project_id: projectId,
      task_id: "",
      process_stage_id: "",
      process_subtask_id: "",
    }));
  }

  async function handleSubmit(eventSubmit: FormEvent) {
    eventSubmit.preventDefault();
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
    if (!form.category) {
      setError("Escolha uma categoria.");
      return;
    }
    if (conflicts.length > 0 && !conflictAcknowledged) {
      setError("Existe uma sobreposição de horário para um dos responsáveis — confirme para continuar.");
      return;
    }
    setSaving(true);
    try {
      const common = {
        title: form.title.trim(),
        starts_at: lisbonWallClockToIso(form.starts_at),
        ends_at: lisbonWallClockToIso(form.ends_at),
        project_id: form.project_id || null,
        task_id: form.task_id || null,
        assigned_to_person_id: form.assigned_to_person_id || null,
        assigned_to_person_ids: form.assigned_to_person_ids,
        category: form.category,
        process_stage_id: form.process_stage_id || null,
        process_subtask_id: form.process_subtask_id || null,
      };
      if (event) await updateCalendarEvent(event.id, common);
      else await createCalendarEvent(common);
      onSaved();
    } catch (saveError) {
      setError(saveError instanceof ApiError ? saveError.detail : "Não foi possível guardar o evento.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={event ? "Editar evento" : "Novo evento"}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} disabled={saving}>
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
          <strong>Sobreposição de horário</strong> para um dos responsáveis:
          <ul className="planning-conflict-list">
            {conflicts.map((conflict) => (
              <li key={conflict.id}>
                {conflict.title} ({formatTimePt(conflict.starts_at)}–{formatTimePt(conflict.ends_at)})
              </li>
            ))}
          </ul>
          <label className="checkbox small">
            <input
              type="checkbox"
              checked={conflictAcknowledged}
              onChange={(change) => setConflictAcknowledged(change.target.checked)}
            />
            Confirmo que quero continuar mesmo com esta sobreposição.
          </label>
        </Alert>
      )}
      <form id="event-form" className="form-grid planning-event-form" onSubmit={handleSubmit}>
        <div className="field span-2">
          <label htmlFor="e-title">Título *</label>
          <input id="e-title" className="input" value={form.title} onChange={(change) => setForm({ ...form, title: change.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="e-starts">Início *</label>
          <input id="e-starts" className="input" type="datetime-local" value={form.starts_at} onChange={(change) => setForm({ ...form, starts_at: change.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="e-ends">Fim *</label>
          <input id="e-ends" className="input" type="datetime-local" value={form.ends_at} onChange={(change) => setForm({ ...form, ends_at: change.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="e-category">Categoria</label>
          <select id="e-category" className="select" value={form.category} onChange={(change) => setForm({ ...form, category: change.target.value })} disabled={categories.length === 0}>
            {categories.length === 0 ? <option value="">Catálogo indisponível</option> : categories.map((category) => <option key={category.code} value={category.code}>{category.label}</option>)}
          </select>
        </div>
        <div className="field planning-event-source-note">
          <span>Origem</span>
          <span className="small">{event?.source === "process" ? "Processo (read-only)" : "Manual"}</span>
        </div>
        <div className="field span-2">
          <PlanningProjectCombobox id="e-project" label="Projeto" projects={projects} value={form.project_id} onChange={selectProject} placeholder="Pesquisar projeto…" />
        </div>
        {form.project_id && (
          <>
            <div className="field span-2">
              <label htmlFor="e-task">Tarefa normal associada</label>
              <select id="e-task" className="select" value={form.task_id} onChange={(change) => setForm({ ...form, task_id: change.target.value })} disabled={tasksLoading}>
                <option value="">— nenhuma —</option>
                {tasks.map((task) => <option key={task.id} value={task.id}>{task.title}</option>)}
              </select>
              {tasksLoading && <span className="field__hint">A carregar tarefas…</span>}
              {tasksError && <span className="field__error">{tasksError}</span>}
            </div>
            <div className="planning-process-fields span-2">
              <div className="planning-process-fields__heading">
                <strong>Ligação ao Processo</strong>
                <span className="small muted">Não cria nem altera tarefas do Processo.</span>
              </div>
              {processLoading && <span className="field__hint">A carregar etapas…</span>}
              {processError && <Alert tone="danger">{processError}</Alert>}
              {!processLoading && !processError && processOptions.length === 0 && <span className="field__hint">Sem etapas disponíveis para este projeto.</span>}
              {processOptions.length > 0 && (
                <div className="form-grid planning-process-fields__grid">
                  <div className="field">
                    <label htmlFor="e-process-stage">Etapa do Processo</label>
                    <select
                      id="e-process-stage"
                      className="select"
                      value={form.process_stage_id}
                      onChange={(change) => setForm({ ...form, process_stage_id: change.target.value, process_subtask_id: "" })}
                      disabled={processLoading}
                    >
                      <option value="">— nenhuma —</option>
                      {processOptions.map((option) => <option key={option.stage_id} value={option.stage_id}>{option.stage_code} — {option.stage_title}</option>)}
                    </select>
                  </div>
                  <div className="field">
                    <label htmlFor="e-process-subtask">Subtarefa do Processo</label>
                    <select
                      id="e-process-subtask"
                      className="select"
                      value={form.process_subtask_id}
                      onChange={(change) => setForm({ ...form, process_subtask_id: change.target.value })}
                      disabled={!selectedStage || processLoading}
                    >
                      <option value="">— nenhuma —</option>
                      {(selectedStage?.subtasks ?? []).map((subtask) => <option key={subtask.id} value={subtask.id}>{subtask.code} — {subtask.title}</option>)}
                    </select>
                  </div>
                </div>
              )}
              {selectedStage?.responsible_display_names.length ? <span className="field__hint">Responsáveis do Processo: {selectedStage.responsible_display_names.join(", ")}</span> : null}
            </div>
          </>
        )}
        <div className="span-2">
          <ParticipantPicker people={people} selectedIds={form.assigned_to_person_ids} onChange={updateAssignedPeople} />
        </div>
      </form>
    </Modal>
  );
}

function EventChip({
  event,
  categories,
  onClick,
  as = "button",
}: {
  event: CalendarEvent;
  categories: CalendarEventCategory[];
  onClick?: () => void;
  as?: "button" | "span";
}) {
  const meta = eventCategoryMeta(event, categories);
  const sourceLabel = event.source === "process" ? "Processo" : "Manual";
  const participants = event.assigned_to_display_names?.length ? event.assigned_to_display_names.join(", ") : event.assigned_to_display_name ?? "sem responsáveis";
  const content = (
    <>
      <span className="planning-event-chip__dot" aria-hidden="true" />
      <span className="planning-event-chip__time">{formatTimePt(event.starts_at)}</span>
      <span className="planning-event-chip__title">{event.title}</span>
      {event.source === "process" && <span className="planning-event-chip__source" aria-hidden="true">P</span>}
    </>
  );
  const style = { "--planning-event-color": meta.color } as CSSProperties;

  if (as === "span") {
    return <span className="planning-event-chip" style={style}>{content}</span>;
  }

  return (
    <button
      type="button"
      className="planning-event-chip"
      style={style}
      onClick={onClick}
      aria-label={`${event.title}, ${meta.label}, ${sourceLabel}, responsáveis: ${participants}`}
    >
      {content}
    </button>
  );
}

function CategoryLegend({ categories }: { categories: CalendarEventCategory[] }) {
  if (categories.length === 0) return null;
  return (
    <div className="planning-category-legend" aria-label="Legenda de categorias">
      {categories.map((category) => (
        <span key={category.code} className="planning-category-legend__item">
          <span className="planning-category-legend__swatch" style={{ backgroundColor: category.color }} aria-hidden="true" />
          <span>{category.label}</span>
        </span>
      ))}
    </div>
  );
}

function EventDetailModal({
  event,
  people,
  categories,
  onClose,
  onEdit,
  onCancel,
}: {
  event: CalendarEvent;
  people: Person[];
  categories: CalendarEventCategory[];
  onClose: () => void;
  onEdit: () => void;
  onCancel: () => void;
}) {
  const meta = eventCategoryMeta(event, categories);
  const processEvent = event.source === "process";
  const projectUrl = projectUrlFor(event);
  const responsibleNames = event.responsible_display_names?.length
    ? event.responsible_display_names
    : event.assigned_to_display_names?.length
      ? event.assigned_to_display_names
      : event.assigned_to_display_name
        ? [event.assigned_to_display_name]
        : [];
  return (
    <Modal
      title={event.title}
      onClose={onClose}
      footer={
        !processEvent && event.can_manage && event.status !== "cancelado" ? (
          <>
            <button type="button" className="btn btn--danger" onClick={onCancel}>Cancelar evento</button>
            <button type="button" className="btn btn--primary" onClick={onEdit}>Editar</button>
          </>
        ) : undefined
      }
    >
      <div className="planning-event-detail__badges">
        <Badge tone={EVENT_STATUS_TONES[event.status] ?? "neutral"}>{event.status}</Badge>
        <span className="planning-category-badge" style={{ "--planning-event-color": meta.color } as CSSProperties}>
          <span className="planning-event-chip__dot" aria-hidden="true" /> {meta.label}
        </span>
        <Badge tone={processEvent ? "violet" : "neutral"}>{processEvent ? "Processo" : "Manual"}</Badge>
      </div>
      {processEvent && <Alert tone="info">Este evento é uma projeção do Processo. Só é possível abrir a etapa; as datas e o progresso não são editáveis aqui.</Alert>}
      <dl className="kv planning-event-detail">
        <dt>Início</dt>
        <dd>{formatDayHeaderPt(lisbonDateOf(event.starts_at))} · {formatTimePt(event.starts_at)}</dd>
        <dt>Fim</dt>
        <dd>{formatDayHeaderPt(lisbonDateOf(event.ends_at))} · {formatTimePt(event.ends_at)}</dd>
        {event.project_id && (
          <>
            <dt>Projeto</dt>
            <dd>{projectUrl ? <Link to={projectUrl}>{event.project_name ?? "Abrir projeto"}</Link> : event.project_name}</dd>
          </>
        )}
        {event.task_title && (
          <>
            <dt>Tarefa normal</dt>
            <dd>{event.task_title}</dd>
          </>
        )}
        {(event.process_stage_title || event.process_stage_code) && (
          <>
            <dt>Etapa do Processo</dt>
            <dd>{event.process_stage_code ? `${event.process_stage_code} — ` : ""}{event.process_stage_title ?? ""}</dd>
          </>
        )}
        {(event.process_subtask_title || event.process_subtask_code) && (
          <>
            <dt>Subtarefa do Processo</dt>
            <dd>{event.process_subtask_code ? `${event.process_subtask_code} — ` : ""}{event.process_subtask_title ?? ""}</dd>
          </>
        )}
        <dt>Responsáveis</dt>
        <dd><ParticipantSummary event={event} people={people} /></dd>
        {processEvent && responsibleNames.length > 0 && (
          <>
            <dt>Responsáveis do Processo</dt>
            <dd>{responsibleNames.join(", ")}</dd>
          </>
        )}
        {processEvent && projectUrl && <><dt>Processo</dt><dd><Link to={projectUrl} aria-label="Abrir processo">Abrir Processo</Link></dd></>}
      </dl>
    </Modal>
  );
}

export default function Planning() {
  const { notify } = useToast();
  const [view, setView] = useState<ViewMode>("month");
  const [anchorIso, setAnchorIso] = useState(() => todayIsoLisbon());
  const [hideWeekends, setHideWeekends] = useState(false);
  const [scope, setScope] = useState<Scope>("all");
  const [scopePmId, setScopePmId] = useState("");
  const [scopeProjectId, setScopeProjectId] = useState("");
  const [scopeResponsibleId, setScopeResponsibleId] = useState("");
  const [scopeTeamId, setScopeTeamId] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("active");

  const [events, setEvents] = useState<CalendarEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [processError, setProcessError] = useState<string | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [people, setPeople] = useState<Person[]>([]);
  const [categories, setCategories] = useState<CalendarEventCategory[]>([]);
  const [projectError, setProjectError] = useState<string | null>(null);
  const [peopleError, setPeopleError] = useState<string | null>(null);
  const [categoryError, setCategoryError] = useState<string | null>(null);
  const [preferenceError, setPreferenceError] = useState<string | null>(null);
  const [preferenceSaveError, setPreferenceSaveError] = useState<string | null>(null);
  const [savingPreference, setSavingPreference] = useState(false);
  const [detailEvent, setDetailEvent] = useState<CalendarEvent | null>(null);
  const [editingEvent, setEditingEvent] = useState<CalendarEvent | null>(null);
  const [creatingForDate, setCreatingForDate] = useState<string | null>(null);
  const loadSequence = useRef(0);

  const range = useMemo(() => getPlanningViewRange(view, anchorIso), [view, anchorIso]);
  const orderedProjects = useMemo(() => sortProjectsNaturally(projects), [projects]);
  const activePeople = useMemo(() => sortedPeople(people), [people]);
  const projectPmMap = useMemo(() => new Map(projects.map((project) => [project.id, project.pm_person_id])), [projects]);
  const projectTeamMap = useMemo(() => new Map(projects.map((project) => [project.id, project.installer_team_id])), [projects]);
  const pmOptions = useMemo(() => {
    const map = new Map<string, string>();
    for (const project of projects) if (project.pm_person_id && project.pm_display_name) map.set(project.pm_person_id, project.pm_display_name);
    return [...map.entries()].sort((a, b) => PERSON_COLLATOR.compare(a[1], b[1]) || a[0].localeCompare(b[0]));
  }, [projects]);
  const teamOptions = useMemo(() => {
    const map = new Map<string, string>();
    for (const project of projects) if (project.installer_team_id && project.installer_team_name) map.set(project.installer_team_id, project.installer_team_name);
    return [...map.entries()].sort((a, b) => PERSON_COLLATOR.compare(a[1], b[1]) || a[0].localeCompare(b[0]));
  }, [projects]);
  const visibleDays = useMemo(() => range.days.filter((day) => !hideWeekends || !isWeekend(day)), [range.days, hideWeekends]);

  useEffect(() => {
    let cancelled = false;
    listProjects({ is_active: true }).then((result) => !cancelled && setProjects(result)).catch((loadError) => {
      if (!cancelled) setProjectError(loadError instanceof ApiError ? loadError.detail : "Não foi possível carregar os projetos.");
    });
    listPeople().then((result) => !cancelled && setPeople(result)).catch((loadError) => {
      if (!cancelled) setPeopleError(loadError instanceof ApiError ? loadError.detail : "Não foi possível carregar as pessoas.");
    });
    listPlanningEventCategories().then((result) => !cancelled && setCategories(result)).catch((loadError) => {
      if (!cancelled) setCategoryError(loadError instanceof ApiError ? loadError.detail : "Não foi possível carregar as categorias de eventos.");
    });
    getPlanningPreferences().then((preference) => {
      if (cancelled) return;
      setView(preference.view);
      setHideWeekends(preference.hide_weekends);
      setPreferenceError(null);
    }).catch(() => {
      if (!cancelled) setPreferenceError("Não foi possível carregar a vista guardada; a usar a vista mensal. Pode tentar novamente.");
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const loadEvents = useCallback(() => {
    const sequence = ++loadSequence.current;
    setEvents(null);
    setError(null);
    setProcessError(null);
    const filters = {
      starts_from: lisbonWallClockToIso(`${range.startIso}T00:00`),
      // End exclusive at Lisbon midnight keeps the complete last day and
      // follows DST instead of adding 24 fixed hours.
      starts_to: lisbonWallClockToIso(`${addDays(range.endIso, 1)}T00:00`),
      mine_only: scope === "mine",
      project_id: scope === "project" && scopeProjectId ? scopeProjectId : undefined,
      assigned_to_person_id: scope === "responsible" && scopeResponsibleId ? scopeResponsibleId : undefined,
      category: categoryFilter || undefined,
    };
    Promise.allSettled([listCalendarEvents(filters), listProcessCalendarEvents(filters)]).then(([manualResult, processResult]) => {
      if (sequence !== loadSequence.current) return;
      const manualEvents = manualResult.status === "fulfilled" ? manualResult.value : [];
      const processEvents = processResult.status === "fulfilled" ? processResult.value : [];
      setEvents(mergePlanningEvents(manualEvents, processEvents));
      if (manualResult.status === "rejected") {
        setError(manualResult.reason instanceof ApiError ? manualResult.reason.detail : "Não foi possível carregar os eventos do planeamento.");
      }
      if (processResult.status === "rejected") {
        setProcessError(processResult.reason instanceof ApiError ? processResult.reason.detail : "Não foi possível carregar as projeções do Processo.");
      }
    });
  }, [categoryFilter, range.endIso, range.startIso, scope, scopeProjectId, scopeResponsibleId]);

  useEffect(() => {
    loadEvents();
  }, [loadEvents]);

  const filteredEvents = useMemo(() => {
    if (!events) return [];
    return events.filter((event) => {
      if (statusFilter === "active" && event.status === "cancelado") return false;
      if (statusFilter === "cancelled" && event.status !== "cancelado") return false;
      if (scope === "pm" && scopePmId && (!event.project_id || projectPmMap.get(event.project_id) !== scopePmId)) return false;
      if (scope === "team" && scopeTeamId && (!event.project_id || projectTeamMap.get(event.project_id) !== scopeTeamId)) return false;
      return true;
    });
  }, [events, projectPmMap, projectTeamMap, scope, scopePmId, scopeTeamId, statusFilter]);

  const eventsByDay = useMemo(() => {
    const map = new Map<string, CalendarEvent[]>();
    for (const day of range.days) {
      const dayStart = lisbonWallClockToIso(`${day}T00:00`);
      const dayEnd = lisbonWallClockToIso(`${addDays(day, 1)}T00:00`);
      const bucket = filteredEvents.filter((event) => eventsOverlap(event.starts_at, event.ends_at, dayStart, dayEnd));
      bucket.sort((a, b) => a.starts_at.localeCompare(b.starts_at) || a.id.localeCompare(b.id));
      map.set(day, bucket);
    }
    return map;
  }, [filteredEvents, range.days]);
  const hasVisibleEvents = useMemo(
    () => visibleDays.some((day) => (eventsByDay.get(day) ?? []).length > 0),
    [eventsByDay, visibleDays]
  );

  async function handleSavePreference() {
    setSavingPreference(true);
    setPreferenceSaveError(null);
    try {
      const saved = await updatePlanningPreferences({ view, hide_weekends: hideWeekends });
      setView(saved.view);
      setHideWeekends(saved.hide_weekends);
      notify("Vista de planeamento fixada.", "success");
    } catch (saveError) {
      setPreferenceSaveError(saveError instanceof ApiError ? saveError.detail : "Não foi possível guardar a vista. Tente novamente.");
    } finally {
      setSavingPreference(false);
    }
  }

  async function retryPreferences() {
    setPreferenceError(null);
    try {
      const preference = await getPlanningPreferences();
      setView(preference.view);
      setHideWeekends(preference.hide_weekends);
    } catch {
      setPreferenceError("Não foi possível carregar a vista guardada; a usar a vista mensal. Pode tentar novamente.");
    }
  }

  async function handleCancel(event: CalendarEvent) {
    if (event.source === "process") return;
    try {
      await cancelCalendarEvent(event.id);
      notify("Evento cancelado.", "success");
      setDetailEvent(null);
      loadEvents();
    } catch (cancelError) {
      notify(cancelError instanceof ApiError ? cancelError.detail : "Não foi possível cancelar o evento.", "error");
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
        <div className="card"><ErrorState message={error} onRetry={loadEvents} /></div>
      </>
    );
  }

  return (
    <div className="planning-page">
      <PageHeader
        title="Planeamento"
        subtitle="Calendário local de visitas, Processo e outras marcações — sem sincronização externa."
        actions={<button type="button" className="btn btn--primary btn--sm" onClick={() => setCreatingForDate(anchorIso)}><Icon name="plus" size={14} /> Novo evento</button>}
      />

      {(preferenceError || preferenceSaveError || projectError || peopleError || categoryError || processError) && (
        <div className="planning-alerts">
          {preferenceError && <Alert tone="warning" title="Vista guardada indisponível" action={<button type="button" className="btn btn--sm" onClick={retryPreferences}>Tentar novamente</button>}>{preferenceError}</Alert>}
          {preferenceSaveError && <Alert tone="warning" title="Vista não guardada" action={<button type="button" className="btn btn--sm" onClick={handleSavePreference} disabled={savingPreference}>Tentar guardar</button>}>{preferenceSaveError}</Alert>}
          {projectError && <Alert tone="warning">{projectError}</Alert>}
          {peopleError && <Alert tone="warning">{peopleError}</Alert>}
          {categoryError && <Alert tone="warning">{categoryError}</Alert>}
          {processError && <Alert tone="warning" title="Projeções do Processo indisponíveis" action={<button type="button" className="btn btn--sm" onClick={loadEvents}>Tentar novamente</button>}>{processError}</Alert>}
        </div>
      )}

      <form className="toolbar planning-toolbar" role="search" aria-label="Filtros de planeamento" onSubmit={(event) => event.preventDefault()}>
        <div className="field">
          <label htmlFor="pl-view">Vista</label>
          <select id="pl-view" className="select" value={view} onChange={(event) => setView(event.target.value as ViewMode)}>
            <option value="week">Semana</option>
            <option value="month">Mês</option>
            <option value="list">Lista</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="pl-scope">Ver</label>
          <select id="pl-scope" className="select" value={scope} onChange={(event) => setScope(event.target.value as Scope)}>
            <option value="all">Todos</option>
            <option value="mine">Meus</option>
            <option value="pm">Por PM</option>
            <option value="project">Por projeto</option>
            <option value="responsible">Por responsável</option>
            <option value="team">Por equipa</option>
          </select>
        </div>
        {scope === "pm" && <div className="field"><label htmlFor="pl-pm">PM</label><select id="pl-pm" className="select" value={scopePmId} onChange={(event) => setScopePmId(event.target.value)}><option value="">Todos os PM</option>{pmOptions.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></div>}
        {scope === "project" && <div className="field field--wide"><PlanningProjectCombobox id="pl-project" label="Projeto" projects={orderedProjects} value={scopeProjectId} onChange={setScopeProjectId} placeholder="Pesquisar projeto…" /></div>}
        {scope === "responsible" && <div className="field"><label htmlFor="pl-responsible">Responsável</label><select id="pl-responsible" className="select" value={scopeResponsibleId} onChange={(event) => setScopeResponsibleId(event.target.value)}><option value="">Todas as pessoas</option>{activePeople.map((person) => <option key={person.id} value={person.id}>{person.display_name}</option>)}</select></div>}
        {scope === "team" && <div className="field"><label htmlFor="pl-team">Equipa</label><select id="pl-team" className="select" value={scopeTeamId} onChange={(event) => setScopeTeamId(event.target.value)}><option value="">Todas as equipas</option>{teamOptions.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></div>}
        <div className="field"><label htmlFor="pl-category">Categoria</label><select id="pl-category" className="select" value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}><option value="">Todas</option>{categories.map((category) => <option key={category.code} value={category.code}>{category.label}</option>)}</select></div>
        <div className="field"><label htmlFor="pl-status">Estado</label><select id="pl-status" className="select" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}><option value="active">Sem cancelados</option><option value="cancelled">Só cancelados</option><option value="all">Todos</option></select></div>
        <div className="field planning-toolbar__period"><span>Período</span><div className="planning-period-controls"><button type="button" className="btn btn--sm" onClick={() => navigate(-1)} aria-label="Período anterior"><Icon name="chevronLeft" size={14} /></button><button type="button" className="btn btn--sm" onClick={() => setAnchorIso(todayIsoLisbon())}>Hoje</button><button type="button" className="btn btn--sm" onClick={() => navigate(1)} aria-label="Período seguinte"><Icon name="chevronRight" size={14} /></button></div></div>
        <label className="planning-toggle"><input type="checkbox" checked={hideWeekends} onChange={(event) => setHideWeekends(event.target.checked)} /> <span>Ocultar fins de semana</span></label>
        <button type="button" className="btn btn--sm planning-save-view" onClick={handleSavePreference} disabled={savingPreference}>{savingPreference ? "A guardar…" : "Fixar vista"}</button>
      </form>

      <CategoryLegend categories={categories} />

      <Card title={rangeTitle} icon="calendar" flush>
        {events === null ? <LoadingState rows={6} /> : !hasVisibleEvents ? <EmptyState compact icon="calendar" title="Sem eventos neste período com estes filtros." /> : view === "list" ? (
          <ul className="list planning-list">
            {visibleDays.filter((day) => (eventsByDay.get(day) ?? []).length > 0).map((day) => (
              <li key={day} className="list__item planning-list__day" data-testid="planning-day">
                <div className="list__title">{formatDayHeaderPt(day)}</div>
                <div className="planning-list__events">{(eventsByDay.get(day) ?? []).map((event) => <button key={event.id} type="button" className="planning-list__event" onClick={() => setDetailEvent(event)} onKeyDown={(keyboardEvent) => { if (keyboardEvent.key === "Enter") { keyboardEvent.preventDefault(); setDetailEvent(event); } }}><EventChip event={event} categories={categories} as="span" /><span className="planning-list__meta">{event.project_name ?? "sem projeto"} · {eventCategoryMeta(event, categories).label} · <ParticipantSummary event={event} people={people} /></span></button>)}</div>
              </li>
            ))}
          </ul>
        ) : view === "week" ? (
          <div className="planning-calendar-grid planning-calendar-grid--week" style={{ gridTemplateColumns: `repeat(${Math.max(visibleDays.length, 1)}, minmax(0, 1fr))` }}>
            {visibleDays.map((day) => <div key={day} className="planning-calendar-day" data-testid="planning-day"><div className="planning-calendar-day__header"><span>{formatDayHeaderPt(day)}</span><button type="button" className="planning-day-add" aria-label={`Novo evento em ${day}`} onClick={() => setCreatingForDate(day)}><Icon name="plus" size={12} /></button></div><div className="planning-calendar-day__events">{(eventsByDay.get(day) ?? []).map((event) => <EventChip key={event.id} event={event} categories={categories} onClick={() => setDetailEvent(event)} />)}</div></div>)}
          </div>
        ) : (
          <div className="planning-calendar-grid planning-calendar-grid--month" style={{ gridTemplateColumns: `repeat(${hideWeekends ? 5 : 7}, minmax(0, 1fr))` }}>
            {visibleDays.map((day) => {
              const dayEvents = eventsByDay.get(day) ?? [];
              const inMonth = day.slice(0, 7) === anchorIso.slice(0, 7);
              return <div key={day} className={`planning-calendar-day planning-calendar-day--month${inMonth ? "" : " planning-calendar-day--muted"}`} data-testid="planning-day"><div className="planning-calendar-day__header"><span>{Number(day.slice(8, 10))}</span><button type="button" className="planning-day-add" aria-label={`Novo evento em ${day}`} onClick={() => setCreatingForDate(day)}><Icon name="plus" size={12} /></button></div>{dayEvents.slice(0, 3).map((event) => <EventChip key={event.id} event={event} categories={categories} onClick={() => setDetailEvent(event)} />)}{dayEvents.length > 3 && <div className="planning-calendar-day__more">+{dayEvents.length - 3} mais</div>}</div>;
            })}
          </div>
        )}
      </Card>

      {detailEvent && <EventDetailModal event={detailEvent} people={people} categories={categories} onClose={() => setDetailEvent(null)} onCancel={() => handleCancel(detailEvent)} onEdit={() => { setEditingEvent(detailEvent); setDetailEvent(null); }} />}
      {(creatingForDate !== null || editingEvent) && <EventModal event={editingEvent} defaultDate={creatingForDate} projects={orderedProjects} people={people} categories={categories} allEvents={events ?? []} onClose={() => { setCreatingForDate(null); setEditingEvent(null); }} onSaved={() => { notify(editingEvent ? "Evento atualizado." : "Evento criado.", "success"); setCreatingForDate(null); setEditingEvent(null); loadEvents(); }} />}
    </div>
  );
}
