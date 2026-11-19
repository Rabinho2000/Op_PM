import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { CabosEngine, CircuitRow, ManualCableCircuitOptions, Result, State } from "../engine";
import type { CableStudyUpdater } from "../useCableStudy";
import ResultsTable from "./ResultsTable";

const state = { proj: "Estudo" } as unknown as State;
const result = {
  invC: [{ code: "C1" }],
  pC: [{ code: "C2" }],
} as unknown as Result;
const rows = [
  { code: "C1", kind: "inv", designation: "Inversor 1", origin: "INV-1", destination: "QFV", lengthM: 20, calculationLengthM: 20, verdict: "ok", message: "OK", cable: null },
  { code: "C2", kind: "perc", designation: "Percurso 2", origin: "QFV", destination: "Gateway 1", lengthM: 10, calculationLengthM: 10, verdict: "ok", message: "OK", cable: null },
] as unknown as CircuitRow[];

const inverterValue = "1x16|Cu|mono";
const gatewayValue = "2x70|Al|mono";
const options: ManualCableCircuitOptions[] = [
  {
    kind: "inv",
    id: 1,
    code: "C1",
    selected: "auto",
    options: [{ value: inverterValue, conductorsPerPhase: 1, sectionMm2: 16, material: "Cu", constitution: "mono", meetsRequirements: true, label: "1 × 16 mm² Cu · monocondutores" }],
  },
  {
    kind: "perc",
    id: "42_3",
    code: "C2",
    selected: gatewayValue,
    options: [{ value: gatewayValue, conductorsPerPhase: 2, sectionMm2: 70, material: "Al", constitution: "mono", meetsRequirements: true, label: "2 × 70 mm² Al · monocondutores" }],
  },
];

async function renderResults(readOnly = false) {
  const setManualCable = vi.fn((current: State) => current);
  const engine = {
    actions: { setManualCable },
    views: { manualCableOptions: vi.fn(() => ({ circuits: options })) },
  } as unknown as CabosEngine;
  const apply = vi.fn((updater: CableStudyUpdater) => {
    updater(state);
  });
  render(<ResultsTable state={state} result={result} rows={rows} engine={engine} readOnly={readOnly} apply={apply} />);
  // As opções vêm do motor (assíncrono, no worker): esperar que apareçam.
  await screen.findAllByRole("combobox");
  return { engine, apply };
}

describe("controlos de seleção manual de cabos", () => {
  it("aplica ao inversor a opção devolvida pelo motor", async () => {
    const { engine, apply } = await renderResults();
    const control = screen.getByRole("combobox", { name: /circuito C1.*automático/i });

    fireEvent.change(control, { target: { value: inverterValue } });

    expect(apply).toHaveBeenCalledTimes(1);
    expect(engine.actions.setManualCable).toHaveBeenCalledWith(state, { kind: "inv", id: 1, value: inverterValue });
  });

  it("preserva o id do subpercurso dividido por gateway recebido do motor", async () => {
    const { engine } = await renderResults();

    fireEvent.change(screen.getByRole("combobox", { name: /circuito C2/i }), { target: { value: "auto" } });

    expect(engine.actions.setManualCable).toHaveBeenCalledWith(state, { kind: "perc", id: "42_3", value: "auto" });
  });

  it("permite repor a seleção automática", async () => {
    const { engine } = await renderResults();

    fireEvent.change(screen.getByRole("combobox", { name: /circuito C1/i }), { target: { value: "auto" } });

    expect(engine.actions.setManualCable).toHaveBeenCalledWith(state, { kind: "inv", id: 1, value: "auto" });
  });

  it("mantém o controlo desativado em modo de leitura e não aplica alterações", async () => {
    const { engine, apply } = await renderResults(true);
    const control = screen.getByRole("combobox", { name: /circuito C1/i });

    expect(control).toBeDisabled();
    fireEvent.change(control, { target: { value: inverterValue } });

    expect(apply).not.toHaveBeenCalled();
    expect(engine.actions.setManualCable).not.toHaveBeenCalled();
  });
});
