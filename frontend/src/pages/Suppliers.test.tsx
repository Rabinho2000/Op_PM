import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Supplier } from "../api/client";
import { makeMe } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import Suppliers, { toApiFilters } from "./Suppliers";

const { listSuppliers, listSupplierMaterialTypes, createSupplier, updateSupplier } = vi.hoisted(() => ({
  listSuppliers: vi.fn(),
  listSupplierMaterialTypes: vi.fn(),
  createSupplier: vi.fn(),
  updateSupplier: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, listSuppliers, listSupplierMaterialTypes, createSupplier, updateSupplier };
});

function makeSupplier(overrides: Partial<Supplier> = {}): Supplier {
  return {
    id: "s-1",
    name: "Energy Systems",
    category: null,
    contact: "Ana",
    phone: "+351 253 145 794",
    email: "info@energysystems.pt",
    website: "https://www.energysystems.pt/",
    address: "Rua de Lamas 541, Rio Covo",
    lat: null,
    lon: null,
    is_preferred: false,
    lead_time_days: null,
    materials: "",
    notes: "",
    is_active: true,
    material_types: ["Carports", "Estruturas de fixação"],
    ...overrides,
  };
}

const TYPES = [
  { id: "t-1", name: "Carports", active_suppliers: 2 },
  { id: "t-2", name: "Estruturas de fixação", active_suppliers: 3 },
];

const withManage = () => makeMe({ permissions: ["supplier.view", "supplier.manage"] });
const viewOnly = () => makeMe({ permissions: ["supplier.view"] });

