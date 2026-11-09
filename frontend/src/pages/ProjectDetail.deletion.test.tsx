import { fireEvent, screen, waitFor } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { makeMe, makeProject } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import ProjectDetail from "./ProjectDetail";

const { getProject, getProjectHistory, listTasks, listPeople, deleteProject } = vi.hoisted(() => ({
  getProject: vi.fn(),
  getProjectHistory: vi.fn(),
  listTasks: vi.fn(),
  listPeople: vi.fn(),
  deleteProject: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, getProject, getProjectHistory, listTasks, listPeople, deleteProject };
});

function renderDetail() {
  return renderWithProviders(
    <Routes>
      <Route path="/projects/:projectId" element={<ProjectDetail />} />
      <Route path="/projects" element={<h1>Lista de projetos</h1>} />
    </Routes>,
    { me: makeMe({ permissions: ["project.view_all", "project.delete"] }), route: "/projects/proj-1" }
  );
}

beforeEach(() => {
  getProject.mockReset();
  getProjectHistory.mockReset();
  listTasks.mockReset();
  listPeople.mockReset();
  deleteProject.mockReset();
  getProject.mockResolvedValue(makeProject({ can_delete: false }));
  getProjectHistory.mockResolvedValue([]);
  listTasks.mockResolvedValue([]);
  listPeople.mockResolvedValue([]);
});

describe("Remoção no detalhe do projeto", () => {
  it("mostra apagar segundo a flag can_delete do servidor e regressa à lista após sucesso", async () => {
    const { unmount } = renderDetail();
    await screen.findByRole("heading", { level: 1, name: makeProject().name });
    expect(screen.queryByRole("button", { name: "Apagar projeto" })).not.toBeInTheDocument();
    unmount();

    const deletable = makeProject({ can_delete: true });
    getProject.mockResolvedValue(deletable);
    deleteProject.mockResolvedValue(undefined);
    renderDetail();
    await screen.findByRole("heading", { level: 1, name: deletable.name });

    fireEvent.click(screen.getByRole("button", { name: "Apagar projeto" }));
    fireEvent.change(screen.getByLabelText("Motivo da remoção"), { target: { value: "Projeto duplicado" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar remoção" }));

    await waitFor(() => expect(deleteProject).toHaveBeenCalledWith(deletable.id, "Projeto duplicado"));
    expect(await screen.findByRole("heading", { name: "Lista de projetos" })).toBeInTheDocument();
  });
});
