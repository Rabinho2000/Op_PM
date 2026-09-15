import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  DashboardSummary,
  DEFAULT_TASK_TYPE_LABELS,
  getDashboardSummary,
  ProjectMini,
  TaskMini,
} from "../api/client";
import { daysUntilLabel, formatDatePt } from "../utils/dates";

const cardStyle: React.CSSProperties = {
  border: "1px solid #ddd",
  borderRadius: 8,
  padding: "1rem",
  minWidth: 200,
  flex: "1 1 200px",
};

const sectionStyle: React.CSSProperties = {
  border: "1px solid #eee",
  borderRadius: 8,
  padding: "1rem",
  flex: "1 1 320px",
  minWidth: 300,
};

function StatCard({ label, value, to }: { label: string; value: number; to?: string }) {
  const content = (
    <div style={cardStyle}>
      <div style={{ fontSize: "1.8rem", fontWeight: 700 }}>{value}</div>
      <div style={{ color: "#666", fontSize: "0.85rem" }}>{label}</div>
    </div>
  );
  if (!to) return content;
  return (
    <Link to={to} style={{ textDecoration: "none", color: "inherit" }}>
      {content}
    </Link>
  );
}

function TaskMiniList({ tasks, emptyLabel }: { tasks: TaskMini[]; emptyLabel: string }) {
  if (tasks.length === 0) return <p style={{ color: "#888", fontSize: "0.85rem" }}>{emptyLabel}</p>;
  return (
    <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
      {tasks.map((t) => (
        <li key={t.id} style={{ padding: "0.35rem 0", borderBottom: "1px solid #f0f0f0", fontSize: "0.85rem" }}>
          <Link to={`/projects/${t.project_id}`}>{t.project_name}</Link> —{" "}
          {DEFAULT_TASK_TYPE_LABELS[t.task_type] ?? t.title}
          {t.due_date && <span style={{ color: "#a66" }}> · prazo {formatDatePt(t.due_date)}</span>}
          {t.assigned_to_display_name && <span style={{ color: "#888" }}> · {t.assigned_to_display_name}</span>}
        </li>
      ))}
    </ul>
  );
}

function ProjectMiniList({ projects, emptyLabel }: { projects: ProjectMini[]; emptyLabel: string }) {
  if (projects.length === 0) return <p style={{ color: "#888", fontSize: "0.85rem" }}>{emptyLabel}</p>;
  return (
    <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
      {projects.map((p) => (
        <li key={p.id} style={{ padding: "0.35rem 0", borderBottom: "1px solid #f0f0f0", fontSize: "0.85rem" }}>
          <Link to={`/projects/${p.id}`}>{p.name}</Link>
          {p.start_date && <span style={{ color: "#888" }}> · início {formatDatePt(p.start_date)}</span>}
          {p.missing_fields.length > 0 && (
            <span style={{ color: "#a66" }}> · em falta: {p.missing_fields.join(", ")}</span>
          )}
        </li>
      ))}
    </ul>
  );
}

