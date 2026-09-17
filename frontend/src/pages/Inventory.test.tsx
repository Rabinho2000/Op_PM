// Inventário: stock central visível a quem tem inventory.view; "Registar
// movimento" só a quem tem inventory.manage_central (D-051, mesmo padrão
// de permissões.test.tsx).
import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { InventoryItem, InventoryMovement } from "../api/client";
import { makeMe } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import Inventory from "./Inventory";

const api = vi.hoisted(() => ({
  listInventoryItems: vi.fn(),
  listInventoryMovements: vi.fn(),
  createCentralMovement: vi.fn(),
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
  api.listInventoryMovements.mockResolvedValue([movement()]);
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
});
