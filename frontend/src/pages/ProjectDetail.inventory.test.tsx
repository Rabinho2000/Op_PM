// Separador "Inventário" do detalhe do projeto — material no local, e as
// ações entregar/recolher (D-064). O servidor continua a validar tudo
// (recolher mais do que o que está no local, permissões por projeto).
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { InventoryItem, ProjectInventorySummary } from "../api/client";
import { makeMe, makeProject, makeTask } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import ProjectDetail from "./ProjectDetail";

const api = vi.hoisted(() => ({
  getProject: vi.fn(),
  getProjectHistory: vi.fn(),
  listTasks: vi.fn(),
  listPeople: vi.fn(),
  getProjectInventory: vi.fn(),
  listInventoryItems: vi.fn(),
  deliverProjectMaterial: vi.fn(),
  collectProjectMaterial: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, ...api };
});

const PANEL: InventoryItem = {
  id: "item-1",
  sku: "PAINEL-450",
  name: "Painel 450 W",
  unit: "un",
  min_stock: "0",
  preferred_supplier_id: null,
  lead_time_days: null,
  is_active: true,
  physical_stock: "100",
  available_stock: "90",
  total_reserved: "10",
  below_min_stock: false,
} as InventoryItem;

function summary(overrides: Partial<ProjectInventorySummary> = {}): ProjectInventorySummary {
  return { project_id: "proj-1", requirements: [], reservations: [], on_site: [], ...overrides };
}

const PERMISSIONS = [
  "project.view_all",
  "inventory.view",
  "inventory.deliver_project",
  "inventory.collect_project",
];

async function openInventoryTab(permissions = PERMISSIONS) {
  renderWithProviders(<ProjectDetail />, {
    me: makeMe({ permissions }),
    route: "/projects/proj-1",
    path: "/projects/:projectId",
  });
  await screen.findByRole("heading", { level: 1, name: makeProject().name });
  fireEvent.click(screen.getByRole("tab", { name: /inventário/i }));
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.getProject.mockResolvedValue(makeProject());
  api.getProjectHistory.mockResolvedValue([]);
  api.listTasks.mockResolvedValue([makeTask()]);
  api.listPeople.mockResolvedValue([]);
  api.listInventoryItems.mockResolvedValue([PANEL]);
  api.getProjectInventory.mockResolvedValue(summary());
});

describe("Detalhe do projeto — material no local", () => {
  it("mostra o material no local, incluindo excedentes sem necessidade associada", async () => {
    api.getProjectInventory.mockResolvedValue(
      summary({ on_site: [{ item_id: "item-1", item_name: "Painel 450 W", item_unit: "un", quantity: "3.000" }] })
    );
    await openInventoryTab();
    expect(await screen.findByText("Material no local")).toBeInTheDocument();
    expect(await screen.findByText("3.000 un")).toBeInTheDocument();
    expect(screen.getByText(/independente da reserva/i)).toBeInTheDocument();
  });

  it("mostra um estado vazio quando nada foi entregue", async () => {
    await openInventoryTab();
    expect(await screen.findByText("Nenhum material entregue e ainda no local.")).toBeInTheDocument();
  });

  it("regista uma entrega com o item e a quantidade certos", async () => {
    await openInventoryTab();
    fireEvent.click(await screen.findByRole("button", { name: /movimento/i }));

    fireEvent.change(await screen.findByLabelText("Ação"), { target: { value: "deliver" } });
    fireEvent.change(screen.getByLabelText("Item *"), { target: { value: "item-1" } });
    fireEvent.change(screen.getByLabelText("Quantidade *"), { target: { value: "13" } });
    fireEvent.change(screen.getByLabelText("Referência"), { target: { value: "Transportadora" } });

    api.deliverProjectMaterial.mockResolvedValue({});
    fireEvent.click(screen.getByRole("button", { name: /^aplicar$/i }));

    await waitFor(() =>
      expect(api.deliverProjectMaterial).toHaveBeenCalledWith("proj-1", {
        item_id: "item-1",
        quantity: "13",
        reference: "Transportadora",
      })
    );
    expect(api.collectProjectMaterial).not.toHaveBeenCalled();
  });

  it("regista uma recolha e mostra o erro do servidor se exceder o que está no local", async () => {
    await openInventoryTab();
    fireEvent.click(await screen.findByRole("button", { name: /movimento/i }));

    fireEvent.change(await screen.findByLabelText("Ação"), { target: { value: "collect" } });
    fireEvent.change(screen.getByLabelText("Item *"), { target: { value: "item-1" } });
    fireEvent.change(screen.getByLabelText("Quantidade *"), { target: { value: "9" } });

    const { ApiError } = await vi.importActual<typeof import("../api/client")>("../api/client");
    api.collectProjectMaterial.mockRejectedValue(
      new ApiError(400, "Não pode recolher mais do que o que está no local (no local 3, pedido 9).")
    );
    fireEvent.click(screen.getByRole("button", { name: /^aplicar$/i }));

    expect(await screen.findByText(/Não pode recolher mais do que o que está no local/)).toBeInTheDocument();
    expect(api.collectProjectMaterial).toHaveBeenCalledWith("proj-1", { item_id: "item-1", quantity: "9", reference: undefined });
  });

  it("só quem tem uma permissão de movimento vê o botão 'Movimento'", async () => {
    await openInventoryTab(["project.view_all", "inventory.view"]);
    await screen.findByText("Material no local");
    expect(screen.queryByRole("button", { name: /movimento/i })).not.toBeInTheDocument();
  });

  it("pode operar só com as permissões de entrega/recolha (sem reservar/consumir)", async () => {
    await openInventoryTab(["project.view_all", "inventory.view", "inventory.collect_project"]);
    expect(await screen.findByRole("button", { name: /movimento/i })).toBeInTheDocument();
  });
});
