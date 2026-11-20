import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { makeMe, makeProject } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import ProjectDetail from "./ProjectDetail";

const api = vi.hoisted(() => ({
  getProject: vi.fn(),
  getProjectHistory: vi.fn(),
  listTasks: vi.fn(),
  listPeople: vi.fn(),
  getProjectProcess: vi.fn(),
  getSafetySheet: vi.fn(),
  getClientReport: vi.fn(),
  listInstallers: vi.fn(),
  listTeamAssignments: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, ...api };
});

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.getProject.mockResolvedValue(makeProject());
  api.getProjectHistory.mockResolvedValue([]);
  api.listTasks.mockResolvedValue([]);
  api.listPeople.mockResolvedValue([]);
  api.listInstallers.mockResolvedValue([]);
  api.listTeamAssignments.mockResolvedValue([]);
});

function renderTab(tab: string) {
  return renderWithProviders(<ProjectDetail />, {
    me: makeMe({ permissions: ["project.view_all"] }),
    route: `/projects/proj-1?tab=${tab}`,
    path: "/projects/:projectId",
  });
}

describe("Detalhe do projeto — erros por secção", () => {
  it("mostra o erro do histórico (e não 'sem alterações') e volta a carregar ao tentar de novo", async () => {
    api.getProjectHistory.mockRejectedValueOnce(new ApiError(403, "Sem permissão para ver o histórico."));
    renderTab("historico");

    const panel = await screen.findByRole("tabpanel");
    expect(await within(panel).findByText("Sem permissão para ver o histórico.")).toBeInTheDocument();
    expect(within(panel).getByTestId("error-state")).toBeInTheDocument();
    expect(within(panel).queryByText("Sem alterações registadas.")).not.toBeInTheDocument();

    api.getProjectHistory.mockResolvedValueOnce([]);
    fireEvent.click(within(panel).getByRole("button", { name: "Tentar novamente" }));

    expect(await within(panel).findByText("Sem alterações registadas.")).toBeInTheDocument();
    expect(within(panel).queryByTestId("error-state")).not.toBeInTheDocument();
    expect(api.getProjectHistory).toHaveBeenCalledTimes(2);
    // O retry é só da secção: o projeto não é pedido outra vez.
    expect(api.getProject).toHaveBeenCalledTimes(1);
  });

  it("mostra o erro das tarefas (e não 'sem tarefas') e volta a carregar ao tentar de novo", async () => {
    api.listTasks.mockRejectedValueOnce(new Error("rede em baixo"));
    renderTab("tarefas");

    const panel = await screen.findByRole("tabpanel");
    expect(await within(panel).findByText("Não foi possível contactar o servidor.")).toBeInTheDocument();
    expect(within(panel).queryByText("Sem tarefas neste projeto.")).not.toBeInTheDocument();

    api.listTasks.mockResolvedValueOnce([]);
    fireEvent.click(within(panel).getByRole("button", { name: "Tentar novamente" }));

    expect(await within(panel).findByText("Sem tarefas neste projeto.")).toBeInTheDocument();
    expect(api.listTasks).toHaveBeenCalledTimes(2);
  });

  it("projeto foreign base-only (sem âmbito) não pede histórico nem tarefas e carrega o projeto uma vez", async () => {
    api.getProject.mockResolvedValue(makeProject({ can_view_project_scope: false }));
    renderTab("resumo");

    await screen.findByRole("tabpanel");
    await waitFor(() => expect(api.getProject).toHaveBeenCalledTimes(1));
    expect(api.getProjectHistory).not.toHaveBeenCalled();
    expect(api.listTasks).not.toHaveBeenCalled();
    expect(screen.queryByRole("tab", { name: /Histórico/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /Tarefas/ })).not.toBeInTheDocument();
  });

  it("projeto foreign não mostra o badge de estado das tarefas (valor por omissão enganador); com âmbito mostra", async () => {
    api.getProject.mockResolvedValue(makeProject({ can_view_project_scope: false, status: "nao_iniciado" }));
    const { unmount } = renderTab("resumo");
    await screen.findByRole("tabpanel");
    await waitFor(() => expect(api.getProject).toHaveBeenCalledTimes(1));
    expect(screen.queryByText("Não iniciado")).not.toBeInTheDocument();
    unmount();

    api.getProject.mockResolvedValue(makeProject({ can_view_project_scope: true, status: "em_curso" }));
    renderTab("resumo");
    await screen.findByRole("tabpanel");
    expect((await screen.findAllByText("Em curso")).length).toBeGreaterThan(0);
  });

  it.each(["processo", "seguranca", "relatorio", "tarefas", "historico", "cliente"])(
    "projeto foreign: ?tab=%s cai em resumo e não monta sub-recursos nem o plano de obra",
    async (requested) => {
      api.getProject.mockResolvedValue(makeProject({ can_view_project_scope: false }));
      renderTab(requested);

      const panel = await screen.findByRole("tabpanel");
      await waitFor(() => expect(api.getProject).toHaveBeenCalledTimes(1));
      expect(panel).toHaveAttribute("id", "panel-resumo");
      expect(screen.getByRole("tab", { name: "Resumo" })).toHaveAttribute("aria-selected", "true");
      for (const fn of [
        api.getProjectProcess,
        api.getSafetySheet,
        api.getClientReport,
        api.getProjectHistory,
        api.listTasks,
        api.listInstallers,
        api.listTeamAssignments,
      ]) {
        expect(fn).not.toHaveBeenCalled();
      }
    }
  );

  it("avisa quando a lista de pessoas não carrega e permite voltar a pedi-la", async () => {
    api.listPeople.mockRejectedValueOnce(new ApiError(500, "Erro interno."));
    renderTab("tarefas");

    const panel = await screen.findByRole("tabpanel");
    expect(await within(panel).findByText("Não foi possível carregar a lista de pessoas.")).toBeInTheDocument();

    api.listPeople.mockResolvedValueOnce([]);
    fireEvent.click(within(panel).getByRole("button", { name: "Tentar novamente" }));
    await waitFor(() =>
      expect(within(panel).queryByText("Não foi possível carregar a lista de pessoas.")).not.toBeInTheDocument()
    );
    expect(api.listPeople).toHaveBeenCalledTimes(2);
  });
});
