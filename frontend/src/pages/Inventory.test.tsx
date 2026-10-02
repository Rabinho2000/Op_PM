// Inventário: stock central visível a quem tem inventory.view; "Registar
// movimento" só a quem tem inventory.manage_central (D-051, mesmo padrão
// de permissões.test.tsx).
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { InventoryItem, InventoryMovement } from "../api/client";
import { makeMe } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import Inventory from "./Inventory";

const api = vi.hoisted(() => ({
  listInventoryItems: vi.fn(),
  listInventoryLocations: vi.fn(),
  listInventoryMovements: vi.fn(),
  reactivateInventoryItem: vi.fn(),
  createCentralMovement: vi.fn(),
  createInventoryItem: vi.fn(),
  updateInventoryItem: vi.fn(),
  deactivateInventoryItem: vi.fn(),
  createInventoryLocation: vi.fn(),
  updateInventoryLocation: vi.fn(),
  deactivateInventoryLocation: vi.fn(),
  createOpeningStock: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, ...api };
});

function item(overrides: Partial<InventoryItem> = {}): InventoryItem {
  return {
    id: "item-1",
    sku: "CABO-DC-6MM",
    name: "Cabo solar DC 6mm²",
    unit: "km",
    category: null,
    min_stock: "10.000",
    preferred_supplier_id: null,
    lead_time_days: null,
    is_active: true,
    physical_stock: "95.000",
    available_stock: "80.000",
    total_reserved: "15.000",
    below_min_stock: false,
    ...overrides,
  };
}

function movement(overrides: Partial<InventoryMovement> = {}): InventoryMovement {
  return {
    id: "mov-1",
    item_id: "item-1",
    movement_type: "entrada",
    quantity: "100.000",
    project_id: null,
    location_id: null,
    destination_location_id: null,
    unit_cost: null,
    reference: "Entrada sintética",
    idempotency_key: null,
    created_by_person_id: null,
    created_at: "2026-09-01T10:00:00Z",
    item_name: "Cabo solar DC 6mm²",
    project_name: null,
    ...overrides,
  };
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.listInventoryItems.mockResolvedValue([item()]);
  api.listInventoryLocations.mockResolvedValue([]);
  api.listInventoryMovements.mockResolvedValue([movement()]);
  api.createInventoryItem.mockResolvedValue(item());
  api.updateInventoryItem.mockResolvedValue(item());
  api.reactivateInventoryItem.mockResolvedValue(item());
  api.deactivateInventoryItem.mockResolvedValue(item({ is_active: false }));
  api.createInventoryLocation.mockResolvedValue({
    id: "location-1",
    code: "CENTRAL",
    name: "Armazém central",
    location_type: "central",
    project_id: null,
    is_active: true,
  });
  api.updateInventoryLocation.mockResolvedValue({
    id: "location-1",
    code: "CENTRAL",
    name: "Armazém central",
    location_type: "central",
    project_id: null,
    is_active: true,
  });
  api.deactivateInventoryLocation.mockResolvedValue({});
  api.createOpeningStock.mockResolvedValue(movement());
});

describe("Inventário", () => {
  it("mostra o stock central com físico/reservado/disponível", async () => {
    renderWithProviders(<Inventory />, { me: makeMe({ permissions: ["inventory.view"] }) });
    expect((await screen.findAllByText("Cabo solar DC 6mm²")).length).toBeGreaterThan(0);
    expect(screen.getByText("95.000 km")).toBeInTheDocument();
    expect(screen.getByText("80.000 km")).toBeInTheDocument();
  });

  it("assinala um item abaixo do stock mínimo", async () => {
    api.listInventoryItems.mockResolvedValue([item({ below_min_stock: true })]);
    renderWithProviders(<Inventory />, { me: makeMe({ permissions: ["inventory.view"] }) });
    expect(await screen.findByText("Abaixo do mínimo")).toBeInTheDocument();
  });

  it("esconde 'Registar movimento' sem inventory.manage_central", async () => {
    renderWithProviders(<Inventory />, { me: makeMe({ permissions: ["inventory.view"] }) });
    await screen.findAllByText("Cabo solar DC 6mm²");
    expect(screen.queryByRole("button", { name: /registar movimento/i })).not.toBeInTheDocument();
  });

  it("mostra 'Registar movimento' com inventory.manage_central", async () => {
    renderWithProviders(<Inventory />, {
      me: makeMe({ permissions: ["inventory.view", "inventory.manage_central"] }),
    });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /registar movimento/i })).toBeInTheDocument()
    );
  });

  it("lista os movimentos recentes", async () => {
    renderWithProviders(<Inventory />, { me: makeMe({ permissions: ["inventory.view"] }) });
    expect(await screen.findByText("Entrada sintética")).toBeInTheDocument();
  });

  it("oferece criar artigo no estado vazio a quem gere o catálogo", async () => {
    api.listInventoryItems.mockResolvedValue([]);
    api.listInventoryMovements.mockResolvedValue([]);
    renderWithProviders(<Inventory />, {
      me: makeMe({ permissions: ["inventory.view", "inventory.manage_catalog"] }),
    });
    expect(await screen.findByRole("button", { name: /criar artigo/i })).toBeInTheDocument();
  });

  it("cria um artigo a partir do estado vazio", async () => {
    api.listInventoryItems.mockResolvedValue([]);
    api.listInventoryMovements.mockResolvedValue([]);
    renderWithProviders(<Inventory />, {
      me: makeMe({ permissions: ["inventory.view", "inventory.manage_catalog"] }),
    });
    fireEvent.click(await screen.findByRole("button", { name: /criar artigo/i }));
    fireEvent.change(screen.getByLabelText("SKU"), { target: { value: "CAT-NEW" } });
    fireEvent.change(screen.getByLabelText("Nome"), { target: { value: "Artigo novo" } });
    fireEvent.change(screen.getByLabelText("Unidade"), { target: { value: "un" } });
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: /^criar artigo$/i }));
    await waitFor(() => expect(api.createInventoryItem).toHaveBeenCalledWith(expect.objectContaining({ sku: "CAT-NEW", name: "Artigo novo" })));
  });

  it("regista stock inicial pela ação do artigo", async () => {
    renderWithProviders(<Inventory />, {
      me: makeMe({ permissions: ["inventory.view", "inventory.manage_central"] }),
    });
    fireEvent.click(await screen.findByRole("button", { name: /stock inicial/i }));
    fireEvent.change(screen.getByLabelText("Quantidade"), { target: { value: "12.5" } });
    fireEvent.change(screen.getByLabelText("Referência"), { target: { value: "Inventário físico" } });
    fireEvent.click(screen.getByRole("button", { name: /registar entrada/i }));
    await waitFor(() =>
      expect(api.createOpeningStock).toHaveBeenCalledWith(
        expect.objectContaining({ item_id: "item-1", quantity: "12.5", reference: "Inventário físico" }),
      ),
    );
  });

  it("oferece reativar artigos inativos e chama o cliente da API", async () => {
    api.listInventoryItems.mockResolvedValue([item({ is_active: false })]);
    api.reactivateInventoryItem.mockResolvedValue(item({ is_active: true }));
    renderWithProviders(<Inventory />, {
      me: makeMe({ permissions: ["inventory.view", "inventory.manage_catalog"] }),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Reativar" }));
    await waitFor(() => expect(api.reactivateInventoryItem).toHaveBeenCalledWith("item-1"));
  });
});
