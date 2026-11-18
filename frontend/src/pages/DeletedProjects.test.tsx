import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { makeMe, makeProject } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import DeletedProjects from "./DeletedProjects";

const { listDeletedProjects, restoreProject } = vi.hoisted(() => ({
  listDeletedProjects: vi.fn(),
  restoreProject: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, listDeletedProjects, restoreProject };
});

const deletedProject = (id: string, can_restore: boolean) =>
  Object.assign(makeProject({ id, name: `Projeto apagado ${id}` }), {
    deleted_at: "2026-10-20T10:00:00Z",
    deleted_by_person_id: "person-deleter",
    can_delete: false,
    can_restore,
  });

const restoreMe = makeMe({ permissions: ["project.view_all", "project.restore"] });

beforeEach(() => {
  listDeletedProjects.mockReset();
  restoreProject.mockReset();
  listDeletedProjects.mockResolvedValue([]);
});

describe("Projetos apagados", () => {
  it("não carrega nem expõe a vista sem project.restore", () => {
    renderWithProviders(<DeletedProjects />, { me: makeMe({ permissions: ["project.view_all"] }) });

    expect(listDeletedProjects).not.toHaveBeenCalled();
    expect(screen.queryByRole("heading", { name: "Projetos apagados" })).not.toBeInTheDocument();
  });

  it("mostra apenas can_restore e remove da lista após restaurar", async () => {
    const restorable = deletedProject("restore-1", true);
    const protectedProject = deletedProject("restore-2", false);
    listDeletedProjects.mockResolvedValue([restorable, protectedProject]);
    restoreProject.mockResolvedValue(makeProject({ id: restorable.id }));
    renderWithProviders(<DeletedProjects />, { me: restoreMe });

    expect(await screen.findByText(restorable.name)).toBeInTheDocument();
    expect(screen.getByText(protectedProject.name)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Restaurar" })).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Restaurar" }));

    await waitFor(() => expect(restoreProject).toHaveBeenCalledWith(restorable.id));
    await waitFor(() => expect(screen.queryByText(restorable.name)).not.toBeInTheDocument());
    expect(screen.getByText(protectedProject.name)).toBeInTheDocument();
  });

  it("mantém o projeto apagado e apresenta erro se a restauração falhar", async () => {
    const restorable = deletedProject("restore-error", true);
    listDeletedProjects.mockResolvedValue([restorable]);
    restoreProject.mockRejectedValue(new Error("Sem permissão para restaurar projetos."));
    renderWithProviders(<DeletedProjects />, { me: restoreMe });

    await screen.findByText(restorable.name);
    fireEvent.click(screen.getByRole("button", { name: "Restaurar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Sem permissão para restaurar projetos.");
    expect(screen.getByText(restorable.name)).toBeInTheDocument();
  });
});
