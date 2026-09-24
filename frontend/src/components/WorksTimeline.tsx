import { Link } from "react-router-dom";
import type { Installer, LifecycleStatus, WorkItem } from "../api/client";
import { LIFECYCLE_STATUS_TONES } from "../utils/labels";
import {
  barGeometry,
  buildRows,
  dayPosition,
  formatIsoPt,
  monthTicks,
  TimelineRow,
  totalDays,
  weekTicks,
  Window,
  ZOOMS,
  Zoom,
} from "../utils/worksTimeline";
import Icon from "./Icon";

const LANE_H = 30;
const LANE_GAP = 4;
const ROW_PAD = 6;
const HEADER_ROW_H = 30;
const AXIS_H = 44;
export const LABEL_W = 210;

const rowHeight = (row: TimelineRow): number =>
  row.kind === "header" ? HEADER_ROW_H : row.laneCount * (LANE_H + LANE_GAP) - LANE_GAP + ROW_PAD * 2;

function describe(work: WorkItem, statusLabel: string): string {
  const where = [work.installer_name, work.installer_team_name].filter(Boolean).join(" / ") || "sem instalador";
  return [
    work.name,
    `${formatIsoPt(work.work_start_date)} a ${formatIsoPt(work.work_end_date)}${work.work_dates_estimated ? " (datas estimadas)" : ""}`,
    where,
    work.pm_display_name ? `PM ${work.pm_display_name}` : "sem PM",
    statusLabel,
    work.conflict ? "Conflito: a equipa tem outra obra sobreposta" : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

// Linha do tempo das obras: uma linha por instalador/equipa, barras posicionadas
// pelas datas (inclusivas), várias obras em simultâneo em faixas separadas. Cada
// barra é uma ligação para o projeto.
export default function WorksTimeline({
  works,
  installers,
  window: win,
  zoom,
  today,
  statuses,
  showIdle,
}: {
  works: WorkItem[];
  installers: Installer[];
  window: Window;
  zoom: Zoom;
  today: string;
  statuses: LifecycleStatus[];
  showIdle: boolean;
}) {
  const dayPx = ZOOMS[zoom].dayPx;
  const rows = buildRows(works, installers, showIdle);
  const width = totalDays(win) * dayPx;
  const months = monthTicks(win, dayPx);
  const weeks = weekTicks(win, dayPx);
  const todayX = dayPosition(today, win, dayPx);
  const bodyHeight = rows.reduce((sum, r) => sum + rowHeight(r), 0);
  const statusLabel = (code: string | null) => (code ? statuses.find((s) => s.code === code)?.label ?? code : "Sem estado");

  return (
    <div className="works" role="region" aria-label="Calendário de obras por instalador e equipa">
      <div className="works__labels" style={{ width: LABEL_W }}>
        <div className="works__corner" style={{ height: AXIS_H }}>
          Instalador / equipa
        </div>
        {rows.map((row) => (
          <div
            key={row.key}
            className={`works__label ${row.kind === "header" ? "works__label--header" : ""} ${row.indent ? "works__label--indent" : ""} ${row.muted ? "works__label--muted" : ""}`}
            style={{ height: rowHeight(row) }}
            title={row.label}
          >
            <span>{row.label}</span>
            {row.kind === "lane" && row.works.length > 0 && <span className="works__count">{row.works.length}</span>}
          </div>
        ))}
      </div>

      <div className="works__scroll">
        <div className="works__canvas" style={{ width, height: AXIS_H + bodyHeight }}>
          <div className="works__axis" style={{ height: AXIS_H }} aria-hidden="true">
            {months.map((m) => (
              <div key={m.left} className="works__month" style={{ left: m.left, width: m.width }}>
                {m.width >= 40 ? m.label : ""}
              </div>
            ))}
            {zoom === "weeks" &&
              weeks.map((w) => (
                <div key={w.iso} className="works__weeklabel" style={{ left: w.left }}>
                  {w.day}
                </div>
              ))}
          </div>

          {/* Linhas de grelha (segundas-feiras) e de "hoje", por baixo das barras. */}
          <div className="works__grid" style={{ top: AXIS_H, height: bodyHeight }} aria-hidden="true">
            {weeks.map((w) => (
              <div key={w.iso} className="works__gridline" style={{ left: w.left }} />
            ))}
            {todayX !== null && <div className="works__today" style={{ left: todayX + dayPx / 2 }} title="Hoje" />}
          </div>

          <div className="works__rows" style={{ top: AXIS_H }}>
            {rows.map((row) => (
              <div
                key={row.key}
                className={`works__row ${row.kind === "header" ? "works__row--header" : ""}`}
                style={{ height: rowHeight(row) }}
                role={row.kind === "lane" ? "group" : undefined}
                aria-label={row.kind === "lane" ? row.label : undefined}
              >
                {row.works.map((work) => {
                  const g = barGeometry(work.work_start_date, work.work_end_date, win, dayPx);
                  const lane = row.lanes.get(work.project_id) ?? 0;
                  const tone = work.lifecycle_status ? LIFECYCLE_STATUS_TONES[work.lifecycle_status] ?? "neutral" : "neutral";
                  const classes = [
                    "works__bar",
                    `works__bar--${tone}`,
                    work.work_dates_estimated ? "works__bar--estimated" : "",
                    work.conflict ? "works__bar--conflict" : "",
                    g.clippedStart ? "works__bar--clip-start" : "",
                    g.clippedEnd ? "works__bar--clip-end" : "",
                  ]
                    .filter(Boolean)
                    .join(" ");
                  const text = describe(work, statusLabel(work.lifecycle_status));
                  return (
                    <Link
                      key={work.project_id}
                      to={`/projects/${work.project_id}`}
                      className={classes}
                      style={{ left: g.left, width: g.width, top: ROW_PAD + lane * (LANE_H + LANE_GAP), height: LANE_H }}
                      title={text}
                      aria-label={text}
                    >
                      {work.conflict && <Icon name="alert" size={13} />}
                      <span className="works__barname">{work.name}</span>
                    </Link>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
