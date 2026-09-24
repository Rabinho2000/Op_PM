// Que projetos a lista mostra por omissão (D-076): os **em curso** — tudo o que ainda não foi
// entregue ao cliente. Os já entregues e certificados são a maioria (262 de 295) e escondem o
// trabalho do dia a dia; continuam a um clique ("Todos") e no URL (`?estado=todos`).
//
// O estado vive no URL, para o painel poder apontar à lista completa e a vista ser partilhável:
//   sem `estado`           → os em curso (por omissão)
//   `estado=todos`         → sem filtro de estado
//   `estado=a&estado=b`    → esses estados
export const IN_PROGRESS_LIFECYCLE = ["on_hold_cliente", "preparacao", "construcao", "construido"] as const;

export const ALL_STATES = "todos";

const sameSet = (a: readonly string[], b: readonly string[]): boolean =>
  a.length === b.length && a.every((x) => b.includes(x));

/** Estados a pedir ao servidor, a partir dos `estado` do URL (lista vazia = todos). */
export function lifecycleFromParams(values: string[]): string[] {
  if (values.length === 0) return [...IN_PROGRESS_LIFECYCLE];
  if (values.includes(ALL_STATES)) return [];
  return values;
}

/** Valores de `estado` a pôr no URL para uma escolha; `[]` (nada por definir) = a omissão. */
export function lifecycleToParams(selected: string[]): string[] {
  if (selected.length === 0) return [ALL_STATES]; // desmarcar tudo = mostrar todos
  if (sameSet(selected, IN_PROGRESS_LIFECYCLE)) return []; // a omissão não vai para o URL
  return selected;
}

export type LifecycleView = "in_progress" | "all" | "custom";

export function lifecycleView(selected: string[]): LifecycleView {
  if (selected.length === 0) return "all";
  if (sameSet(selected, IN_PROGRESS_LIFECYCLE)) return "in_progress";
  return "custom";
}
