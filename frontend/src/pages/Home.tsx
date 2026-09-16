import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  ABSENCE_TYPE_LABELS,
  AbsenceMini,
  ApiError,
  DashboardSummary,
  DEFAULT_TASK_TYPE_LABELS,
  getDashboardSummary,
  ProjectMini,
  TASK_PRIORITY_LABELS,
  TaskMini,
  WeekDaySummary,
} from "../api/client";
import Icon, { IconName } from "../components/Icon";
import {
  Alert,
  Avatar,
  Badge,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  StatCard,
  StatsSkeleton,
  Tone,
} from "../components/ui";
import { useSession } from "../session/SessionContext";
import {
  daysUntilLabel,
  formatDatePt,
  formatDayMonthPt,
  relativeDayLabel,
  todayIsoLisbon,
  weekdayShortPt,
} from "../utils/dates";
import { ABSENCE_TYPE_TONES, TASK_PRIORITY_TONES, TASK_TYPE_ICONS } from "../utils/labels";

// Painel inicial: TODOS os números vêm de GET /api/dashboard/summary,
// já calculados e filtrados pelo servidor (D-041). Aqui só se apresenta —
// nunca se calculam métricas a partir de listas completas.

const LIST_LIMIT = 6;

function greeting(now: Date = new Date()): string {
  const hour = Number(
    new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Lisbon", hour: "numeric", hour12: false }).format(now)
  );
  if (hour < 13) return "Bom dia";
  if (hour < 20) return "Boa tarde";
  return "Boa noite";
}

function MoreLink({ total, to }: { total: number; to: string }) {
  if (total <= LIST_LIMIT) return null;
  return (
    <div className="list-more">
      <Link to={to}>Ver todos ({total})</Link>
    </div>
  );
}

function TaskList({
  tasks,
  emptyTitle,
  moreTo,
  today,
  showPriority,
}: {
  tasks: TaskMini[];
  emptyTitle: string;
  moreTo: string;
  today: string;
  showPriority?: boolean;
}) {
  if (tasks.length === 0) return <EmptyState compact title={emptyTitle} />;
  return (
    <>
      <ul className="list">
        {tasks.slice(0, LIST_LIMIT).map((t) => {
          const overdue = t.due_date !== null && t.due_date < today;
          return (
            <li key={t.id} className="list__item">
              <span className="card__title-icon tone-neutral" aria-hidden="true">
                <Icon name={TASK_TYPE_ICONS[t.task_type] ?? "tasks"} size={15} />
              </span>
              <div className="list__main">
                <Link className="list__title" to={`/projects/${t.project_id}`}>
                  {t.project_name}
                </Link>
                <div className="list__meta">
                  {t.task_type === "custom" ? t.title : DEFAULT_TASK_TYPE_LABELS[t.task_type] ?? t.title}
                  {t.assigned_to_display_name && ` · ${t.assigned_to_display_name}`}
                </div>
              </div>
              <div className="list__aside">
                {showPriority && (
                  <div>
                    <Badge tone={TASK_PRIORITY_TONES[t.priority]}>{TASK_PRIORITY_LABELS[t.priority]}</Badge>
                  </div>
                )}
                <span className={`small ${overdue ? "text-danger" : "muted"}`} title={formatDatePt(t.due_date)}>
                  {relativeDayLabel(t.due_date, today)}
                </span>
              </div>
            </li>
          );
        })}
      </ul>
      <MoreLink total={tasks.length} to={moreTo} />
    </>
  );
}

const MISSING_LABELS: Record<string, string> = { email: "email", contacto: "contacto", coordenadas: "coordenadas" };

