import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ToastProvider } from "../../components/Toast";
import type { CabosEngine, BoardView, Result, State } from "./engine";
import QuadrosTab from "./tabs/QuadrosTab";

const state = Object.freeze({ proj: "Estudo Hager", invs: Object.freeze([]) }) as unknown as State;
const result = Object.freeze({ invC: Object.freeze([]), pC: Object.freeze([]) }) as unknown as Result;
const board = {
  node: "QFV-PRINCIPAL",
  role: "QFV",
  isEnd: false,
  inputs: [],
  output: null,
  aparelhagem: [],
  devices: [],
  cabos: [],
  cables: [],
  envolventeMinima: { ref: "FL213B", heightMm: 500, widthMm: 400, depthMm: 200, area: 200000, rows: [], mountingRows: 1, modulesPerRow: 12, cableRows: 1 },
  minimumEnclosure: null,
  notes: [],
  difficulty: 1,
  currentA: 20,
  modules: 4,
  freeCableZoneMm: 120,
  glandWidthMm: 100,
  components: null,
} as unknown as BoardView;

async function renderBoards(front: string | null) {
  const engine = {
    views: {
      boards: vi.fn(() => ({ boards: [board] })),
      boardFront: vi.fn(() => front),
    },
    exports: { bomPdf: vi.fn() },
  } as unknown as CabosEngine;

  render(<ToastProvider><QuadrosTab state={state} result={result} engine={engine} readOnly apply={vi.fn()} /></ToastProvider>);
  // As vistas vêm do motor (assíncrono, no worker).
  await waitFor(() => expect(engine.views.boardFront).toHaveBeenCalled());
  await screen.findByText("QFV-PRINCIPAL");
  return engine;
}

describe("frente Hager nos cartões Quadros", () => {
  it("pede o desenho pelo id do quadro, mostra-o e sanitiza conteúdo SVG ativo", async () => {
    const front = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 80" width="120" height="80" role="img" aria-label="Frente do quadro QFV"><title>Frente Hager</title><g transform="translate(2 2)"><rect width="40" height="20" fill="#fff" onerror="alert(1)"/><text x="4" y="12">Hager QFV</text><script>alert(2)</script><foreignObject><div>perigoso</div></foreignObject></g></svg>`;
    const engine = await renderBoards(front);

    expect(engine.views.boardFront).toHaveBeenCalledOnce();
    expect(engine.views.boardFront).toHaveBeenCalledWith(state, result, "QFV-PRINCIPAL");
    expect(screen.getByRole("img", { name: "Frente do quadro QFV" })).toBeInTheDocument();

    const svg = document.querySelector('[data-testid="sld-svg"]')?.innerHTML ?? "";
    expect(svg).toContain("<title>Frente Hager</title>");
    expect(svg).toContain("<g transform=\"translate(2 2)\">");
    expect(svg).toContain("Hager QFV");
    expect(svg).not.toMatch(/<script|<foreignObject|onerror|perigoso/i);
    expect(JSON.stringify(state)).toBe('{"proj":"Estudo Hager","invs":[]}');
    expect(JSON.stringify(result)).toBe('{"invC":[],"pC":[]}');
  });

  it("mantém o esboço legado quando boardFront devolve null", async () => {
    const engine = await renderBoards(null);

    expect(engine.views.boardFront).toHaveBeenCalledWith(state, result, "QFV-PRINCIPAL");
    expect(screen.queryByRole("img", { name: "Frente do quadro QFV" })).not.toBeInTheDocument();
    expect(screen.getByTestId("board-space-svg")).toBeInTheDocument();
    expect(screen.getByText(/Envolvente mínima/)).toBeInTheDocument();
  });
});
