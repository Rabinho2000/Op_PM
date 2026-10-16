import { describe, expect, it } from "vitest";
import { makeProject } from "../test/fixtures";
import {
  DEFAULT_PROJECT_LIST_COLUMNS,
  defaultProjectListConfig,
  normalizeProjectListConfig,
  sortProjects,
} from "./projectListConfig";

describe("configuração da lista de projetos", () => {
  it("usa a lista de colunas e filtros de abertura documentados", () => {
    expect(defaultProjectListConfig()).toEqual({
      columns: [...DEFAULT_PROJECT_LIST_COLUMNS],
      sort_by: "name",
      sort_direction: "asc",
      filters: {
        search: "",
        status: "",
        lifecycle: ["on_hold_cliente", "preparacao", "construcao", "construido"],
        pm: "",
        active: "active",
        startFrom: "",
        startTo: "",
      },
    });
  });

  it("normaliza colunas desconhecidas, repetidas e a posição obrigatória do projeto", () => {
    const normalized = normalizeProjectListConfig({
      columns: ["warnings", "project", "warnings", "made_up" as never, "pm"],
      sort_by: "power_kwp",
      sort_direction: "desc",
      filters: {
        search: " cliente ",
        status: "concluido",
        lifecycle: [],
        pm: "p-1",
        active: "all",
        startFrom: "2026-01-01",
        startTo: "",
      },
    });

    expect(normalized.columns).toEqual(["project", "warnings", "pm"]);
    expect(normalized.sort_by).toBe("power_kwp");
    expect(normalized.sort_direction).toBe("desc");
    expect(normalized.filters.search).toBe(" cliente ");
  });

  it("ordena nomes numericamente e deixa nulos no fim com desempate estável", () => {
    const projects = [
      makeProject({ id: "p-10", name: "Projeto 10", start_date: null }),
      makeProject({ id: "p-2", name: "Projeto 2", start_date: "2026-01-03" }),
      makeProject({ id: "p-1", name: "Projeto 1", start_date: "2026-01-03" }),
      makeProject({ id: "p-no-date", name: "Projeto 0", start_date: null }),
    ];

    expect(sortProjects(projects, "name", "asc").map((p) => p.id)).toEqual(["p-no-date", "p-1", "p-2", "p-10"]);
    expect(sortProjects(projects, "start_date", "asc").map((p) => p.id)).toEqual(["p-2", "p-1", "p-10", "p-no-date"]);
    expect(sortProjects(projects, "start_date", "desc").map((p) => p.id)).toEqual(["p-2", "p-1", "p-10", "p-no-date"]);
  });
});
