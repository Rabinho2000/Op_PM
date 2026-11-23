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

/**
 * Data e hora de Lisboa por extenso ("19/11/2026, 15:30"; com `weekday`,
 * "quinta-feira, 19/11/2026, 15:30"). Um valor que não é data volta tal e qual.
 */
export function formatLisbonDateTime(isoDateTime: string, { weekday = false }: { weekday?: boolean } = {}): string {
  const date = new Date(isoDateTime);
  if (Number.isNaN(date.getTime())) return isoDateTime;
  return new Intl.DateTimeFormat("pt-PT", {
    timeZone: "Europe/Lisbon",
    ...(weekday ? { weekday: "long" as const } : {}),
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function formatDateTimePt(isoDateTime: string): string {
  const date = new Date(isoDateTime);
  if (Number.isNaN(date.getTime())) return isoDateTime;
  return date.toLocaleString("pt-PT", { timeZone: "Europe/Lisbon", dateStyle: "short", timeStyle: "short" });
}

// Converte a hora "de parede" de Lisboa (valor de um <input type="datetime-local">,
// ex. "2026-07-15T09:00") no instante UTC correspondente, em ISO com offset
// ("2026-07-15T08:00:00.000Z"). Independente do fuso do browser/runner e
// correto no horário de Verão/Inverno — ao contrário de anexar ":00" a uma
// string sem offset, que o JS interpreta na hora local de quem executa.
const LISBON_WALL_CLOCK = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Europe/Lisbon",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

function lisbonOffsetMinutes(utcMs: number): number {
  const parts = LISBON_WALL_CLOCK.formatToParts(new Date(utcMs));
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value ?? "0");
  const wallAsUtc = Date.UTC(get("year"), get("month") - 1, get("day"), get("hour"), get("minute"));
  return Math.round((wallAsUtc - Math.floor(utcMs / 60000) * 60000) / 60000);
}

export function lisbonWallClockToIso(local: string, ambiguous: "earlier" | "later" = "later"): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(local);
  if (!match) throw new Error(`Data/hora inválida: ${local}`);
  const [, y, mo, d, h, mi] = match.map(Number) as unknown as number[];
  const asUtc = Date.UTC(y, mo - 1, d, h, mi);
  const offsets = new Set([
    lisbonOffsetMinutes(asUtc - 2 * 60 * 60 * 1000),
    lisbonOffsetMinutes(asUtc),
    lisbonOffsetMinutes(asUtc + 2 * 60 * 60 * 1000),
  ]);
  const candidates = [...offsets]
    .map((offset) => asUtc - offset * 60 * 1000)
    .filter((candidate) => {
      const actualOffset = lisbonOffsetMinutes(candidate);
      return candidate + actualOffset * 60 * 1000 === asUtc;
    })
    .sort((a, b) => a - b);
  if (candidates.length > 0) {
    const chosen = ambiguous === "earlier" ? candidates[0] : candidates[candidates.length - 1];
    return new Date(chosen).toISOString();
  }
  // Duas passagens: a primeira aproxima com o offset de `asUtc`, a segunda
  // corrige perto das mudanças de hora (último domingo de Março/Outubro).
  const first = asUtc - lisbonOffsetMinutes(asUtc) * 60000;
  const utc = asUtc - lisbonOffsetMinutes(first) * 60000;
  return new Date(utc).toISOString();
}