function ProjectList({
  projects,
  emptyTitle,
  showMissing,
  showStart,
}: {
  projects: ProjectMini[];
  emptyTitle: string;
  showMissing?: boolean;
  showStart?: boolean;
}) {
  if (projects.length === 0) return <EmptyState compact title={emptyTitle} />;
  return (
    <>
      <ul className="list">
        {projects.slice(0, LIST_LIMIT).map((p) => (
          <li key={p.id} className="list__item">
            <div className="list__main">
              <Link className="list__title" to={`/projects/${p.id}`}>
                {p.name}
              </Link>
              <div className="list__meta">{p.pm_display_name ? `PM: ${p.pm_display_name}` : "Sem PM atribuído"}</div>
            </div>
            <div className="list__aside">
              {showStart && p.start_date && <span className="small muted">início {formatDayMonthPt(p.start_date)}</span>}
              {showMissing && p.missing_fields.length > 0 && (
                <div className="badges" style={{ justifyContent: "flex-end" }}>
                  {p.missing_fields.map((f) => (
                    <Badge key={f} tone="warning">
                      {MISSING_LABELS[f] ?? f}
                    </Badge>
                  ))}
                </div>
              )}
            </div>
          </li>
        ))}
      </ul>
      <MoreLink total={projects.length} to="/projects" />
    </>
  );
}

function AbsenceList({ absences, emptyTitle }: { absences: AbsenceMini[]; emptyTitle: string }) {
  if (absences.length === 0) return <EmptyState compact title={emptyTitle} icon="calendar" />;
  return (
    <ul className="list">
      {absences.slice(0, LIST_LIMIT).map((a) => (
        <li key={a.id} className="list__item">
          <Avatar name={a.person_display_name} small />
          <div className="list__main">
            <span className="list__title">{a.person_display_name}</span>
            <div className="list__meta">
              {formatDayMonthPt(a.start_date)} – {formatDayMonthPt(a.end_date)}
            </div>
          </div>
          <Badge tone={ABSENCE_TYPE_TONES[a.type]}>{ABSENCE_TYPE_LABELS[a.type]}</Badge>
        </li>
      ))}
    </ul>
  );
}

function WeekChart({ days, today }: { days: WeekDaySummary[]; today: string }) {
  if (days.length === 0) return <EmptyState compact title="Sem dados para esta semana." />;
  const max = Math.max(1, ...days.map((d) => Math.max(d.tasks_due_count, d.tasks_completed_count)));
  const scale = (n: number) => `${Math.max(3, Math.round((n / max) * 100))}%`;
  return (
    <>
      <div className="week-chart" role="list" aria-label="Resumo da semana por dia">
        {days.map((d) => {
          const isToday = d.date === today;
          const summary =
            `${weekdayShortPt(d.date)} ${formatDayMonthPt(d.date)}: ${d.tasks_due_count} com prazo, ` +
            `${d.tasks_completed_count} concluídas, ${d.people_absent_count} ausentes`;
          return (
            <div key={d.date} role="listitem" className={`week-day ${isToday ? "week-day--today" : ""}`} aria-label={summary}>
              <div className="week-day__bars" aria-hidden="true">
                <div
                  className={`week-bar ${d.tasks_due_count ? "week-bar--due" : "week-bar--empty"}`}
                  style={{ height: scale(d.tasks_due_count) }}
                  title={`${d.tasks_due_count} com prazo`}
                />
                <div
                  className={`week-bar ${d.tasks_completed_count ? "week-bar--done" : "week-bar--empty"}`}
                  style={{ height: scale(d.tasks_completed_count) }}
                  title={`${d.tasks_completed_count} concluídas`}
                />
              </div>
              <span className="week-day__label" aria-hidden="true">
                {isToday ? "hoje" : weekdayShortPt(d.date)}
              </span>
              <span className="week-day__date" aria-hidden="true">
                {formatDayMonthPt(d.date)}
              </span>
              <span className="week-day__absent" aria-hidden="true">
                {d.people_absent_count > 0 ? `${d.people_absent_count} ausente${d.people_absent_count > 1 ? "s" : ""}` : ""}
              </span>
            </div>
          );
        })}
      </div>
      <div className="legend" style={{ marginTop: 12 }}>
        <span>
          <span className="legend__swatch" style={{ background: "var(--brand)" }} />
          Tarefas com prazo (abertas)
        </span>
        <span>
          <span className="legend__swatch" style={{ background: "var(--success)" }} />
          Tarefas concluídas
        </span>
        <span style={{ color: "var(--violet)" }}>Pessoas ausentes</span>
      </div>
    </>
  );
}

interface StatDef {
  label: string;
  value: number;
  icon: IconName;
  tone: Tone;
  to: string;
  alert?: boolean;
}

