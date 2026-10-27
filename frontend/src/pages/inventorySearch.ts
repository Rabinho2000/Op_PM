export interface InventorySearchableItem {
  id: string;
  name: string;
  sku: string;
  category: string | null;
  manufacturer?: string | null;
  manufacturer_name?: string | null;
  model?: string | null;
  model_name?: string | null;
  section_label?: string | null;
}

const SYNONYM_GROUPS = [
  ["painel", "modulo"],
  ["inversor", "inverter"],
  ["cabo", "fio"],
] as const;

const SYNONYMS = new Map<string, readonly string[]>(
  SYNONYM_GROUPS.flatMap((group) => group.map((word) => [word, group] as const)),
);

export function normalizeInventorySearch(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase("pt-PT")
    .trim();
}

function words(value: string): string[] {
  return normalizeInventorySearch(value).match(/[a-z0-9]+/g) ?? [];
}

function variants(word: string): readonly string[] {
  return SYNONYMS.get(word) ?? [word];
}

function editDistanceAtMostOne(left: string, right: string): boolean {
  if (Math.abs(left.length - right.length) > 1) return false;
  let leftIndex = 0;
  let rightIndex = 0;
  let differences = 0;
  while (leftIndex < left.length && rightIndex < right.length) {
    if (left[leftIndex] === right[rightIndex]) {
      leftIndex += 1;
      rightIndex += 1;
      continue;
    }
    differences += 1;
    if (differences > 1) return false;
    if (left.length > right.length) leftIndex += 1;
    else if (right.length > left.length) rightIndex += 1;
    else {
      leftIndex += 1;
      rightIndex += 1;
    }
  }
  if (leftIndex < left.length || rightIndex < right.length) differences += 1;
  return differences <= 1;
}

function tokenMatches(queryWord: string, targetWord: string): boolean {
  if (variants(queryWord).some((candidate) => targetWord.startsWith(candidate))) return true;
  return queryWord.length >= 5 && targetWord.length >= 5 && editDistanceAtMostOne(queryWord, targetWord);
}

function allQueryWordsMatch(queryWords: string[], targetWords: string[]): boolean {
  return queryWords.every((queryWord) => targetWords.some((targetWord) => tokenMatches(queryWord, targetWord)));
}

function itemFields(item: InventorySearchableItem, categoryLabel?: string): string[] {
  return [
    item.name,
    item.sku,
    categoryLabel ?? item.category ?? "Sem categoria",
    item.manufacturer,
    item.manufacturer_name,
    item.model,
    item.model_name,
  ].filter((value): value is string => Boolean(value));
}

/** Lower scores sort first; null means no match. */
export function rankInventoryItem(
  item: InventorySearchableItem,
  query: string,
  categoryLabel?: string,
): number | null {
  const normalizedQuery = normalizeInventorySearch(query);
  if (!normalizedQuery) return null;

  const normalizedName = normalizeInventorySearch(item.name);
  const normalizedSku = normalizeInventorySearch(item.sku);
  if (normalizedName === normalizedQuery) return 0;
  if (normalizedName.startsWith(normalizedQuery)) return 10;
  if (normalizedName.includes(normalizedQuery)) return 20;

  const queryWords = words(query);
  const skuWords = words(item.sku);
  if (normalizedSku.includes(normalizedQuery) || allQueryWordsMatch(queryWords, skuWords)) return 30;

  const nameWords = words(item.name);
  if (allQueryWordsMatch(queryWords, nameWords)) return 40;

  const otherWords = words(itemFields(item, categoryLabel).slice(1).join(" "));
  if (allQueryWordsMatch(queryWords, [...nameWords, ...otherWords])) return 50;
  return null;
}

export function searchInventoryItems<T extends InventorySearchableItem>(
  items: readonly T[],
  query: string,
  getCategoryLabel?: (item: T) => string,
): T[] {
  if (!normalizeInventorySearch(query)) return [];
  return items
    .map((item, index) => ({
      item,
      index,
      rank: rankInventoryItem(item, query, getCategoryLabel?.(item)),
    }))
    .filter((entry): entry is { item: T; index: number; rank: number } => entry.rank !== null)
    .sort((left, right) => left.rank - right.rank || left.item.name.localeCompare(right.item.name, "pt-PT") || left.index - right.index)
    .map(({ item }) => item);
}
