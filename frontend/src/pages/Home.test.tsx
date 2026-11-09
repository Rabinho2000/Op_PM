import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { makeMe, makeSummary } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import Home from "./Home";

// vi.mock é elevado acima de tudo — o mock tem de ser criado com vi.hoisted.
const { getDashboardSummary, getDashboardWorks, getMapData } = vi.hoisted(() => ({
  getDashboardSummary: vi.fn(),
  getDashboardWorks: vi.fn(),
  getMapData: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, getDashboardSummary, getDashboardWorks, getMapData };
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
    getDashboardWorks.mockReset().mockResolvedValue({ construction: [], preparation: [] });
    getMapData.mockReset();
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

  it("prioriza título e indicadores antes do mapa, das obras e dos widgets de tarefas", async () => {
    getDashboardSummary.mockResolvedValue(makeSummary());
    renderWithProviders(<Home />, { me: makeMe() });

    const title = await screen.findByRole("heading", { level: 1, name: /Chefe/ });
    const indicators = screen.getByRole("region", { name: "Indicadores principais" });
    const works = screen.getByRole("region", { name: "Obras em curso e próximas obras" });
    const weekly = screen.getByRole("region", { name: "Resumo da semana" });
    const follows = Node.DOCUMENT_POSITION_FOLLOWING;

    expect(title.compareDocumentPosition(indicators) & follows).toBeTruthy();
    expect(indicators.compareDocumentPosition(works) & follows).toBeTruthy();
    expect(works.compareDocumentPosition(weekly) & follows).toBeTruthy();
    expect(screen.getByTestId("stat-Projetos ativos")).toBeInTheDocument();
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

  it("mostra as listas de obras sem carregar o mapa sem map.view", async () => {
    getDashboardSummary.mockResolvedValue(makeSummary());
    getDashboardWorks.mockResolvedValue({
      construction: [
        {
          id: "work-build",
          name: "Obra Sintética em Construção",
          expected_start_date: "2026-10-24",
          pm_display_name: "PM Sintético Um",
          installer_display_name: "Instalador Sintético",
          team_display_name: "Equipa Sintética",
          next_task_title: "Montar estrutura sintética",
          next_task_due_date: "2026-10-25",
        },
      ],
      preparation: [
        {
          id: "work-prep",
          name: "Obra Sintética em Preparação",
          expected_start_date: "2026-11-02",
          pm_display_name: "PM Sintético Um",
          installer_display_name: "Instalador Sintético",
          team_display_name: "Equipa Sintética",
          next_task_title: "Confirmar material sintético",
          next_task_due_date: null,
        },
      ],
    });

    renderWithProviders(<Home />, { me: makeMe() });

    expect(await screen.findByRole("heading", { name: "Obras a decorrer" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Próximas obras" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Obra Sintética em Construção" })).toHaveAttribute(
      "href",
      "/projects/work-build"
    );
    expect(screen.getByText(/Montar estrutura sintética/)).toBeInTheDocument();
    expect(screen.getByText(/Confirmar material sintético/)).toBeInTheDocument();
    expect(getMapData).not.toHaveBeenCalled();
  });

  it("mostra o fallback do provider quando tem map.view e mantém as listas", async () => {
    getDashboardSummary.mockResolvedValue(makeSummary());
    getDashboardWorks.mockResolvedValue({ construction: [], preparation: [] });
    getMapData.mockResolvedValue({
      config: { provider_enabled: false, tile_url: "", tile_attribution: "" },
      projects: [],
      projects_without_coordinates: [],
      suppliers: [],
      pickup_points: [],
      issues: [],
      summary: {},
    });

    renderWithProviders(<Home />, { me: makeMe({ permissions: [...makeMe().permissions, "map.view"] }) });

    expect(await screen.findByText(/Sem provider de mapa configurado/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Obras a decorrer" })).toBeInTheDocument();
    expect(getMapData).toHaveBeenCalledTimes(1);
  });

  it("mostra estados vazios para ambas as listas de obras", async () => {
    getDashboardSummary.mockResolvedValue(makeSummary());
    getDashboardWorks.mockResolvedValue({ construction: [], preparation: [] });

    renderWithProviders(<Home />, { me: makeMe() });

    expect(await screen.findByText("Nenhuma obra a decorrer." )).toBeInTheDocument();
    expect(screen.getByText("Nenhuma obra em preparação." )).toBeInTheDocument();
  });
});
