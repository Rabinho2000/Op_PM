import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { makeMe, makeProject, makeTask } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import Tasks from "./Tasks";

const { listTasks, listPeople, listProjects, updateTask } = vi.hoisted(() => ({
  listTasks: vi.fn(),
  listPeople: vi.fn(),
  listProjects: vi.fn(),
  updateTask: vi.fn(),
}));

const {
  getTaskListPreferences,
  updateTaskListPreferences,
  listTaskListViews,
  createTaskListView,
  updateTaskListView,
  deleteTaskListView,
} = vi.hoisted(() => ({
  getTaskListPreferences: vi.fn(),
  updateTaskListPreferences: vi.fn(),
  listTaskListViews: vi.fn(),
  createTaskListView: vi.fn(),
  updateTaskListView: vi.fn(),
  deleteTaskListView: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, listTasks, listPeople, listProjects, updateTask };
});

vi.mock("../api/taskListViews", async () => {
  const actual = await vi.importActual<typeof import("../api/taskListViews")>("../api/taskListViews");
  return {
    ...actual,
    getTaskListPreferences,
    updateTaskListPreferences,
    listTaskListViews,
    createTaskListView,
    updateTaskListView,
    deleteTaskListView,
  };
});

const DEFAULT_TASK_CONFIG = {
  columns: ["task", "project", "assignee", "priority", "due_date", "status"] as const,
  sort_by: "default" as const,
  sort_direction: "asc" as const,
  view: "lista" as const,
  filters: { project_id: "", assigned_to_person_id: "", priority: "", status: "", overdue_only: false },
};

type HistoryControls = { back: () => void; forward: () => void };

function HistoryProbe({ onReady }: { onReady: (controls: HistoryControls) => void }) {
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    onReady({ back: () => navigate(-1), forward: () => navigate(1) });
  }, [navigate, onReady]);

  return <output data-testid="tasks-location">{location.search}</output>;
}

