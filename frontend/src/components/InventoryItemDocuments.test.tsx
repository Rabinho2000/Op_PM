import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type InventoryItemDocument } from "../api/client";
import InventoryItemDocuments from "./InventoryItemDocuments";

const api = vi.hoisted(() => ({
  listInventoryItemDocuments: vi.fn(),
  getInventoryItemDocumentBlob: vi.fn(),
  uploadInventoryItemDocument: vi.fn(),
  deleteInventoryItemDocument: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, ...api };
});

let clickedAnchor: HTMLAnchorElement | null = null;

function document(overrides: Partial<InventoryItemDocument> = {}): InventoryItemDocument {
  return {
    id: "doc-1",
    item_id: "item-1",
    kind: "datasheet",
    title: "Ficha técnica INV-5000",
    filename: "inversor.pdf",
    content_type: "application/pdf",
    size: 245760,
    created_by_person_id: "person-1",
    created_at: "2026-10-22T12:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  clickedAnchor = null;
  let next = 0;
  vi.spyOn(URL, "createObjectURL").mockImplementation(() => `blob:document-${++next}`);
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    clickedAnchor = this;
  });
  vi.spyOn(window, "confirm").mockReturnValue(true);
  api.listInventoryItemDocuments.mockResolvedValue([]);
  api.getInventoryItemDocumentBlob.mockResolvedValue(new Blob(["manual"], { type: "application/pdf" }));
  api.uploadInventoryItemDocument.mockResolvedValue(document());
  api.deleteInventoryItemDocument.mockResolvedValue(undefined);
});

describe("documentos da ficha de inventário", () => {
  it("lista documentos agrupados por tipo com título, nome, tamanho e data legíveis", async () => {
    api.listInventoryItemDocuments.mockResolvedValue([
      document(),
      document({ id: "doc-2", kind: "manual", title: "Manual do inversor", filename: "manual.pdf" }),
      document({ id: "doc-3", kind: "guia", title: "Guia de instalação", filename: "guia.pdf" }),
      document({ id: "doc-4", kind: "outro", title: "Certificado", filename: "certificado.pdf" }),
    ]);
    render(<InventoryItemDocuments itemId="item-1" canManage={false} accountKey="user-a" />);

    expect(await screen.findByRole("heading", { name: "Datasheets" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Manuais" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Guias" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Outros documentos" })).toBeInTheDocument();
    expect(screen.getByText("Ficha técnica INV-5000")).toBeInTheDocument();
    expect(screen.getByText("inversor.pdf · 240 KB")).toBeInTheDocument();
    expect(screen.getAllByText(/22\/10\/2026/)).toHaveLength(4);
  });

  it("mostra estado vazio sem oferecer gestão a quem só pode ler", async () => {
    render(<InventoryItemDocuments itemId="item-1" canManage={false} accountKey="user-a" />);

    expect(await screen.findByText("Ainda não há documentos associados a este artigo.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Adicionar documento" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Tipo de documento")).not.toBeInTheDocument();
  });

  it("descarrega via blob e revoga o URL ao desmontar, mantendo leitura sem permissão de gestão", async () => {
    api.listInventoryItemDocuments.mockResolvedValue([document()]);
    const { unmount } = render(<InventoryItemDocuments itemId="item-1" canManage={false} accountKey="user-a" />);

    const download = await screen.findByRole("button", { name: "Descarregar Ficha técnica INV-5000" });
    expect(download).toHaveStyle({ minHeight: "44px" });
    fireEvent.click(download);
    await waitFor(() => expect(api.getInventoryItemDocumentBlob).toHaveBeenCalledWith("item-1", "doc-1"));
    await waitFor(() => expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled());
    expect(URL.createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(clickedAnchor).toMatchObject({ href: "blob:document-1", download: "inversor.pdf" });
    expect(clickedAnchor?.isConnected).toBe(false);
    unmount();
    await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:document-1"));
  });

  it("só permite upload e remoção com manage_catalog, confirma e refresca a lista sem fechar a ficha", async () => {
    api.listInventoryItemDocuments
      .mockResolvedValueOnce([document()])
      .mockResolvedValueOnce([]);
    const { rerender } = render(<InventoryItemDocuments itemId="item-1" canManage={false} accountKey="user-a" />);
    await screen.findByRole("button", { name: "Descarregar Ficha técnica INV-5000" });
    expect(screen.queryByRole("button", { name: "Remover Ficha técnica INV-5000" })).not.toBeInTheDocument();

    rerender(<InventoryItemDocuments itemId="item-1" canManage accountKey="user-a" />);
    fireEvent.click(await screen.findByRole("button", { name: "Remover Ficha técnica INV-5000" }));
    expect(window.confirm).toHaveBeenCalledWith("Remover «Ficha técnica INV-5000» da lista de documentos?");
    await waitFor(() => expect(api.deleteInventoryItemDocument).toHaveBeenCalledWith("item-1", "doc-1"));
    expect(await screen.findByText("Ainda não há documentos associados a este artigo.")).toBeInTheDocument();
  });

  it("envia kind, título e ficheiro multipart e volta a carregar a lista", async () => {
    api.listInventoryItemDocuments
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([document({ id: "doc-uploaded", title: "Datasheet novo" })]);
    render(<InventoryItemDocuments itemId="item-1" canManage accountKey="user-a" />);
    await screen.findByText("Ainda não há documentos associados a este artigo.");

    fireEvent.change(screen.getByLabelText("Tipo de documento"), { target: { value: "manual" } });
    fireEvent.change(screen.getByLabelText("Título do documento"), { target: { value: "Manual do fabricante" } });
    const file = new File(["%PDF-1.7"], "manual.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText("Ficheiro do documento"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "Adicionar documento" }));

    await waitFor(() => expect(api.uploadInventoryItemDocument).toHaveBeenCalledWith(
      "item-1",
      "manual",
      "Manual do fabricante",
      file,
    ));
    expect(await screen.findByText("Datasheet novo")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Documentos" })).toBeInTheDocument();
  });

  it.each([
    [400, "Formato inválido. Utilize PDF, JPEG, PNG ou WebP."],
    [413, "O documento excede o limite de 25 MB."],
  ])("mostra o detalhe do erro HTTP %s do servidor", async (status, detail) => {
    api.uploadInventoryItemDocument.mockRejectedValue(new ApiError(status, detail));
    render(<InventoryItemDocuments itemId="item-1" canManage accountKey="user-a" />);
    await screen.findByText("Ainda não há documentos associados a este artigo.");

    fireEvent.change(screen.getByLabelText("Título do documento"), { target: { value: "Documento" } });
    fireEvent.change(screen.getByLabelText("Ficheiro do documento"), {
      target: { files: [new File(["data"], "documento.pdf", { type: "application/pdf" })] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Adicionar documento" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(detail);
  });

  it("valida formato e limite no cliente apenas como conveniência", async () => {
    render(<InventoryItemDocuments itemId="item-1" canManage accountKey="user-a" />);
    await screen.findByText("Ainda não há documentos associados a este artigo.");

    fireEvent.change(screen.getByLabelText("Ficheiro do documento"), {
      target: { files: [new File(["x"], "script.exe", { type: "application/octet-stream" })] },
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Formato inválido. Utilize PDF, JPEG, PNG ou WebP.");
    expect(api.uploadInventoryItemDocument).not.toHaveBeenCalled();
  });
});
