// Peças partilhadas pelas configurações de listas (tarefas e projetos): têm a
// mesma estrutura (colunas escolhidas, ordenação, filtros) e antes cada uma
// repetia a validação de colunas, os guardas e a ordenação estável.

export type SortDirection = "asc" | "desc";

/** Guarda de tipo para um conjunto fechado de valores. */
export function oneOf<T extends string>(allowed: readonly T[]): (value: unknown) => value is T {
  return (value: unknown): value is T => typeof value === "string" && (allowed as readonly string[]).includes(value);
}

export function isSortDirection(value: unknown): value is SortDirection {
  return value === "asc" || value === "desc";
}

/**
 * Colunas guardadas -> lista válida: só colunas conhecidas, sem repetidas, por
 * ordem. `required` fica sempre à cabeça; sem nada válido (ou se não for uma
 * lista) voltam as omissões.
 */
export function normalizeColumnList<C extends string>(
  columns: unknown,
  allowed: readonly C[],
  defaults: readonly C[],
  required: readonly C[] = [],
): C[] {
  if (!Array.isArray(columns)) return [...defaults];
  const isColumn = oneOf(allowed);
  const seen = new Set<C>(required);
  const normalized: C[] = [...required];
  for (const value of columns) {
    if (!isColumn(value) || seen.has(value)) continue;
    seen.add(value);
    normalized.push(value);
  }
  return normalized.length > 0 ? normalized : [...defaults];
}

export function isNullish(value: unknown): boolean {
  return value === null || value === undefined || value === "";
}

/** Comparação "natural" (pt, números por valor, sem maiúsculas/acentos). */
export function compareNatural(a: unknown, b: unknown): number {
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

/**
 * Ordenação estável: valores em falta ficam SEMPRE no fim (também em `desc`) e
 * os empates mantêm a ordem original.
 */
export function sortStable<T>(
  items: readonly T[],
  getValue: (item: T) => unknown,
  compare: (a: T, b: T) => number,
  direction: SortDirection,
): T[] {
  return items
    .map((item, index) => ({ item, index }))
    .sort((left, right) => {
      const leftMissing = isNullish(getValue(left.item));
      const rightMissing = isNullish(getValue(right.item));
      if (leftMissing || rightMissing) {
        if (leftMissing && rightMissing) return left.index - right.index;
        return leftMissing ? 1 : -1;
      }
      const compared = compare(left.item, right.item);
      return compared === 0 ? left.index - right.index : direction === "desc" ? -compared : compared;
    })
    .map(({ item }) => item);
}
