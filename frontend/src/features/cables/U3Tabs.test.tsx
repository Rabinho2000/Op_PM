import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "../../components/Toast";
import type { CabosEngine, Result, State } from "./engine";
import EquipamentosTab from "./tabs/EquipamentosTab";
import EsquemaUnifilarTab from "./tabs/EsquemaUnifilarTab";
import QuadrosTab from "./tabs/QuadrosTab";

const state = {
  proj: "Estudo",
  invs: [{ id: 1, modelo: "Modelo Alfa", pman: 10, q: "QFV", L: 20, S: "auto" }],
} as unknown as State;
const result = { invC: [{ code: "C1" }], pC: [] } as unknown as Result;

function engineFor(overrides: Record<string, unknown> = {}) {
  const engine = {
    protocol: 1,
    engine_version: "fake",
    summarize: vi.fn(),
    views: {
      sld: vi.fn(() => `<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script><rect onerror="x"/><foreignObject>x</foreignObject><text>Esquema seguro</text></svg>`),
      boards: vi.fn(() => ({ boards: [] })),
      circuitRows: vi.fn(() => []),
    },
    exports: {
      sldSvg: vi.fn(async () => ({ blob: new Blob(["svg"]), filename: "estudo.svg" })),
      sldPdf: vi.fn(async () => ({ blob: new Blob(["pdf"]), filename: "unifilar.pdf" })),
    sldPng: vi.fn(async () => ({ blob: new Blob(["png"]), filename: "estudo.png" })),
      sldDxf: vi.fn(async () => ({ blob: new Blob(["dxf"]), filename: "estudo.dxf" })),
      bomPdf: vi.fn(async () => ({ blob: new Blob(["pdf"]), filename: "orcamento.pdf" })),
    },
    catalogs: {
      inverters: [
        { marca: "Marca Alfa", modelo: "Modelo Alfa", pnom: 10, pmax: 11, iac: 15, iacmax: 16, fases: 3, mppt: 2 },
        { marca: "Marca Beta", modelo: "Modelo Beta", pnom: 20, pmax: 21, iac: 30, iacmax: 31, fases: 3 },
      ],
      gateways: [{ marca: "Marca Gateway", modelo: "Gateway Alfa", gama: "Gama", fases: 3, In: 40, P: 30, ports: 2, portI: 16, base: true }],
      panels: [{ marca: "Marca Painel", modelo: "Painel Alfa", pmax: 500, cel: 144, vmp: 40, imp: 12, voc: 49, isc: 13, kvoc: null, kisc: null, kp: null, ef: 21 }],
    },
    ...overrides,
  } as unknown as CabosEngine;
  return engine;
}

const props = (engine: CabosEngine) => ({ state, result, engine, readOnly: true, apply: vi.fn() });

afterEach(() => {
  vi.restoreAllMocks();
});

