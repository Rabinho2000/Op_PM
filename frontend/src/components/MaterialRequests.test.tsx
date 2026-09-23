// Pedidos de material a fornecedores (D-067). A UI só mostra as ações que o
// servidor devolve em `allowed_actions`; o sistema nunca envia email; o
// orçamento exige o preço de TODAS as linhas; a mensagem do servidor é a verdade.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { InventoryItem, MaterialRequest } from "../api/client";
import { makeMe } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import {
  CreateMaterialRequestModal,
  formatUnitPrice,
  MaterialRequestDetailModal,
  SupplierRequestsSection,
} from "./MaterialRequests";

const api = vi.hoisted(() => ({
  getMaterialRequest: vi.fn(),
  applyMaterialRequestAction: vi.fn(),
  getMaterialRequestEmailDraft: vi.fn(),
  listMaterialRequests: vi.fn(),
  createMaterialRequest: vi.fn(),
  listInventoryItems: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, ...api };
});

function request(overrides: Partial<MaterialRequest> = {}): MaterialRequest {
  return {
    id: "req-1",
    project_id: "proj-1",
    project_name: "Instalação Sintética Um",
    supplier_id: "sup-1",
    supplier_name: "Fornecedor Sintético",
    status: "rascunho",
    notes: "",
    created_by_display_name: "PM Sintético",
    approved_by_display_name: null,
    created_at: "2026-09-23T10:00:00Z",
    updated_at: "2026-09-23T10:00:00Z",
    lines: [
      { id: "l1", item_id: null, description: "Cabo solar 6mm", quantity: "10.000", unit: "m", unit_price: null, line_total: null },
      { id: "l2", item_id: null, description: "Conectores MC4", quantity: "5.000", unit: null, unit_price: null, line_total: null },
    ],
    total: null,
    allowed_actions: ["send", "cancel"],
    history: [
      { action: "create", from_status: null, to_status: "rascunho", changed_by_display_name: "PM Sintético", note: "", changed_at: "2026-09-23T10:00:00Z" },
    ],
    ...overrides,
  };
}

async function ApiError(status: number, detail: string) {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return new actual.ApiError(status, detail);
}

const ME = makeMe({ permissions: ["inventory.view", "material_request.create"] });

function openDetail(overrides: Partial<MaterialRequest> = {}) {
  api.getMaterialRequest.mockResolvedValue(request(overrides));
  const onChanged = vi.fn();
  const onCopied = vi.fn();
  renderWithProviders(
    <MaterialRequestDetailModal requestId="req-1" onClose={vi.fn()} onChanged={onChanged} onCopied={onCopied} />,
    { me: ME }
  );
  return { onChanged, onCopied };
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.listInventoryItems.mockResolvedValue([]);
});