function buildStats(s: DashboardSummary): StatDef[] {
  return [
    { label: "Projetos ativos", value: s.active_projects_count, icon: "folder", tone: "brand", to: "/projects" },
    {
      label: "A começar nos próximos 30 dias",
      value: s.projects_starting_next_30_days.length,
      icon: "flag",
      tone: "info",
      to: "/projects",
    },
    { label: "Tarefas atrasadas", value: s.overdue_tasks.length, icon: "clock", tone: "danger", to: "/tasks?atrasadas=1", alert: true },
    { label: "Tarefas desta semana", value: s.tasks_due_this_week.length, icon: "calendar", tone: "brand", to: "/tasks" },
    { label: "Tarefas urgentes", value: s.urgent_tasks.length, icon: "flame", tone: "danger", to: "/tasks?prioridade=urgent", alert: true },
    {
      label: "Visitas técnicas pendentes",
      value: s.pending_technical_visits.length,
      icon: "mapPin",
      tone: "violet",
      to: "/tasks",
    },
    {
      label: "Comissionamentos pendentes",
      value: s.pending_commissioning.length,
      icon: "checkCircle",
      tone: "success",
      to: "/tasks",
    },
    { label: "Projetos sem PM", value: s.projects_without_pm.length, icon: "userOff", tone: "warning", to: "/projects", alert: true },
    {
      label: "Projetos com dados incompletos",
      value: s.projects_missing_data.length,
      icon: "info",
      tone: "warning",
      to: "/projects",
    },
    {
      label: "Fotografias por colocar",
      value: s.projects_photos_pending.length,
      icon: "camera",
      tone: "warning",
      to: "/projects",
      alert: true,
    },
  ];
}

