import { describe, expect, it } from "vitest";
import type { TripPlan, TripStop } from "../api/client";
import { buildTripSummaryText } from "./tripPlan";

function stop(overrides: Partial<TripStop> = {}): TripStop {
  return {
    kind: "project",
    id: "p1",
    name: "Instalação Um",
    lat: 38.7,
    lon: -9.1,
    leg_km: 0,
    cumulative_km: 0,
    info: null,
    jobs: { tasks: [], issues: [], collect: [], next_visit: null },
    ...overrides,
  };
}

function plan(overrides: Partial<TripPlan> = {}): TripPlan {
  return {
    stops: [stop()],
    return_leg_km: null,
    round_trip: false,
    total_km: 12.5,
    requested_order_km: 20,
    saved_km: 7.5,
    method: "exact",
    distance_model: "great_circle",
    summary: { projects: 1, suppliers: 0, pickup_points: 0, operational_tasks: 0, overdue_tasks: 0, issues: 0, items_to_collect: 0 },
    visibility: { tasks: true, issues: true, material: true, visits: true },
    ...overrides,
  };
}

describe("buildTripSummaryText", () => {
  it("resume paragens, distância (dita em linha reta) e totais", () => {
    const text = buildTripSummaryText(
      plan({
        stops: [stop(), stop({ id: "p2", name: "Instalação Dois", leg_km: 12.5, cumulative_km: 12.5 })],
        summary: { projects: 2, suppliers: 1, pickup_points: 0, operational_tasks: 3, overdue_tasks: 1, issues: 2, items_to_collect: 1 },
      })
    );
    expect(text).toContain("Deslocação — 2 paragens, 12.5 km (distância em linha reta, aproximação)");
    expect(text).toContain("2 instalação(ões) · 1 fornecedor(es) · 3 tarefa(s) operacional(is) (1 atrasada(s)) · 2 pendência(s) · 1 material(is) a recolher");
    expect(text).toContain("1. Instalação Um (partida)");
    expect(text).toContain("2. Instalação Dois — +12.5 km");
  });

  it("lista tarefas, pendências, material e visita de cada instalação", () => {
    const text = buildTripSummaryText(
      plan({
        stops: [
          stop({
            jobs: {
              tasks: [{ id: "t1", title: "Medir telhado", category: "field", priority: "high", status: "todo", due_date: "2026-10-01", is_overdue: true }],
              issues: [{ id: "i1", description: "Acesso bloqueado", category: "obra", priority: "urgent", due_date: null }],
              collect: [{ item_id: "x", item_name: "Painel 450 W", item_unit: "un", quantity: "3.000" }],
              next_visit: { id: "v1", title: "Visita técnica", starts_at: "2099-03-10T10:00:00Z", ends_at: "2099-03-10T11:00:00Z", assigned_to_display_name: null },
            },
          }),
        ],
      })
    );
    expect(text).toContain("- Tarefa: Medir telhado (atrasada), prazo 01/10/2026 [alta]");
    expect(text).toContain("- Pendência: Acesso bloqueado [urgente]");
    expect(text).toContain("- Recolher: 3.000 un Painel 450 W");
    expect(text).toContain("- Visita agendada: Visita técnica (");
  });

  it("uma secção sem permissão (null) nunca aparece como 'nada a fazer' e é assinalada", () => {
    const text = buildTripSummaryText(
      plan({
        stops: [stop({ jobs: { tasks: null, issues: [], collect: null, next_visit: null } })],
        summary: { projects: 1, suppliers: 0, pickup_points: 0, operational_tasks: null, overdue_tasks: null, issues: 0, items_to_collect: null },
      })
    );
    expect(text).toContain("(algumas secções não visíveis com as suas permissões)");
    expect(text).not.toContain("tarefa(s) operacional(is)");
    expect(text).not.toContain("material(is) a recolher");
  });

  it("mostra os materiais de fornecedores e a perna de regresso", () => {
    const text = buildTripSummaryText(
      plan({
        round_trip: true,
        return_leg_km: 4.2,
        stops: [stop(), stop({ kind: "supplier", id: "s1", name: "Fornecedor X", leg_km: 3, jobs: null, info: "Cabos, conectores" })],
      })
    );
    expect(text).toContain("Materiais: Cabos, conectores");
    expect(text).toContain("3. Regresso à partida — +4.2 km");
    expect(text).toContain(", com regresso");
  });
});
