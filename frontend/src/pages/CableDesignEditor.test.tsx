import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import type { CableDesign, CableDesignHistoryEntry, CableDesignRevision } from "../api/cableDesigns";
import type { CabosEngine, Result, State } from "../features/cables/engine";
import CableDesignEditor from "./CableDesignEditor";
import { makeMe, makeProject } from "../test/fixtures";
import { renderWithProviders } from "../test/render";

const api = vi.hoisted(() => ({
  getCableDesign: vi.fn(),
  getProject: vi.fn(),
  listPeople: vi.fn(),
  saveCableRevision: vi.fn(),
  approveCableDesign: vi.fn(),
  newCableRevision: vi.fn(),
  deactivateCableDesign: vi.fn(),
  listCableRevisions: vi.fn(),
  listCableHistory: vi.fn(),
}));

const engineMock = vi.hoisted(() => ({ useCableEngine: vi.fn() }));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, getProject: api.getProject, listPeople: api.listPeople };
});

vi.mock("../api/cableDesigns", async () => {
  const actual = await vi.importActual<typeof import("../api/cableDesigns")>("../api/cableDesigns");
  return { ...actual, ...api };
});

vi.mock("../features/cables/useCableEngine", () => engineMock);

const result = {} as Result;
const state: State = {
  proj: "",
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
};

const fakeEngine = {
  protocol: 1,
  engine_version: "cabos-fake@1",
  newState: vi.fn(() => structuredClone(state)),
  templates: [],
  migrate: vi.fn((raw: unknown) => raw as State),
  solve: vi.fn((input: State) => ({ state: { ...input, obra: { ...input.obra } }, result })),
  summarize: vi.fn(() => ({
    inverters: 0,
    powerKW: 0,
    currentA: 0,
    connectionBreakerA: null,
    connectionBreaker: null,
    maxVoltageDropPct: 0,
    maxVoltageDrop: 0,
    shortCircuit: { verified: false, currentKA: null },
    cables: 0,
    terminals: 0,
    cablesAndTerminals: 0,
    protectionCost: 0,
    reviewCount: 0,
    estimated: false,
  })),
  persistedResult: vi.fn(() => ({ format: 1, engine_version: "cabos-fake@1", circuits: [], totals: { circuits: 0, review: 0, inverters: 0 } })),
  catalogs: { regions: [{ id: "Porto", label: "Porto", tair: 25, tsoil: 20, tmin: -10 }], materials: [], insulations: [], soilResistivities: [] },
  installModeImage: vi.fn(),
  actions: {
    setWorkData: vi.fn((current: State, args: Record<string, unknown>) => {
      const changes = typeof args.field === "string" ? { [args.field]: args.value } : args;
      const { proj, ...obra } = changes;
      return { ...current, ...(typeof proj === "string" ? { proj } : {}), obra: { ...current.obra, ...obra } };
    }),
  },
  views: { sld: vi.fn(), boards: vi.fn(), circuitRows: vi.fn(() => []) },
  exports: {
    reportPdf: vi.fn(async () => ({ blob: new Blob(["pdf"]), filename: "relatorio.pdf" })),
    reportDocx: vi.fn(async () => ({ blob: new Blob(["docx"]), filename: "relatorio.docx" })),
    bomPdf: vi.fn(async () => ({ blob: new Blob(["bom"]), filename: "orcamento.pdf" })),
    sldSvg: vi.fn(async () => ({ blob: new Blob(["svg"]), filename: "unifilar.svg" })),
    sldPng: vi.fn(async () => ({ blob: new Blob(["png"]), filename: "unifilar.png" })),
    sldDxf: vi.fn(async () => ({ blob: new Blob(["dxf"]), filename: "unifilar.dxf" })),
    copyTable: vi.fn(() => "Circuito\tCabo"),
  },
  compare: { variants: vi.fn(), apply: vi.fn() },
} as unknown as CabosEngine;

const revision: CableDesignRevision = {
  id: "revision-1",
  design_id: "design-1",
  rev: "A",
  input_json: { format: 1 },
  result_json: { format: 1, circuits: [], totals: { circuits: 0, review: 0, inverters: 0 } },
  engine_version: "cabos-fake@1",
  content_sha256: "abcdef1234567890",
  unresolved_circuits: 0,
  status: "rascunho",
  approved_by_person_id: null,
  approved_at: null,
  created_by_person_id: "person-1",
  created_at: "2026-10-19T09:00:00Z",
  updated_at: "2026-10-19T09:00:00Z",
};

