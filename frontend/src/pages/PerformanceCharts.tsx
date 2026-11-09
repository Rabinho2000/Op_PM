import type { GoalPeriod } from "../api/client";
import { GOAL_METRIC_LABELS } from "../api/client";
import "./PerformanceCharts.css";

const PACE_COLOR: Record<GoalPeriod["pace_status"], string> = {
  ahead: "var(--success)",
  on_track: "var(--brand)",
  behind: "var(--danger)",
  no_target: "var(--neutral)",
};

const PACE_LEGEND: Array<{ status: GoalPeriod["pace_status"]; label: string }> = [
  { status: "ahead", label: "Acima do ritmo esperado" },
  { status: "on_track", label: "No ritmo esperado" },
  { status: "behind", label: "Abaixo do ritmo esperado" },
  { status: "no_target", label: "Sem objetivo definido" },
];

function goalTitle(goal: GoalPeriod): string {
  const period = goal.period_type === "quarter"
    ? `T${goal.quarter} · ${goal.year}`
    : goal.period_type === "semester"
      ? `S${goal.semester} · ${goal.year}`
      : goal.period_type === "month"
        ? `Mês ${goal.month} · ${goal.year}`
        : String(goal.year);
  const owner = goal.scope === "pm" && goal.pm_display_name ? ` · ${goal.pm_display_name}` : "";
  return `${GOAL_METRIC_LABELS[goal.metric]} · ${period}${owner}`;
}

function numericValue(value: string): number {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? Math.max(0, parsed) : 0;
}

function shortLabel(label: string): string {
  return label.length > 42 ? `${label.slice(0, 39)}…` : label;
}

export function GoalDonut({ goal }: { goal: GoalPeriod }) {
  const percent = Number.isFinite(goal.percent) ? goal.percent : 0;
  const visualPercent = Math.min(100, Math.max(0, percent));
  const radius = 43;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference * (1 - visualPercent / 100);
  const title = goalTitle(goal);
  const ariaLabel = `Donut da meta ${title}: realizado ${goal.realized} de ${goal.target_value}; ${percent}% do objetivo.`;

  return (
    <figure className="performance-donut">
      <svg
        className="performance-donut__svg"
        viewBox="0 0 120 120"
        role="img"
        aria-label={ariaLabel}
      >
        <title>{ariaLabel}</title>
        <circle className="performance-donut__track" cx="60" cy="60" r={radius} />
        <circle
          className="performance-donut__value"
          cx="60"
          cy="60"
          r={radius}
          stroke={PACE_COLOR[goal.pace_status]}
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          transform="rotate(-90 60 60)"
        />
        <text className="performance-donut__center" x="60" y="56" textAnchor="middle">{goal.realized}</text>
        <text className="performance-donut__denominator" x="60" y="74" textAnchor="middle">de {goal.target_value}</text>
      </svg>
      <figcaption className="performance-donut__caption">
        <strong>{shortLabel(title)}</strong>
        <span>{percent}% realizado</span>
      </figcaption>
    </figure>
  );
}

export function GoalPaceLegend() {
  return (
    <ul className="performance-pace-legend" aria-label="Legenda do ritmo das metas">
      {PACE_LEGEND.map(({ status, label }) => (
        <li key={status}>
          <span className="performance-pace-legend__swatch" style={{ backgroundColor: PACE_COLOR[status] }} aria-hidden="true" />
          {label}
        </li>
      ))}
    </ul>
  );
}

const BAR_SERIES = [
  { key: "realized", label: "Realizado", color: "var(--brand)" },
  { key: "target", label: "Objetivo", color: "var(--accent)" },
  { key: "pace", label: "Ritmo esperado", color: "var(--violet)" },
] as const;

export function GoalComparisonBars({ goals }: { goals: GoalPeriod[] }) {
  const values = goals.map((goal) => ({
    realized: numericValue(goal.realized),
    target: numericValue(goal.target_value),
    pace: numericValue(goal.expected_pace),
  }));
  const maxValue = Math.max(1, ...values.flatMap((value) => [value.realized, value.target, value.pace]));
  const chartWidth = 360;
  const barLeft = 112;
  const barWidth = 232;
  const groupHeight = 78;
  const ariaLabel = goals.map((goal) =>
    `Meta ${goalTitle(goal)}: realizado ${goal.realized}, objetivo ${goal.target_value}, ritmo esperado ${goal.expected_pace}`
  ).join(". ");

  return (
    <div className="performance-bars">
      <svg
        className="performance-bars__svg"
        viewBox={`0 0 ${chartWidth} ${Math.max(groupHeight, goals.length * groupHeight)}`}
        role="img"
        aria-label={`Gráfico de barras — ${ariaLabel}.`}
      >
        <title>{`Comparação entre realizado, objetivo e ritmo esperado. ${ariaLabel}.`}</title>
        {goals.map((goal, index) => {
          const offset = index * groupHeight;
          const title = goalTitle(goal);
          const goalValues = values[index];
          return (
            <g key={goal.id}>
              <text className="performance-bars__goal" x="0" y={offset + 13}>
                <title>{title}</title>
                {shortLabel(title)}
              </text>
              {BAR_SERIES.map((series, seriesIndex) => {
                const value = goalValues[series.key];
                const width = (value / maxValue) * barWidth;
                const y = offset + 20 + seriesIndex * 18;
                return (
                  <g key={series.key}>
                    <text className="performance-bars__series" x="0" y={y + 9}>{series.label}</text>
                    <rect
                      className="performance-bars__bar"
                      x={barLeft}
                      y={y}
                      width={width}
                      height="11"
                      fill={series.color}
                      rx="3"
                    >
                      <title>{`${title} — ${series.label}: ${goal[series.key === "realized" ? "realized" : series.key === "target" ? "target_value" : "expected_pace"]}`}</title>
                    </rect>
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>
      <ul className="performance-bars__legend" aria-label="Legenda do gráfico de barras">
        {BAR_SERIES.map((series) => (
          <li key={series.key}>
            <span className="performance-bars__swatch" style={{ backgroundColor: series.color }} aria-hidden="true" />
            {series.label}
          </li>
        ))}
      </ul>
    </div>
  );
}
