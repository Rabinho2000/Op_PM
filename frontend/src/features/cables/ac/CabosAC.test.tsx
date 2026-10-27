import * as React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { CabosEngine, CircuitRow, Result, State } from "../engine";
import CabosACTab from "../tabs/CabosACTab";

const initialState: State = {
  proj: "Estudo sintético",
  loc: "Porto",
  tair: 25,
  tsoil: 20,
  rsolo: 1.5,
  isol: "XLPE",
  mat: "auto",
  alThr: 15,
  alPmin: 30,
  limT: 3,
  lim: 5,
  folga: true,
  cos: 1,
  descABB: 0,
  descHager: 0,
  sc: { on: false, fonte: "", sn: 100, ucc: 4, scc: 500, icc: 10, L0: 0, s0: 0, m0: "", n0: 0 },
  dc: { tmin: -10, tcell: 25, lim: 1.5, ifuse: 0, f: 1, sel: 0, arr: [] },
  invs: [{ id: 1, modelo: "INV-A", pman: 20, q: "QFV", L: 20, S: "auto", cos: null }],
  rInv: { ref: "13", cons: "mono", disp: "trevo", trays: 1, sol: false },
  percs: [{ id: 2, orig: "QFV", dest: "Q. Entrada", L: 10, S: "auto", ref: "13", cons: "mono", disp: "trevo", trays: 1, sol: false }],
  gws: [{ id: 3, nome: "Gateway 1", modelo: "GW-A", fases: 3, In: 63, dimNom: true }],
  obra: { cliente: "", morada: "", desenho: "", estado: "rascunho", rev: "A", aprov: null },
  icu: { modo: "", icc: 10, sn: 100 },
};

const result = { invC: [], pC: [], costTot: 0, termTot: 0, costEst: false, Ptot: 0, IbTot: 0, ikSrc: 0, icuOn: false, central: [], brkTot: 0 } as Result;

const okRow: CircuitRow = {
  code: "C1",
  kind: "inv",
  designation: "1 x 16 Cu",
  origin: "INV-A",
  destination: "QFV",
  origem: "INV-A",
  destino: "QFV",
  lengthM: 20,
  L: 20,
  calculationLengthM: 20,
  sectionMm2: 16,
  section: "1x16 Cu",
  cable: { material: "Cu", conductors: 1, sectionMm2: 16, constitution: "mono", phase: "1 x 16 Cu", neutral: "1 x 16 Cu", earth: "1 x 16 Cu", text: "1 x 16 Cu" },
  Iz: 48,
  In: 32,
  I2: 46,
  voltageDropV: 3.45,
  voltageDropPct: 1.5,
  deltaU: 1.5,
  breaker: { name: "Disjuntor 32 A", ref: "D32", ratingA: 32, poles: 4, differential: { name: "Diferencial 30 mA", refs: ["DR1"] } },
  disjuntor: { name: "Disjuntor 32 A", ref: "D32", ratingA: 32, poles: 4, differential: { name: "Diferencial 30 mA", refs: ["DR1"] } },
  route: null,
  verdict: "ok",
  veredicto: "ok",
  message: "OK",
  reason: "OK",
};

const reviewRow: CircuitRow = {
  ...okRow,
  code: "C2",
  kind: "perc",
  designation: "2 x 70 Al",
  origin: "QFV",
  destination: "Q. Entrada",
  origem: "QFV",
  destino: "Q. Entrada",
  sectionMm2: 70,
  section: "2x70 Al",
  cable: { material: "Al", conductors: 2, sectionMm2: 70, constitution: "mono", phase: "2 x 70 Al", neutral: "2 x 70 Al", earth: "1 x 35 Cu", text: "2 x 70 Al" },
  verdict: "a rever",
  veredicto: "a rever",
  message: "ΔU troço: secção insuficiente",
  reason: "ΔU troço",
  breaker: { name: "Disjuntor 125 A", ref: "D125", ratingA: 125, poles: 4, differential: null },
  disjuntor: { name: "Disjuntor 125 A", ref: "D125", ratingA: 125, poles: 4, differential: null },
  Iz: 100,
  In: 125,
  I2: 160,
  voltageDropV: 9.2,
  voltageDropPct: 4,
  deltaU: 4,
};