describe("separador Esquema unifilar", () => {
  it("sanitiza o SVG antes de o inserir e fornece controlos de zoom e pan", async () => {
    const engine = engineFor();
    const { container } = render(<ToastProvider><EsquemaUnifilarTab {...props(engine)} /></ToastProvider>);
    await waitFor(() => expect(container.querySelector('[data-testid="sld-svg"]')).not.toBeNull());
    const drawing = container.querySelector('[data-testid="sld-svg"]');
    expect(drawing?.innerHTML).toContain("Esquema seguro");
    expect(drawing?.innerHTML).not.toMatch(/script|foreignObject|onerror/i);

    const zoom = container.querySelector('[data-testid="sld-viewport"]');
    expect(zoom).toHaveAttribute("data-zoom", "1");
    fireEvent.click(screen.getByRole("button", { name: "Aumentar zoom" }));
    expect(zoom).toHaveAttribute("data-zoom", "1.1");
    fireEvent.click(screen.getByRole("button", { name: "100%" }));
    expect(zoom).toHaveAttribute("data-zoom", "1");
    fireEvent.mouseDown(zoom!, { clientX: 20, clientY: 20 });
    fireEvent.mouseMove(zoom!, { clientX: 40, clientY: 35 });
    fireEvent.mouseUp(zoom!);
    expect(zoom).toHaveAttribute("data-pan", "20,15");
  });

  it("chama os quatro exports e mostra o resultado", async () => {
    const engine = engineFor();
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:sld");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    render(<ToastProvider><EsquemaUnifilarTab {...props(engine)} /></ToastProvider>);

    fireEvent.click(screen.getByRole("button", { name: "Descarregar PDF" }));
    await waitFor(() => expect(engine.exports.sldPdf).toHaveBeenCalledWith(state, result));
    fireEvent.click(screen.getByRole("button", { name: "Descarregar SVG" }));
    await waitFor(() => expect(engine.exports.sldSvg).toHaveBeenCalledWith(state, result));
    expect((await screen.findAllByText("Ficheiro descarregado.")).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Descarregar PNG" }));
    await waitFor(() => expect(engine.exports.sldPng).toHaveBeenCalledWith(state, result));
    fireEvent.click(screen.getByRole("button", { name: "Descarregar DXF" }));
    await waitFor(() => expect(engine.exports.sldDxf).toHaveBeenCalledWith(state, result));
  });

  it("mostra erro quando uma exportação falha", async () => {
    const engine = engineFor();
    (engine.exports as { sldSvg: unknown }).sldSvg = vi.fn(async () => { throw new Error("falha"); });
    render(<ToastProvider><EsquemaUnifilarTab {...props(engine)} /></ToastProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Descarregar PDF" }));
    await waitFor(() => expect(engine.exports.sldPdf).toHaveBeenCalledWith(state, result));
    fireEvent.click(screen.getByRole("button", { name: "Descarregar SVG" }));
    expect(await screen.findByText("Não foi possível gerar o ficheiro.")).toBeInTheDocument();
  });
});

describe("separador Quadros", () => {
  it("renderiza aparelhagem, envolvente, espaço útil, aviso e total", async () => {
    const engine = engineFor({
      views: {
        sld: vi.fn(),
        circuitRows: vi.fn(),
        boards: vi.fn(() => ({ boards: [{
          node: "QFV",
          role: "QFV",
          isEnd: false,
          inputs: [],
          output: null,
          aparelhagem: [{ nome: "REF-1", txt: "Proteção", dif: "Tipo diferencial" }],
          devices: [],
          cabos: [{ nome: "C1", cabo: "Cabo", D: 20, r: 200, nCond: 4, mat: "Cu", s: 16, n: 1, cap: 35, multi: false }],
          envolventeMinima: { ref: "ENV-1", heightMm: 500, widthMm: 400, depthMm: 200, area: 200000, rows: [], mountingRows: 1, modulesPerRow: 12, cableRows: 1 },
          minimumEnclosure: null,
          notes: [],
          difficulty: 1,
          currentA: 20,
          modules: 4,
          freeCableZoneMm: 300,
          glandWidthMm: 100,
          components: { items: [{ ref: "COMP-1", des: "Componente", q: 2, total: 12 }], sub: 12 },
        }] })),
      },
    });
    render(<ToastProvider><QuadrosTab {...props(engine)} /></ToastProvider>);
    expect(await screen.findByText("QFV")).toBeInTheDocument();
    expect(screen.getByText("REF-1")).toBeInTheDocument();
    expect(screen.getByLabelText(/ENV-1/)).toBeInTheDocument();
    expect(screen.getByTestId("board-space-svg")).toBeInTheDocument();
    expect(screen.getByText("COMP-1")).toBeInTheDocument();
    expect(screen.getByText(/Subtotal do quadro/)).toBeInTheDocument();
    expect(screen.getByText(/Raio de curvatura/)).toBeInTheDocument();
  });

  it("avisa quando o quadro não cabe numa envolvente de parede", async () => {
    const engine = engineFor({ views: {
      sld: vi.fn(), circuitRows: vi.fn(), boards: vi.fn(() => ({ boards: [{
        node: "CLI", role: "CLI", isEnd: true, inputs: [], output: null,
        aparelhagem: [{ nome: "REF-GRANDE", txt: "Armário", dif: "" }], devices: [], cabos: [],
        envolventeMinima: null, minimumEnclosure: null, notes: [], difficulty: 5, currentA: 1,
        modules: 0, freeCableZoneMm: 0, glandWidthMm: 0, components: null,
      }] })),
    }});
    render(<ToastProvider><QuadrosTab {...props(engine)} /></ToastProvider>);
    expect(await screen.findByText("Não cabe num quadro de parede")).toBeInTheDocument();
  });
});

describe("separador Equipamentos", () => {
  it("filtra a base embutida por fabricante/modelo sem edição", () => {
    const engine = engineFor();
    render(<ToastProvider><EquipamentosTab {...props(engine)} /></ToastProvider>);
    expect(screen.getByText("Base embutida — não editável nesta versão")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("searchbox", { name: "Pesquisar equipamento" }), { target: { value: "alfa" } });
    expect(screen.getByText("Modelo Alfa")).toBeInTheDocument();
    expect(screen.queryByText("Modelo Beta")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Gateways" }));
    expect(screen.getByText("Gateway Alfa")).toBeInTheDocument();
  });

  it("mostra estado vazio quando o catálogo selecionado não tem registos", () => {
    const engine = engineFor({ catalogs: { inverters: [], gateways: [], panels: [] } });
    render(<ToastProvider><EquipamentosTab {...props(engine)} /></ToastProvider>);
    expect(screen.getByTestId("empty-state")).toBeInTheDocument();
  });
});