describe("Tasks", () => {
  beforeEach(() => {
    localStorage.clear();
    for (const fn of [listTasks, listPeople, listProjects, updateTask, getTaskListPreferences, updateTaskListPreferences, listTaskListViews, createTaskListView, updateTaskListView, deleteTaskListView]) fn.mockReset();
    getTaskListPreferences.mockResolvedValue({ config: structuredClone(DEFAULT_TASK_CONFIG) });
    listTaskListViews.mockResolvedValue([]);
    updateTaskListPreferences.mockResolvedValue({ config: structuredClone(DEFAULT_TASK_CONFIG) });
    listPeople.mockResolvedValue([]);
    listProjects.mockResolvedValue([makeProject({ can_manage_tasks: true })]);
    listTasks.mockResolvedValue([
      makeTask(),
      makeTask({
        id: "task-2",
        title: "Resolver reclamação",
        task_type: "custom",
        priority: "urgent",
        is_overdue: true,
        due_date: "2026-09-01",
        status: "in_progress",
      }),
      makeTask({ id: "task-3", title: "Comissionamento", task_type: "comissionamento", can_edit: false }),
    ]);
  });

  it("altera o estado de uma tarefa e confirma visualmente a conclusão", async () => {
    updateTask.mockResolvedValue(makeTask({ status: "done" }));
    renderWithProviders(<Tasks />, { me: makeMe() });

    const select = await screen.findByLabelText("Estado da tarefa Visita técnica");
    fireEvent.change(select, { target: { value: "done" } });

    await waitFor(() => expect(updateTask).toHaveBeenCalledWith("task-1", { status: "done" }));
    expect(await screen.findByText("Tarefa concluída: Visita técnica")).toBeInTheDocument();
    expect(listTasks.mock.calls.length).toBeGreaterThanOrEqual(2); // recarrega do servidor
  });

  it("mostra o erro do servidor quando a transição é recusada", async () => {
    updateTask.mockRejectedValue(new ApiError(400, "Transição de estado não permitida"));
    renderWithProviders(<Tasks />, { me: makeMe() });

    const select = await screen.findByLabelText("Estado da tarefa Visita técnica");
    fireEvent.change(select, { target: { value: "blocked" } });
    expect(await screen.findByText("Transição de estado não permitida")).toBeInTheDocument();
  });

  it("só oferece transições permitidas pela máquina de estados", async () => {
    listTasks.mockResolvedValue([makeTask({ status: "blocked" })]);
    renderWithProviders(<Tasks />, { me: makeMe() });
    const select = await screen.findByLabelText("Estado da tarefa Visita técnica");
    const options = within(select).getAllByRole("option").map((o) => o.getAttribute("value"));
    expect(options).not.toContain("done");
  });

  it("destaca tarefas atrasadas/urgentes e mostra só leitura sem permissão", async () => {
    renderWithProviders(<Tasks />, { me: makeMe() });
    const urgentRow = (await screen.findByText("Resolver reclamação")).closest("tr");
    expect(urgentRow).toHaveClass("row--danger");
    expect(within(urgentRow as HTMLElement).getByText("Urgente")).toBeInTheDocument();
    expect(screen.queryByLabelText("Estado da tarefa Comissionamento")).not.toBeInTheDocument();
  });

  it("envia os filtros de projeto, prioridade e atraso ao servidor", async () => {
    renderWithProviders(<Tasks />, { me: makeMe(), route: "/tasks?prioridade=urgent&atrasadas=1" });
    await screen.findByText("Resolver reclamação");
    expect(listTasks).toHaveBeenLastCalledWith(expect.objectContaining({ priority: "urgent", overdue_only: true }));

    await screen.findByRole("option", { name: "Instalação Sintética de Teste" });
    fireEvent.change(screen.getByLabelText("Projeto"), { target: { value: "proj-1" } });
    await waitFor(() => expect(listTasks).toHaveBeenLastCalledWith(expect.objectContaining({ project_id: "proj-1" })));
  });

  it("vista Kanban agrupa as tarefas por estado", async () => {
    renderWithProviders(<Tasks />, { me: makeMe() });
    await screen.findByText("Resolver reclamação");
    fireEvent.click(screen.getByRole("button", { name: /Kanban/ }));

    const todo = await screen.findByRole("region", { name: "Por fazer (2)" });
    expect(within(todo).getByText("Visita técnica")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Em curso (1)" })).toBeInTheDocument();
  });

  it("esconde 'Nova tarefa' quando nenhum projeto permite criar tarefas", async () => {
    listProjects.mockResolvedValue([makeProject({ can_manage_tasks: false })]);
    renderWithProviders(<Tasks />, { me: makeMe() });
    await screen.findByText("Resolver reclamação");
    await waitFor(() => expect(listProjects).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: /Nova tarefa/ })).not.toBeInTheDocument();
  });

  it("mostra 'Nova tarefa' quando algum projeto permite criar tarefas", async () => {
    renderWithProviders(<Tasks />, { me: makeMe() });
    expect(await screen.findByRole("button", { name: /Nova tarefa/ })).toBeInTheDocument();
  });

  it("mostra estado vazio sem tarefas", async () => {
    listTasks.mockResolvedValue([]);
    renderWithProviders(<Tasks />, { me: makeMe() });
    expect(await screen.findByText("Nenhuma tarefa encontrada")).toBeInTheDocument();
  });

  it("permite esconder, reordenar e restaurar colunas da lista sem alterar o Kanban", async () => {
    renderWithProviders(<Tasks />, { me: makeMe() });
    await screen.findByText("Visita técnica");
    const table = screen.getByRole("table");
    const headings = () => [...table.querySelectorAll("thead th")].map((cell) => cell.textContent);

    expect(headings()).toEqual(["Tarefa", "Projeto", "Responsável", "Prioridade", "Prazo", "Estado"]);
    fireEvent.click(screen.getByRole("button", { name: "Colunas" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Mostrar Responsável" }));
    expect(headings()).toEqual(["Tarefa", "Projeto", "Prioridade", "Prazo", "Estado"]);
    fireEvent.click(screen.getByRole("button", { name: "Descer coluna Prioridade" }));
    expect(headings()).toEqual(["Tarefa", "Projeto", "Prazo", "Prioridade", "Estado"]);
    fireEvent.click(screen.getByRole("button", { name: "Restaurar colunas padrão" }));
    expect(headings()).toEqual(["Tarefa", "Projeto", "Responsável", "Prioridade", "Prazo", "Estado"]);

    fireEvent.click(screen.getByRole("button", { name: /Kanban/ }));
    expect(await screen.findByRole("region", { name: /Por fazer/ })).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("aplica ordenação à lista e conserva paginação de 20 cartões no Kanban", async () => {
    const manyTasks = Array.from({ length: 21 }, (_, index) =>
      makeTask({ id: `task-${index + 1}`, title: `Tarefa ${index + 1}`, task_type: "custom", status: "todo" })
    );
    listTasks.mockResolvedValue(manyTasks);
    renderWithProviders(<Tasks />, { me: makeMe() });
    await screen.findByText("Tarefa 21");

    fireEvent.change(screen.getByLabelText("Ordenar por"), { target: { value: "title" } });
    const rows = screen.getByRole("table").querySelectorAll("tbody tr");
    expect(rows[1]?.textContent).toContain("Tarefa 2");
    expect(rows[2]?.textContent).toContain("Tarefa 3");

    fireEvent.click(screen.getByRole("button", { name: /Kanban/ }));
    const todo = await screen.findByRole("region", { name: "Por fazer (21)" });
    expect(within(todo).getAllByTestId(/^task-card-/)).toHaveLength(20);
    fireEvent.click(within(todo).getByRole("button", { name: "Mostrar mais 1" }));
    expect(within(todo).getAllByTestId(/^task-card-/)).toHaveLength(21);
  });

  it("cria, aplica, atualiza, renomeia e remove vistas e guarda preferência explicitamente", async () => {
    const savedView = {
      id: "view-1",
      name: "Urgentes",
      config: { ...structuredClone(DEFAULT_TASK_CONFIG), columns: ["task", "project"] as const, sort_by: "priority" as const },
      created_at: "2026-10-16T09:00:00Z",
      updated_at: "2026-10-16T09:00:00Z",
    };
    listTaskListViews.mockResolvedValue([savedView]);
    createTaskListView.mockResolvedValue({ ...savedView, id: "view-2", name: "Nova vista" });
    updateTaskListView.mockResolvedValue({ ...savedView, name: "Urgentes renomeada" });
    deleteTaskListView.mockResolvedValue(undefined);
    const prompt = vi.spyOn(window, "prompt").mockReturnValue("Nova vista");
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);

    renderWithProviders(<Tasks />, { me: makeMe() });
    await screen.findByRole("option", { name: "Urgentes" });
    fireEvent.change(screen.getByLabelText("Vistas pessoais"), { target: { value: savedView.id } });
    fireEvent.click(screen.getByRole("button", { name: "Aplicar vista" }));
    await waitFor(() => expect(screen.getByLabelText("Ordenar por")).toHaveValue("priority"));
    expect(screen.queryByRole("columnheader", { name: "Responsável" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Atualizar vista" }));
    await waitFor(() => expect(updateTaskListView).toHaveBeenCalledWith(savedView.id, { config: expect.any(Object) }));
    fireEvent.click(screen.getByRole("button", { name: "Renomear vista" }));
    await waitFor(() => expect(updateTaskListView).toHaveBeenCalledWith(savedView.id, { name: "Nova vista" }));
    fireEvent.click(screen.getByRole("button", { name: "Eliminar vista" }));
    await waitFor(() => expect(deleteTaskListView).toHaveBeenCalledWith(savedView.id));
    expect(confirm).toHaveBeenCalledWith("Eliminar a vista «Urgentes renomeada»?");

    fireEvent.click(screen.getByRole("button", { name: "Guardar preferência de abertura" }));
    await waitFor(() => expect(updateTaskListPreferences).toHaveBeenCalledWith(expect.objectContaining({ view: "lista", sort_by: "priority" })));
    expect(await screen.findAllByText("Preferência de abertura guardada.")).not.toHaveLength(0);
    prompt.mockRestore();
    confirm.mockRestore();
  });

  it("preserva os aliases de URL e o filtro de estado sem o aplicar no Kanban", async () => {
    renderWithProviders(<Tasks />, { me: makeMe(), route: "/tasks?prioridade=urgent&atrasadas=1&status=done&view=kanban" });
    await screen.findByText("Resolver reclamação");
    expect(listTasks).toHaveBeenLastCalledWith(expect.objectContaining({ priority: "urgent", overdue_only: true, status: undefined }));
    expect(screen.getByText("O filtro de estado aplica-se apenas à Lista.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Lista/ }));
    await waitFor(() => expect(listTasks).toHaveBeenLastCalledWith(expect.objectContaining({ status: "done" })));
  });

  it("restaura a vista Lista ao avançar para uma URL sem view", async () => {
    let historyControls: HistoryControls | undefined;
    const registerHistory = (controls: HistoryControls) => {
      historyControls = controls;
    };

    renderWithProviders(
      <>
        <Tasks />
        <HistoryProbe onReady={registerHistory} />
      </>,
      { me: makeMe(), route: "/tasks?prioridade=urgent&atrasadas=1&status=done&view=kanban" },
    );

    expect(await screen.findByRole("region", { name: /Por fazer/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Kanban/ })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: /Lista/ }));
    await waitFor(() => {
      expect(screen.getByTestId("tasks-location")).toHaveTextContent("?prioridade=urgent&atrasadas=1&status=done");
      expect(screen.getByRole("button", { name: /Lista/ })).toHaveAttribute("aria-pressed", "true");
    });

    expect(historyControls).toBeDefined();
    act(() => {
      historyControls?.back();
    });
    await waitFor(() => expect(screen.getByRole("button", { name: /Kanban/ })).toHaveAttribute("aria-pressed", "true"));

    act(() => {
      historyControls?.forward();
    });
    await waitFor(() => {
      expect(screen.getByTestId("tasks-location")).toHaveTextContent("?prioridade=urgent&atrasadas=1&status=done");
      expect(screen.getByRole("button", { name: /Lista/ })).toHaveAttribute("aria-pressed", "true");
    });
    expect(screen.queryByRole("table")).toBeInTheDocument();
  });

  it("mostra erro de preferência sem falso sucesso e permite continuar com as tarefas", async () => {
    getTaskListPreferences.mockRejectedValue(new Error("Preferência indisponível"));
    renderWithProviders(<Tasks />, { me: makeMe() });
    expect(await screen.findByText("Visita técnica")).toBeInTheDocument();
    expect(await screen.findByText(/Preferência de abertura indisponível: Preferência indisponível/)).toBeInTheDocument();

    updateTaskListPreferences.mockRejectedValue(new Error("Preferência recusada"));
    fireEvent.click(screen.getByRole("button", { name: "Guardar preferência de abertura" }));
    expect(await screen.findByText("Preferência recusada")).toBeInTheDocument();
    expect(screen.queryByText("Preferência de abertura guardada.")).not.toBeInTheDocument();
  });
});