describe("Detalhe do pedido de material", () => {
  it("mostra só as ações que o servidor permite (allowed_actions)", async () => {
    openDetail({ allowed_actions: ["send", "cancel"] });
    expect(await screen.findByRole("button", { name: "Marcar como enviado" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancelar pedido" })).toBeInTheDocument();
    for (const hidden of ["Aprovar orçamento", "Adjudicar", "Registar orçamento"]) {
      expect(screen.queryByRole("button", { name: hidden })).not.toBeInTheDocument();
    }
  });

  it("um pedido sem ações permitidas (ex. adjudicado, ou sem permissão) não mostra nenhum botão de ação", async () => {
    openDetail({ status: "adjudicado", allowed_actions: [] });
    await screen.findByText("Adjudicado");
    for (const label of ["Marcar como enviado", "Registar orçamento", "Aprovar orçamento", "Adjudicar", "Cancelar pedido"]) {
      expect(screen.queryByRole("button", { name: label })).not.toBeInTheDocument();
    }
  });

  it("'enviar' avisa que o sistema não envia emails e só depois de confirmar chama o servidor", async () => {
    const { onChanged } = openDetail();
    fireEvent.click(await screen.findByRole("button", { name: "Marcar como enviado" }));
    expect(screen.getByText("O sistema não envia emails.")).toBeInTheDocument();
    expect(api.applyMaterialRequestAction).not.toHaveBeenCalled(); // ainda só pediu confirmação

    api.applyMaterialRequestAction.mockResolvedValue(request({ status: "pedido_enviado", allowed_actions: ["record_quote", "cancel"] }));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar" }));

    await waitFor(() =>
      expect(api.applyMaterialRequestAction).toHaveBeenCalledWith("req-1", { action: "send", note: "", prices: undefined })
    );
    expect(await screen.findByText("Pedido enviado")).toBeInTheDocument();
    expect(onChanged).toHaveBeenCalled();
    // as ações passam a ser as do NOVO estado, também vindas do servidor
    expect(screen.getByRole("button", { name: "Registar orçamento" })).toBeInTheDocument();
  });

  it("o orçamento envia o preço de TODAS as linhas", async () => {
    openDetail({ status: "pedido_enviado", allowed_actions: ["record_quote", "cancel"] });
    fireEvent.click(await screen.findByRole("button", { name: "Registar orçamento" }));
    fireEvent.change(screen.getByLabelText("Preço unitário — Cabo solar 6mm"), { target: { value: "10.10" } });
    fireEvent.change(screen.getByLabelText("Preço unitário — Conectores MC4"), { target: { value: "4.33" } });

    api.applyMaterialRequestAction.mockResolvedValue(request({ status: "orcamento_recebido", total: "127.65" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar" }));

    await waitFor(() =>
      expect(api.applyMaterialRequestAction).toHaveBeenCalledWith("req-1", {
        action: "record_quote",
        note: "",
        prices: [
          { line_id: "l1", unit_price: "10.10" },
          { line_id: "l2", unit_price: "4.33" },
        ],
      })
    );
  });

  it("mostra a mensagem do servidor quando a ação é recusada e não muda o estado apresentado", async () => {
    openDetail({ status: "pedido_enviado", allowed_actions: ["record_quote", "cancel"] });
    fireEvent.click(await screen.findByRole("button", { name: "Registar orçamento" }));
    api.applyMaterialRequestAction.mockRejectedValue(await ApiError(400, "O orçamento tem de indicar o preço de todas as linhas."));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    expect(await screen.findByText("O orçamento tem de indicar o preço de todas as linhas.")).toBeInTheDocument();
    expect(screen.getByText("Pedido enviado")).toBeInTheDocument(); // continua no mesmo estado
  });

  it("a adjudicação avisa que é uma decisão humana e não pode ser desfeita", async () => {
    openDetail({ status: "aprovado", allowed_actions: ["adjudicate", "cancel"], total: "127.65" });
    fireEvent.click(await screen.findByRole("button", { name: "Adjudicar" }));
    expect(screen.getByText(/não pode ser desfeita/)).toBeInTheDocument();
  });

  it("nunca mostra um total parcial: sem orçamento completo diz-o", async () => {
    openDetail({ total: null });
    expect(await screen.findByText(/sem orçamento completo/)).toBeInTheDocument();
  });

  it("mostra o total e o histórico com quem fez cada passo", async () => {
    openDetail({
      status: "aprovado",
      total: "127.65",
      approved_by_display_name: "Chefe Sintético",
      allowed_actions: [],
      history: [
        { action: "create", from_status: null, to_status: "rascunho", changed_by_display_name: "PM Sintético", note: "", changed_at: "2026-09-23T10:00:00Z" },
        { action: "approve", from_status: "orcamento_recebido", to_status: "aprovado", changed_by_display_name: "Chefe Sintético", note: "", changed_at: "2026-09-23T11:00:00Z" },
      ],
    });
    expect(await screen.findByText("Total: 127.65 €")).toBeInTheDocument();
    expect(screen.getByText("Orçamento aprovado por")).toBeInTheDocument();
    const history = within(screen.getByLabelText("Histórico do pedido"));
    expect(history.getByText("Criado")).toBeInTheDocument();
    expect(history.getByText(/Chefe Sintético ·/)).toBeInTheDocument();
  });

  it("o rascunho do email é texto para copiar — e diz que o sistema não o envia", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const { onCopied } = openDetail();
    api.getMaterialRequestEmailDraft.mockResolvedValue({
      to: "orcamentos@fornecedor.invalid",
      subject: "Pedido de orçamento — Instalação Sintética Um (ref. ABC12345)",
      body: "Bom dia,\n\n- 10 m Cabo solar 6mm",
    });
    fireEvent.click(await screen.findByRole("button", { name: "Ver rascunho do email" }));
    const box = await screen.findByLabelText("Rascunho do email");
    expect(within(box).getByText(/Para: orcamentos@fornecedor.invalid/)).toBeInTheDocument();
    expect(within(box).getByText("O sistema não envia este email.")).toBeInTheDocument();

    fireEvent.click(within(box).getByRole("button", { name: "Copiar email" }));
    await waitFor(() => expect(writeText).toHaveBeenCalled());
    expect(String(writeText.mock.calls[0][0])).toContain("Para: orcamentos@fornecedor.invalid");
    expect(String(writeText.mock.calls[0][0])).toContain("- 10 m Cabo solar 6mm");
    expect(onCopied).toHaveBeenCalledWith(true);
  });

  it("um erro ao carregar (ex. 404 de um pedido alheio) mostra a mensagem, sem quebrar", async () => {
    api.getMaterialRequest.mockRejectedValue(await ApiError(404, "Pedido de material não encontrado."));
    renderWithProviders(
      <MaterialRequestDetailModal requestId="x" onClose={vi.fn()} onChanged={vi.fn()} onCopied={vi.fn()} />,
      { me: ME }
    );
    expect(await screen.findByText("Pedido de material não encontrado.")).toBeInTheDocument();
  });
});

describe("Preço unitário", () => {
  it("mostra a escala do servidor sem zeros a mais e nunca com menos de 2 casas", () => {
    expect(formatUnitPrice("10.1000")).toBe("10.10 €");
    expect(formatUnitPrice("4.3250")).toBe("4.325 €");
    expect(formatUnitPrice("0.0875")).toBe("0.0875 €");
    expect(formatUnitPrice("12.0000")).toBe("12.00 €");
    expect(formatUnitPrice("7")).toBe("7.00 €");
    expect(formatUnitPrice(null)).toBe("—");
  });

  it("aparece formatado na tabela de linhas do detalhe", async () => {
    openDetail({
      status: "orcamento_recebido",
      total: "294.20",
      allowed_actions: [],
      lines: [
        { id: "l1", item_id: null, description: "Cabo", quantity: "12.000", unit: "m", unit_price: "10.1000", line_total: "121.20" },
        { id: "l2", item_id: null, description: "Conectores", quantity: "40.000", unit: null, unit_price: "4.3250", line_total: "173.00" },
      ],
    });
    const table = within(await screen.findByLabelText("Linhas do pedido"));
    expect(table.getByText("10.10 €")).toBeInTheDocument();
    expect(table.getByText("4.325 €")).toBeInTheDocument();
    expect(table.getByText("173.00 €")).toBeInTheDocument();
  });
});

describe("Criar pedido de material", () => {
  const PROJECTS = [
    { id: "proj-1", name: "Instalação Sintética Um" },
    { id: "proj-2", name: "Instalação Sintética Dois" },
  ];
  const CABLE = { id: "item-1", name: "Cabo solar 6mm", unit: "m" } as InventoryItem;

  function renderCreate() {
    api.listInventoryItems.mockResolvedValue([CABLE]);
    const onDone = vi.fn();
    renderWithProviders(
      <CreateMaterialRequestModal supplierId="sup-1" supplierName="Fornecedor Sintético" projects={PROJECTS} onClose={vi.fn()} onDone={onDone} />,
      { me: ME }
    );
    return { onDone };
  }

  it("exige o projeto e linhas válidas antes de chamar o servidor", async () => {
    renderCreate();
    fireEvent.click(await screen.findByRole("button", { name: "Criar rascunho" }));
    expect(await screen.findByText("Escolha o projeto.")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Projeto *"), { target: { value: "proj-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Criar rascunho" }));
    expect(await screen.findByText(/Cada linha precisa de um item ou descrição e de uma quantidade positiva/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Descrição da linha 1"), { target: { value: "Cabo" } });
    fireEvent.change(screen.getByLabelText("Quantidade da linha 1"), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "Criar rascunho" }));
    expect(await screen.findByText(/quantidade positiva/)).toBeInTheDocument();
    expect(api.createMaterialRequest).not.toHaveBeenCalled();
  });

  it("cria o rascunho ligado ao fornecedor, com linhas de item e de descrição livre, pela ordem escrita", async () => {
    const { onDone } = renderCreate();
    fireEvent.change(await screen.findByLabelText("Projeto *"), { target: { value: "proj-2" } });
    await waitFor(() => expect(screen.getByRole("option", { name: "Cabo solar 6mm (m)" })).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Item da linha 1"), { target: { value: "item-1" } });
    fireEvent.change(screen.getByLabelText("Quantidade da linha 1"), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "Adicionar linha" }));
    fireEvent.change(screen.getByLabelText("Descrição da linha 2"), { target: { value: "Painel 450 W" } });
    fireEvent.change(screen.getByLabelText("Quantidade da linha 2"), { target: { value: "24" } });
    fireEvent.change(screen.getByLabelText("Notas"), { target: { value: "Urgente" } });

    api.createMaterialRequest.mockResolvedValue(request());
    fireEvent.click(screen.getByRole("button", { name: "Criar rascunho" }));

    await waitFor(() =>
      expect(api.createMaterialRequest).toHaveBeenCalledWith({
        project_id: "proj-2",
        supplier_id: "sup-1",
        notes: "Urgente",
        lines: [
          { item_id: "item-1", description: "", quantity: "10" },
          { item_id: null, description: "Painel 450 W", quantity: "24" },
        ],
      })
    );
    await waitFor(() => expect(onDone).toHaveBeenCalled());
  });

  it("continua a permitir pedir por descrição livre se a lista de itens não estiver disponível", async () => {
    api.listInventoryItems.mockRejectedValue(new Error("403"));
    renderWithProviders(
      <CreateMaterialRequestModal supplierId="sup-1" supplierName="Fornecedor Sintético" projects={PROJECTS} onClose={vi.fn()} onDone={vi.fn()} />,
      { me: ME }
    );
    expect(await screen.findByLabelText("Descrição da linha 1")).toBeInTheDocument();
  });

  it("mostra a mensagem do servidor quando o pedido é recusado", async () => {
    renderCreate();
    fireEvent.change(await screen.findByLabelText("Projeto *"), { target: { value: "proj-1" } });
    fireEvent.change(screen.getByLabelText("Descrição da linha 1"), { target: { value: "Cabo" } });
    fireEvent.change(screen.getByLabelText("Quantidade da linha 1"), { target: { value: "3" } });
    api.createMaterialRequest.mockRejectedValue(await ApiError(403, "Sem permissão para criar pedidos de material neste projeto."));
    fireEvent.click(screen.getByRole("button", { name: "Criar rascunho" }));
    expect(await screen.findByText("Sem permissão para criar pedidos de material neste projeto.")).toBeInTheDocument();
  });
});

describe("Pedidos no detalhe do fornecedor", () => {
  it("lista os pedidos do fornecedor com o estado e abre o detalhe", async () => {
    api.listMaterialRequests.mockResolvedValue([
      request({ id: "r1", status: "pedido_enviado" }),
      request({ id: "r2", project_name: "Instalação Sintética Dois", status: "aprovado", total: "127.65" }),
    ]);
    const onOpen = vi.fn();
    renderWithProviders(
      <SupplierRequestsSection supplierId="sup-1" canCreate={false} refreshKey={0} onCreate={vi.fn()} onOpen={onOpen} />,
      { me: ME }
    );
    expect(await screen.findByText("Pedido enviado")).toBeInTheDocument();
    expect(screen.getByText("Aprovado")).toBeInTheDocument();
    expect(api.listMaterialRequests).toHaveBeenCalledWith({ supplier_id: "sup-1" });
    fireEvent.click(screen.getByRole("button", { name: /Instalação Sintética Dois/ }));
    expect(onOpen).toHaveBeenCalledWith("r2");
  });

  it("só oferece 'Pedir material' a quem pode criar pedidos", async () => {
    api.listMaterialRequests.mockResolvedValue([]);
    const { rerender } = renderWithProviders(
      <SupplierRequestsSection supplierId="sup-1" canCreate={false} refreshKey={0} onCreate={vi.fn()} onOpen={vi.fn()} />,
      { me: ME }
    );
    expect(await screen.findByText("Sem pedidos a este fornecedor.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pedir material" })).not.toBeInTheDocument();
    rerender(<SupplierRequestsSection supplierId="sup-1" canCreate refreshKey={0} onCreate={vi.fn()} onOpen={vi.fn()} />);
    expect(await screen.findByRole("button", { name: "Pedir material" })).toBeInTheDocument();
  });

  it("recarrega quando o refreshKey muda (depois de criar ou agir)", async () => {
    api.listMaterialRequests.mockResolvedValue([]);
    const { rerender } = renderWithProviders(
      <SupplierRequestsSection supplierId="sup-1" canCreate refreshKey={0} onCreate={vi.fn()} onOpen={vi.fn()} />,
      { me: ME }
    );
    await screen.findByText("Sem pedidos a este fornecedor.");
    rerender(<SupplierRequestsSection supplierId="sup-1" canCreate refreshKey={1} onCreate={vi.fn()} onOpen={vi.fn()} />);
    await waitFor(() => expect(api.listMaterialRequests).toHaveBeenCalledTimes(2));
  });

  it("mostra o erro do servidor em vez de uma lista vazia enganadora", async () => {
    api.listMaterialRequests.mockRejectedValue(await ApiError(403, "Sem permissão para ver pedidos de material."));
    renderWithProviders(
      <SupplierRequestsSection supplierId="sup-1" canCreate={false} refreshKey={0} onCreate={vi.fn()} onOpen={vi.fn()} />,
      { me: ME }
    );
    expect(await screen.findByText("Sem permissão para ver pedidos de material.")).toBeInTheDocument();
    expect(screen.queryByText("Sem pedidos a este fornecedor.")).not.toBeInTheDocument();
  });
});
