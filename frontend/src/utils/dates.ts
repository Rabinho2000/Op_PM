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