describe("Suppliers (lista)", () => {
  beforeEach(() => {
    listSuppliers.mockReset();
    listSupplierMaterialTypes.mockReset();
    createSupplier.mockReset();
    updateSupplier.mockReset();
    listSupplierMaterialTypes.mockResolvedValue(TYPES);
    listSuppliers.mockResolvedValue([
      makeSupplier(),
      makeSupplier({
        id: "s-2",
        name: "Sikla Lusa",
        phone: null,
        email: null,
        website: null,
        contact: null,
        address: null,
        material_types: [],
        is_active: false,
        lat: 38.5,
        lon: -8.9,
      }),
    ]);
  });

  it("mostra nome, tipos, telefone, email e localização, com ligações úteis", async () => {
    renderWithProviders(<Suppliers />, { me: viewOnly() });

    expect(await screen.findByText("Energy Systems")).toBeInTheDocument();
    expect(screen.getByText("2 fornecedores")).toBeInTheDocument();
    expect(screen.getAllByText("Carports").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "+351 253 145 794" })).toHaveAttribute("href", "tel:+351253145794");
    expect(screen.getByRole("link", { name: "info@energysystems.pt" })).toHaveAttribute("href", "mailto:info@energysystems.pt");
    expect(screen.getByRole("link", { name: "www.energysystems.pt" })).toHaveAttribute("href", "https://www.energysystems.pt/");
    expect(screen.getByText("Rua de Lamas 541, Rio Covo")).toBeInTheDocument();
    // Sem dados: traço; inativo assinalado; "Ver no mapa" só com coordenadas.
    expect(screen.getByText("Inativo")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Ver no mapa" })).toHaveLength(1);
  });

  it("carrega só fornecedores ativos por omissão e envia os filtros ao servidor", async () => {
    renderWithProviders(<Suppliers />, { me: viewOnly() });
    await screen.findByText("Energy Systems");
    expect(listSuppliers).toHaveBeenLastCalledWith({ q: undefined, material_type: undefined, is_active: true });

    await screen.findByRole("option", { name: "Carports (2)" });
    fireEvent.change(screen.getByLabelText("Tipo de material"), { target: { value: "Carports" } });
    fireEvent.change(screen.getByLabelText("Situação"), { target: { value: "all" } });
    fireEvent.change(screen.getByLabelText("Pesquisar"), { target: { value: "  porto " } });

    await waitFor(() =>
      expect(listSuppliers).toHaveBeenLastCalledWith({ q: "porto", material_type: "Carports", is_active: undefined })
    );
  });

  it("toApiFilters traduz 'todos' para ausência de filtro", () => {
    expect(toApiFilters({ search: " ", materialType: "", active: "all" })).toEqual({
      q: undefined,
      material_type: undefined,
      is_active: undefined,
    });
    expect(toApiFilters({ search: "", materialType: "", active: "inactive" }).is_active).toBe(false);
  });

  it("sem permissão de gestão não mostra criar nem editar", async () => {
    renderWithProviders(<Suppliers />, { me: viewOnly() });
    await screen.findByText("Energy Systems");
    expect(screen.queryByRole("button", { name: /Novo fornecedor/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Editar/ })).not.toBeInTheDocument();
  });

  it("mostra o estado vazio com filtros e permite limpá-los", async () => {
    listSuppliers.mockResolvedValue([]);
    renderWithProviders(<Suppliers />, { me: viewOnly() });
    expect(await screen.findByText("Nenhum fornecedor encontrado")).toBeInTheDocument();
    expect(screen.getByText("Ainda não há fornecedores registados.")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Situação"), { target: { value: "inactive" } });
    expect(await screen.findByText("Nenhum fornecedor corresponde aos filtros escolhidos.")).toBeInTheDocument();
  });

  it("cria um fornecedor com vários tipos de material", async () => {
    createSupplier.mockResolvedValue(makeSupplier({ id: "s-3", name: "Nova Loja" }));
    renderWithProviders(<Suppliers />, { me: withManage() });
    await screen.findByText("Energy Systems");

    fireEvent.click(screen.getByRole("button", { name: /Novo fornecedor/ }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Nome *"), { target: { value: "  Nova Loja " } });
    fireEvent.change(within(dialog).getByLabelText("Telefone"), { target: { value: "210 000 000" } });
    fireEvent.change(within(dialog).getByLabelText("Email"), { target: { value: "geral@novaloja.pt" } });

    const typeInput = within(dialog).getByLabelText("Tipos de material");
    fireEvent.change(typeInput, { target: { value: "Inversores" } });
    fireEvent.keyDown(typeInput, { key: "Enter" });
    fireEvent.change(typeInput, { target: { value: "inversores" } }); // duplicado (sem distinguir maiúsculas)
    fireEvent.keyDown(typeInput, { key: "Enter" });
    fireEvent.change(typeInput, { target: { value: "Baterias" } }); // ainda por confirmar: conta ao guardar

    fireEvent.click(within(dialog).getByRole("button", { name: "Guardar fornecedor" }));

    await waitFor(() => expect(createSupplier).toHaveBeenCalled());
    expect(createSupplier).toHaveBeenCalledWith({
      name: "Nova Loja",
      phone: "210 000 000",
      email: "geral@novaloja.pt",
      address: null,
      website: null,
      contact: null,
      notes: "",
      material_types: ["Inversores", "Baterias"],
    });
    expect(await screen.findByText("Fornecedor «Nova Loja» criado.")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(listSuppliers.mock.calls.length).toBeGreaterThan(1); // recarregou a lista
  });

  it("valida no cliente antes de enviar", async () => {
    renderWithProviders(<Suppliers />, { me: withManage() });
    await screen.findByText("Energy Systems");
    fireEvent.click(screen.getByRole("button", { name: /Novo fornecedor/ }));
    const dialog = await screen.findByRole("dialog");

    fireEvent.click(within(dialog).getByRole("button", { name: "Guardar fornecedor" }));
    expect(within(dialog).getByText("Indique o nome do fornecedor.")).toBeInTheDocument();

    fireEvent.change(within(dialog).getByLabelText("Nome *"), { target: { value: "X" } });
    fireEvent.change(within(dialog).getByLabelText("Email"), { target: { value: "nao-e-email" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Guardar fornecedor" }));
    expect(within(dialog).getByText("O email não parece válido.")).toBeInTheDocument();

    fireEvent.change(within(dialog).getByLabelText("Email"), { target: { value: "" } });
    fireEvent.change(within(dialog).getByLabelText("Telefone"), { target: { value: "abc" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Guardar fornecedor" }));
    expect(within(dialog).getByText(/Telefone inválido/)).toBeInTheDocument();
    expect(createSupplier).not.toHaveBeenCalled();
  });

  it("edita e desativa um fornecedor existente", async () => {
    updateSupplier.mockResolvedValue(makeSupplier({ is_active: false }));
    renderWithProviders(<Suppliers />, { me: withManage() });
    await screen.findByText("Energy Systems");

    fireEvent.click(screen.getByRole("button", { name: "Editar Energy Systems" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("Nome *")).toHaveValue("Energy Systems");
    expect(within(dialog).getByRole("button", { name: "Remover Carports" })).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Remover Carports" }));
    fireEvent.click(within(dialog).getByLabelText(/Fornecedor ativo/));
    fireEvent.click(within(dialog).getByRole("button", { name: "Guardar fornecedor" }));

    await waitFor(() => expect(updateSupplier).toHaveBeenCalled());
    const [id, changes] = updateSupplier.mock.calls[0];
    expect(id).toBe("s-1");
    expect(changes).toMatchObject({ is_active: false, material_types: ["Estruturas de fixação"] });
    expect(await screen.findByText("Fornecedor «Energy Systems» atualizado.")).toBeInTheDocument();
  });

  it("mostra o erro do servidor e mantém o diálogo aberto", async () => {
    const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
    createSupplier.mockImplementation(() => {
      throw new actual.ApiError(409, "Já existe um fornecedor com este nome.");
    });
    renderWithProviders(<Suppliers />, { me: withManage() });
    await screen.findByText("Energy Systems");
    fireEvent.click(screen.getByRole("button", { name: /Novo fornecedor/ }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Nome *"), { target: { value: "Energy Systems" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Guardar fornecedor" }));

    expect(await within(dialog).findByText("Já existe um fornecedor com este nome.")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
