import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { makeMe, makeProject } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import ProjectsList, { toApiFilters } from "./ProjectsList";

const { listProjects, listPeople } = vi.hoisted(() => ({ listProjects: vi.fn(), listPeople: vi.fn() }));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, listProjects, listPeople };
});

describe("ProjectsList (filtros)", () => {
  beforeEach(() => {
    listProjects.mockReset();
    listPeople.mockReset();
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
    expect(screen.getByText("2 projetos")).toBeInTheDocument();
    expect(screen.getByText("Fotos pendentes")).toBeInTheDocument();
    expect(screen.getByText("sem email")).toBeInTheDocument();
    expect(screen.getAllByRole("progressbar")).toHaveLength(2);
  });

  it("envia os filtros de estado, PM e datas ao servidor", async () => {
    renderWithProviders(<ProjectsList />, { me: makeMe() });
    await screen.findByText("Projeto Sintético Sem PM");
    await screen.findByRole("option", { name: "PM Sintético Um" });

    fireEvent.change(screen.getByLabelText("Estado"), { target: { value: "concluido" } });
    fireEvent.change(screen.getByLabelText("PM"), { target: { value: "p-pm" } });
    fireEvent.change(screen.getByLabelText("Início a partir de"), { target: { value: "2026-09-01" } });
    fireEvent.change(screen.getByLabelText("Início até"), { target: { value: "2026-09-30" } });

    await waitFor(() =>
      expect(listProjects).toHaveBeenLastCalledWith({
        q: undefined,
        status: "concluido",
        pm_person_id: "p-pm",
        is_active: true,
        start_from: "2026-09-01",
        start_to: "2026-09-30",
      })
    );
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
    expect(toApiFilters({ search: "  ", status: "", pm: "", active: "all", startFrom: "", startTo: "" })).toEqual({
      q: undefined,
      status: undefined,
      pm_person_id: undefined,
      is_active: undefined,
      start_from: undefined,
      start_to: undefined,
    });
  });
});
