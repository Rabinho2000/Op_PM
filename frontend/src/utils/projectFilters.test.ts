import { describe, expect, it } from "vitest";
import { IN_PROGRESS_LIFECYCLE, lifecycleFromParams, lifecycleToParams, lifecycleView } from "./projectFilters";

describe("projectFilters", () => {
  it("sem parâmetros = os em curso; 'todos' = sem filtro; senão os pedidos", () => {
    expect(lifecycleFromParams([])).toEqual([...IN_PROGRESS_LIFECYCLE]);
    expect(lifecycleFromParams(["todos"])).toEqual([]);
    expect(lifecycleFromParams(["preparacao"])).toEqual(["preparacao"]);
  });

  it("a omissão não vai para o URL e desmarcar tudo vira 'todos'", () => {
    expect(lifecycleToParams([...IN_PROGRESS_LIFECYCLE].reverse())).toEqual([]);
    expect(lifecycleToParams([])).toEqual(["todos"]);
    expect(lifecycleToParams(["construcao"])).toEqual(["construcao"]);
  });

  it("classifica a vista", () => {
    expect(lifecycleView([...IN_PROGRESS_LIFECYCLE])).toBe("in_progress");
    expect(lifecycleView([])).toBe("all");
    expect(lifecycleView(["construcao"])).toBe("custom");
  });
});
