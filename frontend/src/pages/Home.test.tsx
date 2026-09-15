import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import Home from "./Home";
import type { DashboardSummary } from "../api/client";

// vi.mock's factory is hoisted above every top-level statement in this
// file, so any fixture it references has to go through vi.hoisted() —
// a plain top-level const would throw "Cannot access before
// initialization" (see https://vitest.dev/api/vi.html#vi-hoisted).
const { summary } = vi.hoisted(() => {
  const summary: DashboardSummary = {
    generated_at: "2026-09-15T10:00:00Z",
    scope: "all",
    week_start: "2026-09-14",
    week_end: "2026-09-20",
    active_projects_count: 3,
    projects_starting_next_30_days: [
      { id: "p1", name: "Projeto A", pm_display_name: "PM Um", start_date: "2026-09-25", missing_fields: [] },
    ],
    overdue_tasks: [
      {
        id: "t1",
        title: "Preparação da instalação",
        task_type: "preparacao_instalacao",
        priority: "medium",
        project_id: "p1",
        project_name: "Projeto A",
        assigned_to_display_name: null,
        due_date: "2026-09-10",
      },
    ],
    tasks_due_this_week: [],
    pending_technical_visits: [],
    pending_commissioning: [],
    projects_without_pm: [],
    projects_missing_data: [],
    current_absences: [],
    upcoming_absences: [],
    upcoming_birthdays: [
      { person_id: "u1", person_display_name: "Comercial Sintético", birth_date: "1996-09-15", days_until: 0 },
    ],
    urgent_tasks: [],
  };
  return { summary };
});

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    getDashboardSummary: vi.fn().mockResolvedValue(summary),
  };
});

describe("Home (dashboard)", () => {
  it("renders the key metrics returned by the API", async () => {
    render(
      <MemoryRouter>
        <Home />
      </MemoryRouter>
    );

    expect(await screen.findByText("Painel de operações")).toBeInTheDocument();
    expect(await screen.findByText("3")).toBeInTheDocument(); // projetos ativos
    expect(await screen.findByText(/Preparação da instalação/)).toBeInTheDocument();
    expect(await screen.findByText(/Comercial Sintético.*hoje/)).toBeInTheDocument();
  });
});