const history: CableDesignHistoryEntry = {
  id: "history-1",
  design_id: "design-1",
  action: "created",
  actor_person_id: "person-1",
  rev: "A",
  old_value: null,
  new_value: { version: 1 },
  created_at: "2026-10-19T09:00:00Z",
};

let currentDesign: CableDesign;

beforeEach(() => {
  currentDesign = {
    id: "design-1",
    project_id: "project-1",
    title: "Estudo A",
    status: "rascunho",
    current_revision: "A",
    version: 1,
    updated_at: "2026-10-19T09:00:00Z",
    unresolved_circuits: 0,
    is_active: true,
    created_by_person_id: "person-1",
    created_at: "2026-10-19T09:00:00Z",
    revision,
  };
  Object.values(api).forEach((fn) => fn.mockReset());
  Object.values(fakeEngine.exports).forEach((fn) => (fn as ReturnType<typeof vi.fn>).mockClear());
  api.getCableDesign.mockImplementation(() => Promise.resolve(currentDesign));
  api.getProject.mockResolvedValue(makeProject({ id: "project-1", name: "Projeto A", client_name: "Cliente A", address: "Morada A" }));
  api.listPeople.mockResolvedValue([{ id: "person-1", display_name: "Pessoa Um", email: "person@example.com", is_active: true }]);
  api.saveCableRevision.mockResolvedValue({ ...currentDesign, version: 2 });
  api.approveCableDesign.mockResolvedValue({ ...currentDesign, status: "aprovado", revision: { ...revision, status: "aprovada" } });
  api.newCableRevision.mockResolvedValue({ ...currentDesign, status: "rascunho", current_revision: "B", version: 3, revision: { ...revision, id: "revision-2", rev: "B", status: "rascunho" } });
  api.deactivateCableDesign.mockResolvedValue(undefined);
  api.listCableRevisions.mockResolvedValue([revision]);
  api.listCableHistory.mockResolvedValue([history]);
  engineMock.useCableEngine.mockImplementation((enabled: boolean) => enabled
    ? { engine: fakeEngine, status: "ready", error: null, retry: vi.fn() }
    : { engine: null, status: "idle", error: null, retry: vi.fn() });
});

async function renderEditor(
  permissions = ["cable_design.view", "cable_design.edit", "cable_design.view_costs"],
  waitForNative = true,
) {
  renderWithProviders(<CableDesignEditor />, {
    me: makeMe({ permissions }),
    route: "/projects/project-1/cables/design-1",
    path: "/projects/:projectId/cables/:designId",
  });
  if (waitForNative) await screen.findByRole("tab", { name: "Cabos AC" });
}

