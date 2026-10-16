import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { makeMe, makeProject } from "../test/fixtures";
import type { ProjectListConfig } from "../api/projectListViews";
import { renderWithProviders } from "../test/render";
import ProjectsList, { toApiFilters } from "./ProjectsList";

const { listProjects, listPeople, getLifecycleStatuses } = vi.hoisted(() => ({
  listProjects: vi.fn(),
  listPeople: vi.fn(),
  getLifecycleStatuses: vi.fn(),
}));

const {
  getProjectListPreferences,
  updateProjectListPreferences,
  listProjectListViews,
  createProjectListView,
  updateProjectListView,
  deleteProjectListView,
} = vi.hoisted(() => ({
  getProjectListPreferences: vi.fn(),
  updateProjectListPreferences: vi.fn(),
  listProjectListViews: vi.fn(),
  createProjectListView: vi.fn(),
  updateProjectListView: vi.fn(),
  deleteProjectListView: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, listProjects, listPeople, getLifecycleStatuses };
});

vi.mock("../api/projectListViews", async () => {
  const actual = await vi.importActual<typeof import("../api/projectListViews")>("../api/projectListViews");
  return {
    ...actual,
    getProjectListPreferences,
    updateProjectListPreferences,
    listProjectListViews,
    createProjectListView,
    updateProjectListView,
    deleteProjectListView,
  };
});

const LIFECYCLE = [
  { code: "on_hold_cliente", label: "On hold pelo cliente", flow_position: null },
  { code: "preparacao", label: "Preparação", flow_position: 1 },
  { code: "construcao", label: "Construção", flow_position: 2 },
];

const DEFAULT_CONFIG: ProjectListConfig = {
  columns: ["project", "pm", "lifecycle", "progress", "next_task", "overdue", "warnings"],
  sort_by: "name",
  sort_direction: "asc",
  filters: {
    search: "",
    status: "",
    lifecycle: ["on_hold_cliente", "preparacao", "construcao", "construido"],
    pm: "",
    active: "active",
    startFrom: "",
    startTo: "",
  },
};

const SAVED_VIEW = {
  id: "view-synthetic",
  name: "Obras prioritárias",
  config: {
    ...DEFAULT_CONFIG,
    columns: ["project", "pm", "lifecycle"] as const,
    sort_by: "power_kwp" as const,
    sort_direction: "desc" as const,
    filters: { ...DEFAULT_CONFIG.filters, lifecycle: [] },
  },
  created_at: "2026-10-16T09:00:00Z",
  updated_at: "2026-10-16T09:00:00Z",
};

