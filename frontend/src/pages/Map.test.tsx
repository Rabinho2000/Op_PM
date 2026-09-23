// Mapa operacional: sem provider de tiles configurado tem de mostrar
// sempre a lista funcional (nunca uma página quebrada); com provider,
// mostra também o mapa Leaflet.
import { fireEvent, screen, waitFor } from "@testing-library/react";
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
