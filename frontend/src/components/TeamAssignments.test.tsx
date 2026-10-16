import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import type { Installer, TeamAssignment } from "../api/client";
import { makeProject } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import TeamAssignments from "./TeamAssignments";

const { listTeamAssignments, listInstallers, createTeamAssignment, updateTeamAssignment, deleteTeamAssignment } = vi.hoisted(() => ({
  listTeamAssignments: vi.fn(),
  listInstallers: vi.fn(),
  createTeamAssignment: vi.fn(),
  updateTeamAssignment: vi.fn(),
  deleteTeamAssignment: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, listTeamAssignments, listInstallers, createTeamAssignment, updateTeamAssignment, deleteTeamAssignment };
});

const INSTALLERS: Installer[] = [
  {
    id: "installer-sintetico",
    name: "Instalador Sintético",
    is_active: true,
    project_count: 1,
    teams: [
      { id: "team-active", name: "Equipa Activa", leader_name: "Chefe Sintético", leader_phone: "910 000 002", is_active: true, project_count: 0 },
      { id: "team-inactive", name: "Equipa Inactiva", leader_name: null, leader_phone: null, is_active: false, project_count: 0 },
    ],
  },
];

const ASSIGNMENT: TeamAssignment = {
  id: "assignment-1",
  project_id: "project-1",
  installer_id: "installer-sintetico",
  team_id: "team-active",
  start_date: "2026-09-10",
  end_date: "2026-09-15",
  note: "Nota sintética",
  created_by_person_id: "person-sintetica",
  team_name: "Equipa Activa",
  team_leader_name: "Chefe Sintético",
  team_leader_phone: "910 000 002",
};

const PROJECT = makeProject({
  id: "project-1",
  installer_id: "installer-sintetico",
  installer_name: "Instalador Sintético",
  can_plan_work: true,
  work_start_date: "2026-09-01",
  work_end_date: "2026-09-30",
});

beforeEach(() => {
  listTeamAssignments.mockReset().mockResolvedValue([ASSIGNMENT]);
  listInstallers.mockReset().mockResolvedValue(INSTALLERS);
  createTeamAssignment.mockReset().mockResolvedValue({ ...ASSIGNMENT, id: "assignment-2", note: "Nova nota", start_date: "2026-09-20", end_date: "2026-09-22" });
  updateTeamAssignment.mockReset().mockResolvedValue(ASSIGNMENT);
  deleteTeamAssignment.mockReset().mockResolvedValue(undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("TeamAssignments", () => {
  it("limita o selector às equipas activas e cria uma afectação", async () => {
    renderWithProviders(<TeamAssignments project={PROJECT} />);

    expect(await screen.findByText("Equipa Activa")).toBeInTheDocument();
    expect(screen.getByText(/chefe Chefe Sintético/)).toBeInTheDocument();
    expect(screen.getByText(/910 000 002/)).toBeInTheDocument();
    expect(screen.getByText("Nota sintética")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Adicionar equipa" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Adicionar equipa" }));
    const select = screen.getByLabelText("Equipa");
    expect(screen.getByRole("option", { name: /Equipa Activa/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Equipa Inactiva/ })).not.toBeInTheDocument();
    fireEvent.change(select, { target: { value: "team-active" } });
    fireEvent.change(screen.getByLabelText(/Nota/), { target: { value: "Nova nota" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));

    await waitFor(() => expect(createTeamAssignment).toHaveBeenCalledWith("project-1", {
      team_id: "team-active",
      start_date: "2026-09-01",
      end_date: "2026-09-30",
      note: "Nova nota",
    }));
    expect(await screen.findByText("Nova nota")).toBeInTheDocument();
  });

  it("confirma a remoção e esconde a afectação removida", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderWithProviders(<TeamAssignments project={PROJECT} />);

    expect(await screen.findByText("Nota sintética")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remover" }));

    await waitFor(() => expect(deleteTeamAssignment).toHaveBeenCalledWith("project-1", "assignment-1"));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("Equipa Activa"));
    await waitFor(() => expect(screen.queryByText("Nota sintética")).not.toBeInTheDocument());
  });

  it("não mostra operações quando o servidor não autoriza planear", async () => {
    renderWithProviders(<TeamAssignments project={{ ...PROJECT, can_plan_work: false }} />);

    expect(await screen.findByText("Nota sintética")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Adicionar equipa" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Editar" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remover" })).not.toBeInTheDocument();
  });
});
