import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Link, Route, Routes, useLocation } from "react-router-dom";
import { makeMe, makeProject } from "../test/fixtures";
import type { ProjectListConfig } from "../api/projectListViews";
import { renderWithProviders } from "../test/render";
import ProjectDetail from "./ProjectDetail";
import ProjectsList, { toApiFilters } from "./ProjectsList";

const {
  listProjects,
  listPeople,
  getLifecycleStatuses,
  changeProjectStatus,
  deleteProject,
  getProject,
  getProjectHistory,
  listTasks,
} = vi.hoisted(() => ({
  listProjects: vi.fn(),
  listPeople: vi.fn(),
  getLifecycleStatuses: vi.fn(),
  changeProjectStatus: vi.fn(),
  deleteProject: vi.fn(),
  getProject: vi.fn(),
  getProjectHistory: vi.fn(),
  listTasks: vi.fn(),
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
  return {
    ...actual,
    listProjects,
    listPeople,
    getLifecycleStatuses,
    changeProjectStatus,
    deleteProject,
    getProject,
    getProjectHistory,
    listTasks,
  };
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

function CurrentLocation() {
  const { pathname, search, hash } = useLocation();
  return <output data-testid="current-location">{`${pathname}${search}${hash}`}</output>;
}

function ProjectLinkWithState({ state }: { state: unknown }) {
  return <Link to="/projects/proj-1" state={state}>Abrir projeto</Link>;
}

describe("ProjectsList (filtros)", () => {
  beforeEach(() => {
    listProjects.mockReset();
    listPeople.mockReset();
    getLifecycleStatuses.mockReset();
    changeProjectStatus.mockReset();
    deleteProject.mockReset();
    getProject.mockReset();
    getProjectHistory.mockReset();
    listTasks.mockReset();
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
    getProject.mockResolvedValue(makeProject());
    getProjectHistory.mockResolvedValue([]);
    listTasks.mockResolvedValue([]);
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

  it("preserva o URL filtrado da lista ao abrir e regressar do detalhe pelo link Projetos", async () => {
    const origin = "/projects?search=Fotos+Pendentes&status=em_curso&estado=todos&pm=p-pm&active=all&startFrom=2026-01-10&startTo=2026-02-20&sort_by=created_at&sort_direction=desc&page=4#results";
    renderWithProviders(
      <>
        <Routes>
          <Route path="/projects" element={<ProjectsList />} />
          <Route path="/projects/:projectId" element={<ProjectDetail />} />
        </Routes>
        <CurrentLocation />
      </>,
      { me: makeMe({ permissions: ["project.view_all"] }), route: origin },
    );

    const projectLink = await screen.findByRole("link", { name: makeProject().name });
    expect(projectLink).toHaveAttribute("href", "/projects/proj-1");
    fireEvent.click(projectLink);
    await screen.findByRole("heading", { level: 1, name: makeProject().name });
    fireEvent.click(screen.getByRole("link", { name: /projetos/i }));

    await waitFor(() => expect(screen.getByTestId("current-location")).toHaveTextContent(origin));
    expect(screen.getByLabelText("Pesquisar")).toHaveValue("Fotos Pendentes");
    expect(screen.getByLabelText("Ordenar por")).toHaveValue("created_at");
    expect(screen.getByLabelText("Direção")).toHaveValue("desc");
  });

  it("usa /projects ao regressar de um detalhe aberto diretamente sem origem de lista", async () => {
    renderWithProviders(
      <>
        <Routes>
          <Route path="/projects" element={<ProjectsList />} />
          <Route path="/projects/:projectId" element={<ProjectDetail />} />
        </Routes>
        <CurrentLocation />
      </>,
      { me: makeMe({ permissions: ["project.view_all"] }), route: "/projects/proj-1?tab=cliente" },
    );

    await screen.findByRole("heading", { level: 1, name: makeProject().name });
    const projectsLink = screen.getByRole("link", { name: /projetos/i });
    expect(projectsLink).toHaveAttribute("href", "/projects");
    fireEvent.click(projectsLink);

    await waitFor(() => expect(screen.getByTestId("current-location")).toHaveTextContent("/projects"));
    expect(screen.getByLabelText("Pesquisar")).toHaveValue("");
  });

  it.each([
    ["destino externo", { from: { pathname: "https://evil.example/path", search: "?next=/projects", hash: "#x" } }],
    ["rota que não é a lista", { from: { pathname: "/projects/proj-2", search: "?search=Fotos", hash: "#results" } }],
    ["sufixo de pesquisa inválido", { from: { pathname: "/projects", search: "//evil.example", hash: "" } }],
  ])("ignora origem inválida (%s)", async (_description, state) => {
    renderWithProviders(
      <>
        <Routes>
          <Route path="/projects" element={<ProjectLinkWithState state={state} />} />
          <Route path="/projects/:projectId" element={<ProjectDetail />} />
        </Routes>
        <CurrentLocation />
      </>,
      { me: makeMe({ permissions: ["project.view_all"] }), route: "/projects" },
    );

    fireEvent.click(screen.getByRole("link", { name: "Abrir projeto" }));
    await screen.findByRole("heading", { level: 1, name: makeProject().name });
    expect(screen.getByRole("link", { name: /projetos/i })).toHaveAttribute("href", "/projects");
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

  it("identifica a região como lista de projetos sem prometer deslize em cartões", async () => {
    const { container } = renderWithProviders(<ProjectsList />, { me: makeMe() });

    expect(await screen.findByText("Projeto Sintético Sem PM")).toBeInTheDocument();
    expect(container.querySelector(".projects-page")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Lista de projetos" })).toHaveAttribute("tabindex", "0");
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

  it("mostra o controlo de estado autorizado na lista e atualiza a linha após guardar", async () => {
    const project = makeProject({ id: "proj-status", name: "Projeto com estado editável", lifecycle_status: "preparacao", can_change_status: true });
    const changed = makeProject({ ...project, lifecycle_status: "construcao" });
    listProjects.mockResolvedValue([project]);
    changeProjectStatus.mockResolvedValue({ project: changed, warning: null });

    renderWithProviders(<ProjectsList />, { me: makeMe() });
    expect(await screen.findByText("Projeto com estado editável")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Estado do projeto" })).toHaveValue("preparacao");
    fireEvent.change(screen.getByRole("combobox", { name: "Estado do projeto" }), { target: { value: "construcao" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar estado" }));

    await waitFor(() => expect(changeProjectStatus).toHaveBeenCalledWith("proj-status", "construcao", ""));
    expect((await screen.findAllByText("Construção")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("não mostra o controlo de estado sem a flag do servidor", async () => {
    listProjects.mockResolvedValue([makeProject({ id: "proj-status-readonly", name: "Projeto sem estado editável", can_change_status: false })]);

    renderWithProviders(<ProjectsList />, { me: makeMe() });
    await screen.findByText("Projeto sem estado editável");
    expect(screen.queryByRole("button", { name: "Alterar estado" })).not.toBeInTheDocument();
  });

  it("mostra o erro ao alterar o estado na lista e mantém a confirmação aberta", async () => {
    const project = makeProject({ id: "proj-status-error", name: "Projeto com erro de estado", lifecycle_status: "preparacao", can_change_status: true });
    listProjects.mockResolvedValue([project]);
    const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
    changeProjectStatus.mockRejectedValue(new actual.ApiError(403, "Sem permissão para alterar o estado deste projeto."));

    renderWithProviders(<ProjectsList />, { me: makeMe() });
    await screen.findByText("Projeto com erro de estado");
    fireEvent.change(screen.getByRole("combobox", { name: "Estado do projeto" }), { target: { value: "construcao" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar estado" }));

    expect(await screen.findByText("Sem permissão para alterar o estado deste projeto.")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
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

  it("mostra o acesso a projetos apagados apenas com project.restore", async () => {
    const withoutPermission = renderWithProviders(<ProjectsList />, { me: makeMe(), route: "/projects?estado=todos" });
    expect(await screen.findByText("Projeto Sintético Sem PM")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Projetos apagados" })).not.toBeInTheDocument();
    withoutPermission.unmount();

    renderWithProviders(<ProjectsList />, {
      me: makeMe({ permissions: ["project.view_all", "project.restore"] }),
      route: "/projects?estado=todos",
    });
    expect(await screen.findByRole("link", { name: "Projetos apagados" })).toHaveAttribute("href", "/projects/deleted");
  });

  it("mostra apagar apenas quando can_delete vem ativo e exige motivo antes de refrescar a lista", async () => {
    const deletable = Object.assign(makeProject(), { can_delete: true });
    listProjects.mockResolvedValueOnce([deletable]).mockResolvedValueOnce([]);
    deleteProject.mockResolvedValue(undefined);
    renderWithProviders(<ProjectsList />, { me: makeMe(), route: "/projects?estado=todos" });

    await screen.findByText(deletable.name);
    fireEvent.click(screen.getByRole("button", { name: "Apagar projeto" }));
    const dialog = screen.getByRole("dialog", { name: "Apagar projeto" });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByLabelText("Motivo da remoção")).toBeRequired();
    expect(deleteProject).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Motivo da remoção"), { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar remoção" }));
    expect(await screen.findByText("Indique o motivo da remoção.")).toBeInTheDocument();
    expect(deleteProject).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Motivo da remoção"), { target: { value: "  Projeto duplicado  " } });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar remoção" }));
    await waitFor(() => expect(deleteProject).toHaveBeenCalledWith(deletable.id, "Projeto duplicado"));
    await screen.findByText("Nenhum projeto encontrado");
    expect(listProjects).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("dialog", { name: "Apagar projeto" })).not.toBeInTheDocument();
  });

  it("mantém o diálogo e apresenta erro quando o servidor recusa a remoção", async () => {
    const deletable = Object.assign(makeProject(), { can_delete: true });
    listProjects.mockResolvedValue([deletable]);
    deleteProject.mockRejectedValue(new Error("Sem permissão para apagar projetos."));
    renderWithProviders(<ProjectsList />, { me: makeMe(), route: "/projects?estado=todos" });

    await screen.findByText(deletable.name);
    fireEvent.click(screen.getByRole("button", { name: "Apagar projeto" }));
    fireEvent.change(screen.getByLabelText("Motivo da remoção"), { target: { value: "Duplicado" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar remoção" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Sem permissão para apagar projetos.");
    expect(screen.getByRole("dialog", { name: "Apagar projeto" })).toBeInTheDocument();
  });

  it("não mostra o botão de apagar quando can_delete está falso", async () => {
    listProjects.mockResolvedValue([Object.assign(makeProject(), { can_delete: false })]);
    renderWithProviders(<ProjectsList />, { me: makeMe(), route: "/projects?estado=todos" });

    await screen.findByText(makeProject().name);
    expect(screen.queryByRole("button", { name: "Apagar projeto" })).not.toBeInTheDocument();
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
