// Formatação de números em pt-PT, com as `Intl.NumberFormat` em cache (criar uma
// por chamada, numa tabela com centenas de células, é caro).

const cache = new Map<string, Intl.NumberFormat>();

function formatter(minimumFractionDigits: number | undefined, maximumFractionDigits: number): Intl.NumberFormat {
  const key = `${minimumFractionDigits ?? ""}|${maximumFractionDigits}`;
  let instance = cache.get(key);
  if (!instance) {
    instance = new Intl.NumberFormat("pt-PT", { minimumFractionDigits, maximumFractionDigits });
    cache.set(key, instance);
  }
  return instance;
}

export const EMPTY_VALUE = "—";

/** `1234,5` -> "1234,5" (pt-PT); `null`, `undefined` e valores não finitos -> "—". */
export function formatNumberPt(
  value: number | null | undefined,
  { max = 2, min }: { max?: number; min?: number } = {},
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EMPTY_VALUE;
  return formatter(min, Math.max(max, min ?? 0)).format(value);
}
