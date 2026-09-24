import { describe, expect, it } from "vitest";
import type { MapProject } from "../api/client";
import { canFilterByMaterial, EMPTY_MAP_FILTERS, filterMapProjects } from "./mapFilters";

function project(overrides: Partial<MapProject> = {}): MapProject {
  return {
    id: "p",
    name: "Instalação Um",
    client_name: "Cliente A",
    pm_person_id: "pm-1",
    pm_display_name: "PM Um",
    status: "em_curso",
    lifecycle_status: "construcao",
    lat: 1,
    lon: 1,
    power_kwp: null,
    open_tasks_count: 0,
    issues_count: 0,
    attention: "green",
    operational_tasks_count: 0,
    overdue_operational_tasks_count: 0,
    blocked_operational_tasks_count: 0,
    urgent_operational_tasks_count: 0,
    next_operational_task: null,
    material_visible: true,
    has_material_on_site: false,
    material_sku_count: 0,
    visits_visible: true,
    upcoming_visits_count: 0,
    next_visit: null,
    ...overrides,
  };
}

const green = project({ id: "g", name: "Verde" });
const yellow = project({ id: "y", name: "Amarelo", attention: "yellow", operational_tasks_count: 1 });
const red = project({ id: "r", name: "Vermelho", client_name: "Cliente B", attention: "red", issues_count: 2 });
const withMaterial = project({ id: "m", name: "Material", has_material_on_site: true, material_sku_count: 2 });
const all = [green, yellow, red, withMaterial];

describe("filterMapProjects", () => {
  it("filtra pelo estado do projeto (ciclo de vida), independente do estado das tarefas", () => {
    const hold = project({ id: "h", name: "Em espera", lifecycle_status: "on_hold_cliente" });
    const none = project({ id: "n", name: "Sem estado", lifecycle_status: null });
    const list = [green, hold, none];
    expect(filterMapProjects(list, { ...EMPTY_MAP_FILTERS, lifecycle: "on_hold_cliente" })).toEqual([hold]);
    expect(filterMapProjects(list, { ...EMPTY_MAP_FILTERS, lifecycle: "construcao" })).toEqual([green]);
    expect(filterMapProjects(list, EMPTY_MAP_FILTERS)).toHaveLength(3);
  });

  it("sem filtros devolve tudo", () => {
    expect(filterMapProjects(all, EMPTY_MAP_FILTERS)).toHaveLength(4);
  });

  it("filtra por attention sem o recalcular", () => {
    const result = filterMapProjects(all, { ...EMPTY_MAP_FILTERS, attention: "red" });
    expect(result.map((p) => p.id)).toEqual(["r"]);
  });

  it("'com pendências' inclui pendências abertas e tarefas operacionais", () => {
    const result = filterMapProjects(all, { ...EMPTY_MAP_FILTERS, onlyWithPending: true });
    expect(result.map((p) => p.id).sort()).toEqual(["r", "y"]);
  });

  it("'material no local' só devolve projetos com has_material_on_site=true", () => {
    const result = filterMapProjects(all, { ...EMPTY_MAP_FILTERS, onlyWithMaterial: true });
    expect(result.map((p) => p.id)).toEqual(["m"]);
  });

  it("null (sem inventory.view) nunca conta como material no local", () => {
    const hidden = project({ id: "h", material_visible: false, has_material_on_site: null, material_sku_count: null });
    expect(filterMapProjects([hidden], { ...EMPTY_MAP_FILTERS, onlyWithMaterial: true })).toHaveLength(0);
  });

  it("filtra por cliente (correspondência exata)", () => {
    expect(filterMapProjects(all, { ...EMPTY_MAP_FILTERS, client: "Cliente B" }).map((p) => p.id)).toEqual(["r"]);
    expect(filterMapProjects(all, { ...EMPTY_MAP_FILTERS, client: "Cliente" })).toHaveLength(0);
  });

  it("combina pesquisa (nome/cliente), PM e estado", () => {
    expect(filterMapProjects(all, { ...EMPTY_MAP_FILTERS, search: "cliente b" }).map((p) => p.id)).toEqual(["r"]);
    expect(filterMapProjects(all, { ...EMPTY_MAP_FILTERS, pm: "Outro" })).toHaveLength(0);
    expect(filterMapProjects(all, { ...EMPTY_MAP_FILTERS, status: "concluido" })).toHaveLength(0);
  });
});

describe("canFilterByMaterial", () => {
  it("só oferece o filtro quando o utilizador pode ver inventário", () => {
    expect(canFilterByMaterial([green])).toBe(true);
    expect(canFilterByMaterial([project({ material_visible: false, has_material_on_site: null })])).toBe(false);
    expect(canFilterByMaterial([])).toBe(false);
  });
});
