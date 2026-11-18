import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import TimeBankNotes from "./TimeBankNotes";

const api = vi.hoisted(() => ({ listTimeBankNotes: vi.fn(), createTimeBankNote: vi.fn() }));
vi.mock("../api/timeBank", async () => ({ ...(await vi.importActual<typeof import("../api/timeBank")>("../api/timeBank")), ...api }));

const note = (id: string, body = "Nota histórica") => ({ id, person_id: "p1", body, author_display_name: "Gestor", created_at: "2026-10-27T10:00:00Z" });

beforeEach(() => { vi.clearAllMocks(); api.listTimeBankNotes.mockResolvedValue({ items: [note("1")], total: 1 }); api.createTimeBankNote.mockResolvedValue(note("2")); });

describe("TimeBankNotes", () => {
  it("reads notes, creates and reads back while preserving text on failure", async () => {
    render(<TimeBankNotes personId="p1" canManage accountId="u1" />);
    expect(await screen.findByText("Nota histórica")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Nova nota/), { target: { value: "  Nova nota  " } });
    fireEvent.click(screen.getByRole("button", { name: "Adicionar nota" }));
    await waitFor(() => expect(api.createTimeBankNote).toHaveBeenCalledWith("p1", "Nova nota"));
    await waitFor(() => expect(api.listTimeBankNotes).toHaveBeenCalledTimes(2));
    api.createTimeBankNote.mockRejectedValueOnce(new Error("falha"));
    fireEvent.change(screen.getByLabelText(/Nova nota/), { target: { value: "Manter texto" } });
    fireEvent.click(screen.getByRole("button", { name: "Adicionar nota" }));
    expect(await screen.findByText("Não foi possível guardar a nota.")).toBeInTheDocument();
    expect(screen.getByLabelText(/Nova nota/)).toHaveValue("Manter texto");
  });

  it("paginates by total and stays read-only without manage capability", async () => {
    api.listTimeBankNotes.mockResolvedValue({ items: [note("1")], total: 21 });
    render(<TimeBankNotes personId="p1" canManage={false} />);
    expect(await screen.findByText("1–20 de 21")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Nova nota/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Seguinte" }));
    await waitFor(() => expect(api.listTimeBankNotes).toHaveBeenLastCalledWith("p1", 20, 20));
  });

  it("requires person selection", () => {
    render(<TimeBankNotes canManage={false} />);
    expect(screen.getByText(/Selecione uma pessoa/)).toBeInTheDocument();
    expect(api.listTimeBankNotes).not.toHaveBeenCalled();
  });

  it("ignores a late read after the selected person changes", async () => {
    let resolveFirst!: (value: { items: ReturnType<typeof note>[]; total: number }) => void;
    api.listTimeBankNotes.mockImplementation((personId: string) => personId === "p1"
      ? new Promise((resolve) => { resolveFirst = resolve; })
      : Promise.resolve({ items: [note("2", "Nota da pessoa dois")], total: 1 }));
    const { rerender } = render(<TimeBankNotes personId="p1" canManage={false} />);
    rerender(<TimeBankNotes personId="p2" canManage={false} />);
    expect(await screen.findByText("Nota da pessoa dois")).toBeInTheDocument();
    resolveFirst({ items: [note("1", "Resposta atrasada")], total: 1 });
    await waitFor(() => expect(screen.queryByText("Resposta atrasada")).not.toBeInTheDocument());
  });

  it.each(["person", "account"]) ("resets a pending create when the %s changes", async (changed) => {
    let resolveOld!: (value: ReturnType<typeof note>) => void;
    let resolveNew!: (value: ReturnType<typeof note>) => void;
    api.createTimeBankNote.mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }));
    api.createTimeBankNote.mockImplementationOnce(() => new Promise((resolve) => { resolveNew = resolve; }));
    const { rerender } = render(<TimeBankNotes personId="p1" accountId="a1" canManage />);
    await screen.findByText("Nota histórica");
    fireEvent.change(screen.getByLabelText(/Nova nota/), { target: { value: "Rascunho antigo" } });
    fireEvent.click(screen.getByRole("button", { name: "Adicionar nota" }));
    await waitFor(() => expect(api.createTimeBankNote).toHaveBeenCalledTimes(1));
    rerender(<TimeBankNotes personId={changed === "person" ? "p2" : "p1"} accountId={changed === "account" ? "a2" : "a1"} canManage />);
    const textbox = await screen.findByLabelText(/Nova nota/);
    expect(textbox).toHaveValue("");
    fireEvent.change(textbox, { target: { value: "Nova nota alvo" } });
    fireEvent.click(screen.getByRole("button", { name: "Adicionar nota" }));
    await waitFor(() => expect(api.createTimeBankNote).toHaveBeenCalledTimes(2));
    resolveOld(note("old"));
    await waitFor(() => expect(screen.getByLabelText(/Nova nota/)).toHaveValue("Nova nota alvo"));
    expect(await screen.findByLabelText(/Nova nota/)).toHaveValue("Nova nota alvo");
    expect(screen.queryByText("falha antiga")).not.toBeInTheDocument();
    resolveNew(note("new"));
    await waitFor(() => expect(api.listTimeBankNotes).toHaveBeenCalledTimes(3));
  });

  it("invalidates a create when manage capability is lost and allows a fresh create", async () => {
    let resolveOld!: (value: ReturnType<typeof note>) => void;
    let resolveNew!: (value: ReturnType<typeof note>) => void;
    api.createTimeBankNote.mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }));
    api.createTimeBankNote.mockImplementationOnce(() => new Promise((resolve) => { resolveNew = resolve; }));
    const { rerender } = render(<TimeBankNotes personId="p1" accountId="a1" canManage />);
    await screen.findByText("Nota histórica");
    fireEvent.change(screen.getByLabelText(/Nova nota/), { target: { value: "Rascunho conservado" } });
    fireEvent.click(screen.getByRole("button", { name: "Adicionar nota" }));
    await waitFor(() => expect(api.createTimeBankNote).toHaveBeenCalledTimes(1));
    rerender(<TimeBankNotes personId="p1" accountId="a1" canManage={false} />);
    expect(screen.queryByLabelText(/Nova nota/)).not.toBeInTheDocument();
    rerender(<TimeBankNotes personId="p1" accountId="a1" canManage />);
    expect(await screen.findByLabelText(/Nova nota/)).toHaveValue("Rascunho conservado");
    resolveOld(note("old"));
    await waitFor(() => expect(api.listTimeBankNotes).toHaveBeenCalledTimes(1));
    expect(screen.getByLabelText(/Nova nota/)).toHaveValue("Rascunho conservado");
    fireEvent.click(screen.getByRole("button", { name: "Adicionar nota" }));
    await waitFor(() => expect(api.createTimeBankNote).toHaveBeenCalledTimes(2));
    resolveNew(note("new"));
    await waitFor(() => expect(api.listTimeBankNotes).toHaveBeenCalledTimes(2));
  });
});
