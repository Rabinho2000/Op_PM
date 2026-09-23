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