function makeEngine() {
  const actions = {
    addInverter: vi.fn((state: State) => ({ ...state, invs: [...state.invs, { ...state.invs[0], id: 4 }] })),
    removeInverter: vi.fn((state: State, args: { id: number }) => ({ ...state, invs: state.invs.filter((item) => item.id !== args.id) })),
    duplicateInverter: vi.fn((state: State) => ({ ...state, invs: [...state.invs, { ...state.invs[0], id: 5, S: "auto" }] })),
    setInverterModel: vi.fn((state: State, args: { id: number; modelo: string }) => ({ ...state, invs: state.invs.map((item) => item.id === args.id ? { ...item, modelo: args.modelo } : item) })),
    setInverterPman: vi.fn((state: State) => state),
    setInverterBoard: vi.fn((state: State) => state),
    setInverterLength: vi.fn((state: State) => state),
    setInverterSection: vi.fn((state: State) => state),
    setInverterField: vi.fn((state: State) => state),
    setInverterRoute: vi.fn((state: State) => state),
    addPerc: vi.fn((state: State) => state),
    removePerc: vi.fn((state: State) => state),
    setPercField: vi.fn((state: State) => state),
    setPercOrigin: vi.fn((state: State) => state),
    setPercDestination: vi.fn((state: State) => state),
    setPercSection: vi.fn((state: State) => state),
    setPercRoute: vi.fn((state: State) => state),
    addGateway: vi.fn((state: State) => state),
    removeGateway: vi.fn((state: State) => state),
    renameGateway: vi.fn((state: State) => state),
    configureGateway: vi.fn((state: State) => state),
    setGatewayField: vi.fn((state: State) => state),
    updateGateway: vi.fn((state: State) => state),
    setWorkData: vi.fn((state: State, args: { field?: string; value?: unknown }) => {
      const changes = args.field ? { [args.field]: args.value } : args;
      const { proj, ...obraChanges } = changes as { proj?: string; [key: string]: unknown };
      return { ...state, ...(proj === undefined ? {} : { proj }), obra: { ...state.obra, ...obraChanges } };
    }),
    setCriteria: vi.fn((state: State, args: { field?: string; value?: unknown }) => {
      const changes = args.field ? { [args.field]: args.value } : args;
      return { ...state, ...changes } as State;
    }),
  };
  return {
    protocol: 1 as const,
    engine_version: "fake",
    newState: vi.fn(() => structuredClone(initialState)),
    templates: [],
    migrate: vi.fn(() => structuredClone(initialState)),
    solve: vi.fn((state: State) => ({ state, result })),
    summarize: vi.fn(() => ({
      inverters: 1,
      powerKW: 20,
      currentA: 30,
      connectionBreakerA: 125,
      connectionBreaker: { ratingA: 125, code: "C2" },
      maxVoltageDropPct: 4,
      maxVoltageDrop: 9.2,
      shortCircuit: { verified: false, currentKA: null },
      cables: 100,
      terminals: 10,
      cablesAndTerminals: 110,
      protectionCost: 50,
      reviewCount: 1,
      estimated: false,
    })),
    catalogs: {
      inverters: [{ marca: "Marca", modelo: "INV-A", pnom: 20, pmax: 22, iac: 29, iacmax: 30, fases: 3 }, { marca: "Marca", modelo: "INV-B", pnom: 30, pmax: 33, iac: 40, iacmax: 42, fases: 3 }],
      gateways: [{ marca: "Marca", modelo: "GW-A", gama: "Gama", fases: 3, In: 63, P: 50, ports: 2, portI: 40, base: true }],
      regions: [{ id: "Porto", label: "Porto", tair: 25, tsoil: 20, tmin: -3 }],
      installModes: [{ id: "13", label: "Ref. 13", description: "Cabo em esteira", method: "EF", group: "fav", imageId: "13" }],
      materials: [{ id: "Cu", label: "Cobre" }],
      insulations: [{ id: "XLPE", label: "XLPE" }],
      constitutions: [{ id: "mono", label: "Monocondutores" }, { id: "multi", label: "Multicondutor" }],
      dispositions: [{ id: "trevo", label: "Em trevo" }],
      boardTypes: {},
      soilResistivities: [[1.5, 0.86, "Terreno muito seco"]],
      installModeImage: vi.fn(() => null),
    },
    installModeImage: vi.fn(() => null),
    actions,
    views: { sld: vi.fn(() => ""), boards: vi.fn(() => ({ boards: [] })), circuitRows: vi.fn(() => [okRow, reviewRow]) },
    persistedResult: vi.fn(),
    exports: {} as CabosEngine["exports"],
    compare: { variants: vi.fn(() => []), apply: vi.fn() },
  } as unknown as CabosEngine;
}

function Harness({ engine, readOnly = false, state = initialState }: { engine: CabosEngine; readOnly?: boolean; state?: State }) {
  const [current, setCurrent] = React.useState(state);
  return (
    <CabosACTab
      state={current}
      result={result}
      engine={engine}
      readOnly={readOnly}
      apply={(updater) => setCurrent((previous) => updater(previous))}
    />
  );
}

