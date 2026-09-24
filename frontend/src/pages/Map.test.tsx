// Mapa operacional: sem provider de tiles configurado tem de mostrar
// sempre a lista funcional (nunca uma página quebrada); com provider,
// mostra também o mapa Leaflet.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { MapData } from "../api/client";
import { makeMe } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import MapPage from "./Map";

const api = vi.hoisted(() => ({
  getMapData: vi.fn(),
  createSupplier: vi.fn(),
  createPickupPoint: vi.fn(),
  updateProject: vi.fn(),
  createTask: vi.fn(),
  optimizeRoute: vi.fn(),
  planTrip: vi.fn(),
  createCalendarEvent: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, ...api };
});

function mapData(overrides: Partial<MapData> = {}): MapData {
  return {
    config: { provider_enabled: false, tile_url: "", tile_attribution: "" },
    projects: [
      {
        id: "proj-1",
        name: "Instalação Sintética Um",
        client_name: "Cliente Sintético",
        pm_person_id: "pm-1",
        pm_display_name: "PM Sintético",
        status: "em_curso",
        lifecycle_status: "construcao",
        lat: 38.7,
        lon: -9.1,
        power_kwp: 10,
        open_tasks_count: 2,
        issues_count: 1,
        attention: "yellow",
        operational_tasks_count: 1,
        overdue_operational_tasks_count: 0,
        blocked_operational_tasks_count: 0,
        urgent_operational_tasks_count: 0,
        next_operational_task: { id: "task-1", title: "Recolher material sintético", due_date: "2026-10-01", priority: "medium" },
        material_visible: true,
        has_material_on_site: false,
        material_sku_count: 0,
        visits_visible: true,
        upcoming_visits_count: 2,
        next_visit: { id: "ev-1", title: "Visita técnica sintética", starts_at: "2099-03-10T10:00:00Z", ends_at: "2099-03-10T11:00:00Z", assigned_to_display_name: "PM Sintético" },
      },
    ],
    projects_without_coordinates: [
      {
        id: "proj-2",
        name: "Instalação Sem Coordenadas",
        client_name: null,
        pm_person_id: null,
        pm_display_name: null,
        status: "planeado",
        lifecycle_status: "construcao",
        lat: null,
        lon: null,
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
      },
    ],
    suppliers: [
      {
        id: "sup-1",
        name: "Fornecedor Sintético",
        category: "cabos",
        contact: "912345000",
        email: null,
        address: "Rua Sintética 1",
        lat: 38.71,
        lon: -9.12,
        is_preferred: true,
        lead_time_days: 3,
        materials: "cabo solar",
        is_active: true,
      },
    ],
    pickup_points: [
      {
        id: "pk-1",
        name: "Ponto de Recolha Sintético",
        supplier_id: "sup-1",
        address: "Rua Sintética 2",
        lat: 38.72,
        lon: -9.13,
        schedule: "9h-18h",
        contact: null,
        materials: "cabo solar",
        notes: "",
        is_active: true,
      },
    ],
    issues: [
      {
        id: "iss-1",
        project_id: "proj-1",
        description: "Acesso bloqueado ao telhado",
        category: "acesso",
        priority: "alta",
        status: "aberta",
        assigned_to_person_id: null,
        due_date: null,
        lat: 38.7,
        lon: -9.1,
        related_task_id: null,
        notes: "",
        visible_on_map: true,
        created_by_person_id: null,
        created_at: "2026-09-01T10:00:00Z",
        project_name: "Instalação Sintética Um",
      },
    ],
    summary: {
      visible_active_projects: 4,
      mapped_projects: 3,
      unmapped_projects: 1,
      map_coverage_percent: 75,
      green_projects: 2,
      yellow_projects: 1,
      red_projects: 1,
      operational_clean_percent: 50,
      projects_with_material: 0,
    },
    ...overrides,
  };
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.getMapData.mockResolvedValue(mapData());
});

