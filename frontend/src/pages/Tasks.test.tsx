import { fireEvent, screen, waitFor, within } from "@testing-library/react";
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

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, listTasks, listPeople, listProjects, updateTask };
});

describe("Tasks", () => {
  beforeEach(() => {
    localStorage.clear();
    for (const fn of [listTasks, listPeople, listProjects, updateTask]) fn.mockReset();
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
});
