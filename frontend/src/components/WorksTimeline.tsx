import { MouseEvent as ReactMouseEvent, PointerEvent as ReactPointerEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { Installer, LifecycleStatus, WorkItem, WorkPlanInput } from "../api/client";
import { LIFECYCLE_STATUS_TONES } from "../utils/labels";
import {
  barGeometry,
  buildPlanChange,
  buildRows,
  dayPosition,
  dayTicks,
  formatIsoPt,
  DragMode,
  monthTicks,
  pixelsToDays,
  rowAtOffset,
  rowTops,
  shiftDates,
  TimelineRow,
  totalDays,
  workEndDate,
  workEntryKey,
  workStartDate,
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

// Deslocamento mínimo (px) para um clique passar a ser um arrasto.
const DRAG_THRESHOLD = 4;

interface DragState {
  entryKey: string;
  mode: DragMode;
  originRowKey: string;
  startX: number;
  startY: number;
  days: number;
  targetRow: TimelineRow;
  moved: boolean;
}

const rowHeight = (row: TimelineRow): number =>
  row.kind === "header" ? HEADER_ROW_H : row.laneCount * (LANE_H + LANE_GAP) - LANE_GAP + ROW_PAD * 2;

function describe(work: WorkItem, statusLabel: string): string {
  const where = [work.installer_name, work.installer_team_name ?? work.team_name].filter(Boolean).join(" / ") || "sem instalador";
  return [
    work.name,
    `${formatIsoPt(workStartDate(work))} a ${formatIsoPt(workEndDate(work))}${work.work_dates_estimated ? " (datas estimadas)" : ""}`,
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
  onPlanChange,
  onOpenProject,
}: {
  works: WorkItem[];
  installers: Installer[];
  window: Window;
  zoom: Zoom;
  today: string;
  statuses: LifecycleStatus[];
  showIdle: boolean;
  /** Chamado ao largar uma obra com alterações; sem esta propriedade o calendário é só de leitura. */
  onPlanChange?: (work: WorkItem, changes: WorkPlanInput) => void;
  /** Abre o detalhe em overlay apenas para cliques primários sem modificadores. */
  onOpenProject?: (projectId: string, event: ReactMouseEvent<HTMLAnchorElement>) => void;
}) {
  const dayPx = ZOOMS[zoom].dayPx;
  const rows = buildRows(works, installers, showIdle);
  const width = totalDays(win) * dayPx;
  const months = monthTicks(win, dayPx);
  const weeks = weekTicks(win, dayPx);
  const days = zoom === "month_days" ? dayTicks(win, dayPx) : [];
  const todayX = dayPosition(today, win, dayPx);
  const bodyHeight = rows.reduce((sum, r) => sum + rowHeight(r), 0);
  const tops = rowTops(rows, rowHeight);
  const axisHeight = zoom === "month_days" ? 56 : AXIS_H;
  const rowsRef = useRef<HTMLDivElement>(null);
  const suppressClick = useRef(false);
  const [drag, setDrag] = useState<DragState | null>(null);
  const statusLabel = (code: string | null) => (code ? statuses.find((s) => s.code === code)?.label ?? code : "Sem estado");

  // Esc cancela o arrasto em curso.
  useEffect(() => {
    if (!drag) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDrag(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drag]);

  // Afectações têm datas próprias e só podem ser alteradas no cartão de
  // equipas, via PATCH /team-assignments. O drag legado usa /work-plan.
  const editable = (work: WorkItem) => Boolean(onPlanChange) && !work.assignment_id && work.can_plan_work === true;

  function onPointerDown(e: ReactPointerEvent<HTMLElement>, work: WorkItem, row: TimelineRow) {
    if (!editable(work) || e.button !== 0) return;
    const handle = (e.target as HTMLElement).dataset?.handle;
    const mode: DragMode = handle === "start" ? "resize-start" : handle === "end" ? "resize-end" : "move";
    e.currentTarget.setPointerCapture?.(e.pointerId);
    setDrag({
      entryKey: workEntryKey(work),
      mode,
      originRowKey: row.key,
      startX: e.clientX,
      startY: e.clientY,
      days: 0,
      targetRow: row,
      moved: false,
    });
  }

  function onPointerMove(e: ReactPointerEvent<HTMLElement>, row: TimelineRow) {
    if (!drag || drag.entryKey !== e.currentTarget.dataset.entryKey) return;
    const dx = e.clientX - drag.startX;
    const dy = e.clientY - drag.startY;
    if (!drag.moved && Math.abs(dx) < DRAG_THRESHOLD && Math.abs(dy) < DRAG_THRESHOLD) return;
    let targetRow = row;
    if (drag.mode === "move" && rowsRef.current) {
      const y = e.clientY - rowsRef.current.getBoundingClientRect().top;
      targetRow = rowAtOffset(rows, rowHeight, y) ?? drag.targetRow;
    }
    setDrag({ ...drag, days: pixelsToDays(dx, dayPx), targetRow, moved: true });
  }

  function onPointerUp(e: ReactPointerEvent<HTMLElement>, work: WorkItem) {
    if (!drag || drag.entryKey !== workEntryKey(work)) return;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
    const finished = drag;
    setDrag(null);
    if (!finished.moved) return;
    suppressClick.current = true; // o clique que o navegador gera a seguir não abre o projeto
    const dates = shiftDates(work.work_start_date, work.work_end_date, finished.mode, finished.days);
    const changes = buildPlanChange(work, dates, finished.targetRow);
    if (changes) onPlanChange?.(work, changes);
  }

  return (
    <div className="works" role="region" aria-label="Calendário de obras por instalador e equipa">
      <div className="works__labels" style={{ width: LABEL_W }}>
        <div className="works__corner" style={{ height: axisHeight }}>
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
        <div className="works__canvas" style={{ width, height: axisHeight + bodyHeight }}>
          <div className={`works__axis ${zoom === "month_days" ? "works__axis--days" : ""}`} style={{ height: axisHeight }} aria-hidden="true">
            {months.map((m) => (
              <div key={m.left} className="works__month" style={{ left: m.left, width: m.width }}>
                {m.width >= 40 ? m.label : ""}
              </div>
            ))}
            {days.map((day) => (
              <div
                key={day.iso}
                className={`works__day ${day.weekend ? "works__day--weekend" : ""} ${day.iso === today ? "works__day--today" : ""}`}
                style={{ left: day.left, width: day.width }}
                title={formatIsoPt(day.iso)}
              >
                <span className="works__day-number">{day.day}</span>
                <span className="works__day-weekday">{day.weekday}</span>
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
          <div className="works__grid" style={{ top: axisHeight, height: bodyHeight }} aria-hidden="true">
            {(zoom === "month_days" ? days : weeks).map((tick) => (
              <div
                key={tick.iso}
                className={`works__gridline ${zoom === "month_days" ? "works__gridline--day" : ""}`}
                style={{ left: tick.left }}
              />
            ))}
            {todayX !== null && <div className="works__today" style={{ left: todayX + dayPx / 2 }} title="Hoje" />}
          </div>

          <div className="works__rows" style={{ top: axisHeight }} ref={rowsRef}>
            {rows.map((row, rowIndex) => (
              <div
                key={row.key}
                className={`works__row ${row.kind === "header" ? "works__row--header" : ""} ${drag?.moved && drag.mode === "move" && drag.targetRow.key === row.key ? "works__row--target" : ""}`}
                style={{ height: rowHeight(row) }}
                role={row.kind === "lane" ? "group" : undefined}
                aria-label={row.kind === "lane" ? row.label : undefined}
              >
                {row.works.map((work) => {
                  const dragging = drag?.moved === true && drag.entryKey === workEntryKey(work) ? drag : null;
                  const dates = dragging
                    ? shiftDates(workStartDate(work), workEndDate(work), dragging.mode, dragging.days)
                    : { start: workStartDate(work), end: workEndDate(work) };
                  const g = barGeometry(dates.start, dates.end, win, dayPx);
                  const lane = row.lanes.get(workEntryKey(work)) ?? 0;
                  const tone = work.lifecycle_status ? LIFECYCLE_STATUS_TONES[work.lifecycle_status] ?? "neutral" : "neutral";
                  const canDrag = editable(work);
                  const classes = [
                    "works__bar",
                    `works__bar--${tone}`,
                    work.work_dates_estimated ? "works__bar--estimated" : "",
                    work.conflict ? "works__bar--conflict" : "",
                    g.clippedStart ? "works__bar--clip-start" : "",
                    g.clippedEnd ? "works__bar--clip-end" : "",
                    canDrag ? "works__bar--draggable" : "",
                    dragging ? "works__bar--dragging" : "",
                  ]
                    .filter(Boolean)
                    .join(" ");
                  const text = describe(work, statusLabel(work.lifecycle_status));
                  const ownTop = ROW_PAD + lane * (LANE_H + LANE_GAP);
                  // Ao mudar de linha, a barra acompanha o rato na vertical até à linha de destino.
                  const targetIndex = dragging ? rows.findIndex((r) => r.key === dragging.targetRow.key) : rowIndex;
                  const top = dragging && targetIndex >= 0 && targetIndex !== rowIndex ? tops[targetIndex] - tops[rowIndex] + ROW_PAD : ownTop;
                  return (
                    <Link
                      key={workEntryKey(work)}
                      to={`/projects/${work.project_id}`}
                      className={classes}
                      data-entry-key={workEntryKey(work)}
                      style={{ left: g.left, width: g.width, top, height: LANE_H }}
                      title={dragging ? `${formatIsoPt(dates.start)} a ${formatIsoPt(dates.end)}` : text}
                      aria-label={text}
                      draggable={false}
                      onPointerDown={canDrag ? (e) => onPointerDown(e, work, row) : undefined}
                      onPointerMove={canDrag ? (e) => onPointerMove(e, row) : undefined}
                      onPointerUp={canDrag ? (e) => onPointerUp(e, work) : undefined}
                      onPointerCancel={canDrag ? () => setDrag(null) : undefined}
                      onClick={(e) => {
                        if (suppressClick.current) {
                          suppressClick.current = false;
                          e.preventDefault();
                          return;
                        }
                        if (onOpenProject && e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey) {
                          e.preventDefault();
                          onOpenProject(work.project_id, e);
                        }
                      }}
                    >
                      {canDrag && !g.clippedStart && <span className="works__handle works__handle--start" data-handle="start" aria-hidden="true" />}
                      {work.conflict && <Icon name="alert" size={13} />}
                      <span className="works__barname">{work.name}</span>
                      {canDrag && !g.clippedEnd && <span className="works__handle works__handle--end" data-handle="end" aria-hidden="true" />}
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
