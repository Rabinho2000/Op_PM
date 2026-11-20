/**
 * Texto para pesquisa: sem acentos, em minúsculas (pt-PT) e sem espaços nas
 * pontas. Única fonte para o planeamento, o inventário e o resto das pesquisas.
 */
export function normalizeSearchText(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLocaleLowerCase("pt-PT")
    .trim();
}
