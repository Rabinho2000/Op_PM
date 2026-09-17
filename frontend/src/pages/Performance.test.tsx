// Metas e indicadores: página única (nunca "Metas"/"Dashboards"
// separados), progresso sempre calculado no servidor, "Nova meta" só a
// quem tem performance.manage_goals.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { GoalPeriod, PerformanceSummary } from "../api/client";
import { makeMe } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import Performance from "./Performance";

const api = vi.hoisted(() => ({
  getPerformanceSummary: vi.fn(),
  createGoal: vi.fn(),
  updateGoal: vi.fn(),
  listPeople: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, ...api };
});

function goal(overrides: Partial<GoalPeriod> = {}): GoalPeriod {
  return {
    id: "goal-1",
    period_type: "year",
    year: 2026,
    quarter: null,
    semester: null,
    month: null,
    metric: "installations",
    target_value: "40.000",
    scope: "company",
    pm_person_id: null,
    pm_display_name: null,
    notes: "",
    realized: "10",
    percent: 25,
    missing: "30.000",
    expected_pace: "20.000",
    projection: "15.000",
    pace_status: "behind",
    ...overrides,
  };
}

function summary(overrides: Partial<PerformanceSummary> = {}): PerformanceSummary {
  return {
    goals: [goal()],
    portfolio: {
      not_started: 5,
      in_progress: 3,
      completed: 2,
      kwp_not_started: "0",
      kwp_in_progress: "0",
      kwp_completed: "20.000",
      certified_count: 1,
      pending_certification_count: 1,
    },
    yearly: [{ year: 2026, installations: "2", kwp: "20.000" }],
    ...overrides,
  };
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.getPerformanceSummary.mockResolvedValue(summary());
  api.listPeople.mockResolvedValue([]);
});

describe("Metas e indicadores", () => {
  it("mostra o progresso da meta calculado pelo servidor", async () => {
    renderWithProviders(<Performance />, { me: makeMe({ permissions: ["performance.view_all"] }) });
    expect((await screen.findAllByText(/Instalações concluídas/)).length).toBeGreaterThan(0);
    expect(screen.getByText(/Abaixo do ritmo esperado/)).toBeInTheDocument();
    expect(screen.getByText(/Realizado: 10 de 40.000/)).toBeInTheDocument();
  });

  it("mostra o portefólio por estado e o histórico anual", async () => {
    renderWithProviders(<Performance />, { me: makeMe({ permissions: ["performance.view_all"] }) });
    await screen.findAllByText(/Instalações concluídas/);
    expect(screen.getByText("Em preparação (não iniciado)")).toBeInTheDocument();
    expect(screen.getAllByText("2026").length).toBeGreaterThan(0);
  });

  it("esconde 'Nova meta' sem performance.manage_goals", async () => {
    renderWithProviders(<Performance />, { me: makeMe({ permissions: ["performance.view_all"] }) });
    await screen.findAllByText(/Instalações concluídas/);
    expect(screen.queryByRole("button", { name: /nova meta/i })).not.toBeInTheDocument();
  });

  it("mostra 'Nova meta' com performance.manage_goals", async () => {
    renderWithProviders(<Performance />, {
      me: makeMe({ permissions: ["performance.view_all", "performance.manage_goals"] }),
    });
    await waitFor(() => expect(screen.getByRole("button", { name: /nova meta/i })).toBeInTheDocument());
  });

  it("PM só com performance.view_own continua a ver a página", async () => {
    renderWithProviders(<Performance />, { me: makeMe({ permissions: ["performance.view_own"] }) });
    expect((await screen.findAllByText(/Instalações concluídas/)).length).toBeGreaterThan(0);
  });

  it("muda de período (trimestre) e volta a pedir o resumo com esse filtro", async () => {
    renderWithProviders(<Performance />, { me: makeMe({ permissions: ["performance.view_all"] }) });
    await screen.findAllByText(/Instalações concluídas/);
    api.getPerformanceSummary.mockClear();

    fireEvent.change(screen.getByLabelText("Período"), { target: { value: "quarter" } });
    await waitFor(() => expect(screen.getByLabelText("Trimestre")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Trimestre"), { target: { value: "2" } });

    await waitFor(() =>
      expect(api.getPerformanceSummary).toHaveBeenLastCalledWith(
        expect.objectContaining({ period_type: "quarter", quarter: 2 })
      )
    );
  });

  it("permite editar uma meta existente com performance.manage_goals", async () => {
    renderWithProviders(<Performance />, {
      me: makeMe({ permissions: ["performance.view_all", "performance.manage_goals"] }),
    });
    await screen.findAllByText(/Instalações concluídas/);

    fireEvent.click(screen.getByRole("button", { name: /editar/i }));
    const targetInput = await screen.findByLabelText("Valor do objetivo");
    fireEvent.change(targetInput, { target: { value: "60" } });

    api.updateGoal.mockResolvedValue(goal({ target_value: "60.000" }));
    fireEvent.click(screen.getByRole("button", { name: /^guardar$/i }));

    await waitFor(() => expect(api.updateGoal).toHaveBeenCalledWith("goal-1", { target_value: "60", notes: "" }));
  });

  it("esconde o botão 'Editar' de cada meta sem performance.manage_goals", async () => {
    renderWithProviders(<Performance />, { me: makeMe({ permissions: ["performance.view_all"] }) });
    await screen.findAllByText(/Instalações concluídas/);
    expect(screen.queryByRole("button", { name: /editar/i })).not.toBeInTheDocument();
  });
});
