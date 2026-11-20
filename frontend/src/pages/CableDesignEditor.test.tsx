import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import type { CableDesign, CableDesignHistoryEntry, CableDesignRevision } from "../api/cableDesigns";
import type { CabosEngine, Result, State } from "../features/cables/engine";
import CableDesignEditor from "./CableDesignEditor";
import { makeMe, makeProject } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import type { Perm } from "../generated/permissions";

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
  rInv: { ref: "", cons: "mono", disp: "trevo", trays: 1, sol: false },
  rts: [],
  rtV: 2,
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
    sldPdf: vi.fn(async () => ({ blob: new Blob(["pdf"]), filename: "unifilar.pdf" })),
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
  result_json: { format: 1 },
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
  permissions: Perm[] = ["cable_design.view", "cable_design.edit", "cable_design.view_costs"],
  waitForNative = true,
) {
  renderWithProviders(<CableDesignEditor />, {
    me: makeMe({ permissions }),
    route: "/projects/project-1/cables/design-1",
    path: "/projects/:projectId/cables/:designId",
  });
  if (waitForNative) {
    await screen.findByRole("tab", { name: "Cabos AC" });
    // O conteúdo do separador vem do motor (assíncrono, no worker).
    await screen.findByRole("heading", { name: "Cabos AC" });
  }
  else await screen.findByRole("button", { name: /Nova revisão|Revisões e histórico/ });
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

  it.each([
    ["aprovado", "rascunho", true],
    ["aprovado", "aprovada", false],
    ["aprovada", "rascunho", true],
    ["rascunho", "aprovado", true],
    ["rascunho", "aprovada", true],
  ])("mostra apenas o resultado histórico aprovado para status %s / %s", async (designStatus, revisionStatus, viewCosts) => {
    const historicalDesign = {
      ...currentDesign,
      status: designStatus,
      revision: {
        ...revision,
        status: revisionStatus,
        rev: "B",
        engine_version: "cabos-historico@12",
        approved_by_person_id: "person-1",
        approved_at: "2026-10-19T10:00:00Z",
        result_json: {
          format: 1,
          engine_version: "cabos-historico@12",
          circuits: [{ code: "OLD-01", name: "Circuito aprovado histórico", review: true, note: "ΔU anterior" }],
          totals: { circuits: 1, review: 1, inverters: 1, kw_ac: 18.5 },
        },
      },
    };
    currentDesign = historicalDesign;
    api.getCableDesign.mockResolvedValue(currentDesign);
    const solve = vi.spyOn(fakeEngine, "solve");
    solve.mockClear();
    const before = JSON.stringify(historicalDesign);
    await renderEditor(["cable_design.view", "cable_design.edit", ...(viewCosts ? (["cable_design.view_costs"] as const) : [])], false);

    expect(await screen.findByText("Resultado histórico aprovado · Rev. B")).toBeInTheDocument();
    expect(screen.getByText("cabos-historico@12")).toBeInTheDocument();
    expect(screen.getByText("Circuito aprovado histórico")).toBeInTheDocument();
    expect(screen.getByText("OLD-01")).toBeInTheDocument();
    expect(screen.getByText("Circuitos a rever")).toBeInTheDocument();
    expect(screen.getByText(/18,5/)).toBeInTheDocument();
    expect(screen.getByText(/Nova revisão recalcula com o motor atual/)).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Cabos AC" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Nome do projeto")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Nova revisão" })).toBeInTheDocument();
    expect(screen.queryByText("Alterações por guardar")).not.toBeInTheDocument();
    expect(solve).not.toHaveBeenCalled();
    expect(JSON.stringify(historicalDesign)).toBe(before);
    expect(api.saveCableRevision).not.toHaveBeenCalled();
    expect(fakeEngine.views.circuitRows).not.toHaveBeenCalled();
    expect(engineMock.useCableEngine).toHaveBeenLastCalledWith(false);

    fireEvent.click(screen.getByRole("button", { name: "⋯ Mais" }));
    expect(screen.queryByRole("menuitem", { name: "Relatório de cálculo (PDF)" })).not.toBeInTheDocument();
  });

  it("não substitui um resultado histórico ausente ou ilegível por cálculo atual", async () => {
    currentDesign = {
      ...currentDesign,
      status: "aprovado",
      revision: { ...revision, status: "aprovada", result_json: { format: 1, circuits: "inválido", totals: {} } },
    };
    api.getCableDesign.mockResolvedValue(currentDesign);
    const solve = vi.spyOn(fakeEngine, "solve");
    solve.mockClear();
    await renderEditor(["cable_design.view", "cable_design.edit", "cable_design.view_costs"], false);

    expect(await screen.findByText("Resultado histórico indisponível")).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Cabos AC" })).not.toBeInTheDocument();
    expect(screen.queryByText("Circuito aprovado histórico")).not.toBeInTheDocument();
    expect(solve).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Nova revisão" })).toBeInTheDocument();
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

  it("confirma saída imediata durante debounce e cancelar mantém a edição sem guardar", async () => {
    await renderEditor();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    try {
      fireEvent.change(screen.getByLabelText("Nome do projeto"), { target: { value: "Pendente imediato" } });
      fireEvent.click(screen.getByRole("button", { name: "← Voltar" }));
      expect(confirm).toHaveBeenCalledWith("Tem alterações por guardar. Sair sem guardar?");
      // O motor corre num worker: a edição aplica-se de forma assíncrona.
      await waitFor(() => expect(screen.getByLabelText("Nome do projeto")).toHaveValue("Pendente imediato"));
      expect(api.saveCableRevision).not.toHaveBeenCalled();
    } finally { confirm.mockRestore(); }
  });

  it("descarrega edições pendentes antes de unload e antes da gravação explícita", async () => {
    await renderEditor();
    fireEvent.change(screen.getByLabelText("Nome do projeto"), { target: { value: "Unload pendente" } });
    const unload = new Event("beforeunload", { cancelable: true });
    fireEvent(window, unload);
    expect(unload.defaultPrevented).toBe(true);
    await waitFor(() => expect(screen.getByLabelText("Nome do projeto")).toHaveValue("Unload pendente"));
    expect(api.saveCableRevision).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Nome do projeto"), { target: { value: "Guardar pendente" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(api.saveCableRevision).toHaveBeenCalledWith("design-1", expect.objectContaining({
      input: expect.objectContaining({ state: expect.objectContaining({ proj: "Guardar pendente" }) }),
    })));
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

  it("cria uma nova revisão e só então volta a calcular e editar o input aprovado", async () => {
    const approvedInput = { ...state, proj: "Estado persistido" };
    currentDesign = {
      ...currentDesign,
      status: "aprovado",
      revision: { ...revision, status: "aprovada", input_json: { format: 1, state: approvedInput } },
    };
    api.getCableDesign.mockResolvedValue(currentDesign);
    api.newCableRevision.mockResolvedValue({
      ...currentDesign,
      status: "rascunho",
      current_revision: "B",
      version: 2,
      revision: {
        ...currentDesign.revision,
        id: "revision-2",
        rev: "B",
        status: "rascunho",
        input_json: { format: 1, state: approvedInput },
        result_json: { format: 1, circuits: [], totals: { circuits: 0, review: 0, inverters: 0 } },
      },
    });
    const solve = vi.spyOn(fakeEngine, "solve");
    solve.mockClear();
    await renderEditor(["cable_design.view", "cable_design.edit", "cable_design.view_costs"], false);
    expect(await screen.findByText("Resultado histórico indisponível")).toBeInTheDocument();
    expect(solve).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Nova revisão" }));

    await waitFor(() => expect(api.newCableRevision).toHaveBeenCalledWith("design-1", 1));
    expect(await screen.findByRole("tab", { name: "Cabos AC" })).toBeInTheDocument();
    expect(screen.getByLabelText("Nome do projeto")).toHaveValue("Estado persistido");
    expect(screen.getByLabelText("Nome do projeto")).not.toBeDisabled();
    await waitFor(() => expect(solve).toHaveBeenCalledTimes(1));
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

  it("mostra erros por secção na gaveta (e não 'sem revisões'/'sem histórico') e volta a carregar", async () => {
    api.listCableRevisions.mockRejectedValue(new ApiError(403, "Sem acesso às revisões."));
    api.listCableHistory.mockRejectedValue(new Error("rede em baixo"));
    await renderEditor();
    fireEvent.click(screen.getByRole("button", { name: "⋯ Mais" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Revisões e histórico" }));
    const drawer = await screen.findByRole("dialog", { name: "Revisões e histórico" });

    expect(await within(drawer).findByText("Sem acesso às revisões.")).toBeInTheDocument();
    expect(within(drawer).getByText("Não foi possível contactar o servidor.")).toBeInTheDocument();
    expect(within(drawer).queryByText("Sem revisões registadas.")).not.toBeInTheDocument();
    expect(within(drawer).queryByText("Sem histórico registado.")).not.toBeInTheDocument();

    api.listCableRevisions.mockResolvedValue([revision]);
    api.listCableHistory.mockResolvedValue([]);
    const [retryRevisions, retryHistory] = within(drawer).getAllByRole("button", { name: "Tentar novamente" });
    fireEvent.click(retryRevisions);
    await waitFor(() => expect(within(drawer).queryByText("Sem acesso às revisões.")).not.toBeInTheDocument());
    fireEvent.click(retryHistory);
    expect(await within(drawer).findByText("Sem histórico registado.")).toBeInTheDocument();
    expect(within(drawer).queryByTestId("error-state")).not.toBeInTheDocument();
  });

  it("avisa quando o projeto não carrega e recarrega os dados ao tentar de novo", async () => {
    api.getProject.mockRejectedValueOnce(new ApiError(403, "Sem acesso ao projeto."));
    await renderEditor();

    expect(await screen.findByText("Não foi possível carregar os dados do projeto.")).toBeInTheDocument();
    expect(screen.getByText(/Sem acesso ao projeto\./)).toBeInTheDocument();
    expect(screen.getByLabelText("Nome do projeto")).toHaveValue("");

    fireEvent.click(screen.getByRole("button", { name: "Tentar novamente" }));
    await waitFor(() => expect(screen.queryByText("Não foi possível carregar os dados do projeto.")).not.toBeInTheDocument());
    await waitFor(() => expect(screen.getByLabelText("Nome do projeto")).toHaveValue("Projeto A"));
    expect(api.getProject).toHaveBeenCalledTimes(2);
  });

  it("não mostra controlos dependentes do motor na revisão aprovada", async () => {
    currentDesign = { ...currentDesign, status: "aprovado", revision: { ...revision, status: "aprovada" } };
    api.getCableDesign.mockResolvedValue(currentDesign);
    await renderEditor(["cable_design.view", "cable_design.edit", "cable_design.view_costs"], false);
    expect(await screen.findByText("Resultado histórico indisponível")).toBeInTheDocument();
    expect(screen.queryByLabelText("Nome do projeto")).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Cabos AC" })).not.toBeInTheDocument();
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
      ["Esquema unifilar (PDF)", fakeEngine.exports.sldPdf],
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

  it("esconde a exportação de cálculo no histórico aprovado", async () => {
    currentDesign = {
      ...currentDesign,
      status: "aprovado",
      revision: {
        ...revision,
        status: "aprovada",
        result_json: {
          format: 1,
          engine_version: "cabos-fake@1",
          circuits: [],
          totals: { circuits: 0, review: 0, inverters: 0 },
        },
      },
    };
    api.getCableDesign.mockResolvedValue(currentDesign);
    await renderEditor(["cable_design.view", "cable_design.edit", "cable_design.view_costs"], false);
    expect(await screen.findByText("Resultado histórico aprovado · Rev. A")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "⋯ Mais" }));
    expect(screen.queryByRole("menuitem", { name: "Relatório de cálculo (PDF)" })).not.toBeInTheDocument();
  });
});
