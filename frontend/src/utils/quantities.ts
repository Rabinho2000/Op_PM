const DISCRETE_UNITS = new Set([
  "un",
  "und",
  "unid",
  "unid.",
  "unidade",
  "unidades",
  "pc",
  "pcs",
  "pç",
  "pçs",
  "peca",
  "pecas",
  "peça",
  "peças",
]);

function isDiscreteUnit(unit: string | null | undefined): boolean {
  const normalized = (unit ?? "").trim().toLocaleLowerCase("pt-PT");
  return DISCRETE_UNITS.has(normalized.replace(/\.$/, ""));
}

/**
 * Formats a quantity without hiding precision errors in discrete articles.
 * Integer quantities counted by unit lose only redundant decimal zeroes;
 * fractional quantities and fractional-unit values keep the received text.
 */
export function formatQuantity(value: string | number | null | undefined, unit?: string | null): string {
  if (value === null || value === undefined) return "—";

  const raw = String(value).trim();
  if (!raw || !isDiscreteUnit(unit)) return raw;

  const numeric = Number(raw.replace(",", "."));
  return Number.isFinite(numeric) && Number.isInteger(numeric) ? String(numeric) : raw;
}
