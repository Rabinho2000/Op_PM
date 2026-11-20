import { describe, expect, it } from "vitest";
import { compareNatural, isNullish, isSortDirection, normalizeColumnList, oneOf, sortStable } from "./listConfig";

describe("configuração partilhada de listas", () => {
  it("oneOf e isSortDirection são guardas estritos", () => {
    const isColor = oneOf(["red", "blue"] as const);
    expect(isColor("red")).toBe(true);
    expect(isColor("green")).toBe(false);
    expect(isColor(1)).toBe(false);
    expect(isSortDirection("desc")).toBe(true);
    expect(isSortDirection("up")).toBe(false);
  });

  it("normalizeColumnList valida, tira repetidas e põe as obrigatórias à cabeça", () => {
    const allowed = ["a", "b", "c"] as const;
    const defaults = ["a", "b"] as const;
    expect(normalizeColumnList(["c", "x", "c", "b"], allowed, defaults)).toEqual(["c", "b"]);
    expect(normalizeColumnList(["c", "a"], allowed, defaults, ["a"])).toEqual(["a", "c"]);
    expect(normalizeColumnList("nada", allowed, defaults)).toEqual(["a", "b"]);
    expect(normalizeColumnList(["x", "y"], allowed, defaults)).toEqual(["a", "b"]);
    expect(normalizeColumnList(["x"], allowed, defaults, ["c"])).toEqual(["c"]);
  });

  it("isNullish e compareNatural", () => {
    expect(isNullish(null) && isNullish(undefined) && isNullish("")).toBe(true);
    expect(isNullish(0)).toBe(false);
    expect(compareNatural("Obra 2", "obra 10")).toBeLessThan(0);
    expect(compareNatural("a", "A")).toBe(0);
  });

  it("sortStable deixa os vazios no fim nas duas direções e mantém a ordem dos empates", () => {
    const items = [
      { id: 1, v: "b" },
      { id: 2, v: null },
      { id: 3, v: "a" },
      { id: 4, v: "b" },
      { id: 5, v: "" },
    ];
    const by = (direction: "asc" | "desc") =>
      sortStable(items, (i) => i.v, (a, b) => compareNatural(a.v, b.v), direction).map((i) => i.id);
    expect(by("asc")).toEqual([3, 1, 4, 2, 5]);
    expect(by("desc")).toEqual([1, 4, 3, 2, 5]);
    expect(items.map((i) => i.id)).toEqual([1, 2, 3, 4, 5]); // não altera a entrada
  });
});