describe("ProjectsList (filtros)", () => {
  beforeEach(() => {
    listProjects.mockReset();
    listPeople.mockReset();
    getLifecycleStatuses.mockReset();
    getProjectListPreferences.mockReset();
    updateProjectListPreferences.mockReset();
    listProjectListViews.mockReset();
    createProjectListView.mockReset();
    updateProjectListView.mockReset();
    deleteProjectListView.mockReset();
    getProjectListPreferences.mockResolvedValue({ config: structuredClone(DEFAULT_CONFIG) });
    listProjectListViews.mockResolvedValue([]);
    updateProjectListPreferences.mockResolvedValue({ config: structuredClone(DEFAULT_CONFIG) });
    getLifecycleStatuses.mockResolvedValue(LIFECYCLE);
    listPeople.mockResolvedValue([{ id: "p-pm", display_name: "PM Sintético Um", email: null, is_active: true }]);
    listProjects.mockResolvedValue([
      makeProject(),
      makeProject({
        id: "proj-2",
        name: "Projeto Sintético Sem PM",
        has_pm: false,
        pm_display_name: null,
        pm_person_id: null,
        has_email: false,
        photos_pending_warning: true,
        overdue_tasks_count: 2,
      }),
    ]);
  });

  it("carrega só projetos ativos por omissão e mostra os avisos de cada projeto", async () => {
    renderWithProviders(<ProjectsList />, { me: makeMe() });

    expect(await screen.findByText("Projeto Sintético Sem PM")).toBeInTheDocument();
    expect(listProjects).toHaveBeenLastCalledWith(expect.objectContaining({ is_active: true }));
    expect(screen.getByText("2 projetos em curso")).toBeInTheDocument();
    expect(screen.getByText("Fotos pendentes")).toBeInTheDocument();
    expect(screen.getByText("sem email")).toBeInTheDocument();
    expect(screen.getAllByRole("progressbar")).toHaveLength(2);
  });

  it("envia os filtros de estado, PM e datas ao servidor", async () => {
    renderWithProviders(<ProjectsList />, { me: makeMe() });
    await screen.findByText("Projeto Sintético Sem PM");
    await screen.findByRole("option", { name: "PM Sintético Um" });

    fireEvent.change(screen.getByLabelText("Tarefas"), { target: { value: "concluido" } });
    fireEvent.change(screen.getByLabelText("PM"), { target: { value: "p-pm" } });
    fireEvent.change(screen.getByLabelText("Início a partir de"), { target: { value: "2026-09-01" } });
    fireEvent.change(screen.getByLabelText("Início até"), { target: { value: "2026-09-30" } });

    await waitFor(() =>
      expect(listProjects).toHaveBeenLastCalledWith({
        q: undefined,
        status: "concluido",
        pm_person_id: "p-pm",
        lifecycle_status: ["on_hold_cliente", "preparacao", "construcao", "construido"],
        is_active: true,
        start_from: "2026-09-01",
        start_to: "2026-09-30",
      })
    );
  });

  it("agrupa por estado do ciclo de vida, mostra contagens e preserva o total global", async () => {
    getLifecycleStatuses.mockResolvedValue([
      { code: "preparacao", label: "Preparação", flow_position: 1 },
      { code: "construcao", label: "Construção", flow_position: 2 },
    ]);
    listProjects.mockResolvedValue([
      makeProject({ id: "proj-construcao-1", name: "Projeto Construção 1", lifecycle_status: "construcao", status: "concluido" }),
      makeProject({ id: "proj-preparacao", name: "Projeto Preparação", lifecycle_status: "preparacao", status: "nao_iniciado" }),
      makeProject({ id: "proj-construcao-2", name: "Projeto Construção 2", lifecycle_status: "construcao", status: "em_curso" }),
    ]);

    renderWithProviders(<ProjectsList />, { me: makeMe() });

    expect(await screen.findByText("Projeto Construção 2")).toBeInTheDocument();
    expect(screen.getByText("3 projetos em curso")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Recolher grupo Preparação (1 projeto)" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: "Recolher grupo Construção (2 projetos)" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Projeto Construção 1")).toBeInTheDocument();
  });

  it("mantém a edição de PM autorizada e apenas a leitura quando a permissão falta", async () => {
    listProjects.mockResolvedValue([
      makeProject({ id: "proj-editavel", name: "Projeto Editável", editable_fields: ["pm_person_id"] }),
      makeProject({ id: "proj-leitura", name: "Projeto Só Leitura", editable_fields: [], pm_display_name: "PM Sintético Um" }),
    ]);

    renderWithProviders(<ProjectsList />, { me: makeMe() });

    expect(await screen.findByText("Projeto Só Leitura")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "PM do projeto Projeto Editável" })).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "PM do projeto Projeto Só Leitura" })).not.toBeInTheDocument();
    expect(screen.getByRole("row", { name: /Projeto Só Leitura.*PM Sintético Um/ })).toBeInTheDocument();
  });

  it("permite fechar um grupo e conserva o estado fechado depois de recarregar por filtro", async () => {
    const firstResult = [
      makeProject({ id: "proj-construcao", name: "Projeto Construção", lifecycle_status: "construcao" }),
      makeProject({ id: "proj-preparacao", name: "Projeto Preparação", lifecycle_status: "preparacao" }),
    ];
    listProjects.mockResolvedValueOnce(firstResult).mockResolvedValueOnce([firstResult[0]]);
    getLifecycleStatuses.mockResolvedValue([
      { code: "preparacao", label: "Preparação", flow_position: 1 },
      { code: "construcao", label: "Construção", flow_position: 2 },
    ]);

    renderWithProviders(<ProjectsList />, { me: makeMe() });
    expect(await screen.findByText("Projeto Construção")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Recolher grupo Construção (1 projeto)" }));
    expect(screen.getByRole("button", { name: "Expandir grupo Construção (1 projeto)" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "Projeto Construção" })).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Tarefas"), { target: { value: "concluido" } });
    await waitFor(() => expect(listProjects).toHaveBeenLastCalledWith(expect.objectContaining({ status: "concluido" })));
    expect(screen.getByRole("button", { name: "Expandir grupo Construção (1 projeto)" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "Projeto Construção" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Expandir todos" }));
    expect(screen.getByRole("button", { name: "Recolher grupo Construção (1 projeto)" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Projeto Construção")).toBeInTheDocument();
  });

  it("mostra o estado do projeto e filtra por vários estados no servidor", async () => {
    listProjects.mockResolvedValue([
      makeProject({ lifecycle_status: "construcao" }),
      makeProject({ id: "proj-2", name: "Projeto Sintético Sem PM", lifecycle_status: null }),
    ]);
    renderWithProviders(<ProjectsList />, { me: makeMe() });
    await screen.findByText("Projeto Sintético Sem PM");

    // Rótulo vindo do servidor (não do código) e "Sem estado" quando não há.
    expect(await screen.findAllByText("Construção")).not.toHaveLength(0);
    expect(screen.getAllByText("Sem estado")).toHaveLength(2);

    fireEvent.click(await screen.findByRole("button", { name: "Todos" }));
    fireEvent.click(await screen.findByLabelText("On hold pelo cliente"));
    fireEvent.click(screen.getByLabelText("Preparação"));
    await waitFor(() =>
      expect(listProjects).toHaveBeenLastCalledWith(
        expect.objectContaining({ lifecycle_status: ["on_hold_cliente", "preparacao"] })
      )
    );
    fireEvent.click(screen.getByLabelText("On hold pelo cliente"));
    await waitFor(() =>
      expect(listProjects).toHaveBeenLastCalledWith(expect.objectContaining({ lifecycle_status: ["preparacao"] }))
    );
  });

  it("abre nos projetos em curso e o botão Todos tira o filtro de estado (fica no URL)", async () => {
    renderWithProviders(<ProjectsList />, { me: makeMe() });
    await screen.findByText("Projeto Sintético Sem PM");

    expect(listProjects).toHaveBeenLastCalledWith(
      expect.objectContaining({ lifecycle_status: ["on_hold_cliente", "preparacao", "construcao", "construido"] })
    );
    expect(screen.getByText("Em curso", { selector: "summary" })).toBeInTheDocument();
    expect(screen.getByText("2 projetos em curso")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Todos" }));
    await waitFor(() => expect(listProjects).toHaveBeenLastCalledWith(expect.objectContaining({ lifecycle_status: undefined })));
    expect(screen.getByText("Todos", { selector: "summary" })).toBeInTheDocument();
  });

  it("?estado=todos abre sem filtro de estado", async () => {
    renderWithProviders(<ProjectsList />, { me: makeMe(), route: "/projects?estado=todos" });
    await screen.findByText("Projeto Sintético Sem PM");
    expect(listProjects).toHaveBeenLastCalledWith(expect.objectContaining({ lifecycle_status: undefined }));
  });

  it("pesquisa por projeto/cliente depois de uma breve pausa", async () => {
    renderWithProviders(<ProjectsList />, { me: makeMe() });
    await screen.findByText("Projeto Sintético Sem PM");

    fireEvent.change(screen.getByLabelText("Pesquisar"), { target: { value: "cliente x" } });
    await waitFor(() => expect(listProjects).toHaveBeenLastCalledWith(expect.objectContaining({ q: "cliente x" })));
  });

  it("mostra estado vazio com opção de limpar filtros", async () => {
    renderWithProviders(<ProjectsList />, { me: makeMe() });
    await screen.findByText("Projeto Sintético Sem PM");

    listProjects.mockResolvedValue([]);
    fireEvent.change(screen.getByLabelText("Situação"), { target: { value: "inactive" } });

    expect(await screen.findByText("Nenhum projeto encontrado")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: /Limpar filtros/ })[0]);
    await waitFor(() => expect(listProjects).toHaveBeenLastCalledWith(expect.objectContaining({ is_active: true })));
  });

  it("toApiFilters traduz 'todos' para ausência de filtro", () => {
    expect(toApiFilters({ search: "  ", status: "", lifecycle: [], pm: "", active: "all", startFrom: "", startTo: "" })).toEqual({
      q: undefined,
      status: undefined,
      lifecycle_status: undefined,
      pm_person_id: undefined,
      is_active: undefined,
      start_from: undefined,
      start_to: undefined,
    });
  });

  it("permite esconder, reordenar e restaurar colunas sem destruir os grupos", async () => {
    renderWithProviders(<ProjectsList />, { me: makeMe() });
    await screen.findByText("Projeto Sintético Sem PM");
    const table = screen.getByRole("table");
    const headings = () => [...table.querySelectorAll("thead th")].map((cell) => cell.textContent);

    expect(headings()).toEqual(["Projeto", "PM", "Estado", "Tarefas e progresso", "Próxima tarefa", "Atrasadas", "Avisos"]);
    fireEvent.click(screen.getByRole("button", { name: "Colunas" }));
    expect(screen.getByRole("dialog", { name: "Configurar colunas" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Mostrar PM" }));
    expect(headings()).toEqual(["Projeto", "Estado", "Tarefas e progresso", "Próxima tarefa", "Atrasadas", "Avisos"]);
    fireEvent.click(screen.getByRole("button", { name: "Subir coluna Tarefas e progresso" }));
    expect(headings()).toEqual(["Projeto", "Tarefas e progresso", "Estado", "Próxima tarefa", "Atrasadas", "Avisos"]);
    fireEvent.click(screen.getByRole("button", { name: "Restaurar colunas padrão" }));
    expect(headings()).toEqual(["Projeto", "PM", "Estado", "Tarefas e progresso", "Próxima tarefa", "Atrasadas", "Avisos"]);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Configurar colunas" })).not.toBeInTheDocument();
  });

  it("aplica uma vista pessoal e só confirma atualizar, renomear e remover após a API responder", async () => {
    listProjectListViews.mockResolvedValue([SAVED_VIEW]);
    createProjectListView.mockResolvedValue({ ...SAVED_VIEW, id: "view-new", name: "Nova vista" });
    updateProjectListView.mockResolvedValue({ ...SAVED_VIEW, name: "Vista renomeada" });
    deleteProjectListView.mockResolvedValue(undefined);
    const prompt = vi.spyOn(window, "prompt");
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);

    renderWithProviders(<ProjectsList />, { me: makeMe() });
    await screen.findByRole("option", { name: "Obras prioritárias" });
    fireEvent.change(screen.getByLabelText("Vistas pessoais"), { target: { value: SAVED_VIEW.id } });
    fireEvent.click(screen.getByRole("button", { name: "Aplicar vista" }));
    await waitFor(() => expect(screen.getByLabelText("Ordenar por")).toHaveValue("power_kwp"));
    expect(listProjects).toHaveBeenLastCalledWith(expect.objectContaining({ lifecycle_status: undefined }));
    expect(screen.getByRole("columnheader", { name: "Estado" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Tarefas e progresso" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Atualizar vista" }));
    await waitFor(() => expect(updateProjectListView).toHaveBeenCalledWith(SAVED_VIEW.id, { config: expect.any(Object) }));

    prompt.mockReturnValue("Vista renomeada");
    fireEvent.click(screen.getByRole("button", { name: "Renomear vista" }));
    await waitFor(() => expect(updateProjectListView).toHaveBeenCalledWith(SAVED_VIEW.id, { name: "Vista renomeada" }));
    expect(await screen.findByRole("option", { name: "Vista renomeada" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Eliminar vista" }));
    await waitFor(() => expect(deleteProjectListView).toHaveBeenCalledWith(SAVED_VIEW.id));
    expect(screen.queryByRole("option", { name: "Vista renomeada" })).not.toBeInTheDocument();
    expect(confirm).toHaveBeenCalledWith("Eliminar a vista «Vista renomeada»?");
    prompt.mockRestore();
    confirm.mockRestore();
  });

  it("guarda a preferência de abertura com o DTO completo e mantém as colunas ao limpar filtros", async () => {
    renderWithProviders(<ProjectsList />, { me: makeMe() });
    await screen.findByText("Projeto Sintético Sem PM");
    fireEvent.change(screen.getByLabelText("Tarefas"), { target: { value: "concluido" } });
    fireEvent.click(screen.getByRole("button", { name: "Colunas" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Mostrar PM" }));
    fireEvent.click(screen.getByRole("button", { name: "Fechar configuração de colunas" }));
    fireEvent.click(screen.getByRole("button", { name: "Guardar preferência de abertura" }));

    await waitFor(() =>
      expect(updateProjectListPreferences).toHaveBeenCalledWith(
        expect.objectContaining({
          columns: ["project", "lifecycle", "progress", "next_task", "overdue", "warnings"],
          filters: expect.objectContaining({ status: "concluido" }),
        })
      )
    );
    expect(await screen.findAllByText("Preferência de abertura guardada.")).not.toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: /Limpar filtros/ }));
    expect(screen.queryByRole("columnheader", { name: "PM" })).not.toBeInTheDocument();
  });

  it("não deixa uma preferência atrasada substituir URL explícito ou interação manual", async () => {
    let resolvePreference!: (value: { config: typeof DEFAULT_CONFIG }) => void;
    getProjectListPreferences.mockReturnValue(new Promise((resolve) => { resolvePreference = resolve; }));
    const firstRender = renderWithProviders(<ProjectsList />, { me: makeMe() });
    await screen.findByRole("option", { name: "PM Sintético Um" });
    fireEvent.change(screen.getByLabelText("PM"), { target: { value: "p-pm" } });
    resolvePreference({
      config: {
        ...DEFAULT_CONFIG,
        columns: ["project"],
        filters: { ...DEFAULT_CONFIG.filters, pm: "outro-pm" },
      },
    });
    await waitFor(() => expect(screen.getByLabelText("PM")).toHaveValue("p-pm"));
    expect(screen.queryByRole("columnheader", { name: "PM" })).toBeInTheDocument();

    firstRender.unmount();
    getProjectListPreferences.mockResolvedValue({
      config: { ...DEFAULT_CONFIG, columns: ["project"], filters: { ...DEFAULT_CONFIG.filters, pm: "p-pm", lifecycle: [] } },
    });
    renderWithProviders(<ProjectsList />, { me: makeMe(), route: "/projects?estado=todos" });
    await screen.findByText("Projeto Sintético Sem PM");
    expect(screen.getByLabelText("PM")).toHaveValue("");
    expect(screen.getByRole("columnheader", { name: "Projeto" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "PM" })).toBeInTheDocument();
  });

  it("mostra erros de carregar e gravar vistas sem falso sucesso", async () => {
    listProjectListViews.mockRejectedValue(new Error("Vistas indisponíveis"));
    updateProjectListPreferences.mockRejectedValue(new Error("Preferência recusada"));
    renderWithProviders(<ProjectsList />, { me: makeMe() });
    await screen.findByText("Projeto Sintético Sem PM");
    expect(await screen.findByText("Vistas indisponíveis")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Guardar preferência de abertura" }));
    expect(await screen.findByText("Preferência recusada")).toBeInTheDocument();
    expect(screen.queryByText("Preferência de abertura guardada.")).not.toBeInTheDocument();
  });
});