describe("Mapa operacional", () => {
  it("mostra a lista funcional quando o provider de mapa não está configurado", async () => {
    renderWithProviders(<MapPage />, { me: makeMe({ permissions: ["map.view"] }) });
    expect(await screen.findByRole("button", { name: "Instalação Sintética Um" })).toBeInTheDocument();
    expect(screen.getByText(/Sem provider de mapa configurado/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Fornecedor Sintético/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Ponto de Recolha Sintético/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Acesso bloqueado ao telhado/ })).toBeInTheDocument();
  });

  it("mostra o resumo (summary) e o estado de attention de cada projeto, sem recalcular no frontend", async () => {
    renderWithProviders(<MapPage />, { me: makeMe({ permissions: ["map.view"] }) });
    await screen.findByRole("button", { name: "Instalação Sintética Um" });

    // Resumo vem sempre de data.summary — nunca calculado a partir das listas.
    expect(screen.getByText("75%", { selector: ".stat__value" })).toBeInTheDocument();
    expect(screen.getByText("50%", { selector: ".stat__value" })).toBeInTheDocument();
    expect(screen.getAllByText(/^Atenção$|^Crítico$/).length).toBeGreaterThan(0);
  });

  it("filtra instalações por attention e por 'com pendências'", async () => {
    renderWithProviders(<MapPage />, { me: makeMe({ permissions: ["map.view"] }) });
    await screen.findByRole("button", { name: "Instalação Sintética Um" }); // attention=yellow

    fireEvent.change(screen.getByLabelText("Atenção"), { target: { value: "red" } });
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Instalação Sintética Um" })).not.toBeInTheDocument()
    );

    fireEvent.change(screen.getByLabelText("Atenção"), { target: { value: "yellow" } });
    expect(await screen.findByRole("button", { name: "Instalação Sintética Um" })).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Com pendências"));
    expect(screen.getByRole("button", { name: "Instalação Sintética Um" })).toBeInTheDocument();
  });

  it("não oferece 'Criar tarefa' sem permissão de tarefas", async () => {
    renderWithProviders(<MapPage />, { me: makeMe({ permissions: ["map.view"] }) });
    fireEvent.click(await screen.findByRole("button", { name: "Instalação Sintética Um" }));
    await screen.findByText("Detalhe");
    expect(screen.queryByRole("button", { name: /criar tarefa/i })).not.toBeInTheDocument();
  });

  it("cria uma tarefa a partir da instalação selecionada e recarrega o mapa", async () => {
    renderWithProviders(<MapPage />, { me: makeMe({ permissions: ["map.view", "task.edit_all"] }) });
    fireEvent.click(await screen.findByRole("button", { name: "Instalação Sintética Um" }));
    fireEvent.click(await screen.findByRole("button", { name: /criar tarefa/i }));

    fireEvent.change(await screen.findByLabelText("Título *"), { target: { value: "Recolher módulos" } });
    fireEvent.change(screen.getByLabelText("Categoria"), { target: { value: "material" } });
    fireEvent.change(screen.getByLabelText("Prioridade"), { target: { value: "urgent" } });

    api.createTask.mockResolvedValue({});
    api.getMapData.mockClear();
    fireEvent.click(screen.getByRole("button", { name: /^criar tarefa$/i }));

    await waitFor(() =>
      expect(api.createTask).toHaveBeenCalledWith({
        project_id: "proj-1",
        title: "Recolher módulos",
        category: "material",
        priority: "urgent",
        due_date: null,
      })
    );
    await waitFor(() => expect(api.getMapData).toHaveBeenCalled()); // attention pode ter mudado
  });

  it("exige título para criar a tarefa", async () => {
    renderWithProviders(<MapPage />, { me: makeMe({ permissions: ["map.view", "task.edit_own"] }) });
    fireEvent.click(await screen.findByRole("button", { name: "Instalação Sintética Um" }));
    fireEvent.click(await screen.findByRole("button", { name: /criar tarefa/i }));
    fireEvent.click(await screen.findByRole("button", { name: /^criar tarefa$/i }));
    expect(await screen.findByText("Indique o título da tarefa.")).toBeInTheDocument();
    expect(api.createTask).not.toHaveBeenCalled();
  });

  it("mostra a próxima visita e o número de visitas futuras no detalhe", async () => {
    renderWithProviders(<MapPage />, { me: makeMe({ permissions: ["map.view"] }) });
    fireEvent.click(await screen.findByRole("button", { name: "Instalação Sintética Um" }));
    expect(await screen.findByText(/Visita técnica sintética — .*\(PM Sintético\) · 2 agendada\(s\)/)).toBeInTheDocument();
  });

  it("sem calendar.view mostra 'sem permissão' e nunca '0 visitas'", async () => {
    api.getMapData.mockResolvedValue(
      mapData({
        projects: [
          { ...mapData().projects[0], visits_visible: false, upcoming_visits_count: null, next_visit: null },
        ],
      })
    );
    renderWithProviders(<MapPage />, { me: makeMe({ permissions: ["map.view"] }) });
    fireEvent.click(await screen.findByRole("button", { name: "Instalação Sintética Um" }));
    expect(await screen.findByText("Sem permissão para ver o calendário")).toBeInTheDocument();
    expect(screen.queryByText(/agendada\(s\)/)).not.toBeInTheDocument();
  });

  it("não oferece 'Agendar visita' sem calendar.manage", async () => {
    renderWithProviders(<MapPage />, { me: makeMe({ permissions: ["map.view"] }) });
    fireEvent.click(await screen.findByRole("button", { name: "Instalação Sintética Um" }));
    await screen.findByText("Detalhe");
    expect(screen.queryByRole("button", { name: /agendar visita/i })).not.toBeInTheDocument();
  });

  it("agenda uma visita com as horas de Lisboa convertidas para instantes com offset", async () => {
    renderWithProviders(<MapPage />, { me: makeMe({ permissions: ["map.view", "calendar.manage"] }) });
    fireEvent.click(await screen.findByRole("button", { name: "Instalação Sintética Um" }));
    fireEvent.click(await screen.findByRole("button", { name: /agendar visita/i }));

    fireEvent.change(await screen.findByLabelText("Início *"), { target: { value: "2099-07-15T09:00" } });
    fireEvent.change(screen.getByLabelText("Fim *"), { target: { value: "2099-07-15T10:30" } });

    api.createCalendarEvent.mockResolvedValue({});
    api.getMapData.mockClear();
    fireEvent.click(screen.getByRole("button", { name: /^agendar visita$/i }));

    // Verão em Lisboa (UTC+1): 09:00 -> 08:00Z. Nunca uma string sem offset.
    await waitFor(() =>
      expect(api.createCalendarEvent).toHaveBeenCalledWith({
        title: "Visita técnica",
        starts_at: "2099-07-15T08:00:00.000Z",
        ends_at: "2099-07-15T09:30:00.000Z",
        project_id: "proj-1",
      })
    );
    await waitFor(() => expect(api.getMapData).toHaveBeenCalled());
  });

  it("valida o intervalo e recusa visitas no passado", async () => {
    renderWithProviders(<MapPage />, { me: makeMe({ permissions: ["map.view", "calendar.manage"] }) });
    fireEvent.click(await screen.findByRole("button", { name: "Instalação Sintética Um" }));
    fireEvent.click(await screen.findByRole("button", { name: /agendar visita/i }));

    fireEvent.click(await screen.findByRole("button", { name: /^agendar visita$/i }));
    expect(await screen.findByText("Indique título, início e fim.")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Início *"), { target: { value: "2099-07-15T10:00" } });
    fireEvent.change(screen.getByLabelText("Fim *"), { target: { value: "2099-07-15T09:00" } });
    fireEvent.click(screen.getByRole("button", { name: /^agendar visita$/i }));
    expect(await screen.findByText("O fim tem de ser depois do início.")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Início *"), { target: { value: "2020-01-01T09:00" } });
    fireEvent.change(screen.getByLabelText("Fim *"), { target: { value: "2020-01-01T10:00" } });
    fireEvent.click(screen.getByRole("button", { name: /^agendar visita$/i }));
    expect(await screen.findByText("Uma visita futura tem de começar no futuro.")).toBeInTheDocument();
    expect(api.createCalendarEvent).not.toHaveBeenCalled();
  });

  describe("otimização de rota", () => {
    function optimized(overrides: Record<string, unknown> = {}) {
      return {
        stops: [
          { kind: "project", id: "proj-1", name: "Instalação Sintética Um", lat: 38.7, lon: -9.1, leg_km: 0, cumulative_km: 0 },
          { kind: "pickup", id: "pk-1", name: "Ponto de Recolha Sintético", lat: 38.72, lon: -9.13, leg_km: 3.5, cumulative_km: 3.5 },
          { kind: "supplier", id: "sup-1", name: "Fornecedor Sintético", lat: 38.71, lon: -9.12, leg_km: 1.6, cumulative_km: 5.1 },
        ],
        return_leg_km: null,
        round_trip: false,
        total_km: 5.1,
        requested_order_km: 7.4,
        saved_km: 2.3,
        method: "exact",
        distance_model: "great_circle",
        ...overrides,
      };
    }

    async function selectThree() {
      renderWithProviders(<MapPage />, { me: makeMe({ permissions: ["map.view"] }) });
      await screen.findByRole("button", { name: "Instalação Sintética Um" });
      // Ordem de seleção = ordem pedida: obra (partida), fornecedor, recolha.
      fireEvent.click(screen.getByLabelText("Selecionar Instalação Sintética Um para rota"));
      fireEvent.click(screen.getByLabelText("Selecionar Fornecedor Sintético para rota"));
      fireEvent.click(screen.getByLabelText("Selecionar Ponto de Recolha Sintético para rota"));
    }

    it("só permite otimizar com pelo menos duas paragens", async () => {
      renderWithProviders(<MapPage />, { me: makeMe({ permissions: ["map.view"] }) });
      await screen.findByRole("button", { name: "Instalação Sintética Um" });
      expect(screen.getByRole("button", { name: /otimizar ordem/i })).toBeDisabled();
      fireEvent.click(screen.getByLabelText("Selecionar Instalação Sintética Um para rota"));
      expect(screen.getByRole("button", { name: /otimizar ordem/i })).toBeDisabled();
      fireEvent.click(screen.getByLabelText("Selecionar Fornecedor Sintético para rota"));
      expect(screen.getByRole("button", { name: /otimizar ordem/i })).toBeEnabled();
    });

    it("envia só as referências pela ordem de seleção (nunca coordenadas) e mostra o resultado", async () => {
      await selectThree();
      api.optimizeRoute.mockResolvedValue(optimized());
      fireEvent.click(screen.getByRole("button", { name: /otimizar ordem/i }));

      await waitFor(() =>
        expect(api.optimizeRoute).toHaveBeenCalledWith(
          [
            { kind: "project", id: "proj-1" },
            { kind: "supplier", id: "sup-1" },
            { kind: "pickup", id: "pk-1" },
          ],
          false
        )
      );
      const result = await screen.findByLabelText("Rota otimizada");
      expect(result).toHaveTextContent("5.1 km em linha reta");
      expect(result).toHaveTextContent("menos 2.3 km do que a ordem escolhida (7.4 km)");
      expect(result).toHaveTextContent("Ordem ótima.");
      expect(result).toHaveTextContent("Instalação Sintética Um (partida)");
      expect(result).toHaveTextContent("Distâncias em linha reta (aproximação) — não são quilómetros de condução.");
      // A ordem mostrada é a do servidor (recolha antes do fornecedor).
      const items = Array.from(result.querySelectorAll("li")).map((li) => li.textContent);
      expect(items[1]).toContain("Ponto de Recolha Sintético");
      expect(items[2]).toContain("Fornecedor Sintético");
    });

    it("distingue uma heurística de uma ordem ótima", async () => {
      await selectThree();
      api.optimizeRoute.mockResolvedValue(optimized({ method: "heuristic" }));
      fireEvent.click(screen.getByRole("button", { name: /otimizar ordem/i }));
      expect(await screen.findByText(/Boa ordem, mas não garantidamente a ótima\./)).toBeInTheDocument();
    });

    it("'Abrir rota' usa exatamente a ordem calculada pelo servidor", async () => {
      const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
      await selectThree();
      api.optimizeRoute.mockResolvedValue(optimized());
      fireEvent.click(screen.getByRole("button", { name: /otimizar ordem/i }));
      await screen.findByLabelText("Rota otimizada");

      fireEvent.click(screen.getByRole("button", { name: /abrir rota \(3\)/i }));
      const url = decodeURIComponent(String(openSpy.mock.calls[0][0]));
      // partida -> recolha -> fornecedor (destino): não a ordem de seleção.
      expect(url).toContain("destination=38.71,-9.12");
      expect(url).toContain("waypoints=38.7,-9.1|38.72,-9.13");
      openSpy.mockRestore();
    });

    it("com 'Voltar ao ponto de partida' pede regresso e mostra a perna final", async () => {
      await selectThree();
      fireEvent.click(screen.getByLabelText("Voltar ao ponto de partida"));
      api.optimizeRoute.mockResolvedValue(optimized({ round_trip: true, return_leg_km: 2.2, total_km: 7.3 }));
      fireEvent.click(screen.getByRole("button", { name: /otimizar ordem/i }));

      await waitFor(() => expect(api.optimizeRoute).toHaveBeenCalledWith(expect.any(Array), true));
      expect(await screen.findByText("Regresso à partida — +2.2 km")).toBeInTheDocument();
    });

    it("mostra a mensagem do servidor quando a otimização é recusada", async () => {
      await selectThree();
      const { ApiError } = await vi.importActual<typeof import("../api/client")>("../api/client");
      api.optimizeRoute.mockRejectedValue(new ApiError(400, "Paragens sem coordenadas: Fornecedor X."));
      fireEvent.click(screen.getByRole("button", { name: /otimizar ordem/i }));
      expect(await screen.findByText("Paragens sem coordenadas: Fornecedor X.")).toBeInTheDocument();
      expect(screen.queryByLabelText("Rota otimizada")).not.toBeInTheDocument();
    });

    it("descarta a rota otimizada quando a seleção muda (deixa de valer)", async () => {
      await selectThree();
      api.optimizeRoute.mockResolvedValue(optimized());
      fireEvent.click(screen.getByRole("button", { name: /otimizar ordem/i }));
      await screen.findByLabelText("Rota otimizada");

      fireEvent.click(screen.getByLabelText("Selecionar Ponto de Recolha Sintético para rota")); // desmarca
      await waitFor(() => expect(screen.queryByLabelText("Rota otimizada")).not.toBeInTheDocument());
    });
  });

  describe("plano de deslocação", () => {
    function plan(overrides: Record<string, unknown> = {}) {
      return {
        stops: [
          {
            kind: "project", id: "proj-1", name: "Instalação Sintética Um", lat: 38.7, lon: -9.1, leg_km: 0, cumulative_km: 0, info: null,
            jobs: {
              tasks: [{ id: "t1", title: "Medir telhado", category: "field", priority: "high", status: "todo", due_date: "2026-10-01", is_overdue: true }],
              issues: [{ id: "i1", description: "Acesso bloqueado ao telhado", category: "obra", priority: "high", due_date: null }],
              collect: [{ item_id: "it1", item_name: "Painel 450 W", item_unit: "un", quantity: "3.000" }],
              next_visit: null,
            },
          },
          { kind: "pickup", id: "pk-1", name: "Ponto de Recolha Sintético", lat: 38.72, lon: -9.13, leg_km: 3.5, cumulative_km: 3.5, info: "cabo solar", jobs: null },
          { kind: "supplier", id: "sup-1", name: "Fornecedor Sintético", lat: 38.71, lon: -9.12, leg_km: 1.6, cumulative_km: 5.1, info: null, jobs: null },
        ],
        return_leg_km: null, round_trip: false, total_km: 5.1, requested_order_km: 7.4, saved_km: 2.3, method: "exact", distance_model: "great_circle",
        summary: { projects: 1, suppliers: 1, pickup_points: 1, operational_tasks: 1, overdue_tasks: 1, issues: 1, items_to_collect: 1 },
        visibility: { tasks: true, issues: true, material: true, visits: true },
        ...overrides,
      };
    }

    async function selectThreeAndPlan(response: unknown = plan()) {
      renderWithProviders(<MapPage />, { me: makeMe({ permissions: ["map.view"] }) });
      await screen.findByRole("button", { name: "Instalação Sintética Um" });
      fireEvent.click(screen.getByLabelText("Selecionar Instalação Sintética Um para rota"));
      fireEvent.click(screen.getByLabelText("Selecionar Fornecedor Sintético para rota"));
      fireEvent.click(screen.getByLabelText("Selecionar Ponto de Recolha Sintético para rota"));
      api.planTrip.mockResolvedValue(response);
      fireEvent.click(screen.getByRole("button", { name: /planear deslocação/i }));
      return await screen.findByText("Plano da deslocação");
    }

    it("só permite planear com pelo menos duas paragens", async () => {
      renderWithProviders(<MapPage />, { me: makeMe({ permissions: ["map.view"] }) });
      await screen.findByRole("button", { name: "Instalação Sintética Um" });
      expect(screen.getByRole("button", { name: /planear deslocação/i })).toBeDisabled();
      fireEvent.click(screen.getByLabelText("Selecionar Instalação Sintética Um para rota"));
      fireEvent.click(screen.getByLabelText("Selecionar Fornecedor Sintético para rota"));
      expect(screen.getByRole("button", { name: /planear deslocação/i })).toBeEnabled();
    });

    it("envia só as referências pela ordem de seleção e mostra o que há a fazer em cada paragem", async () => {
      await selectThreeAndPlan();
      expect(api.planTrip).toHaveBeenCalledWith(
        [
          { kind: "project", id: "proj-1" },
          { kind: "supplier", id: "sup-1" },
          { kind: "pickup", id: "pk-1" },
        ],
        false
      );
      const summary = screen.getByLabelText("Resumo da deslocação");
      expect(summary).toHaveTextContent("5.1 km em linha reta — menos 2.3 km");
      expect(summary).toHaveTextContent("1 instalação(ões) · 1 fornecedor(es) · 1 ponto(s) de recolha · 1 tarefa(s) operacional(is) (1 atrasada(s)) · 1 pendência(s) · 1 material(is) a recolher");
      // Dentro do diálogo: a página por trás também lista as pendências do mapa.
      const dialog = within(screen.getByRole("dialog"));
      expect(dialog.getByText(/Medir telhado/)).toBeInTheDocument();
      expect(dialog.getByText(/Acesso bloqueado ao telhado/)).toBeInTheDocument();
      expect(dialog.getByText(/3.000 un — Painel 450 W/)).toBeInTheDocument();
      expect(dialog.getByText(/Materiais: cabo solar/)).toBeInTheDocument(); // info do ponto de recolha
    });

    it("uma secção sem permissão mostra 'sem permissão' e nunca 'nenhuma tarefa'", async () => {
      const restricted = plan();
      restricted.stops[0] = { ...restricted.stops[0], jobs: { tasks: null, issues: [], collect: null, next_visit: null } } as never;
      restricted.summary = { ...restricted.summary, operational_tasks: null, overdue_tasks: null, items_to_collect: null } as never;
      await selectThreeAndPlan(restricted);
      expect(screen.getByText("Sem permissão para ver as tarefas.")).toBeInTheDocument();
      expect(screen.getByText("Sem permissão para ver o inventário.")).toBeInTheDocument();
      expect(screen.getByText("Nenhuma pendência aberta.")).toBeInTheDocument(); // esta sim é vazia de verdade
      expect(screen.queryByText("Nenhuma tarefa operacional aberta.")).not.toBeInTheDocument();
    });

    it("'Abrir rota' do plano usa exatamente a ordem do servidor", async () => {
      const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
      await selectThreeAndPlan();
      fireEvent.click(screen.getByRole("button", { name: /^abrir rota$/i }));
      const url = decodeURIComponent(String(openSpy.mock.calls[0][0]));
      // partida -> recolha -> fornecedor (destino): não a ordem de seleção.
      expect(url).toContain("destination=38.71,-9.12");
      expect(url).toContain("waypoints=38.7,-9.1|38.72,-9.13");
      openSpy.mockRestore();
    });

    it("copia o resumo em texto para a área de transferência", async () => {
      const writeText = vi.fn().mockResolvedValue(undefined);
      Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
      await selectThreeAndPlan();
      fireEvent.click(screen.getByRole("button", { name: /copiar resumo/i }));
      await waitFor(() => expect(writeText).toHaveBeenCalled());
      const text = String(writeText.mock.calls[0][0]);
      expect(text).toContain("Deslocação — 3 paragens, 5.1 km (distância em linha reta, aproximação)");
      expect(text).toContain("- Tarefa: Medir telhado (atrasada)");
      expect(await screen.findByText("Resumo copiado.")).toBeInTheDocument();
    });

    it("mostra a mensagem do servidor quando o plano é recusado", async () => {
      renderWithProviders(<MapPage />, { me: makeMe({ permissions: ["map.view"] }) });
      await screen.findByRole("button", { name: "Instalação Sintética Um" });
      fireEvent.click(screen.getByLabelText("Selecionar Instalação Sintética Um para rota"));
      fireEvent.click(screen.getByLabelText("Selecionar Fornecedor Sintético para rota"));
      const { ApiError } = await vi.importActual<typeof import("../api/client")>("../api/client");
      api.planTrip.mockRejectedValue(new ApiError(400, "Uma das paragens não existe ou não tem permissão para a ver."));
      fireEvent.click(screen.getByRole("button", { name: /planear deslocação/i }));
      expect(await screen.findByText("Uma das paragens não existe ou não tem permissão para a ver.")).toBeInTheDocument();
      expect(screen.queryByText("Plano da deslocação")).not.toBeInTheDocument();
    });
  });

  it("filtra instalações por pesquisa", async () => {
    renderWithProviders(<MapPage />, { me: makeMe({ permissions: ["map.view"] }) });
    await screen.findByRole("button", { name: "Instalação Sintética Um" });

    fireEvent.change(screen.getByLabelText("Pesquisar"), { target: { value: "não existe nenhuma" } });
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Instalação Sintética Um" })).not.toBeInTheDocument()
    );
  });

  it("lista projetos sem coordenadas e permite defini-las", async () => {
    renderWithProviders(<MapPage />, { me: makeMe({ permissions: ["map.view"] }) });
    await screen.findByText("Instalação Sem Coordenadas");

    fireEvent.click(screen.getByRole("button", { name: /definir coordenadas/i }));
    fireEvent.change(screen.getByLabelText("Latitude"), { target: { value: "38.5" } });
    fireEvent.change(screen.getByLabelText("Longitude"), { target: { value: "-9.0" } });

    api.updateProject.mockResolvedValue({});
    fireEvent.click(screen.getByRole("button", { name: /^guardar$/i }));

    await waitFor(() =>
      expect(api.updateProject).toHaveBeenCalledWith("proj-2", { lat: 38.5, lon: -9.0 })
    );
  });

  it("esconde os botões de gestão sem as permissões de fornecedor/recolha", async () => {
    renderWithProviders(<MapPage />, { me: makeMe({ permissions: ["map.view"] }) });
    await screen.findByRole("button", { name: "Instalação Sintética Um" });
    expect(screen.queryByRole("button", { name: /^fornecedor$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^ponto de recolha$/i })).not.toBeInTheDocument();
  });

  it("permite criar um fornecedor com supplier.manage", async () => {
    renderWithProviders(<MapPage />, { me: makeMe({ permissions: ["map.view", "supplier.manage"] }) });
    await screen.findByRole("button", { name: "Instalação Sintética Um" });

    fireEvent.click(screen.getByRole("button", { name: /^fornecedor$/i }));
    fireEvent.change(screen.getByLabelText("Nome *"), { target: { value: "Novo Fornecedor Sintético" } });

    api.createSupplier.mockResolvedValue({});
    fireEvent.click(screen.getByRole("button", { name: /^criar$/i }));

    await waitFor(() =>
      expect(api.createSupplier).toHaveBeenCalledWith(
        expect.objectContaining({ name: "Novo Fornecedor Sintético" })
      )
    );
  });

  it("abre uma rota externa apenas com pelo menos dois locais selecionados", async () => {
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    renderWithProviders(<MapPage />, { me: makeMe({ permissions: ["map.view"] }) });
    await screen.findByRole("button", { name: "Instalação Sintética Um" });

    fireEvent.click(screen.getByRole("button", { name: /abrir rota \(0\)/i }));
    expect(openSpy).not.toHaveBeenCalled();

    fireEvent.click(screen.getByLabelText("Selecionar Instalação Sintética Um para rota"));
    fireEvent.click(screen.getByLabelText("Selecionar Fornecedor Sintético para rota"));
    fireEvent.click(screen.getByRole("button", { name: /abrir rota \(2\)/i }));

    expect(openSpy).toHaveBeenCalledWith(expect.stringContaining("google.com/maps/dir"), "_blank", "noopener,noreferrer");
    openSpy.mockRestore();
  });
});