export default function Home() {
  const { me } = useSession();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    setSummary(null);
    getDashboardSummary()
      .then(setSummary)
      .catch((e) => setError(e instanceof ApiError ? e.detail : "Não foi possível contactar o servidor."));
  }, []);

  useEffect(load, [load]);

  const firstName = me?.display_name?.split(" ")[0];
  const title = firstName ? `${greeting()}, ${firstName}` : "Painel de operações";

  if (error) {
    return (
      <>
        <PageHeader title="Painel de operações" />
        <div className="card">
          <ErrorState message={error} onRetry={load} />
        </div>
      </>
    );
  }

  if (!summary) {
    return (
      <>
        <PageHeader title={title} subtitle="A carregar os indicadores…" />
        <StatsSkeleton />
        <div className="grid grid--3 section-gap">
          {[0, 1, 2].map((i) => (
            <div key={i} className="card">
              <LoadingState />
            </div>
          ))}
        </div>
      </>
    );
  }

  const today = todayIsoLisbon();
  const scopeLabel =
    summary.scope === "all" ? "Visão de toda a operação" : summary.scope === "own" ? "Os seus projetos e tarefas" : "";

  if (summary.scope === "none") {
    return (
      <>
        <PageHeader title={title} />
        <div className="card">
          <EmptyState
            icon="lock"
            title="Sem projetos visíveis para o seu perfil"
            text="O seu perfil não tem permissão para ver projetos ou tarefas. Fale com um administrador se precisar de acesso."
          />
        </div>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title={title}
        subtitle={
          <>
            {scopeLabel} · semana de {formatDatePt(summary.week_start)} a {formatDatePt(summary.week_end)}
          </>
        }
        actions={
          <button type="button" className="btn" onClick={load}>
            <Icon name="refresh" size={16} /> Atualizar
          </button>
        }
      />

      {summary.projects_photos_pending.length > 0 && (
        <Alert
          tone="warning"
          title={`Fotografias por colocar na Drive em ${summary.projects_photos_pending.length} projeto${
            summary.projects_photos_pending.length > 1 ? "s" : ""
          }`}
        >
          Visita técnica ou comissionamento concluídos sem a tarefa “Colocar fotos na Drive” fechada:{" "}
          {summary.projects_photos_pending.slice(0, 4).map((p, i) => (
            <span key={p.id}>
              {i > 0 && ", "}
              <Link to={`/projects/${p.id}`}>{p.name}</Link>
            </span>
          ))}
          {summary.projects_photos_pending.length > 4 && ` e mais ${summary.projects_photos_pending.length - 4}`}.
        </Alert>
      )}

      <div className="grid grid--stats" aria-label="Indicadores principais">
        {buildStats(summary).map((stat) => (
          <StatCard key={stat.label} {...stat} />
        ))}
      </div>

      <div className="grid grid--main-side section-gap">
        <Card title="Resumo da semana" icon="activity">
          <WeekChart days={summary.week_overview} today={today} />
        </Card>
        <Card title="Tarefas urgentes" icon="flame" tone="danger" flush>
          <TaskList
            tasks={summary.urgent_tasks}
            emptyTitle="Sem tarefas urgentes em aberto."
            moreTo="/tasks?prioridade=urgent"
            today={today}
          />
        </Card>
      </div>

      <div className="grid grid--3 section-gap">
        <Card title="Tarefas atrasadas" icon="clock" tone="danger" flush>
          <TaskList
            tasks={summary.overdue_tasks}
            emptyTitle="Sem tarefas atrasadas."
            moreTo="/tasks?atrasadas=1"
            today={today}
            showPriority
          />
        </Card>
        <Card title="Tarefas desta semana" icon="calendar" flush>
          <TaskList tasks={summary.tasks_due_this_week} emptyTitle="Nada com prazo esta semana." moreTo="/tasks" today={today} />
        </Card>
        <Card title="A começar nos próximos 30 dias" icon="flag" tone="info" flush>
          <ProjectList
            projects={summary.projects_starting_next_30_days}
            emptyTitle="Nenhum projeto a começar nos próximos 30 dias."
            showStart
          />
        </Card>
      </div>

      <div className="grid grid--2 section-gap">
        <Card title="Visitas técnicas pendentes" icon="mapPin" tone="violet" flush>
          <TaskList
            tasks={summary.pending_technical_visits}
            emptyTitle="Sem visitas técnicas pendentes."
            moreTo="/tasks"
            today={today}
          />
        </Card>
        <Card title="Comissionamentos pendentes" icon="checkCircle" tone="success" flush>
          <TaskList
            tasks={summary.pending_commissioning}
            emptyTitle="Sem comissionamentos pendentes."
            moreTo="/tasks"
            today={today}
          />
        </Card>
      </div>

      <div className="grid grid--2 section-gap">
        <Card title="Projetos sem PM" icon="userOff" tone="warning" flush>
          <ProjectList projects={summary.projects_without_pm} emptyTitle="Todos os projetos ativos têm PM atribuído." />
        </Card>
        <Card title="Projetos com dados incompletos" icon="info" tone="warning" flush>
          <ProjectList
            projects={summary.projects_missing_data}
            emptyTitle="Nenhum projeto com email, contacto ou coordenadas em falta."
            showMissing
          />
        </Card>
      </div>

      <div className="grid grid--3 section-gap">
        <Card title="Férias e ausências atuais" icon="plane" tone="violet" flush>
          <AbsenceList absences={summary.current_absences} emptyTitle="Ninguém ausente neste momento." />
        </Card>
        <Card title="Próximas férias (30 dias)" icon="calendar" tone="violet" flush>
          <AbsenceList absences={summary.upcoming_absences} emptyTitle="Sem férias marcadas nos próximos 30 dias." />
        </Card>
        <Card title="Aniversários próximos" icon="gift" tone="warning" flush>
          {summary.upcoming_birthdays.length === 0 ? (
            <EmptyState compact icon="gift" title="Sem aniversários nos próximos 30 dias." />
          ) : (
            <ul className="list">
              {summary.upcoming_birthdays.slice(0, LIST_LIMIT).map((b) => (
                <li key={b.person_id} className="list__item">
                  <Avatar name={b.person_display_name} small />
                  <div className="list__main">
                    <span className="list__title">{b.person_display_name}</span>
                    <div className="list__meta">{formatDayMonthPt(b.birth_date)}</div>
                  </div>
                  <Badge tone={b.days_until === 0 ? "warning" : "neutral"}>
                    {b.days_until === 0 ? "🎉 hoje" : daysUntilLabel(b.days_until)}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <p className="small muted section-gap">
        Atualizado às{" "}
        {new Date(summary.generated_at).toLocaleTimeString("pt-PT", {
          timeZone: "Europe/Lisbon",
          hour: "2-digit",
          minute: "2-digit",
        })}{" "}
        · todos os indicadores são calculados pelo servidor.
      </p>
    </>
  );
}
