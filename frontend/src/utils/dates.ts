// Funções puras de datas — isoladas para serem testáveis sem montar
// nenhum componente (ver src/utils/dates.test.ts).

const ISO_DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;

export function formatDatePt(iso: string | null): string {
  if (!iso) return "—";
  const match = ISO_DATE_PATTERN.exec(iso);
  if (!match) return iso;
  const [, year, month, day] = match;
  return `${day}/${month}/${year}`;
}

export function isIsoDateInRange(iso: string | null, startIso: string, endIso: string): boolean {
  if (!iso) return false;
  return iso >= startIso && iso <= endIso;
}

export function daysUntilLabel(daysUntil: number): string {
  if (daysUntil === 0) return "hoje";
  if (daysUntil === 1) return "amanhã";
  return `daqui a ${daysUntil} dias`;
}

// --- D-051: apresentação de datas na interface (sempre Europe/Lisbon) ---

const LISBON_DATE_FORMAT = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Europe/Lisbon",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

// "Hoje" na perspetiva de Lisboa (mesma regra do backend), em ISO.
export function todayIsoLisbon(now: Date = new Date()): string {
  return LISBON_DATE_FORMAT.format(now);
}

function parseIso(iso: string): Date | null {
  const match = ISO_DATE_PATTERN.exec(iso);
  if (!match) return null;
  const [, y, m, d] = match;
  return new Date(Date.UTC(Number(y), Number(m) - 1, Number(d)));
}

export function addDaysIso(iso: string, days: number): string {
  const date = parseIso(iso);
  if (!date) return iso;
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

export function diffDaysIso(fromIso: string, toIso: string): number {
  const a = parseIso(fromIso);
  const b = parseIso(toIso);
  if (!a || !b) return 0;
  return Math.round((b.getTime() - a.getTime()) / 86_400_000);
}

const WEEKDAYS_SHORT = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];
const MONTHS_SHORT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
export const MONTHS_LONG = [
  "janeiro",
  "fevereiro",
  "março",
  "abril",
  "maio",
  "junho",
  "julho",
  "agosto",
  "setembro",
  "outubro",
  "novembro",
  "dezembro",
];

export function weekdayShortPt(iso: string): string {
  const date = parseIso(iso);
  return date ? WEEKDAYS_SHORT[date.getUTCDay()] : "";
}

export function formatDayMonthPt(iso: string | null): string {
  if (!iso) return "—";
  const date = parseIso(iso);
  if (!date) return iso;
  return `${date.getUTCDate()} ${MONTHS_SHORT[date.getUTCMonth()]}`;
}

// "hoje", "amanhã", "ontem", "daqui a N dias", "há N dias".
export function relativeDayLabel(iso: string | null, todayIso: string): string {
  if (!iso) return "sem prazo";
  const diff = diffDaysIso(todayIso, iso);
  if (diff === 0) return "hoje";
  if (diff === 1) return "amanhã";
  if (diff === -1) return "ontem";
  return diff > 0 ? `daqui a ${diff} dias` : `há ${-diff} dias`;
}

export function formatDateTimePt(isoDateTime: string): string {
  const date = new Date(isoDateTime);
  if (Number.isNaN(date.getTime())) return isoDateTime;
  return date.toLocaleString("pt-PT", { timeZone: "Europe/Lisbon", dateStyle: "short", timeStyle: "short" });
}