describe("CableDesignEditor nativo", () => {
  it("carrega sem iframe e pré-preenche os dados do projeto", async () => {
    await renderEditor();
    expect(document.querySelector("iframe")).toBeNull();
    expect(screen.queryByRole("document")).not.toBeInTheDocument();
    expect(screen.queryByTitle("Ferramenta de dimensionamento de cabos")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Nome do projeto")).toHaveValue("Projeto A");
    expect(screen.getByLabelText("Cliente / dono de obra")).toHaveValue("Cliente A");
    expect(screen.getByLabelText("Morada da instalação")).toHaveValue("Morada A");
    expect(fakeEngine.newState).toHaveBeenCalled();
  });

  it("passa revisão e aprovação oficiais às views e exportações sem marcar o estudo dirty", async () => {
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    currentDesign = {
      ...currentDesign,
      status: "aprovado",
      current_revision: "B",
      revision: {
        ...revision,
        rev: "B",
        status: "aprovada",
        approved_by_person_id: "person-1",
        approved_at: "2026-10-19T10:00:00Z",
      },
    };
    api.getCableDesign.mockResolvedValue(currentDesign);
    await renderEditor();

    await waitFor(() => expect(fakeEngine.views.circuitRows).toHaveBeenCalled());
    const viewState = (fakeEngine.views.circuitRows as ReturnType<typeof vi.fn>).mock.calls[(fakeEngine.views.circuitRows as ReturnType<typeof vi.fn>).mock.calls.length - 1]?.[0] as State;
    expect(viewState.obra.rev).toBe("B");
    expect(viewState.obra.aprov).toEqual({ id: "person-1", nome: "Pessoa Um", em: "2026-10-19T10:00:00Z" });
    expect(screen.queryByText("Alterações por guardar")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "⋯ Mais" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Relatório de cálculo (PDF)" }));
    await waitFor(() => expect(fakeEngine.exports.reportPdf).toHaveBeenCalled());
    const exportState = (fakeEngine.exports.reportPdf as ReturnType<typeof vi.fn>).mock.calls[(fakeEngine.exports.reportPdf as ReturnType<typeof vi.fn>).mock.calls.length - 1]?.[0] as State;
    expect(exportState.obra.rev).toBe("B");
    expect(exportState.obra.aprov).toEqual(viewState.obra.aprov);
  });

  it("marca dirty e guarda com expected_version e resultado persistido", async () => {
    await renderEditor();
    const projectName = screen.getByLabelText("Nome do projeto");
    fireEvent.change(projectName, { target: { value: "Projeto alterado" } });
    await waitFor(() => expect(screen.getByText("Alterações por guardar")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Guardar" })).not.toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(api.saveCableRevision).toHaveBeenCalled());
    expect(api.saveCableRevision).toHaveBeenCalledWith("design-1", expect.objectContaining({
      expected_version: 1,
      input: expect.objectContaining({ format: 1, state: expect.objectContaining({ proj: "Projeto alterado" }) }),
      result: { format: 1, engine_version: "cabos-fake@1", circuits: [], totals: { circuits: 0, review: 0, inverters: 0 } },
      engine_version: "cabos-fake@1",
    }));
    expect(fakeEngine.persistedResult).toHaveBeenCalled();
  });

  it("bloqueia todos os campos e ações de mutação durante um PUT pendente", async () => {
    let resolveSave: ((value: CableDesign) => void) | undefined;
    api.saveCableRevision.mockImplementation(() => new Promise<CableDesign>((resolve) => {
      resolveSave = resolve;
    }));
    await renderEditor();

    fireEvent.change(screen.getByLabelText("Nome do projeto"), { target: { value: "Projeto durante save" } });
    await waitFor(() => expect(screen.getByText("Alterações por guardar")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(api.saveCableRevision).toHaveBeenCalled());

    expect(screen.getByLabelText("Nome do projeto")).toBeDisabled();
    expect(screen.getByLabelText("Cliente / dono de obra")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Comparar alternativas" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Modelos" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Aprovar" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Nome do projeto"), { target: { value: "Alteração tardia" } });
    expect(screen.getByLabelText("Nome do projeto")).toHaveValue("Projeto durante save");

    resolveSave?.({ ...currentDesign, version: 2 });
    await waitFor(() => expect(screen.getByLabelText("Nome do projeto")).not.toBeDisabled());
  });

  it("aprova depois de guardar e mostra a mensagem do servidor num 409", async () => {
    api.approveCableDesign.mockRejectedValue(new ApiError(409, "Existem circuitos a rever."));
    await renderEditor();
    fireEvent.click(screen.getByRole("button", { name: "Aprovar" }));
    expect(await screen.findByText("Existem circuitos a rever.")).toBeInTheDocument();
    expect(api.saveCableRevision).toHaveBeenCalledWith("design-1", expect.objectContaining({ expected_version: 1 }));
  });

  it("cria uma nova revisão a partir de uma revisão aprovada", async () => {
    currentDesign = { ...currentDesign, status: "aprovado", revision: { ...revision, status: "aprovada" } };
    api.getCableDesign.mockResolvedValue(currentDesign);
    await renderEditor();
    fireEvent.click(screen.getByRole("button", { name: "Nova revisão" }));
    await waitFor(() => expect(api.newCableRevision).toHaveBeenCalledWith("design-1", 1));
  });

  it("abre o diálogo de conflito quando a versão ficou obsoleta", async () => {
    api.saveCableRevision.mockRejectedValue(new ApiError(409, "Outra pessoa gravou este estudo."));
    await renderEditor();
    fireEvent.change(screen.getByLabelText("Nome do projeto"), { target: { value: "Estado local" } });
    await waitFor(() => expect(screen.getByText("Alterações por guardar")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    expect(await screen.findByRole("dialog", { name: /outra pessoa gravou este estudo/i })).toBeInTheDocument();
    expect(screen.getByText(/Estado local/)).toBeInTheDocument();
  });

  it("transforma 423 em modo só leitura e desativa os campos", async () => {
    api.saveCableRevision.mockRejectedValue(new ApiError(423, "Estudo bloqueado."));
    await renderEditor();
    fireEvent.change(screen.getByLabelText("Nome do projeto"), { target: { value: "Estado local" } });
    await waitFor(() => expect(screen.getByText("Alterações por guardar")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    expect(await screen.findByText("Este estudo foi bloqueado. Foi recarregado em modo só leitura.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Nome do projeto")).toBeDisabled());
  });

  it("sem view_costs não carrega o motor e mantém o resumo de acesso", async () => {
    await renderEditor(["cable_design.view"], false);
    expect(await screen.findByText("Não tem acesso à ferramenta de cálculo (custos e catálogos comerciais).")).toBeInTheDocument();
    expect(engineMock.useCableEngine).toHaveBeenCalledWith(false);
    expect(screen.queryByRole("tab", { name: "Cabos AC" })).not.toBeInTheDocument();
  });

  it("abre a gaveta de revisões e histórico com nomes, e deixa os outros separadores nativos", async () => {
    await renderEditor();
    fireEvent.click(screen.getByRole("button", { name: "⋯ Mais" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Revisões e histórico" }));
    expect(await screen.findByRole("dialog", { name: "Revisões e histórico" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText(/Pessoa Um/).length).toBeGreaterThanOrEqual(2));
    fireEvent.click(screen.getByRole("button", { name: "Fechar" }));
    fireEvent.click(screen.getByRole("tab", { name: "Esquema unifilar" }));
    expect(screen.getByText("Sem inversores para desenhar")).toBeInTheDocument();
  });

  it("torna os campos só de leitura quando a revisão está aprovada", async () => {
    currentDesign = { ...currentDesign, status: "aprovado", revision: { ...revision, status: "aprovada" } };
    api.getCableDesign.mockResolvedValue(currentDesign);
    await renderEditor();
    expect(screen.getByLabelText("Nome do projeto")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Nova revisão" })).toBeInTheDocument();
  });

  it("liga cada entrada do menu Exportar ao exportador do motor", async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:cabo");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    await renderEditor();
    const entries = [
      ["Relatório de cálculo (PDF)", fakeEngine.exports.reportPdf],
      ["Relatório (Word)", fakeEngine.exports.reportDocx],
      ["Orçamento (PDF)", fakeEngine.exports.bomPdf],
      ["Esquema unifilar (SVG)", fakeEngine.exports.sldSvg],
      ["Esquema unifilar (PNG)", fakeEngine.exports.sldPng],
      ["Esquema unifilar (DXF)", fakeEngine.exports.sldDxf],
    ] as const;
    for (const [label, exporter] of entries) {
      fireEvent.click(screen.getByRole("button", { name: "⋯ Mais" }));
      fireEvent.click(screen.getByRole("menuitem", { name: label }));
      await waitFor(() => expect(exporter).toHaveBeenCalledWith(expect.anything(), expect.anything()));
      expect(screen.getAllByText("Ficheiro descarregado.").length).toBeGreaterThan(0);
    }
    expect(click).toHaveBeenCalledTimes(entries.length);
  });

  it("copia a tabela e mostra uma mensagem clara quando a área de transferência recusa", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    await renderEditor();
    fireEvent.click(screen.getByRole("button", { name: "⋯ Mais" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Copiar tabela" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("Circuito\tCabo"));
    expect(await screen.findByText("Tabela copiada")).toBeInTheDocument();

    writeText.mockRejectedValueOnce(new Error("bloqueado"));
    fireEvent.click(screen.getByRole("button", { name: "⋯ Mais" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Copiar tabela" }));
    expect(await screen.findByText(/Não foi possível copiar a tabela/)).toBeInTheDocument();
  });

  it("mantém os três diálogos desativados em só leitura mas deixa as exportações disponíveis", async () => {
    currentDesign = { ...currentDesign, status: "aprovado", revision: { ...revision, status: "aprovada" } };
    api.getCableDesign.mockResolvedValue(currentDesign);
    await renderEditor();
    fireEvent.click(screen.getByRole("tab", { name: "Cabos AC" }));
    expect(screen.getByRole("button", { name: "Comparar alternativas" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Modelos" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Adicionar quadro" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "⋯ Mais" }));
    expect(screen.getByRole("menuitem", { name: "Relatório de cálculo (PDF)" })).not.toBeDisabled();
  });
});
