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