export default function Home() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getDashboardSummary()
      .then(setSummary)
      .catch((e) => setError(e instanceof ApiError ? e.detail : String(e)));
  }, []);

  if (error) {
    return (
      <div style={{ fontFamily: "system-ui, sans-serif", padding: "1.5rem" }}>
        <p style={{ color: "crimson" }}>Erro a carregar o dashboard: {error}</p>
      </div>
    );
  }

  if (!summary) {
    return (
      <div style={{ fontFamily: "system-ui, sans-serif", padding: "1.5rem" }}>
        <p>A carregar…</p>
      </div>
    );
  }

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", padding: "1.5rem", maxWidth: 1200 }}>
      <h1>Painel de operações</h1>
      <p style={{ color: "#666", fontSize: "0.85rem" }}>
        Semana de {formatDatePt(summary.week_start)} a {formatDatePt(summary.week_end)} (Europe/Lisbon)
      </p>

      <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", marginTop: "1rem" }}>
        <StatCard label="Projetos ativos" value={summary.active_projects_count} to="/projects" />
        <StatCard
          label="A iniciar nos próximos 30 dias"
          value={summary.projects_starting_next_30_days.length}
          to="/projects"
        />
        <StatCard label="Tarefas atrasadas" value={summary.overdue_tasks.length} to="/tasks" />
        <StatCard label="Tarefas pendentes esta semana" value={summary.tasks_due_this_week.length} to="/tasks" />
        <StatCard label="Visitas técnicas pendentes" value={summary.pending_technical_visits.length} to="/tasks" />
        <StatCard label="Comissionamentos pendentes" value={summary.pending_commissioning.length} to="/tasks" />
        <StatCard label="Projetos sem PM" value={summary.projects_without_pm.length} to="/projects" />
        <StatCard label="Projetos com dados em falta" value={summary.projects_missing_data.length} to="/projects" />
      </div>

      <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", marginTop: "1.5rem" }}>
        <div style={sectionStyle}>
          <h2 style={{ fontSize: "1rem" }}>Trabalhos urgentes</h2>
          <TaskMiniList tasks={summary.urgent_tasks} emptyLabel="Sem trabalhos urgentes." />
        </div>

        <div style={sectionStyle}>
          <h2 style={{ fontSize: "1rem" }}>Tarefas atrasadas</h2>
          <TaskMiniList tasks={summary.overdue_tasks} emptyLabel="Sem tarefas atrasadas." />
        </div>

        <div style={sectionStyle}>
          <h2 style={{ fontSize: "1rem" }}>Pendentes esta semana</h2>
          <TaskMiniList tasks={summary.tasks_due_this_week} emptyLabel="Nada pendente esta semana." />
        </div>
      </div>

      <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", marginTop: "1rem" }}>
        <div style={sectionStyle}>
          <h2 style={{ fontSize: "1rem" }}>Visitas técnicas pendentes</h2>
          <TaskMiniList tasks={summary.pending_technical_visits} emptyLabel="Sem visitas técnicas pendentes." />
        </div>

        <div style={sectionStyle}>
          <h2 style={{ fontSize: "1rem" }}>Comissionamentos pendentes</h2>
          <TaskMiniList tasks={summary.pending_commissioning} emptyLabel="Sem comissionamentos pendentes." />
        </div>

        <div style={sectionStyle}>
          <h2 style={{ fontSize: "1rem" }}>Projetos que começam em breve</h2>
          <ProjectMiniList
            projects={summary.projects_starting_next_30_days}
            emptyLabel="Nenhum projeto a começar nos próximos 30 dias."
          />
        </div>
      </div>

      <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", marginTop: "1rem" }}>
        <div style={sectionStyle}>
          <h2 style={{ fontSize: "1rem" }}>Projetos sem PM</h2>
          <ProjectMiniList projects={summary.projects_without_pm} emptyLabel="Todos os projetos têm PM atribuído." />
        </div>

        <div style={sectionStyle}>
          <h2 style={{ fontSize: "1rem" }}>Projetos com dados em falta</h2>
          <ProjectMiniList
            projects={summary.projects_missing_data}
            emptyLabel="Nenhum projeto com email/contacto/coordenadas em falta."
          />
        </div>
      </div>

      <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", marginTop: "1rem" }}>
        <div style={sectionStyle}>
          <h2 style={{ fontSize: "1rem" }}>Férias atuais</h2>
          {summary.current_absences.length === 0 ? (
            <p style={{ color: "#888", fontSize: "0.85rem" }}>Ninguém de férias/ausente neste momento.</p>
          ) : (
            <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {summary.current_absences.map((a) => (
                <li key={a.id} style={{ padding: "0.35rem 0", borderBottom: "1px solid #f0f0f0", fontSize: "0.85rem" }}>
                  {a.person_display_name} · {formatDatePt(a.start_date)} – {formatDatePt(a.end_date)}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div style={sectionStyle}>
          <h2 style={{ fontSize: "1rem" }}>Férias próximas</h2>
          {summary.upcoming_absences.length === 0 ? (
            <p style={{ color: "#888", fontSize: "0.85rem" }}>Sem férias agendadas nos próximos 30 dias.</p>
          ) : (
            <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {summary.upcoming_absences.map((a) => (
                <li key={a.id} style={{ padding: "0.35rem 0", borderBottom: "1px solid #f0f0f0", fontSize: "0.85rem" }}>
                  {a.person_display_name} · {formatDatePt(a.start_date)} – {formatDatePt(a.end_date)}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div style={sectionStyle}>
          <h2 style={{ fontSize: "1rem" }}>Aniversários próximos</h2>
          {summary.upcoming_birthdays.length === 0 ? (
            <p style={{ color: "#888", fontSize: "0.85rem" }}>Sem aniversários nos próximos 30 dias.</p>
          ) : (
            <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {summary.upcoming_birthdays.map((b) => (
                <li
                  key={b.person_id}
                  style={{ padding: "0.35rem 0", borderBottom: "1px solid #f0f0f0", fontSize: "0.85rem" }}
                >
                  {b.person_display_name} · {daysUntilLabel(b.days_until)}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
