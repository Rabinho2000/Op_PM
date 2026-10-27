import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { CableDesign } from "../../api/cableDesigns";
import type { CabosEngine, Result, State } from "./engine";
import { buildCableSavePayload, buildCablePresentationState, canonicalJson, initializeCableStudy, studyReducer, useCableStudy } from "./useCableStudy";
import { makeProject } from "../../test/fixtures";

const baseState = {
  proj: "Modelo",
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
  invs: [],
  rInv: { ref: "", cons: "", disp: "", trays: 1, sol: false },
  percs: [],
  gws: [],
  obra: { cliente: "", morada: "", desenho: "", estado: "rascunho", rev: "A", aprov: null },
  icu: { modo: "", icc: 10, sn: 100 },
} as unknown as State;

const result = {} as Result;
const fakeEngine = {
  protocol: 1,
  engine_version: "cabos-fake@7",
  newState: vi.fn(() => structuredClone(baseState)),
  templates: [],
  migrate: vi.fn((raw: unknown) => raw as State),
  solve: vi.fn((state: State) => ({ state: { ...state, obra: { ...state.obra } }, result })),
  summarize: vi.fn(),
  persistedResult: vi.fn((state: State, solved: Result) => ({ format: 1, engine_version: "cabos-fake@7", circuits: [{ code: state.proj, name: "C1", review: false }], totals: { circuits: 1, review: 0, inverters: 0 }, solved })),
  catalogs: { regions: [], materials: [], insulations: [], soilResistivities: [] },
  installModeImage: vi.fn(),
  actions: {
    setWorkData: vi.fn((state: State, args: Record<string, unknown>) => {
      const changes = args.field ? { [String(args.field)]: args.value } : args;
      const { proj, ...obra } = changes;
      return { ...state, ...(typeof proj === "string" ? { proj } : {}), obra: { ...state.obra, ...obra } };
    }),
  },
  views: { sld: vi.fn(), boards: vi.fn(), circuitRows: vi.fn() },
  exports: {},
  compare: { variants: vi.fn(), apply: vi.fn() },
} as unknown as CabosEngine;

const design = (input: Record<string, unknown> = {}): CableDesign => ({
  id: "design-1",
  project_id: "project-1",
  title: "Estudo",
  status: "rascunho",
  current_revision: "A",
  version: 4,
  updated_at: "2026-10-19T09:00:00Z",
  unresolved_circuits: 0,
  is_active: true,
  created_by_person_id: "person-1",
  created_at: "2026-10-19T09:00:00Z",
  revision: {
    id: "revision-1",
    design_id: "design-1",
    rev: "A",
    input_json: { format: 1, ...input },
    result_json: { format: 1 },
    engine_version: "cabos-fake@7",
    content_sha256: "hash",
    unresolved_circuits: 0,
    status: "rascunho",
    approved_by_person_id: null,
    approved_at: null,
    created_by_person_id: "person-1",
    created_at: "2026-10-19T09:00:00Z",
    updated_at: "2026-10-19T09:00:00Z",
  },
});

describe("store do estudo de cabos", () => {
  it("pré-preenche um estudo novo e resolve imediatamente", async () => {
    const store = await initializeCableStudy(fakeEngine, design(), makeProject({ name: "Projeto Sintético", client_name: "Cliente Sintético", address: "Morada Sintética" }));
    expect(fakeEngine.newState).toHaveBeenCalled();
    expect(store.state.proj).toBe("Projeto Sintético");
    expect(store.state.obra.cliente).toBe("Cliente Sintético");
    expect(store.state.obra.morada).toBe("Morada Sintética");
    expect(fakeEngine.solve).toHaveBeenCalledTimes(1);
    expect(store.dirty).toBe(false);
  });

  it("migra uma revisão existente sem pré-preencher por cima", async () => {
    const existing = { ...baseState, proj: "Estado guardado", obra: { ...baseState.obra, cliente: "Cliente guardado" } };
    const store = await initializeCableStudy(fakeEngine, design({ state: existing }), makeProject({ name: "Outro projeto" }));
    expect(fakeEngine.migrate).toHaveBeenCalledWith(existing);
    expect(store.state.proj).toBe("Estado guardado");
    expect(store.state.obra.cliente).toBe("Cliente guardado");
  });

  it("deriva a revisão e aprovação oficiais para views sem sujar o store", async () => {
    const store = await initializeCableStudy(fakeEngine, design(), null);
    const approvedDesign = {
      ...design(),
      current_revision: "B",
      revision: {
        ...design().revision,
        rev: "B",
        approved_by_person_id: "person-2",
        approved_at: "2026-10-19T10:00:00Z",
      },
    };

    const presented = buildCablePresentationState(fakeEngine, store.state, approvedDesign, new Map([["person-2", "Pessoa Dois"]]));

    expect(presented).not.toBe(store.state);
    expect(presented.obra.rev).toBe("B");
    expect(presented.obra.aprov).toEqual({ id: "person-2", nome: "Pessoa Dois", em: "2026-10-19T10:00:00Z" });
    expect(store.state.obra.rev).toBe("A");
    expect(store.state.obra.aprov).toBeNull();
    expect(store.dirty).toBe(false);
  });

  it("não inventa aprovação se a pessoa oficial ainda não tiver nome", async () => {
    const store = await initializeCableStudy(fakeEngine, design(), null);
    const approvedDesign = {
      ...design(),
      current_revision: "B",
      revision: { ...design().revision, approved_by_person_id: "person-2", approved_at: "2026-10-19T10:00:00Z" },
    };

    expect(buildCablePresentationState(fakeEngine, store.state, approvedDesign, new Map()).obra.aprov).toBeNull();
  });

  it("produz o corpo de gravação sem guardar o resultado integral", async () => {
    const store = await initializeCableStudy(fakeEngine, design(), null);
    const payload = buildCableSavePayload(fakeEngine, store);
    expect(payload.input).toEqual({ format: 1, state: store.state });
    expect(payload.result).toMatchObject({ format: 1, engine_version: "cabos-fake@7" });
    expect(payload.engine_version).toBe("cabos-fake@7");
    expect(fakeEngine.persistedResult).toHaveBeenCalledWith(store.state, store.result);
  });

  it("usa hash canónico e marca o estado limpo após guardar", async () => {
    const store = await initializeCableStudy(fakeEngine, design(), null);
    const changed = { ...store, state: { ...store.state, proj: "B" } };
    const reduced = studyReducer(store, { type: "replace", state: changed.state, result: changed.result, dirty: true });
    expect(canonicalJson({ b: 1, a: 2 })).toBe(canonicalJson({ a: 2, b: 1 }));
    expect(studyReducer(reduced, { type: "markSaved", state: reduced.state, hash: "hash" })).toEqual({ ...reduced, savedHash: "hash", dirty: false });
  });

  it("aplica uma mutação, resolve e permite markSaved", async () => {
    const view = renderHook(() => useCableStudy(fakeEngine, design(), null));
    await waitFor(() => expect(view.result.current.store).not.toBeNull());
    view.result.current.apply((current) => ({ ...current, proj: "Alterado" }));
    await waitFor(() => expect(view.result.current.dirty).toBe(true));
    expect(view.result.current.state?.proj).toBe("Alterado");
    await view.result.current.markSaved();
    await waitFor(() => expect(view.result.current.dirty).toBe(false));
  });
});
