import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SafetySheetPrefillRead, SafetySheetRead } from "../api/client";
import { makeMe, makeProject, makeTask } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import ProjectDetail from "./ProjectDetail";

const api = vi.hoisted(() => ({
  getProject: vi.fn(),
  getProjectHistory: vi.fn(),
  listTasks: vi.fn(),
  listPeople: vi.fn(),
  getSafetySheet: vi.fn(),
  prefillSafetySheetWorkers: vi.fn(),
  updateSafetySheet: vi.fn(),
  getSafetySheetPrintHtml: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, ...api };
});

function safetySheet(overrides: Partial<SafetySheetRead> = {}): SafetySheetRead {
  return {
    project_id: "proj-1",
    version: 2,
    roof_type: null,
    roof_other: null,
    approximate_height_m: null,
    access_method: null,
    access_other: null,
    risks: [],
    risk_other: null,
    safety_measures: [],
    measure_other: null,
    workers: [],
    safety_responsible: null,
    emergency_contacts: null,
    observations: null,
    work_start_date: null,
    work_end_date: null,
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

const EDITABLE_PROJECT = makeProject({ editable_fields: ["notes"] });

async function openSafetySheet(project = EDITABLE_PROJECT, permissions = ["project.view_all"]) {
  api.getProject.mockResolvedValue(project);
  renderWithProviders(<ProjectDetail />, {
    me: makeMe({ permissions }),
    route: "/projects/proj-1",
    path: "/projects/:projectId",
  });
  await screen.findByRole("heading", { level: 1, name: makeProject().name });
  fireEvent.click(screen.getByRole("tab", { name: "Segurança" }));
  await screen.findByRole("heading", { name: "Ficha de segurança da obra" });
  return project;
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.getProject.mockResolvedValue(EDITABLE_PROJECT);
  api.getProjectHistory.mockResolvedValue([]);
  api.listTasks.mockResolvedValue([makeTask()]);
  api.listPeople.mockResolvedValue([]);
  api.getSafetySheet.mockResolvedValue(safetySheet());
  api.prefillSafetySheetWorkers.mockResolvedValue({ project_id: "proj-1", workers: [] });
  api.updateSafetySheet.mockImplementation(async (_id, body) => safetySheet({ ...body, version: body.expected_version + 1 }));
  api.getSafetySheetPrintHtml.mockResolvedValue("<!doctype html><html><body>Ficha imprimível</body></html>");
});

describe("Detalhe do projeto — ficha de segurança", () => {
  it("apresenta o separador e carrega uma ficha com os campos do formulário", async () => {
    api.getSafetySheet.mockResolvedValue(safetySheet({ roof_type: "telha_ceramica", version: 4 }));
    await openSafetySheet();

    expect(api.getSafetySheet).toHaveBeenCalledWith("proj-1");
    expect(screen.getByLabelText("Tipo de telhado")).toHaveValue("telha_ceramica");
    expect(screen.getByLabelText("Altura aproximada (m)")).toHaveValue(null);
    expect(screen.getByRole("button", { name: "Gerar ficha (imprimir)" })).toBeInTheDocument();
  });

  it("não mostra controlos de edição sem permissão", async () => {
    const readOnlyProject = makeProject({ editable_fields: [] });
    api.getSafetySheet.mockResolvedValue(safetySheet({ workers: [{ person_id: "person-1", name: "Pessoa Sintética", installer_id: "installer-1", team_id: "team-1" }] }));
    await openSafetySheet(readOnlyProject, ["project.view_all"]);

    expect(screen.getByLabelText("Tipo de telhado")).toBeDisabled();
    expect(screen.queryByRole("button", { name: /preencher a partir das equipas/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /adicionar trabalhador/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /remover trabalhador/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^guardar ficha$/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Gerar ficha (imprimir)" })).toBeEnabled();
  });

  it("mostra a sugestão de trabalhadores para confirmação antes de a usar ou gravar", async () => {
    const suggestion: SafetySheetPrefillRead = {
      project_id: "proj-1",
      workers: [{ person_id: "person-1", name: "Pessoa Sintética", installer_id: "installer-1", team_id: "team-1" }],
    };
    api.prefillSafetySheetWorkers.mockResolvedValue(suggestion);
    await openSafetySheet();

    fireEvent.click(screen.getByRole("button", { name: /preencher a partir das equipas da obra/i }));

    const preview = await screen.findByRole("region", { name: "Sugestão de trabalhadores" });
    expect(within(preview).getByText("Pessoa Sintética")).toBeInTheDocument();
    expect(api.prefillSafetySheetWorkers).toHaveBeenCalledWith("proj-1");
    expect(api.updateSafetySheet).not.toHaveBeenCalled();

    fireEvent.click(within(preview).getByRole("button", { name: "Aplicar sugestão à ficha" }));
    expect(await screen.findByLabelText("Nome do trabalhador 1")).toHaveValue("Pessoa Sintética");
    expect(api.updateSafetySheet).not.toHaveBeenCalled();
  });

  it("desvincula uma pessoa registada quando o nome do trabalhador é alterado", async () => {
    api.getSafetySheet.mockResolvedValue(safetySheet({
      workers: [{ person_id: "person-1", name: "Pessoa original", installer_id: "installer-1", team_id: "team-1" }],
    }));
    await openSafetySheet();

    fireEvent.change(screen.getByLabelText("Nome do trabalhador 1"), { target: { value: "Trabalhador externo" } });
    fireEvent.click(screen.getByRole("button", { name: /^guardar ficha$/i }));

    await waitFor(() => expect(api.updateSafetySheet).toHaveBeenCalledTimes(1));
    expect(api.updateSafetySheet).toHaveBeenCalledWith("proj-1", expect.objectContaining({
      workers: [{ person_id: null, name: "Trabalhador externo", installer_id: null, team_id: null }],
    }));
  });

  it("grava o formulário completo com a versão lida", async () => {
    api.getSafetySheet.mockResolvedValue(safetySheet({ version: 7 }));
    await openSafetySheet();
    fireEvent.change(screen.getByLabelText("Tipo de telhado"), { target: { value: "telha_ceramica" } });
    fireEvent.change(screen.getByLabelText("Altura aproximada (m)"), { target: { value: "6.5" } });
    fireEvent.change(screen.getByLabelText("Responsável de segurança"), { target: { value: "Responsável Sintético" } });
    fireEvent.change(screen.getByLabelText("Contactos de emergência / hospital mais próximo"), { target: { value: "112; hospital sintético" } });
    fireEvent.change(screen.getByLabelText("Data de início dos trabalhos"), { target: { value: "2026-11-02" } });
    fireEvent.click(screen.getByLabelText("Queda em altura"));
    fireEvent.click(screen.getByLabelText("Arnês"));

    fireEvent.click(screen.getByRole("button", { name: /^guardar ficha$/i }));

    await waitFor(() => expect(api.updateSafetySheet).toHaveBeenCalledTimes(1));
    expect(api.updateSafetySheet).toHaveBeenCalledWith("proj-1", expect.objectContaining({
      expected_version: 7,
      roof_type: "telha_ceramica",
      roof_other: null,
      approximate_height_m: 6.5,
      risks: ["queda_altura"],
      safety_measures: ["arnes"],
      safety_responsible: "Responsável Sintético",
      emergency_contacts: "112; hospital sintético",
      work_start_date: "2026-11-02",
      work_end_date: null,
    }));
    expect(await screen.findByText("Ficha de segurança guardada.")).toBeInTheDocument();
  });

  it("apresenta a instrução de recarregar quando a versão é obsoleta", async () => {
    const { ApiError } = await vi.importActual<typeof import("../api/client")>("../api/client");
    api.updateSafetySheet.mockRejectedValue(new ApiError(409, "Versão desatualizada"));
    await openSafetySheet();

    fireEvent.click(screen.getByRole("button", { name: /^guardar ficha$/i }));

    expect(await screen.findByText("A ficha foi alterada por outra pessoa — recarregar")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Recarregar ficha" })).toBeInTheDocument();
  });

  it("abre a ficha HTML numa nova janela usando o endpoint de impressão", async () => {
    const popup = {
      document: { open: vi.fn(), write: vi.fn(), close: vi.fn() },
      focus: vi.fn(),
      close: vi.fn(),
    };
    const openWindow = vi.spyOn(window, "open").mockReturnValue(popup as unknown as Window);
    await openSafetySheet();

    fireEvent.click(screen.getByRole("button", { name: "Gerar ficha (imprimir)" }));

    await waitFor(() => expect(api.getSafetySheetPrintHtml).toHaveBeenCalledWith("proj-1"));
    expect(openWindow).toHaveBeenCalled();
    expect(popup.document.write).toHaveBeenCalledWith("<!doctype html><html><body>Ficha imprimível</body></html>");
    expect(popup.focus).toHaveBeenCalled();
    openWindow.mockRestore();
  });
});
