// Separador "Inventário" do detalhe do projeto — material no local, e as
// ações entregar/recolher (D-064). O servidor continua a validar tudo
// (recolher mais do que o que está no local, permissões por projeto).
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { InventoryItem, InventoryMovement, ProjectInventorySummary } from "../api/client";
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
  reverseProjectMovement: vi.fn(),
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

const INACTIVE_PANEL: InventoryItem = {
  ...PANEL,
  id: "item-inactive",
  sku: "PAINEL-INATIVO",
  name: "Painel inativo",
  is_active: false,
};

const INACTIVE_CABLE: InventoryItem = {
  ...PANEL,
  id: "item-km",
  sku: "CABO-INATIVO",
  name: "Cabo inativo",
  unit: "km",
  is_active: false,
};

function summary(overrides: Partial<ProjectInventorySummary> = {}): ProjectInventorySummary {
  return { project_id: "proj-1", requirements: [], reservations: [], on_site: [], ...overrides };
}

function movement(
  overrides: Partial<InventoryMovement> & { reversal_of_movement_id?: string | null } = {},
): InventoryMovement {
  return {
    id: "movement-1",
    item_id: "item-1",
    movement_type: "entrega",
    quantity: "3.000",
    project_id: "proj-1",
    location_id: null,
    destination_location_id: null,
    unit_cost: null,
    reference: "Entrega sintética",
    idempotency_key: null,
    created_by_person_id: null,
    created_at: "2026-10-14T10:00:00Z",
    item_name: "Painel 450 W",
    project_name: "Instalação Sintética Um",
    ...overrides,
  } as InventoryMovement;
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
    expect(await screen.findByText("3 un")).toBeInTheDocument();
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

  it("mantém artigos ativos e exclui artigos inativos do seletor de movimentos", async () => {
    api.listInventoryItems.mockResolvedValue([PANEL, INACTIVE_PANEL]);
    await openInventoryTab();
    fireEvent.click(await screen.findByRole("button", { name: /movimento/i }));

    const itemSelector = await screen.findByLabelText("Item *");
    expect(within(itemSelector).getByRole("option", { name: "Painel 450 W (un)" })).toBeInTheDocument();
    expect(within(itemSelector).queryByRole("option", { name: "Painel inativo (un)" })).not.toBeInTheDocument();
  });

  it("regista uma recolha e mostra o erro do servidor se exceder o que está no local", async () => {
    await openInventoryTab();
    fireEvent.click(await screen.findByRole("button", { name: /^movimento$/i }));

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

  it("mantém o catálogo completo para formatar movimentos de artigos inativos", async () => {
    api.listInventoryItems.mockResolvedValue([PANEL, INACTIVE_PANEL, INACTIVE_CABLE]);
    api.getProjectInventory.mockResolvedValue(
      summary({
        reservations: [
          movement({ id: "inactive-unit", item_id: "item-inactive", item_name: "Painel inativo", quantity: "3.000" }),
          movement({ id: "inactive-distance", item_id: "item-km", item_name: "Cabo inativo", quantity: "1.500" }),
        ],
      }),
    );
    await openInventoryTab([...PERMISSIONS, "inventory.reverse_project"]);

    expect(await screen.findByText(/Painel inativo · 3 un/)).toBeInTheDocument();
    expect(screen.getByText(/Cabo inativo · 1.500 km/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^movimento$/i }));
    const itemSelector = await screen.findByLabelText("Item *");
    expect(within(itemSelector).getByRole("option", { name: "Painel 450 W (un)" })).toBeInTheDocument();
    expect(within(itemSelector).queryByRole("option", { name: "Painel inativo (un)" })).not.toBeInTheDocument();
    expect(within(itemSelector).queryByRole("option", { name: "Cabo inativo (km)" })).not.toBeInTheDocument();
  });

  it("mostra erro e retry quando o refresh do inventário falha sem perder o projeto", async () => {
    api.getProjectInventory.mockRejectedValueOnce(new Error("timeout de inventário"));
    await openInventoryTab();

    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível atualizar o inventário.");
    expect(screen.getByRole("button", { name: "Tentar novamente" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: makeProject().name })).toBeInTheDocument();
    expect(screen.queryByTestId("loading-state")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Tentar novamente" }));
    await waitFor(() => expect(api.getProjectInventory).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("Não foi possível atualizar o inventário.")).not.toBeInTheDocument();
  });

  it("mantém dados conhecidos, bloqueia nova anulação e permite retry após falha do refresh", async () => {
    const original = movement();
    const reversal = movement({ id: "reversal-1", reversal_of_movement_id: original.id, quantity: "-3.000" });
    api.getProjectInventory
      .mockResolvedValueOnce(summary({ reservations: [original] }))
      .mockRejectedValueOnce(new Error("refresh indisponível"))
      .mockResolvedValueOnce(summary({ reservations: [original, reversal] }));
    api.reverseProjectMovement.mockResolvedValue(reversal);
    await openInventoryTab([...PERMISSIONS, "inventory.reverse_project"]);

    fireEvent.click(await screen.findByRole("button", { name: /anular movimento de painel 450 w/i }));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar anulação" }));

    await waitFor(() => expect(api.getProjectInventory).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(await screen.findByText(/Movimento anulado, mas não foi possível atualizar os dados/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /anular movimento de painel 450 w/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Tentar novamente" }));
    await waitFor(() => expect(api.getProjectInventory).toHaveBeenCalledTimes(3));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /anular movimento de painel 450 w/i })).not.toBeInTheDocument();
  });

  it("preserva o catálogo e dá retry quando a atualização de metadados falha", async () => {
    const original = movement({ item_id: "item-inactive", item_name: "Painel inativo" });
    const reversal = movement({ id: "reversal-1", item_id: "item-inactive", item_name: "Painel inativo", reversal_of_movement_id: original.id, quantity: "-3.000" });
    api.listInventoryItems
      .mockResolvedValueOnce([PANEL, INACTIVE_PANEL])
      .mockRejectedValueOnce(new Error("catálogo indisponível"))
      .mockResolvedValueOnce([PANEL, INACTIVE_PANEL]);
    api.getProjectInventory
      .mockResolvedValueOnce(summary({ reservations: [original] }))
      .mockResolvedValueOnce(summary({ reservations: [original, reversal] }))
      .mockResolvedValueOnce(summary({ reservations: [original, reversal] }));
    api.reverseProjectMovement.mockResolvedValue(reversal);
    await openInventoryTab([...PERMISSIONS, "inventory.reverse_project"]);
    expect(await screen.findByText(/Painel inativo · 3 un/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /anular movimento de painel inativo/i }));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar anulação" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível atualizar o catálogo");
    expect(screen.getByText(/Painel inativo · 3 un/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /anular movimento de painel 450 w/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Tentar novamente" }));
    await waitFor(() => expect(api.listInventoryItems).toHaveBeenCalledTimes(3));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("não mostra a anulação sem a capability de reversão", async () => {
    api.getProjectInventory.mockResolvedValue(summary({ reservations: [movement()] }));
    await openInventoryTab();
    expect(screen.queryByRole("button", { name: /anular movimento/i })).not.toBeInTheDocument();
  });

  it("mostra a anulação com a capability de reversão", async () => {
    api.getProjectInventory.mockResolvedValue(summary({ reservations: [movement()] }));
    await openInventoryTab([...PERMISSIONS, "inventory.reverse_project"]);
    expect(await screen.findByRole("button", { name: /anular movimento de painel 450 w/i })).toBeInTheDocument();
  });

  it("esconde anulação do movimento já compensado e da própria compensação", async () => {
    api.getProjectInventory.mockResolvedValue(
      summary({
        reservations: [
          movement(),
          movement({ id: "reversal-1", movement_type: "entrega", reversal_of_movement_id: "movement-1", quantity: "-3.000" }),
        ],
      }),
    );
    await openInventoryTab([...PERMISSIONS, "inventory.reverse_project"]);
    expect(screen.queryByRole("button", { name: /anular movimento/i })).not.toBeInTheDocument();
  });

  it("confirma a anulação com motivo, impede duplo clique e atualiza os saldos", async () => {
    api.getProjectInventory.mockResolvedValue(summary({ reservations: [movement()] }));
    let resolveReverse!: (value: InventoryMovement) => void;
    api.reverseProjectMovement.mockReturnValue(new Promise<InventoryMovement>((resolve) => {
      resolveReverse = resolve;
    }));
    await openInventoryTab([...PERMISSIONS, "inventory.reverse_project"]);

    fireEvent.click(await screen.findByRole("button", { name: /anular movimento de painel 450 w/i }));
    fireEvent.change(screen.getByLabelText("Motivo"), { target: { value: "Lançamento duplicado" } });
    const confirm = screen.getByRole("button", { name: "Confirmar anulação" });
    fireEvent.click(confirm);
    expect(confirm).toBeDisabled();
    fireEvent.click(confirm);
    expect(api.reverseProjectMovement).toHaveBeenCalledTimes(1);
    expect(api.reverseProjectMovement).toHaveBeenCalledWith("proj-1", "movement-1", "Lançamento duplicado");

    resolveReverse(movement({ id: "reversal-1", reversal_of_movement_id: "movement-1", quantity: "-3.000" }));
    await waitFor(() => expect(api.getProjectInventory).toHaveBeenCalledTimes(2));
    expect(api.listInventoryItems).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(await screen.findByText("Movimento anulado. O registo original foi mantido.")).toBeInTheDocument();
  });

  it.each([400, 409])("mantém erros dependentes visíveis na confirmação (%s)", async (status) => {
    const { ApiError } = await vi.importActual<typeof import("../api/client")>("../api/client");
    api.getProjectInventory.mockResolvedValue(summary({ reservations: [movement()] }));
    api.reverseProjectMovement.mockRejectedValue(new ApiError(status, "O saldo disponível ficaria negativo."));
    await openInventoryTab([...PERMISSIONS, "inventory.reverse_project"]);

    fireEvent.click(await screen.findByRole("button", { name: /anular movimento de painel 450 w/i }));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar anulação" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("O saldo disponível ficaria negativo.");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
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