describe("separador Cabos AC", () => {
  it("mostra linhas de circuito, cabo, proteções e veredicto acessível", () => {
    const engine = makeEngine();
    render(<Harness engine={engine} />);
    expect(screen.getByText("C1")).toBeInTheDocument();
    expect(screen.getByText("C2")).toBeInTheDocument();
    expect(screen.getByText("a rever")).toBeInTheDocument();
    expect(screen.getByText("ΔU troço: secção insuficiente")).toBeInTheDocument();
    expect(screen.getByText(/Diferencial 30 mA/)).toBeInTheDocument();
    expect(screen.getAllByText(/2 x 70 Al/).length).toBeGreaterThan(0);
    expect(screen.getByText("1 circuitos a rever")).toBeInTheDocument();
  });

  it("adiciona, duplica e remove inversores através das actions", () => {
    const engine = makeEngine();
    render(<Harness engine={engine} />);
    fireEvent.click(screen.getByRole("button", { name: "Adicionar inversor" }));
    expect(engine.actions.addInverter).toHaveBeenCalled();
    expect(screen.getAllByRole("row", { name: /INV-A/ }).length).toBeGreaterThan(0);
    const duplicate = screen.getByRole("button", { name: /Duplicar inversor 1/ });
    fireEvent.click(duplicate);
    expect(engine.actions.duplicateInverter).toHaveBeenCalledWith(expect.anything(), { id: 1 });
    fireEvent.click(screen.getByRole("button", { name: /Remover inversor 1/ }));
    expect(engine.actions.removeInverter).toHaveBeenCalledWith(expect.anything(), { id: 1 });
  });

  it("abre o seletor pesquisável e rejeita valores numéricos inválidos", () => {
    const engine = makeEngine();
    render(<Harness engine={engine} />);
    fireEvent.click(screen.getByRole("button", { name: /Escolher modelo.*INV-A/ }));
    expect(screen.getByRole("dialog", { name: /Escolher modelo/ })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Pesquisar modelo de inversor" }), { target: { value: "INV-B" } });
    fireEvent.click(screen.getByRole("button", { name: /INV-B/ }));
    expect(engine.actions.setInverterModel).toHaveBeenCalledWith(expect.anything(), { id: 1, field: "modelo", value: "INV-B" });
    const before = (engine.actions.setInverterLength as unknown as { mock: { calls: unknown[][] } }).mock.calls.length;
    fireEvent.change(screen.getByLabelText("Distância do inversor 1 (m)"), { target: { value: "-2" } });
    expect((engine.actions.setInverterLength as unknown as { mock: { calls: unknown[][] } }).mock.calls).toHaveLength(before);
    expect(screen.getByText(/valor entre 0 e 10000/)).toBeInTheDocument();
  });

  it("desativa os controlos de edição em modo só leitura", () => {
    const engine = makeEngine();
    render(<Harness engine={engine} readOnly state={{ ...initialState, invs: [], percs: [], gws: [] }} />);
    expect(screen.queryByRole("button", { name: "Adicionar inversor" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Adicionar percurso" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Adicionar gateway" })).not.toBeInTheDocument();
    expect(screen.getByText("Sem inversores")).toBeInTheDocument();
  });

  it("liga gateways às actions e mostra estados vazios", () => {
    const engine = makeEngine();
    render(<Harness engine={engine} />);
    fireEvent.click(screen.getByRole("button", { name: "Adicionar gateway" }));
    expect(engine.actions.addGateway).toHaveBeenCalled();
    const gatewayRow = screen.getByRole("row", { name: /Gateway 1/ });
    fireEvent.change(within(gatewayRow).getByLabelText("Nome do gateway"), { target: { value: "Gateway Principal" } });
    expect(engine.actions.setGatewayField).toHaveBeenCalledWith(expect.anything(), { id: 3, field: "nome", value: "Gateway Principal" });
    fireEvent.click(within(gatewayRow).getByRole("button", { name: /Remover gateway/ }));
    expect(engine.actions.removeGateway).toHaveBeenCalledWith(expect.anything(), { id: 3 });
  });

  it("edita obra e critérios apenas através das actions reais e não expõe lifecycle paralelo", () => {
    const engine = makeEngine();
    render(<Harness engine={engine} />);

    expect(screen.queryByLabelText("Estado da obra")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Nome do projeto"), { target: { value: "Projeto editado" } });
    fireEvent.change(screen.getByLabelText("Cliente / dono de obra"), { target: { value: "Cliente editado" } });
    fireEvent.change(screen.getByLabelText("Região"), { target: { value: "Porto" } });
    fireEvent.change(screen.getByLabelText("cos φ"), { target: { value: "0.95" } });

    expect(engine.actions.setWorkData).toHaveBeenCalledWith(expect.anything(), { field: "proj", value: "Projeto editado" });
    expect(engine.actions.setWorkData).toHaveBeenCalledWith(expect.anything(), { field: "cliente", value: "Cliente editado" });
    expect(engine.actions.setCriteria).toHaveBeenCalledWith(expect.anything(), { field: "loc", value: "Porto" });
    expect(engine.actions.setCriteria).toHaveBeenCalledWith(expect.anything(), { field: "cos", value: 0.95 });
  });
});
