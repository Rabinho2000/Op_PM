// Inventário: stock central visível a quem tem inventory.view; "Registar
// movimento" só a quem tem inventory.manage_central (D-051, mesmo padrão
// de permissões.test.tsx).
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type InventoryItem, type InventoryMovement } from "../api/client";
import { makeMe } from "../test/fixtures";
import { StaticSessionProvider } from "../session/SessionContext";
import { ToastProvider } from "../components/Toast";
import { renderWithProviders } from "../test/render";
import Inventory, { LEGACY_INVENTORY_CATEGORY_ALIASES } from "./Inventory";
import type { Perm } from "../generated/permissions";

const api = vi.hoisted(() => ({
  listInventoryItems: vi.fn(),
  listInventoryLocations: vi.fn(),
  listInventoryMovements: vi.fn(),
  listInventoryCategories: vi.fn(),
  listInventoryCategoryDetails: vi.fn(),
  getInventoryCategoryImageBlob: vi.fn(),
  getInventoryItemPhotoBlob: vi.fn(),
  listInventoryItemDocuments: vi.fn(),
  getInventoryItemDocumentBlob: vi.fn(),
  uploadInventoryItemDocument: vi.fn(),
  deleteInventoryItemDocument: vi.fn(),
  uploadInventoryCategoryImage: vi.fn(),
  deleteInventoryCategoryImage: vi.fn(),
  uploadInventoryItemPhoto: vi.fn(),
  deleteInventoryItemPhoto: vi.fn(),
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
    reversal_of_movement_id: null,
    created_by_person_id: null,
    created_at: "2026-09-01T10:00:00Z",
    item_name: "Cabo solar DC 6mm²",
    project_name: null,
    ...overrides,
  };
}

function RouterControls() {
  const navigate = useNavigate();
  const location = useLocation();
  return <><output data-testid="router-search">{location.search}</output><output data-testid="router-hash">{location.hash}</output><button type="button" onClick={() => navigate(-1)}>Voltar no histórico</button><button type="button" onClick={() => navigate(1)}>Avançar no histórico</button></>;
}

function renderWithHistory(initialEntry = "/inventory", permissions: Perm[] = ["inventory.view"]) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <StaticSessionProvider me={makeMe({ permissions })} health={null}>
        <ToastProvider>
          <RouterControls />
          <Routes><Route path="/inventory" element={<Inventory />} /></Routes>
        </ToastProvider>
      </StaticSessionProvider>
    </MemoryRouter>,
  );
}

async function openCategory(label: string) {
  const card = await screen.findByRole("button", {
    name: (accessibleName) => accessibleName.includes(label) && accessibleName.includes("Ver artigos"),
  });
  fireEvent.click(card);
}

beforeEach(() => {
  localStorage.clear();
  Object.values(api).forEach((fn) => fn.mockReset());
  api.listInventoryItems.mockResolvedValue([item()]);
  api.listInventoryLocations.mockResolvedValue([]);
  api.listInventoryMovements.mockResolvedValue([movement()]);
  api.listInventoryCategories.mockResolvedValue([
    "Painéis",
    "Inversores",
    "Baterias",
    "Estruturas",
    "Cabos DC",
    "Cabos AC",
    "Proteções/Quadros",
    "Conectores",
    "Monitorização/Comunicação",
    "Consumíveis",
    "Outros",
  ]);
  api.listInventoryCategoryDetails.mockResolvedValue([
    "Painéis", "Inversores", "Baterias", "Estruturas", "Cabos DC", "Cabos AC",
    "Proteções/Quadros", "Conectores", "Monitorização/Comunicação", "Consumíveis", "Outros/Sem categoria",
  ].map((name) => ({ name, has_custom_image: false, image_version: null })));
  api.getInventoryCategoryImageBlob.mockResolvedValue(new Blob(["category"], { type: "image/png" }));
  api.getInventoryItemPhotoBlob.mockResolvedValue(new Blob(["item"], { type: "image/jpeg" }));
  api.listInventoryItemDocuments.mockResolvedValue([]);
  api.getInventoryItemDocumentBlob.mockResolvedValue(new Blob(["pdf"], { type: "application/pdf" }));
  api.uploadInventoryItemDocument.mockResolvedValue({});
  api.deleteInventoryItemDocument.mockResolvedValue(undefined);
  api.uploadInventoryCategoryImage.mockResolvedValue({ name: "Inversores", has_custom_image: true, image_version: "v2", content_type: "image/png" });
  api.deleteInventoryCategoryImage.mockResolvedValue(undefined);
  api.uploadInventoryItemPhoto.mockResolvedValue({ has_photo: true, content_type: "image/jpeg" });
  api.deleteInventoryItemPhoto.mockResolvedValue(undefined);
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
    owner: "solcor",
    is_active: true,
  });
  api.updateInventoryLocation.mockResolvedValue({
    id: "location-1",
    code: "CENTRAL",
    name: "Armazém central",
    location_type: "central",
    project_id: null,
    owner: "solcor",
    is_active: true,
  });
  api.deactivateInventoryLocation.mockResolvedValue({});
  api.createOpeningStock.mockResolvedValue(movement());
});

