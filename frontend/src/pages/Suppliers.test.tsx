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
    name: "Fornecedor A",
    category: null,
    contact: "Ana",
    phone: "+351 253 145 794",
    email: "info@fornecedor-a.example",
    website: "https://www.fornecedor-a.example/",
    address: "Rua de Lamas 541, Rio Covo",
    maps_url: null,
    contacts: [],
    lat: null,
    lon: null,
    is_preferred: false,
    lead_time_days: null,
    materials: "",
    notes: "",
    is_active: true,
    material_types: ["Carports", "Estruturas de fixação"],
    company_codes: [],
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
        name: "Fornecedor B",
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

    expect(await screen.findByText("Fornecedor A")).toBeInTheDocument();
    expect(screen.getByText("2 fornecedores")).toBeInTheDocument();
    expect(screen.getAllByText("Carports").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "+351 253 145 794" })).toHaveAttribute("href", "tel:+351253145794");
    expect(screen.getByRole("link", { name: "info@fornecedor-a.example" })).toHaveAttribute("href", "mailto:info@fornecedor-a.example");
    expect(screen.getByRole("link", { name: "www.fornecedor-a.example" })).toHaveAttribute("href", "https://www.fornecedor-a.example/");
    expect(screen.getByText("Rua de Lamas 541, Rio Covo")).toBeInTheDocument();
    // Sem dados: traço; inativo assinalado; "Ver no mapa" só com coordenadas.
    expect(screen.getByText("Inativo")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Ver no mapa" })).toHaveLength(1);
  });

  it("mostra os contactos (pessoa, departamento, telefone, email) e a ligação à localização", async () => {
    listSuppliers.mockResolvedValue([
      makeSupplier({
        maps_url: "https://maps.example.invalid/abc",
        contacts: [
          { id: "c-1", name: "Contacto Sintético", department: "Backoffice", phone: "000 000 001", email: "c1@example.invalid" },
          { id: "c-2", name: "Geral", department: null, phone: "000 000 002", email: null },
        ],
      }),
    ]);
    renderWithProviders(<Suppliers />, { me: viewOnly() });

    expect(await screen.findByText("Contacto Sintético")).toBeInTheDocument();
    expect(screen.getByText(/(Backoffice)/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "000 000 001" })).toHaveAttribute("href", "tel:000000001");
    expect(screen.getByRole("link", { name: "c1@example.invalid" })).toHaveAttribute("href", "mailto:c1@example.invalid");
    expect(screen.getByText("Geral")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Abrir localização" })).toHaveAttribute("href", "https://maps.example.invalid/abc");
  });

  it("separa contacto da empresa (sob o nome) e pessoas de contacto (coluna própria, primeira em destaque)", async () => {
    listSuppliers.mockResolvedValue([
      makeSupplier({
        contact: "Texto legado que não deve aparecer",
        contacts: [
          { id: "c-1", name: "Pessoa Um", department: "Comercial", phone: "000 000 001", email: "um@example.invalid" },
          { id: "c-2", name: "Pessoa Dois", department: null, phone: null, email: "dois@example.invalid" },
        ],
      }),
    ]);
    renderWithProviders(<Suppliers />, { me: viewOnly() });
    await screen.findByText("Fornecedor A");

    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(["Fornecedor", "Pessoa de contacto", "Tipos de material", "Localização"]);

    const [companyCell, personCell] = within(screen.getAllByRole("row")[1]).getAllByRole("cell");
    // Empresa: telefone e email à esquerda, sob o nome.
    expect(within(companyCell).getByRole("link", { name: "+351 253 145 794" })).toHaveAttribute("href", "tel:+351253145794");
    expect(within(companyCell).getByRole("link", { name: "info@fornecedor-a.example" })).toHaveAttribute("href", "mailto:info@fornecedor-a.example");
    expect(within(companyCell).queryByText("Pessoa Um")).not.toBeInTheDocument();
    // Pessoas: todas, a primeira destacada; sem o texto legado.
    expect(within(personCell).getByText("Pessoa Um").closest(".supplier-person")).toHaveClass("supplier-person--primary");
    expect(within(personCell).getByText("Pessoa Dois").closest(".supplier-person")).toHaveClass("supplier-person--secondary");
    expect(within(personCell).getByRole("link", { name: "000 000 001" })).toHaveAttribute("href", "tel:000000001");
    expect(within(personCell).getByRole("link", { name: "dois@example.invalid" })).toHaveAttribute("href", "mailto:dois@example.invalid");
    expect(within(personCell).queryByText("+351 253 145 794")).not.toBeInTheDocument();
    expect(screen.queryByText("Texto legado que não deve aparecer")).not.toBeInTheDocument();
  });

  it("usa o texto legado de contacto como alternativa quando não há pessoas estruturadas", async () => {
    renderWithProviders(<Suppliers />, { me: viewOnly() });
    await screen.findByText("Fornecedor A");
    const rows = screen.getAllByRole("row");
    const personCellA = within(rows[1]).getAllByRole("cell")[1];
    expect(within(personCellA).getByText("Ana")).toBeInTheDocument();
    // Sem pessoas nem texto legado: traço.
    const personCellB = within(rows[2]).getAllByRole("cell")[1];
    expect(personCellB).toHaveTextContent("—");
  });

  it("abre o detalhe completo ao clicar no nome e fecha com Escape", async () => {
    listSuppliers.mockResolvedValue([
      makeSupplier({
        materials: "Painéis, cabos e fixadores",
        notes: "Nota sintética do fornecedor.",
        contacts: [
          { id: "c-1", name: "Contacto Sintético Um", department: "Comercial", phone: "000 000 001", email: "um@example.invalid" },
          { id: "c-2", name: "Contacto Sintético Dois", department: "Logística", phone: null, email: "dois@example.invalid" },
        ],
      }),
    ]);
    renderWithProviders(<Suppliers />, { me: viewOnly() });
    await screen.findByText("Fornecedor A");

    fireEvent.click(screen.getByRole("button", { name: "Ver detalhe de Fornecedor A" }));
    const dialog = await screen.findByRole("dialog", { name: "Detalhe do fornecedor: Fornecedor A" });
    expect(within(dialog).getByText("Dados gerais")).toBeInTheDocument();
    expect(within(dialog).getByText("Carports")).toBeInTheDocument();
    expect(within(dialog).getByText("Painéis, cabos e fixadores")).toBeInTheDocument();
    expect(within(dialog).getByText("Contacto Sintético Um")).toBeInTheDocument();
    expect(within(dialog).getByText("Contacto Sintético Dois")).toBeInTheDocument();
    expect(within(dialog).getByText("Nota sintética do fornecedor.")).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Detalhe do fornecedor: Fornecedor A" })).not.toBeInTheDocument());
  });

  it("fecha o detalhe do fornecedor ao clicar fora da janela", async () => {
    renderWithProviders(<Suppliers />, { me: viewOnly() });
    await screen.findByText("Fornecedor A");
    fireEvent.click(screen.getByRole("button", { name: "Ver detalhe de Fornecedor A" }));
    const dialog = await screen.findByRole("dialog", { name: "Detalhe do fornecedor: Fornecedor A" });
    fireEvent.mouseDown(dialog.parentElement!);
    expect(screen.queryByRole("dialog", { name: "Detalhe do fornecedor: Fornecedor A" })).not.toBeInTheDocument();
  });

  it("edita os contactos e envia a lista completa (valida antes)", async () => {
    updateSupplier.mockResolvedValue(makeSupplier());
    renderWithProviders(<Suppliers />, { me: withManage() });
    await screen.findByText("Fornecedor A");

    fireEvent.click(screen.getAllByRole("button", { name: /Editar Fornecedor A/ })[0]);
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Adicionar contacto" }));
    fireEvent.change(within(dialog).getByLabelText("Nome do contacto 1"), { target: { value: "Contacto Sintético" } });
    fireEvent.change(within(dialog).getByLabelText("Email do contacto 1"), { target: { value: "sem-arroba" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Guardar fornecedor" }));
    expect(await within(dialog).findByText("Contacto 1: o email não parece válido.")).toBeInTheDocument();
    expect(updateSupplier).not.toHaveBeenCalled();

    fireEvent.change(within(dialog).getByLabelText("Email do contacto 1"), { target: { value: "c1@example.invalid" } });
    fireEvent.change(within(dialog).getByLabelText("Departamento do contacto 1"), { target: { value: "Comercial" } });
    fireEvent.change(within(dialog).getByLabelText("Ligação ao mapa (Google Maps…)"), { target: { value: "https://maps.example.invalid/x" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Guardar fornecedor" }));

    await waitFor(() => expect(updateSupplier).toHaveBeenCalled());
    expect(updateSupplier.mock.calls[0][1]).toMatchObject({
      maps_url: "https://maps.example.invalid/x",
      contacts: [{ name: "Contacto Sintético", department: "Comercial", phone: null, email: "c1@example.invalid" }],
    });
  });

  it("carrega só fornecedores ativos por omissão e envia os filtros ao servidor", async () => {
    renderWithProviders(<Suppliers />, { me: viewOnly() });
    await screen.findByText("Fornecedor A");
    expect(listSuppliers).toHaveBeenLastCalledWith({ q: undefined, material_type: undefined, is_active: true, company_code: undefined });

    await screen.findByRole("option", { name: "Carports (2)" });
    fireEvent.change(screen.getByLabelText("Tipo de material"), { target: { value: "Carports" } });
    fireEvent.change(screen.getByLabelText("Situação"), { target: { value: "all" } });
    fireEvent.change(screen.getByLabelText("Pesquisar"), { target: { value: "  porto " } });

    await waitFor(() =>
      expect(listSuppliers).toHaveBeenLastCalledWith({ q: "porto", material_type: "Carports", is_active: undefined, company_code: undefined })
    );
  });

  it("toApiFilters traduz 'todos' para ausência de filtro", () => {
    expect(toApiFilters({ search: " ", materialType: "", active: "all", company: "all" })).toEqual({
      q: undefined,
      material_type: undefined,
      is_active: undefined,
      company_code: undefined,
    });
    expect(toApiFilters({ search: "", materialType: "", active: "inactive", company: "all" }).is_active).toBe(false);
  });

  it("filtra cada empresa e mantém os restantes filtros ao trocar de separador", async () => {
    renderWithProviders(<Suppliers />, { me: viewOnly() });
    await screen.findByText("Fornecedor A");
    fireEvent.change(screen.getByLabelText("Pesquisar"), { target: { value: "porto" } });
    fireEvent.change(screen.getByLabelText("Tipo de material"), { target: { value: "Carports" } });
    fireEvent.change(screen.getByLabelText("Situação"), { target: { value: "all" } });
    for (const [label, code] of [["Solcor", "solcor"], ["Verde Milenar", "verde_milenar"], ["Por classificar", "unclassified"]]) {
      fireEvent.click(screen.getByRole("button", { name: label }));
      await waitFor(() => expect(listSuppliers).toHaveBeenLastCalledWith({
        q: "porto", material_type: "Carports", is_active: undefined, company_code: code,
      }));
    }
  });

  it("permite classificar um fornecedor em ambas as empresas", async () => {
    updateSupplier.mockResolvedValue(makeSupplier({ company_codes: ["solcor", "verde_milenar"] }));
    renderWithProviders(<Suppliers />, { me: withManage() });
    await screen.findByText("Fornecedor A");
    fireEvent.click(screen.getAllByRole("button", { name: /Editar Fornecedor A/ })[0]);
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByLabelText("Solcor"));
    fireEvent.click(within(dialog).getByLabelText("Verde Milenar"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Guardar fornecedor" }));
    await waitFor(() => expect(updateSupplier).toHaveBeenCalledWith("s-1", expect.objectContaining({ company_codes: ["solcor", "verde_milenar"] })));
  });

  it("permite filtrar como leitor sem mostrar controlos de classificação", async () => {
    renderWithProviders(<Suppliers />, { me: viewOnly() });
    await screen.findByText("Fornecedor A");
    fireEvent.click(screen.getByRole("button", { name: "Solcor" }));
    await waitFor(() => expect(listSuppliers).toHaveBeenLastCalledWith(expect.objectContaining({ company_code: "solcor" })));
    expect(screen.queryByRole("button", { name: /Novo fornecedor/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Editar/ })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Solcor")).not.toBeInTheDocument();
  });

  it("sem permissão de gestão não mostra criar nem editar", async () => {
    renderWithProviders(<Suppliers />, { me: viewOnly() });
    await screen.findByText("Fornecedor A");
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
    await screen.findByText("Fornecedor A");

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
      maps_url: null,
      contacts: [],
      website: null,
      contact: null,
      notes: "",
      material_types: ["Inversores", "Baterias"],
      company_codes: [],
    });
    expect(await screen.findByText("Fornecedor «Nova Loja» criado.")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(listSuppliers.mock.calls.length).toBeGreaterThan(1); // recarregou a lista
  });

  it("valida no cliente antes de enviar", async () => {
    renderWithProviders(<Suppliers />, { me: withManage() });
    await screen.findByText("Fornecedor A");
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
    await screen.findByText("Fornecedor A");

    fireEvent.click(screen.getByRole("button", { name: "Editar Fornecedor A" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("Nome *")).toHaveValue("Fornecedor A");
    expect(within(dialog).getByRole("button", { name: "Remover Carports" })).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Remover Carports" }));
    fireEvent.click(within(dialog).getByLabelText(/Fornecedor ativo/));
    fireEvent.click(within(dialog).getByRole("button", { name: "Guardar fornecedor" }));

    await waitFor(() => expect(updateSupplier).toHaveBeenCalled());
    const [id, changes] = updateSupplier.mock.calls[0];
    expect(id).toBe("s-1");
    expect(changes).toMatchObject({ is_active: false, material_types: ["Estruturas de fixação"], company_codes: [] });
    expect(await screen.findByText("Fornecedor «Fornecedor A» atualizado.")).toBeInTheDocument();
  });

  it("mostra o erro do servidor e mantém o diálogo aberto", async () => {
    const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
    createSupplier.mockImplementation(() => {
      throw new actual.ApiError(409, "Já existe um fornecedor com este nome.");
    });
    renderWithProviders(<Suppliers />, { me: withManage() });
    await screen.findByText("Fornecedor A");
    fireEvent.click(screen.getByRole("button", { name: /Novo fornecedor/ }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Nome *"), { target: { value: "Fornecedor A" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Guardar fornecedor" }));

    expect(await within(dialog).findByText("Já existe um fornecedor com este nome.")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
