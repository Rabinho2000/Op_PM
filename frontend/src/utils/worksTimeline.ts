// Lógica pura do calendário de obras (D-072) — testável sem DOM. Datas sempre
// como texto ISO `YYYY-MM-DD` e contas em UTC, para o fuso e a hora de verão
// nunca deslocarem um dia.
import type { Installer, WorkItem } from "../api/client";

export type Zoom = "weeks" | "months" | "quarters";

export const ZOOMS: Record<Zoom, { label: string; dayPx: number }> = {
  weeks: { label: "Semanas", dayPx: 24 },
  months: { label: "Meses", dayPx: 6 },
  quarters: { label: "Trimestres", dayPx: 3 },
};

const DAY_MS = 86_400_000;

function parse(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  return Date.UTC(y, m - 1, d);
}

function format(ms: number): string {
  const d = new Date(ms);
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`;
}

export const addDays = (iso: string, n: number): string => format(parse(iso) + n * DAY_MS);
export const daysBetween = (a: string, b: string): number => Math.round((parse(b) - parse(a)) / DAY_MS);

export function startOfMonth(iso: string): string {
  return `${iso.slice(0, 7)}-01`;
}

export function addMonths(iso: string, n: number): string {
  const [y, m] = iso.split("-").map(Number);
  const total = y * 12 + (m - 1) + n;
  return `${Math.floor(total / 12)}-${String((total % 12) + 1).padStart(2, "0")}-01`;
}

export const endOfMonth = (iso: string): string => addDays(addMonths(iso, 1), -1);

/** Segunda-feira da semana que contém `iso`. */
export function startOfWeek(iso: string): string {
  const weekday = new Date(parse(iso)).getUTCDay(); // 0 = domingo
  return addDays(iso, -((weekday + 6) % 7));
}

// --- janela --------------------------------------------------------------------

export interface Window {
  from: string;
  to: string;
}

/** Janela de cada zoom a partir de uma data de arranque. Semanas: 10 semanas;
 * meses: 10 meses; trimestres: 19 meses. */
export function windowFrom(zoom: Zoom, from: string): Window {
  if (zoom === "weeks") {
    const monday = startOfWeek(from);
    return { from: monday, to: addDays(monday, 10 * 7 - 1) };
  }
  const first = startOfMonth(from);
  return { from: first, to: endOfMonth(addMonths(first, zoom === "months" ? 9 : 18)) };
}

/** Janela por omissão à volta de hoje (D10): semanas −2/+8; meses −3/+6; trimestres −6/+12. */
export function defaultWindow(zoom: Zoom, today: string): Window {
  if (zoom === "weeks") return windowFrom("weeks", addDays(today, -14));
  return windowFrom(zoom, addMonths(today, zoom === "months" ? -3 : -6));
}

/** Desloca a janela para a frente (+1) ou para trás (−1): 4 semanas, 3 meses ou 6 meses. */
export function shiftWindow(zoom: Zoom, from: string, direction: 1 | -1): Window {
  if (zoom === "weeks") return windowFrom("weeks", addDays(from, 28 * direction));
  return windowFrom(zoom, addMonths(from, (zoom === "months" ? 3 : 6) * direction));
}

export const totalDays = (w: Window): number => daysBetween(w.from, w.to) + 1;

// --- geometria das barras ----------------------------------------------------------

export interface BarGeometry {
  left: number;
  width: number;
  /** A obra começa antes da janela / acaba depois dela. */
  clippedStart: boolean;
  clippedEnd: boolean;
}

export function barGeometry(startDate: string, endDate: string, w: Window, dayPx: number): BarGeometry {
  const last = totalDays(w) - 1;
  const startIndex = daysBetween(w.from, startDate);
  const endIndex = daysBetween(w.from, endDate);
  const from = Math.max(0, startIndex);
  const to = Math.min(last, endIndex);
  return {
    left: from * dayPx,
    width: Math.max(4, (to - from + 1) * dayPx),
    clippedStart: startIndex < 0,
    clippedEnd: endIndex > last,
  };
}

/** Posição em píxeis de uma data, ou `null` se estiver fora da janela. */
export function dayPosition(iso: string, w: Window, dayPx: number): number | null {
  const index = daysBetween(w.from, iso);
  return index < 0 || index >= totalDays(w) ? null : index * dayPx;
}

// --- faixas (várias obras em simultâneo na mesma linha) ------------------------------

/** Atribui cada obra à primeira faixa livre: duas obras que partilham um dia nunca
 * ficam na mesma faixa (as datas são inclusivas). */
export function packLanes(works: WorkItem[]): { lanes: Map<string, number>; count: number } {
  const ordered = [...works].sort(
    (a, b) => a.work_start_date.localeCompare(b.work_start_date) || a.work_end_date.localeCompare(b.work_end_date)
  );
  const laneEnds: string[] = [];
  const lanes = new Map<string, number>();
  for (const work of ordered) {
    let lane = laneEnds.findIndex((end) => end < work.work_start_date);
    if (lane === -1) {
      lane = laneEnds.length;
      laneEnds.push(work.work_end_date);
    } else {
      laneEnds[lane] = work.work_end_date;
    }
    lanes.set(work.project_id, lane);
  }
  return { lanes, count: laneEnds.length };
}

// --- linhas: instalador → equipa ------------------------------------------------------

export interface TimelineRow {
  key: string;
  /** "header": só o nome do instalador (as equipas vêm por baixo); "lane": linha com barras. */
  kind: "header" | "lane";
  label: string;
  /** Linha de uma equipa (indentada) ou o instalador sem equipas / sem instalador. */
  indent: boolean;
  works: WorkItem[];
  lanes: Map<string, number>;
  laneCount: number;
  muted?: boolean;
}

function laneRow(key: string, label: string, indent: boolean, works: WorkItem[], muted = false): TimelineRow {
  const { lanes, count } = packLanes(works);
  return { key, kind: "lane", label, indent, works, lanes, laneCount: Math.max(1, count), muted };
}

/** Agrupa as obras por instalador e equipa. Um instalador com equipas tem uma linha
 * de cabeçalho e uma linha por equipa (mais "Sem equipa" quando há obras sem equipa);
 * sem equipas, uma só linha. As obras sem instalador ficam no fim. Por omissão só
 * há linhas com obras; `showIdle` acrescenta as equipas ativas sem obras. */
export function buildRows(works: WorkItem[], installers: Installer[], showIdle = false): TimelineRow[] {
  const rows: TimelineRow[] = [];
  const byInstaller = new Map<string | null, WorkItem[]>();
  for (const work of works) {
    const list = byInstaller.get(work.installer_id) ?? [];
    list.push(work);
    byInstaller.set(work.installer_id, list);
  }

  for (const installer of installers) {
    const own = byInstaller.get(installer.id) ?? [];
    const teamRows: TimelineRow[] = [];
    for (const team of installer.teams) {
      const teamWorks = own.filter((w) => w.installer_team_id === team.id);
      if (teamWorks.length > 0 || (showIdle && team.is_active)) {
        teamRows.push(laneRow(`${installer.id}:${team.id}`, team.name, true, teamWorks, teamWorks.length === 0));
      }
    }
    const noTeam = own.filter((w) => w.installer_team_id === null);
    if (installer.teams.length === 0) {
      if (own.length > 0 || (showIdle && installer.is_active)) {
        rows.push(laneRow(installer.id, installer.name, false, own, own.length === 0));
      }
      continue;
    }
    if (teamRows.length === 0 && noTeam.length === 0) continue;
    rows.push({ key: `${installer.id}:header`, kind: "header", label: installer.name, indent: false, works: [], lanes: new Map(), laneCount: 0 });
    rows.push(...teamRows);
    if (noTeam.length > 0) rows.push(laneRow(`${installer.id}:none`, "Sem equipa", true, noTeam));
  }

  const orphan = byInstaller.get(null) ?? [];
  if (orphan.length > 0) rows.push(laneRow("none", "Sem instalador", false, orphan));
  return rows;
}

// --- cabeçalho do eixo do tempo --------------------------------------------------------

const MONTHS_PT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

export interface MonthTick {
  left: number;
  width: number;
  label: string;
}

export function monthTicks(w: Window, dayPx: number): MonthTick[] {
  const ticks: MonthTick[] = [];
  let cursor = w.from;
  while (cursor <= w.to) {
    const monthEnd = endOfMonth(cursor);
    const end = monthEnd < w.to ? monthEnd : w.to;
    const [y, m] = cursor.split("-").map(Number);
    ticks.push({
      left: daysBetween(w.from, cursor) * dayPx,
      width: (daysBetween(cursor, end) + 1) * dayPx,
      label: `${MONTHS_PT[m - 1]} ${y}`,
    });
    cursor = addDays(end, 1);
  }
  return ticks;
}

export interface WeekTick {
  left: number;
  /** Dia do mês da segunda-feira, para etiquetar (só no zoom de semanas). */
  day: number;
  iso: string;
}

/** Uma marca por segunda-feira dentro da janela. */
export function weekTicks(w: Window, dayPx: number): WeekTick[] {
  const ticks: WeekTick[] = [];
  let monday = startOfWeek(w.from);
  if (monday < w.from) monday = addDays(monday, 7);
  for (; monday <= w.to; monday = addDays(monday, 7)) {
    ticks.push({ left: daysBetween(w.from, monday) * dayPx, day: Number(monday.slice(8)), iso: monday });
  }
  return ticks;
}

/** "12/05/2026" (pt-PT) a partir de ISO, sem passar por `Date` local. */
export function formatIsoPt(iso: string): string {
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
}
