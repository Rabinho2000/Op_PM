import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "../../../components/Toast";
import type { CabosEngine, Result, State, Variant } from "../engine";
import CompareDialog from "./CompareDialog";
import NewBoardDialog from "./NewBoardDialog";
import TemplatesDialog from "./TemplatesDialog";

const state = {
  proj: "Projeto original",
  obra: { cliente: "Cliente original", morada: "Morada original" },
  invs: [{ id: 1, q: "QFV", modelo: "Modelo", pman: 10, L: 20, S: "auto" }],
  percs: [{ id: 7, orig: "QFV", dest: "Q. Entrada", L: 10, S: "auto" }],
  gws: [],
} as unknown as State;
const result = { invC: [], pC: [] } as unknown as Result;

function engineFor(overrides: Record<string, unknown> = {}) {
  return {
    protocol: 1,
    engine_version: "fake",
    newState: vi.fn((id?: string) => ({ ...state, proj: id ?? "novo" })),
    templates: [{ id: "cliente", label: "Cliente", description: "Modelo de cliente" }],
    actions: {
      applyTemplate: vi.fn((current: State) => ({ ...current, proj: "modelo", obra: { ...current.obra, cliente: "perdido", morada: "perdida" } })),
      addBoard: vi.fn((current: State) => current),
    },
    compare: {
      variants: vi.fn((): Variant[] => [
        { id: "atual", label: "Atual", note: "Sem alterações", summary: { cables: 10, terminals: 2, cablesAndTerminals: 12, protection: 4, total: 16, maxVoltageDropPct: 2.4, differentCables: 1, review: 0, estimated: false, aluminum: 0, circuits: 1 }, error: null },
        { id: "cu", label: "Cobre", note: "Mais robusta", summary: { cables: 14, terminals: 2, cablesAndTerminals: 16, protection: 4, total: 20, maxVoltageDropPct: 1.8, differentCables: 2, review: 0, estimated: false, aluminum: 0, circuits: 1 }, error: null },
      ]),
      apply: vi.fn((current: State) => current),
    },
    catalogs: { gateways: [{ marca: "", modelo: "Gateway Alfa", gama: "", fases: 3, In: 40, P: 0, ports: 2, portI: 20, base: true }] },
    ...overrides,
  } as unknown as CabosEngine;
}

function withToast(ui: React.ReactElement) {
  return render(<ToastProvider>{ui}</ToastProvider>);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("diálogo Comparar alternativas", () => {
  it("lista variantes, destaca a mais barata que cumpre e aplica só após confirmação", async () => {
    const engine = engineFor();
    const apply = vi.fn();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    withToast(<CompareDialog engine={engine} state={state} readOnly={false} apply={apply} onClose={vi.fn()} />);

    expect(await screen.findByRole("dialog", { name: "Comparar alternativas" })).toBeInTheDocument();
    expect(await screen.findByText("Atual")).toBeInTheDocument();
    expect(screen.getByText("Mais barata")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Aplicar.*Atual/i }));
    expect(confirm).toHaveBeenCalled();
    expect(apply).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: /Aplicar.*Atual/i }));
    expect(apply).toHaveBeenCalledTimes(1);
    const updater = apply.mock.calls[0][0] as (value: State) => State;
    updater(state);
    expect(engine.compare.apply).toHaveBeenCalledWith(state, "atual");
  });

  it("mantém a janela acessível, prende o foco e fecha com Escape", async () => {
    const onClose = vi.fn();
    withToast(<CompareDialog engine={engineFor()} state={state} readOnly={false} apply={vi.fn()} onClose={onClose} />);
    const dialog = await screen.findByRole("dialog", { name: "Comparar alternativas" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(document.activeElement).toBeInstanceOf(HTMLElement);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("diálogo Modelos / Novo projeto", () => {
  it("pede confirmação e preserva projeto, cliente e morada", () => {
    const engine = engineFor();
    const apply = vi.fn();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    withToast(<TemplatesDialog engine={engine} state={state} readOnly={false} apply={apply} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Aplicar.*Cliente/i }));
    expect(confirm).toHaveBeenCalled();
    expect(apply).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: /Aplicar.*Cliente/i }));
    expect(apply).toHaveBeenCalledTimes(1);
    const updater = apply.mock.calls[0][0] as (value: State) => State;
    const next = updater(state);
    expect(next.proj).toBe(state.proj);
    expect(next.obra.cliente).toBe(state.obra.cliente);
    expect(next.obra.morada).toBe(state.obra.morada);
  });
});

describe("diálogo Novo quadro", () => {
  it("valida o nome e chama addBoard com tipo, posição, distância e modelo", async () => {
    const engine = engineFor();
    const apply = vi.fn();
    withToast(<NewBoardDialog engine={engine} state={state} readOnly={false} apply={apply} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Gateway Recebe/i }));
    fireEvent.change(screen.getByLabelText("Nome do quadro"), { target: { value: "Gateway novo" } });
    fireEvent.change(screen.getByLabelText("Modelo do gateway"), { target: { value: "Gateway Alfa" } });
    fireEvent.click(screen.getByRole("button", { name: "Adicionar quadro" }));
    await waitFor(() => expect(apply).toHaveBeenCalledTimes(1));
    const updater = apply.mock.calls[0][0] as (value: State) => State;
    updater(state);
    expect(engine.actions.addBoard).toHaveBeenCalledWith(state, expect.objectContaining({ type: "GW", name: "Gateway novo", L: 5, modelo: "Gateway Alfa", dimNom: true }));

    fireEvent.change(screen.getByLabelText("Nome do quadro"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Adicionar quadro" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Indica o nome do quadro");
    expect(apply).toHaveBeenCalledTimes(1);
  });
});
