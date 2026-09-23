import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { makeMe, makeSummary } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import Home from "./Home";

// vi.mock é elevado acima de tudo — o mock tem de ser criado com vi.hoisted.
const { getDashboardSummary } = vi.hoisted(() => ({ getDashboardSummary: vi.fn() }));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, getDashboardSummary };
});

const task = {
  id: "t1",
  title: "Preparação da instalação",
  task_type: "preparacao_instalacao",
  priority: "medium" as const,
  project_id: "p1",
  project_name: "Projeto Sintético A",
  assigned_to_display_name: null,
  due_date: "2026-09-10",
};

function statValue(label: string): string | null {
  return screen.getByTestId(`stat-${label}`).textContent;
}

describe("Home (painel)", () => {
  beforeEach(() => {
    getDashboardSummary.mockReset();
  });

  it("mostra os indicadores exatamente como vêm da API", async () => {
    getDashboardSummary.mockResolvedValue(
      makeSummary({
        active_projects_count: 22,
        overdue_tasks: [task],
        urgent_tasks: [{ ...task, id: "t2", priority: "urgent" }],
        projects_without_pm: [{ id: "p2", name: "Projeto Sem PM", pm_display_name: null, start_date: null, missing_fields: [] }],
        upcoming_birthdays: [
          { person_id: "u1", person_display_name: "Comercial Sintético", birth_date: "1996-09-16", days_until: 0 },
        ],
        current_absences: [
          {
            id: "a1",
            person_id: "u2",
            person_display_name: "PM Sintético Um",
            start_date: "2026-09-14",
            end_date: "2026-09-19",
            type: "ferias",
          },
        ],
        week_overview: [
          { date: "2026-09-14", tasks_due_count: 2, tasks_completed_count: 1, people_absent_count: 1 },
          { date: "2026-09-15", tasks_due_count: 0, tasks_completed_count: 0, people_absent_count: 0 },
        ],
      })
    );

    renderWithProviders(<Home />, { me: makeMe() });

    expect(await screen.findByRole("heading", { level: 1, name: /Chefe/ })).toBeInTheDocument();
    expect(statValue("Projetos ativos")).toBe("22");
    expect(statValue("Tarefas atrasadas")).toBe("1");
    expect(statValue("Tarefas urgentes")).toBe("1");
    expect(statValue("Projetos sem PM")).toBe("1");
    expect(statValue("Tarefas desta semana")).toBe("0");
    expect(statValue("Fotografias por colocar")).toBe("0");

    const overdue = screen.getByRole("region", { name: "Tarefas atrasadas" });
    expect(within(overdue).getByText("Projeto Sintético A")).toBeInTheDocument();
    expect(screen.getByText("Comercial Sintético")).toBeInTheDocument();
    expect(screen.getByText(/hoje/, { selector: ".badge" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Resumo da semana por dia" })).toBeInTheDocument();
    expect(getDashboardSummary).toHaveBeenCalledTimes(1);
  });

  it("mostra o estado de carregamento enquanto a API não responde", () => {
    getDashboardSummary.mockReturnValue(new Promise(() => undefined));
    renderWithProviders(<Home />, { me: makeMe() });
    expect(screen.getAllByTestId("loading-state").length).toBeGreaterThan(0);
    expect(screen.getByText("A carregar os indicadores…")).toBeInTheDocument();
  });

  it("mostra o erro e permite tentar novamente", async () => {
    getDashboardSummary
      .mockRejectedValueOnce(new ApiError(500, "Servidor indisponível"))
      .mockResolvedValueOnce(makeSummary({ active_projects_count: 3 }));

    renderWithProviders(<Home />, { me: makeMe() });

    expect(await screen.findByTestId("error-state")).toHaveTextContent("Servidor indisponível");
    fireEvent.click(screen.getByRole("button", { name: /Tentar novamente/ }));
    await waitFor(() => expect(statValue("Projetos ativos")).toBe("3"));
  });

  it("mostra estados vazios quando não há dados", async () => {
    getDashboardSummary.mockResolvedValue(makeSummary());
    renderWithProviders(<Home />, { me: makeMe() });

    expect(await screen.findByText("Sem tarefas atrasadas.")).toBeInTheDocument();
    expect(screen.getByText("Sem tarefas urgentes em aberto.")).toBeInTheDocument();
    expect(screen.getByText("Todos os projetos ativos têm PM atribuído.")).toBeInTheDocument();
    expect(screen.getByText("Sem aniversários nos próximos 30 dias.")).toBeInTheDocument();
  });

  it("explica quando o perfil não vê projetos (scope none)", async () => {
    getDashboardSummary.mockResolvedValue(makeSummary({ scope: "none" }));
    renderWithProviders(<Home />, { me: makeMe({ permissions: [] }) });
    expect(await screen.findByText("Sem projetos visíveis para o seu perfil")).toBeInTheDocument();
  });

  it("mostra o aviso de fotografias pendentes com ligação aos projetos", async () => {
    getDashboardSummary.mockResolvedValue(
      makeSummary({
        projects_photos_pending: [
          { id: "p9", name: "Fábrica Sintética", pm_display_name: "PM Sintético Um", start_date: null, missing_fields: [] },
        ],
      })
    );
    renderWithProviders(<Home />, { me: makeMe() });

    const alert = await screen.findByText(/Fotografias por colocar na Drive em 1 projeto/);
    expect(alert).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Fábrica Sintética" })).toHaveAttribute("href", "/projects/p9");
    expect(statValue("Fotografias por colocar")).toBe("1");
  });

  it("não mostra o aviso de fotografias quando não há pendentes", async () => {
    getDashboardSummary.mockResolvedValue(makeSummary({ active_projects_count: 1 }));
    renderWithProviders(<Home />, { me: makeMe() });
    await screen.findByTestId("stat-Projetos ativos");
    expect(screen.queryByText(/Fotografias por colocar na Drive em/)).not.toBeInTheDocument();
  });
});