describe("Inventário", () => {
  it("filtra todas as listas pelo inventário escolhido e memoriza a seleção", async () => {
    renderWithProviders(<Inventory />, { me: makeMe({ permissions: ["inventory.view"] }) });
    await screen.findAllByText("Cabo solar DC 6mm²");
    expect(api.listInventoryItems).toHaveBeenLastCalledWith("solcor");
    expect(api.listInventoryLocations).toHaveBeenLastCalledWith("solcor");
    expect(api.listInventoryMovements).toHaveBeenLastCalledWith({ owner: "solcor" });

    fireEvent.click(screen.getByRole("button", { name: "Verde Milenar" }));
    await waitFor(() => {
      expect(api.listInventoryItems).toHaveBeenLastCalledWith("verde_milenar");
      expect(api.listInventoryLocations).toHaveBeenLastCalledWith("verde_milenar");
      expect(api.listInventoryMovements).toHaveBeenLastCalledWith({ owner: "verde_milenar" });
    });
    expect(localStorage.getItem("op_pm_inventory_owner")).toBe("verde_milenar");
  });

  it("restaura do localStorage o inventário escolhido anteriormente", async () => {
    localStorage.setItem("op_pm_inventory_owner", "verde_milenar");
    renderWithProviders(<Inventory />, { me: makeMe({ permissions: ["inventory.view"] }) });
    expect(await screen.findAllByText("Cabo solar DC 6mm²")).not.toHaveLength(0);
    expect(screen.getByRole("button", { name: "Verde Milenar" })).toHaveAttribute("aria-pressed", "true");
    await waitFor(() => expect(api.listInventoryItems).toHaveBeenLastCalledWith("verde_milenar"));
  });

  it("inclui o proprietário selecionado no pedido de stock inicial", async () => {
    localStorage.setItem("op_pm_inventory_owner", "verde_milenar");
    renderWithProviders(<Inventory />, {
      me: makeMe({ permissions: ["inventory.view", "inventory.manage_central"] }),
    });
    await openCategory("Outros/Sem categoria");
    fireEvent.click(await screen.findByRole("button", { name: /stock inicial/i }));
    fireEvent.change(screen.getByLabelText("Quantidade"), { target: { value: "12.5" } });
    fireEvent.change(screen.getByLabelText("Referência"), { target: { value: "Contagem Verde" } });
    fireEvent.click(screen.getByRole("button", { name: /registar entrada/i }));
    await waitFor(() =>
      expect(api.createOpeningStock).toHaveBeenCalledWith(
        expect.objectContaining({ item_id: "item-1", quantity: "12.5", reference: "Contagem Verde" }),
        "verde_milenar",
      ),
    );
  });

  it("mantém as localizações como resumo operacional e abre o catálogo sob ação secundária", async () => {
    api.listInventoryLocations.mockResolvedValue([
      { id: "sc-central", code: "SC", name: "Central Solcor", location_type: "central", project_id: null, owner: "solcor", is_active: true },
      { id: "sc-office", code: "OFF", name: "Escritório Solcor", location_type: "office", project_id: null, owner: "solcor", is_active: true },
      { id: "vm-central", code: "VM", name: "Central Verde", location_type: "central", project_id: null, owner: "verde_milenar", is_active: true },
    ]);
    renderWithHistory("/inventory", ["inventory.view", "inventory.manage_catalog"]);
    const nav = await screen.findByRole("navigation", { name: "Secções do inventário" });
    const locationsLink = within(nav).getByRole("link", { name: "Localizações" });
    const section = document.getElementById("inventory-locations");
    expect(section).toBeInTheDocument();
    expect(within(section as HTMLElement).getByText(/Central Solcor/)).toBeInTheDocument();
    expect(within(section as HTMLElement).getByText(/2 localizações ativas/)).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Localizações de inventário" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /nova localização/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Código")).not.toBeInTheDocument();

    fireEvent.click(locationsLink);
    expect(await screen.findByTestId("router-hash")).toHaveTextContent("#inventory-locations");
    expect(locationsLink).toHaveAttribute("aria-current", "location");

    const manage = within(section as HTMLElement).getByRole("button", { name: "Gerir localizações" });
    manage.focus();
    fireEvent.click(manage);
    await screen.findByRole("dialog", { name: "Gerir localizações" });
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Gerir localizações" })).not.toBeInTheDocument());
    expect(manage).toHaveFocus();

    fireEvent.click(manage);
    const catalog = await screen.findByRole("dialog", { name: "Gerir localizações" });
    expect(within(catalog).getByRole("table", { name: "Localizações de inventário" })).toBeInTheDocument();
    expect(within(catalog).getByText("Central Solcor")).toBeInTheDocument();
    expect(within(catalog).getByText("Escritório Solcor")).toBeInTheDocument();
    expect(within(catalog).queryByLabelText("Código")).not.toBeInTheDocument();
    fireEvent.click(within(catalog).getByRole("button", { name: /nova localização/i }));
    expect(await screen.findByLabelText("Código")).toBeInTheDocument();
  });

  it("não mostra catálogo nem ação de gestão de localizações sem permissão", async () => {
    renderWithProviders(<Inventory />, { me: makeMe({ permissions: ["inventory.view"] }) });
    const section = document.getElementById("inventory-locations");
    await screen.findByRole("navigation", { name: "Secções do inventário" });
    expect(section).toBeInTheDocument();
    expect(within(section as HTMLElement).queryByRole("button", { name: "Gerir localizações" })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Gerir localizações" })).not.toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Localizações de inventário" })).not.toBeInTheDocument();
  });

  it("envia o proprietário escolhido ao criar uma localização", async () => {
    renderWithProviders(<Inventory />, {
      me: makeMe({ permissions: ["inventory.view", "inventory.manage_catalog"] }),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Gerir localizações" }));
    const catalog = await screen.findByRole("dialog", { name: "Gerir localizações" });
    fireEvent.click(within(catalog).getByRole("button", { name: /nova localização/i }));
    fireEvent.change(screen.getByLabelText("Código"), { target: { value: "VM-ARMAZEM" } });
    fireEvent.change(screen.getByLabelText("Nome"), { target: { value: "Armazém VM" } });
    fireEvent.change(screen.getByLabelText("Proprietário"), { target: { value: "verde_milenar" } });
    fireEvent.click(within(screen.getByRole("dialog", { name: "Criar localização" })).getByRole("button", { name: /^criar localização$/i }));
    await waitFor(() =>
      expect(api.createInventoryLocation).toHaveBeenCalledWith(
        expect.objectContaining({ code: "VM-ARMAZEM", name: "Armazém VM", owner: "verde_milenar" }),
      ),
    );
  });

  it("só oferece localizações ativas do inventário escolhido num movimento", async () => {
    api.listInventoryLocations.mockResolvedValue([
      { id: "sc-central", code: "SC", name: "Central Solcor", location_type: "central", project_id: null, owner: "solcor", is_active: true },
      { id: "vm-central", code: "VM", name: "Central Verde", location_type: "central", project_id: null, owner: "verde_milenar", is_active: true },
      { id: "sc-inactive", code: "SC-OLD", name: "Local inativo", location_type: "vehicle", project_id: null, owner: "solcor", is_active: false },
    ]);
    renderWithProviders(<Inventory />, {
      me: makeMe({ permissions: ["inventory.view", "inventory.manage_central"] }),
    });
    fireEvent.click(await screen.findByRole("button", { name: /registar movimento/i }));
    const location = screen.getByLabelText("Localização");
    expect(within(location).getByRole("option", { name: "Central Solcor" })).toBeInTheDocument();
    expect(within(location).queryByRole("option", { name: "Central Verde" })).not.toBeInTheDocument();
    expect(within(location).queryByRole("option", { name: "Local inativo" })).not.toBeInTheDocument();
  });

  it("mostra o detalhe do 400 ao transferir entre inventários", async () => {
    api.listInventoryLocations.mockResolvedValue([
      { id: "sc-central", code: "SC", name: "Central Solcor", location_type: "central", project_id: null, owner: "solcor", is_active: true },
    ]);
    api.createCentralMovement.mockRejectedValue(
      new ApiError(400, "Não são permitidas transferências entre inventários diferentes."),
    );
    renderWithProviders(<Inventory />, {
      me: makeMe({ permissions: ["inventory.view", "inventory.manage_central"] }),
    });
    fireEvent.click(await screen.findByRole("button", { name: /registar movimento/i }));
    fireEvent.change(screen.getByLabelText("Tipo"), { target: { value: "transito_saida" } });
    fireEvent.change(screen.getByLabelText("Origem"), { target: { value: "sc-central" } });
    fireEvent.change(screen.getByLabelText("Destino"), { target: { value: "sc-central" } });
    fireEvent.change(screen.getByLabelText("Quantidade"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Registar" }));
    expect(await screen.findByText("Não são permitidas transferências entre inventários diferentes.")).toBeInTheDocument();
  });

  it("mostra o stock central com físico/reservado/disponível", async () => {
    renderWithProviders(<Inventory />, { me: makeMe({ permissions: ["inventory.view"] }) });
    await openCategory("Outros/Sem categoria");
    expect((await screen.findAllByText("Cabo solar DC 6mm²")).length).toBeGreaterThan(0);
    expect(screen.getByText("95.000 km")).toBeInTheDocument();
    expect(screen.getByText("80.000 km")).toBeInTheDocument();
  });

  it("remove zeros decimais de artigos contados à unidade sem arredondar frações", async () => {
    api.listInventoryItems.mockResolvedValue([
      item({
        unit: "un",
        physical_stock: "1.000",
        available_stock: "1.000",
        total_reserved: "0.000",
        min_stock: "0.000",
      }),
    ]);
    api.listInventoryMovements.mockResolvedValue([movement({ quantity: "1.500" })]);
    renderWithProviders(<Inventory />, { me: makeMe({ permissions: ["inventory.view"] }) });
    await openCategory("Outros/Sem categoria");
    await screen.findAllByText("Cabo solar DC 6mm²");
    expect(screen.getAllByText("1 un").length).toBeGreaterThan(0);
    expect(screen.getByText("1.500 un")).toBeInTheDocument();
  });

  it("assinala um item abaixo do stock mínimo", async () => {
    api.listInventoryItems.mockResolvedValue([item({ below_min_stock: true })]);
    renderWithProviders(<Inventory />, { me: makeMe({ permissions: ["inventory.view"] }) });
    await openCategory("Outros/Sem categoria");
    expect(await screen.findByText("Abaixo do mínimo")).toBeInTheDocument();
  });

  it("esconde 'Registar movimento' sem inventory.manage_central", async () => {
    renderWithProviders(<Inventory />, { me: makeMe({ permissions: ["inventory.view"] }) });
    await openCategory("Outros/Sem categoria");
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
    fireEvent.change(screen.getByLabelText("Categoria"), { target: { value: "Painéis" } });
    fireEvent.change(screen.getByLabelText("Fabricante"), { target: { value: "Marca Solar" } });
    fireEvent.change(screen.getByLabelText("Modelo"), { target: { value: "M-450" } });
    fireEvent.change(screen.getByLabelText("Subsecção"), { target: { value: "Monocristalino" } });
    fireEvent.change(screen.getByLabelText("Potência (W)"), { target: { value: "450.5" } });
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: /^criar artigo$/i }));
    await waitFor(() => expect(api.createInventoryItem).toHaveBeenCalledWith(expect.objectContaining({
      sku: "CAT-NEW",
      name: "Artigo novo",
      manufacturer: "Marca Solar",
      model: "M-450",
      subcategory: "Monocristalino",
      power_w: "450.5",
      cross_section_mm2: null,
    })));
  });

  it("envia PATCH de metadados e null para o campo numérico vazio", async () => {
    api.listInventoryItems.mockResolvedValue([item({
      category: "Painéis",
      manufacturer: "Marca antiga",
      model: "Modelo antigo",
      subcategory: "Secção antiga",
      power_w: "430.000",
    })]);
    renderWithProviders(<Inventory />, {
      me: makeMe({ permissions: ["inventory.view", "inventory.manage_catalog"] }),
    });
    await openCategory("Painéis");
    fireEvent.click(await screen.findByRole("button", { name: "Editar Cabo solar DC 6mm²" }));
    fireEvent.change(screen.getByLabelText("Fabricante"), { target: { value: "Marca Nova" } });
    fireEvent.change(screen.getByLabelText("Modelo"), { target: { value: "Modelo X" } });
    fireEvent.change(screen.getByLabelText("Subsecção"), { target: { value: "N-Type" } });
    fireEvent.change(screen.getByLabelText("Potência (W)"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar alterações" }));
    await waitFor(() => expect(api.updateInventoryItem).toHaveBeenCalledWith("item-1", expect.objectContaining({
      manufacturer: "Marca Nova",
      model: "Modelo X",
      subcategory: "N-Type",
      power_w: null,
      cross_section_mm2: null,
    })));
  });

  it("regista stock inicial pela ação do artigo", async () => {
    renderWithProviders(<Inventory />, {
      me: makeMe({ permissions: ["inventory.view", "inventory.manage_central"] }),
    });
    await openCategory("Outros/Sem categoria");
    fireEvent.click(await screen.findByRole("button", { name: /stock inicial/i }));
    fireEvent.change(screen.getByLabelText("Quantidade"), { target: { value: "12.5" } });
    fireEvent.change(screen.getByLabelText("Referência"), { target: { value: "Inventário físico" } });
    fireEvent.click(screen.getByRole("button", { name: /registar entrada/i }));
    await waitFor(() =>
      expect(api.createOpeningStock).toHaveBeenCalledWith(
        expect.objectContaining({ item_id: "item-1", quantity: "12.5", reference: "Inventário físico" }),
        "solcor",
      ),
    );
  });

  it("oferece reativar artigos inativos e chama o cliente da API", async () => {
    api.listInventoryItems.mockResolvedValue([item({ is_active: false })]);
    api.reactivateInventoryItem.mockResolvedValue(item({ is_active: true }));
    renderWithProviders(<Inventory />, {
      me: makeMe({ permissions: ["inventory.view", "inventory.manage_catalog"] }),
    });
    await openCategory("Outros/Sem categoria");
    fireEvent.click(await screen.findByRole("button", { name: "Reativar" }));
    await waitFor(() => expect(api.reactivateInventoryItem).toHaveBeenCalledWith("item-1"));
  });

  it("agrupa categorias antigas e sem categoria em Outros/Sem categoria", async () => {
    api.listInventoryItems.mockResolvedValue([
      item({ id: "legacy-1", name: "Item legado", category: "Módulos antigos" }),
      item({ id: "none-1", name: "Item sem categoria", category: null }),
    ]);
    renderWithProviders(<Inventory />, { me: makeMe({ permissions: ["inventory.view"] }) });
    await openCategory("Outros/Sem categoria");

    expect(await screen.findByText("Item legado")).toBeInTheDocument();
    expect(screen.getByText("Item sem categoria")).toBeInTheDocument();
    expect(screen.getByText((_, element) => element?.tagName === "SPAN" && element.textContent?.trim() === "Categoria: Módulos antigos")).toBeInTheDocument();
    expect(screen.getByText((_, element) => element?.tagName === "SPAN" && element.textContent?.trim() === "Categoria: Sem categoria")).toBeInTheDocument();
  });

  it("mantém a tabela de aliases sincronizada com o backend", () => {
    expect(LEGACY_INVENTORY_CATEGORY_ALIASES).toEqual({
      "Cabo AC": "Cabos AC",
      "Cabo DC": "Cabos DC",
      Painel: "Painéis",
      "Painéis solares": "Painéis",
      Inversor: "Inversores",
      Bateria: "Baterias",
      Estrutura: "Estruturas",
      Conector: "Conectores",
      Consumível: "Consumíveis",
    });
  });

  it("agrupa aliases de categoria legada na categoria canónica", async () => {
    api.listInventoryItems.mockResolvedValue([
      item({ id: "legacy-cable-dc", name: "Cabo DC legado", category: "Cabo DC" }),
    ]);
    renderWithProviders(<Inventory />, { me: makeMe({ permissions: ["inventory.view"] }) });
    await openCategory("Cabos DC");

    expect(await screen.findByText("Cabo DC legado")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Trilho de navegação" })).toHaveTextContent("Cabos DC");
  });

  it("gere a imagem da categoria aberta e atualiza os metadados sem botões dentro do cartão", async () => {
    api.listInventoryCategoryDetails.mockResolvedValue([
      { name: "Cabos DC", has_custom_image: false, image_version: null },
    ]);
    api.uploadInventoryCategoryImage.mockResolvedValue({ name: "Cabos DC", has_custom_image: true, image_version: "v2", content_type: "image/png" });
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:category-image");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    renderWithHistory("/inventory", ["inventory.view", "inventory.manage_catalog"]);

    const card = await screen.findByRole("button", { name: /Cabos DC.*Ver artigos/ });
    expect(card.querySelector("button")).toBeNull();
    expect(card.querySelector('input[type="file"]')).toBeNull();
    await openCategory("Cabos DC");

    const imageInput = screen.getByLabelText("Selecionar imagem de categoria");
    fireEvent.change(imageInput, {
      target: { files: [new File(["category image"], "cabos.png", { type: "image/png" })] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Guardar imagem de categoria" }));
    await waitFor(() => expect(api.uploadInventoryCategoryImage).toHaveBeenCalledWith("Cabos DC", expect.any(File)));
    await waitFor(() => expect(api.getInventoryCategoryImageBlob).toHaveBeenCalledWith("Cabos DC", "v2"));
    expect(document.querySelector(".inventory-category-detail img.inventory-illustration--photo")).toHaveAttribute("src", "blob:category-image");

    fireEvent.click(screen.getByRole("button", { name: "Inventário" }));
    await waitFor(() => expect(api.getInventoryCategoryImageBlob).toHaveBeenCalledTimes(2));
    await openCategory("Cabos DC");
    await waitFor(() => expect(api.getInventoryCategoryImageBlob).toHaveBeenCalledTimes(3));
    fireEvent.click(screen.getByRole("button", { name: "Remover imagem de categoria" }));
    await waitFor(() => expect(api.deleteInventoryCategoryImage).toHaveBeenCalledWith("Cabos DC"));
    expect(document.querySelector(".inventory-category-detail [data-testid=category-illustration]")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Inventário" }));
    await screen.findByRole("button", { name: /Cabos DC.*Ver artigos/ });
    expect(api.getInventoryCategoryImageBlob).toHaveBeenCalledTimes(3);
  });

  it("mantém a imagem da categoria aberta só para leitura sem inventory.manage_catalog", async () => {
    api.listInventoryCategoryDetails.mockResolvedValue([
      { name: "Cabos DC", has_custom_image: true, image_version: "version-1" },
    ]);
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:category-readonly");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    renderWithProviders(<Inventory />, { me: makeMe({ permissions: ["inventory.view"] }) });
    await openCategory("Cabos DC");

    await waitFor(() => expect(api.getInventoryCategoryImageBlob).toHaveBeenCalledWith("Cabos DC", "version-1"));
    expect(screen.queryByLabelText("Selecionar imagem de categoria")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /imagem de categoria/i })).not.toBeInTheDocument();
    await waitFor(() => expect(document.querySelector(".inventory-category-detail img.inventory-illustration--photo")).toHaveAttribute("src", "blob:category-readonly"));
  });

  it("não oferece gestão na categoria agregada sem correspondência canónica da API", async () => {
    api.listInventoryCategoryDetails.mockResolvedValue([
      { name: "Outros", has_custom_image: false, image_version: null },
    ]);
    renderWithProviders(<Inventory />, {
      me: makeMe({ permissions: ["inventory.view", "inventory.manage_catalog"] }),
    });
    await openCategory("Outros/Sem categoria");

    expect(screen.queryByLabelText("Selecionar imagem de categoria")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /imagem de categoria/i })).not.toBeInTheDocument();
  });

  it("usa has_custom_image e os metadados devolvidos pelo backend na ficha do artigo", async () => {
    api.listInventoryCategoryDetails.mockResolvedValue([
      { name: "Inversores", has_custom_image: true, image_version: "2026-10-22T12:00:00Z" },
      { name: "Painéis", has_custom_image: false, image_version: null },
    ]);
    api.listInventoryItems.mockResolvedValue([item({
      id: "visual-item",
      name: "Inversor híbrido",
      unit: "un",
      category: "Inversores",
      manufacturer: "Marca Solar",
      model: "H-5000",
      subcategory: "Híbrido",
      power_w: "5000.000",
      section_label: "Marca Solar",
      has_photo: true,
      location_stocks: [{ location_id: "loc-1", location_name: "Armazém central", physical_stock: "2.000" }],
    })]);
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:inventory-visual");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    renderWithProviders(<Inventory />, { me: makeMe({ permissions: ["inventory.view"] }) });

    await waitFor(() => expect(api.getInventoryCategoryImageBlob).toHaveBeenCalledWith("Inversores", "2026-10-22T12:00:00Z"));
    expect(api.getInventoryCategoryImageBlob).toHaveBeenCalledTimes(1);
    await openCategory("Inversores");
    fireEvent.click(await screen.findByRole("button", { name: "Ver artigo Inversor híbrido" }));
    const detail = await screen.findByRole("dialog", { name: /Ficha do artigo/ });
    expect(within(detail).getByText("Marca Solar")).toBeInTheDocument();
    expect(within(detail).getByText("H-5000")).toBeInTheDocument();
    expect(within(detail).getByText("Híbrido")).toBeInTheDocument();
    expect(within(detail).getByText("5000 W")).toBeInTheDocument();
    expect(within(detail).getByText("Armazém central: 2 un")).toBeInTheDocument();
    expect(await within(detail).findByRole("img", { name: "Fotografia de Inversor híbrido" })).toHaveAttribute("src", "blob:inventory-visual");
    expect(within(detail).queryByLabelText("Selecionar fotografia do artigo")).not.toBeInTheDocument();
    expect(within(detail).queryByRole("button", { name: /fotografia/i })).not.toBeInTheDocument();
  });

  it("permite gerir a fotografia na ficha do artigo com inventory.manage_catalog", async () => {
    api.listInventoryItems.mockResolvedValue([item({
      id: "visual-item",
      name: "Inversor híbrido",
      unit: "un",
      category: "Inversores",
      has_photo: false,
    })]);
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:inventory-managed-preview");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    renderWithProviders(<Inventory />, {
      me: makeMe({ permissions: ["inventory.view", "inventory.manage_catalog"] }),
    });

    await openCategory("Inversores");
    fireEvent.click(await screen.findByRole("button", { name: "Ver artigo Inversor híbrido" }));
    const detail = await screen.findByRole("dialog", { name: /Ficha do artigo — Inversor híbrido/ });
    const photoInput = within(detail).getByLabelText("Selecionar fotografia do artigo");

    fireEvent.change(photoInput, {
      target: { files: [new File(["first photo"], "inversor.jpg", { type: "image/jpeg" })] },
    });
    expect(await within(detail).findByRole("img", { name: "Pré-visualização da fotografia de Inversor híbrido" })).toHaveAttribute("src", "blob:inventory-managed-preview");
    fireEvent.click(within(detail).getByRole("button", { name: "Guardar fotografia" }));
    await waitFor(() => expect(api.uploadInventoryItemPhoto).toHaveBeenCalledWith("visual-item", expect.any(File)));
    expect(await within(detail).findByRole("button", { name: "Substituir fotografia" })).toBeInTheDocument();

    fireEvent.change(photoInput, {
      target: { files: [new File(["replacement photo"], "inversor-novo.jpg", { type: "image/jpeg" })] },
    });
    expect(await within(detail).findByRole("img", { name: "Pré-visualização da fotografia de Inversor híbrido" })).toBeInTheDocument();
    fireEvent.click(within(detail).getByRole("button", { name: "Guardar fotografia" }));
    await waitFor(() => expect(api.uploadInventoryItemPhoto).toHaveBeenCalledTimes(2));

    fireEvent.click(within(detail).getByRole("button", { name: "Remover fotografia" }));
    await waitFor(() => expect(api.deleteInventoryItemPhoto).toHaveBeenCalledWith("visual-item"));
    expect(within(detail).queryByRole("button", { name: "Remover fotografia" })).not.toBeInTheDocument();
  });

  it("agrupa artigos por secção opcional dentro da categoria", async () => {
    api.listInventoryItems.mockResolvedValue([
      item({ id: "section-cable", name: "Cabo de ligação", category: "Cabos DC", section_label: "Instalação" } as Partial<InventoryItem>),
      item({ id: "section-connector", name: "Conector MC4", category: "Cabos DC", section_label: "Acessórios" } as Partial<InventoryItem>),
    ]);
    renderWithProviders(<Inventory />, { me: makeMe({ permissions: ["inventory.view"] }) });
    await openCategory("Cabos DC");

    expect(await screen.findByRole("heading", { name: "Acessórios" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Instalação" })).toBeInTheDocument();
    expect(screen.getByText("Cabo de ligação")).toBeInTheDocument();
    expect(screen.getByText("Conector MC4")).toBeInTheDocument();
  });

  it("pesquisa sem acentos, abre resultados e permite limpar pela tecla Esc", async () => {
    api.listInventoryItems.mockResolvedValue([
      item({ id: "panel-1", name: "Módulo fotovoltaico", sku: "PN-450", category: "Painéis" }),
      item({ id: "cable-1", name: "Cabo de ligação", sku: "CABO-DC", category: "Cabos DC" }),
    ]);
    renderWithProviders(<Inventory />, { me: makeMe({ permissions: ["inventory.view"] }) });
    const search = await screen.findByRole("combobox", { name: "Pesquisar inventário" });
    fireEvent.focus(search);
    fireEvent.change(search, { target: { value: "PAINEIS" } });

    await screen.findByRole("option", { name: /Módulo fotovoltaico/ });
    fireEvent.keyDown(search, { key: "Enter" });
    expect(await screen.findByRole("heading", { name: /Resultados para.*PAINEIS/i })).toBeInTheDocument();
    expect(screen.getByText("Módulo fotovoltaico")).toBeInTheDocument();
    expect(screen.queryByText("Cabo de ligação")).not.toBeInTheDocument();

    fireEvent.keyDown(search, { key: "Escape" });
    expect(await screen.findByRole("button", { name: /Cabos DC.*Ver artigos/ })).toBeInTheDocument();
    expect(search).toHaveValue("");
  });

  it("esconde categorias vazias quando a opção está ativa", async () => {
    api.listInventoryItems.mockResolvedValue([item({ category: "Painéis" })]);
    renderWithProviders(<Inventory />, { me: makeMe({ permissions: ["inventory.view"] }) });
    const panelCard = await screen.findByRole("button", { name: /Painéis.*Ver artigos/ });
    expect(screen.getByRole("button", { name: /Inversores.*Ver artigos/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Esconder categorias vazias" }));
    expect(screen.queryByRole("button", { name: /Inversores.*Ver artigos/ })).not.toBeInTheDocument();
    expect(panelCard).toBeInTheDocument();
  });

  it("mostra a tabela de painéis com stock por localização e sinaliza campos ausentes", async () => {
    api.listInventoryItems.mockResolvedValue([
      item({
        name: "Módulo FV 450 W",
        sku: "PAINEL-450",
        unit: "un",
        category: "Painéis",
        location_stocks: [{ location_id: "loc-1", location_name: "Armazém central", physical_stock: "4.000" }],
      }),
    ]);
    renderWithProviders(<Inventory />, { me: makeMe({ permissions: ["inventory.view"] }) });
    await openCategory("Painéis");
    expect(await screen.findByRole("columnheader", { name: "Stock por localização" })).toBeInTheDocument();
    expect(screen.getByText("Armazém central: 4 un")).toBeInTheDocument();
    expect(screen.getByText(/abra um artigo para consultar os metadados disponíveis/i)).toBeInTheDocument();
  });

  it("mantém o proprietário nos pedidos de inventário com a nova pesquisa", async () => {
    localStorage.setItem("op_pm_inventory_owner", "verde_milenar");
    renderWithProviders(<Inventory />, { me: makeMe({ permissions: ["inventory.view"] }) });
    await screen.findByRole("combobox", { name: "Pesquisar inventário" });
    expect(api.listInventoryItems).toHaveBeenLastCalledWith("verde_milenar");
    expect(api.listInventoryLocations).toHaveBeenLastCalledWith("verde_milenar");
    expect(api.listInventoryMovements).toHaveBeenLastCalledWith({ owner: "verde_milenar" });
  });

  it("mostra cartões por categoria com a contagem e o stock agregado", async () => {
    api.listInventoryItems.mockResolvedValue([
      item({ id: "dc-1", category: "Cabo DC", physical_stock: "10.000" }),
      item({ id: "dc-2", name: "Cabo solar DC 4mm²", sku: "CABO-DC-4", category: "Cabos DC", physical_stock: "2.000" }),
      item({ id: "panel-1", name: "Painel 450 W", category: "Painéis", unit: "un", physical_stock: "4.000" }),
    ]);
    renderWithProviders(<Inventory />, { me: makeMe({ permissions: ["inventory.view"] }), route: "/inventory" });
    const cableCard = await screen.findByRole("button", { name: /Cabos DC/ });
    expect(within(cableCard).getByText("2 artigos")).toBeInTheDocument();
    expect(within(cableCard).getByText(/12\.000 km/)).toBeInTheDocument();
    const panelCard = screen.getByRole("button", { name: /Painéis/ });
    expect(within(panelCard).getByText(/4 un/)).toBeInTheDocument();
    expect(screen.getAllByTestId("category-illustration").length).toBe(11);
  });

  it("abre uma categoria pelo URL e apresenta os artigos com stock por localização", async () => {
    api.listInventoryItems.mockResolvedValue([
      item({ category: "Cabos DC", location_stocks: [{ location_id: "loc-1", location_name: "Armazém central", physical_stock: "95.000" }] }),
    ]);
    renderWithProviders(<Inventory />, { me: makeMe({ permissions: ["inventory.view"] }), route: "/inventory?categoria=cabos-dc" });
    expect(await screen.findByRole("navigation", { name: "Trilho de navegação" })).toHaveTextContent("Inventário›Cabos DC");
    expect(screen.getByText("CABO-DC-6MM")).toBeInTheDocument();
    expect(screen.getByText((_, element) => element?.tagName === "LI" && element.textContent?.trim() === "Armazém central: 95.000 km")).toBeInTheDocument();
  });

  it("abre categorias com pushState e respeita voltar/avançar do browser", async () => {
    api.listInventoryItems.mockResolvedValue([item({ category: "Cabos DC" })]);
    renderWithHistory();
    fireEvent.click(await screen.findByRole("button", { name: /Cabos DC/ }));
    expect(await screen.findByTestId("router-search")).toHaveTextContent("?categoria=cabos-dc");
    expect(screen.getByRole("navigation", { name: "Trilho de navegação" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Voltar no histórico" }));
    await waitFor(() => expect(screen.getByTestId("router-search")).toHaveTextContent(""));
    expect(screen.getByRole("button", { name: /Cabos DC/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Avançar no histórico" }));
    expect(await screen.findByRole("navigation", { name: "Trilho de navegação" })).toBeInTheDocument();
  });

  it("permite navegar nas sugestões da pesquisa com setas e Enter", async () => {
    api.listInventoryItems.mockResolvedValue([item({ category: "Cabos DC" })]);
    renderWithProviders(<Inventory />, { me: makeMe({ permissions: ["inventory.view"] }), route: "/inventory" });
    const search = await screen.findByRole("combobox", { name: "Pesquisar inventário" });
    fireEvent.focus(search);
    fireEvent.change(search, { target: { value: "cabo" } });
    const option = await screen.findByRole("option", { name: /Cabo solar DC 6mm²/ });
    fireEvent.keyDown(search, { key: "ArrowDown" });
    expect(search).toHaveAttribute("aria-activedescendant", option.id);
    expect(option).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(search, { key: "Enter" });
    expect(await screen.findByRole("navigation", { name: "Trilho de navegação" })).toHaveTextContent("Cabos DC");
  });

  it("pesquisa 'cabo 6', sincroniza q com o histórico e restaura a vista ao voltar/avançar", async () => {
    api.listInventoryItems.mockResolvedValue([
      item({ id: "dc-6", category: "Cabos DC" }),
      item({ id: "panel-1", name: "Painel 450 W", sku: "PN-450", category: "Painéis" }),
    ]);
    renderWithHistory();
    const search = await screen.findByRole("combobox", { name: "Pesquisar inventário" });
    fireEvent.focus(search);
    fireEvent.change(search, { target: { value: "cabo 6" } });
    await screen.findByRole("option", { name: /Cabo solar DC 6mm²/ });
    fireEvent.keyDown(search, { key: "Enter" });

    expect(await screen.findByRole("heading", { name: /Resultados para.*cabo 6/i })).toBeInTheDocument();
    expect(screen.getAllByText("Cabo solar DC 6mm²").length).toBeGreaterThan(0);
    expect(screen.queryByText("Painel 450 W")).not.toBeInTheDocument();
    expect(await screen.findByTestId("router-search")).toHaveTextContent("?q=cabo+6");

    fireEvent.click(screen.getByRole("button", { name: "Voltar no histórico" }));
    await waitFor(() => expect(screen.getByTestId("router-search")).toHaveTextContent(""));
    expect(screen.getByRole("button", { name: /Cabos DC.*Ver artigos/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Avançar no histórico" }));
    expect(await screen.findByRole("heading", { name: /Resultados para.*cabo 6/i })).toBeInTheDocument();
    expect(screen.getAllByText("Cabo solar DC 6mm²").length).toBeGreaterThan(0);
  });

  it("abre a pesquisa com '/' e não rouba foco a um campo de edição", async () => {
    api.listInventoryItems.mockResolvedValue([item({ category: "Cabos DC" })]);
    renderWithProviders(<Inventory />, { me: makeMe({ permissions: ["inventory.view", "inventory.manage_catalog"] }), route: "/inventory" });
    const search = await screen.findByRole("combobox", { name: "Pesquisar inventário" });
    fireEvent.keyDown(document.body, { key: "/" });
    expect(search).toHaveFocus();

    await openCategory("Cabos DC");
    fireEvent.click(await screen.findByRole("button", { name: "Editar Cabo solar DC 6mm²" }));
    const sku = await screen.findByLabelText("SKU");
    sku.focus();
    fireEvent.keyDown(sku, { key: "/" });
    expect(sku).toHaveFocus();
  });

  it("liga documentos à ficha e mantém a leitura disponível sem manage_catalog", async () => {
    api.listInventoryItemDocuments.mockResolvedValue([{
      id: "doc-1",
      item_id: "item-1",
      kind: "datasheet",
      title: "Ficha técnica do cabo",
      filename: "cabo.pdf",
      content_type: "application/pdf",
      size: 1024,
      created_by_person_id: "person-1",
      created_at: "2026-10-22T12:00:00Z",
    }]);
    renderWithProviders(<Inventory />, { me: makeMe({ permissions: ["inventory.view"] }) });
    await openCategory("Outros/Sem categoria");
    fireEvent.click(await screen.findByRole("button", { name: "Ver artigo Cabo solar DC 6mm²" }));

    const detail = await screen.findByRole("dialog", { name: /Ficha do artigo/ });
    expect(await within(detail).findByRole("heading", { name: "Datasheets" })).toBeInTheDocument();
    expect(within(detail).getByText("Ficha técnica do cabo")).toBeInTheDocument();
    expect(api.listInventoryItemDocuments).toHaveBeenCalledWith("item-1");
    expect(within(detail).queryByRole("button", { name: "Adicionar documento" })).not.toBeInTheDocument();
  });

  it("oferece gestão de documentos na ficha com inventory.manage_catalog", async () => {
    renderWithProviders(<Inventory />, {
      me: makeMe({ permissions: ["inventory.view", "inventory.manage_catalog"] }),
    });
    await openCategory("Outros/Sem categoria");
    fireEvent.click(await screen.findByRole("button", { name: "Ver artigo Cabo solar DC 6mm²" }));

    const detail = await screen.findByRole("dialog", { name: /Ficha do artigo/ });
    expect(within(detail).getByRole("combobox", { name: "Tipo de documento" })).toBeInTheDocument();
    expect(within(detail).getByRole("button", { name: "Adicionar documento" })).toBeInTheDocument();
  });

  it("liga as âncoras aos blocos Localizações e Movimentos", async () => {
    renderWithProviders(<Inventory />, { me: makeMe({ permissions: ["inventory.view"] }) });
    await screen.findByRole("navigation", { name: "Secções do inventário" });
    expect(document.getElementById("inventory-locations")).toBeInTheDocument();
    expect(document.getElementById("inventory-movements")).toBeInTheDocument();
  });

  it("expõe o proprietário como controlo segmentado e envia o selecionado nos pedidos", async () => {
    renderWithProviders(<Inventory />, { me: makeMe({ permissions: ["inventory.view"] }) });
    const group = await screen.findByRole("group", { name: "Inventário por proprietário" });
    const solcor = within(group).getByRole("button", { name: "Solcor" });
    const verde = within(group).getByRole("button", { name: "Verde Milenar" });
    expect(solcor).toHaveAttribute("aria-pressed", "true");
    expect(verde).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(verde);
    expect(verde).toHaveAttribute("aria-pressed", "true");
    await waitFor(() => {
      expect(api.listInventoryItems).toHaveBeenLastCalledWith("verde_milenar");
      expect(api.listInventoryLocations).toHaveBeenLastCalledWith("verde_milenar");
      expect(api.listInventoryMovements).toHaveBeenLastCalledWith({ owner: "verde_milenar" });
    });
  });

  it.each([
    [true, "complementary"],
    [false, "dialog"],
  ] as const)("mostra a ficha como inspector em desktop e modal em mobile (desktop=%s)", async (desktop, role) => {
    const originalMatchMedia = window.matchMedia;
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: desktop && query === "(min-width: 1100px)",
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
    try {
      renderWithProviders(<Inventory />, { me: makeMe({ permissions: ["inventory.view"] }), route: "/inventory" });
      await openCategory("Outros/Sem categoria");
      fireEvent.click(await screen.findByRole("button", { name: "Ver artigo Cabo solar DC 6mm²" }));
      const detail = await screen.findByRole(role, { name: "Ficha do artigo — Cabo solar DC 6mm²" });
      expect(within(detail).getByText("CABO-DC-6MM")).toBeInTheDocument();
      expect(screen.queryByRole(desktop ? "dialog" : "complementary", { name: desktop ? /Ficha do artigo/ : "Ficha do artigo" })).not.toBeInTheDocument();
    } finally {
      if (originalMatchMedia) Object.defineProperty(window, "matchMedia", { configurable: true, value: originalMatchMedia });
      else delete (window as Partial<Window>).matchMedia;
    }
  });

  it("marca a secção ativa nas tabs ao navegar pelos hashes", async () => {
    renderWithHistory();
    const nav = await screen.findByRole("navigation", { name: "Secções do inventário" });
    const categories = within(nav).getByRole("link", { name: "Categorias" });
    const locations = within(nav).getByRole("link", { name: "Localizações" });
    const movements = within(nav).getByRole("link", { name: "Movimentos" });
    expect(categories).toHaveAttribute("aria-current", "location");
    fireEvent.click(locations);
    expect(await screen.findByTestId("router-hash")).toHaveTextContent("#inventory-locations");
    expect(locations).toHaveAttribute("aria-current", "location");
    expect(categories).not.toHaveAttribute("aria-current");
    fireEvent.click(movements);
    expect(await screen.findByTestId("router-hash")).toHaveTextContent("#inventory-movements");
    expect(movements).toHaveAttribute("aria-current", "location");
  });

  it("rederiva a secção ativa do histórico ao limpar o hash com pesquisa/categoria", async () => {
    renderWithHistory("/inventory#inventory-movements");
    const nav = await screen.findByRole("navigation", { name: "Secções do inventário" });
    const categories = within(nav).getByRole("link", { name: "Categorias" });
    const movements = within(nav).getByRole("link", { name: "Movimentos" });
    expect(await screen.findByTestId("router-hash")).toHaveTextContent("#inventory-movements");
    expect(movements).toHaveAttribute("aria-current", "location");

    const search = screen.getByRole("combobox", { name: "Pesquisar inventário" });
    fireEvent.focus(search);
    fireEvent.change(search, { target: { value: "cabo 6" } });
    await screen.findByRole("option", { name: /Cabo solar DC 6mm²/ });
    fireEvent.keyDown(search, { key: "Enter" });
    await waitFor(() => expect(screen.getByTestId("router-search")).toHaveTextContent("?q=cabo+6"));
    expect(screen.getByTestId("router-hash")).toBeEmptyDOMElement();
    expect(categories).toHaveAttribute("aria-current", "location");
    expect(movements).not.toHaveAttribute("aria-current");

    fireEvent.click(screen.getByRole("button", { name: "Voltar no histórico" }));
    await waitFor(() => expect(screen.getByTestId("router-hash")).toHaveTextContent("#inventory-movements"));
    expect(movements).toHaveAttribute("aria-current", "location");
    fireEvent.click(screen.getByRole("button", { name: "Avançar no histórico" }));
    await waitFor(() => expect(screen.getByTestId("router-search")).toHaveTextContent("?q=cabo+6"));
    expect(categories).toHaveAttribute("aria-current", "location");

    fireEvent.click(await screen.findByRole("button", { name: /Ver categoria/ }));
    await waitFor(() => expect(screen.getByTestId("router-search")).toHaveTextContent("?categoria=outros-sem-categoria"));
    expect(screen.getByTestId("router-hash")).toBeEmptyDOMElement();
    expect(categories).toHaveAttribute("aria-current", "location");
    expect(movements).not.toHaveAttribute("aria-current");

    fireEvent.click(screen.getByRole("button", { name: "Voltar no histórico" }));
    await waitFor(() => expect(screen.getByTestId("router-search")).toHaveTextContent("?q=cabo+6"));
    expect(categories).toHaveAttribute("aria-current", "location");
    fireEvent.click(screen.getByRole("button", { name: "Voltar no histórico" }));
    await waitFor(() => expect(screen.getByTestId("router-hash")).toHaveTextContent("#inventory-movements"));
    expect(movements).toHaveAttribute("aria-current", "location");
    fireEvent.click(screen.getByRole("button", { name: "Avançar no histórico" }));
    fireEvent.click(screen.getByRole("button", { name: "Avançar no histórico" }));
    await waitFor(() => expect(screen.getByTestId("router-search")).toHaveTextContent("?categoria=outros-sem-categoria"));
    expect(categories).toHaveAttribute("aria-current", "location");
  });

  it("abre o inspector desktop por teclado com nome do artigo e devolve foco ao trigger", async () => {
    const originalMatchMedia = window.matchMedia;
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: query === "(min-width: 1100px)",
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
    try {
      renderWithHistory("/inventory");
      await openCategory("Outros/Sem categoria");
      const trigger = await screen.findByRole("button", { name: "Ver artigo Cabo solar DC 6mm²" });
      trigger.focus();
      fireEvent.keyDown(trigger, { key: "Enter" });
      fireEvent.click(trigger);

      const inspector = await screen.findByRole("complementary", { name: "Ficha do artigo — Cabo solar DC 6mm²" });
      const heading = within(inspector).getByRole("heading", { name: "Ficha do artigo — Cabo solar DC 6mm²" });
      expect(heading).toHaveFocus();
      expect(inspector).toHaveAttribute("aria-labelledby", "inventory-item-inspector-heading");

      fireEvent.click(within(inspector).getByRole("button", { name: "Fechar ficha do artigo" }));
      expect(trigger).toHaveFocus();
      expect(screen.queryByRole("complementary", { name: /Ficha do artigo/ })).not.toBeInTheDocument();
    } finally {
      if (originalMatchMedia) Object.defineProperty(window, "matchMedia", { configurable: true, value: originalMatchMedia });
      else delete (window as Partial<Window>).matchMedia;
    }
  });
});
