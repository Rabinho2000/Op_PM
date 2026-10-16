import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Project } from "../api/client";
import { makeMe, makeProject } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import {
  InstallerInventoryPage,
  InstallerProjectsPage,
  InstallerTeamsPage,
  InstallerWorksPage,
} from "./InstallerAccessPages";

const api = vi.hoisted(() => ({
  listProjects: vi.fn(),
  listInstallerInventory: vi.fn(),
  listInstallerAccessTeams: vi.fn(),
  getWorksCalendar: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, ...api };
});

const EXTERNAL_ME = makeMe({
  roles: ["instalador_colaborador"],
  permissions: [
    "project.view_assigned_installer",
    "task.view_assigned_installer",
    "works_calendar.view_assigned_installer",
    "installer_team.view_assigned_installer",
    "inventory.view_assigned_installer",
    "time_bank.view_own",
  ],
});

beforeEach(() => {
  Object.values(api).forEach((mock) => mock.mockReset());
  api.listProjects.mockResolvedValue([makeProject({ id: "project-a", name: "Obra A" }) as Project]);
  api.listInstallerInventory.mockResolvedValue({
    items: [{ project_id: "project-a", project_name: "Obra A", article_name: "Painel", unit: "un", required_quantity: "4.00", reserved_quantity: "4.00", consumed_quantity: "1.00", delivered_quantity: "2.00", locations: [{ label: "Obra A" }] }],
    total: 1,
    limit: 100,
    offset: 0,
  });
  api.listInstallerAccessTeams.mockResolvedValue([{ id: "installer-a", name: "Instalador A", is_active: true, teams: [{ id: "team-a", installer_id: "installer-a", name: "Equipa A", is_active: true }] }]);
  api.getWorksCalendar.mockResolvedValue({ start: "2026-10-15", end: "2026-11-14", works: [], unscheduled: [], summary: { works: 0, conflicts: 0, estimated: 0, unscheduled: 0 } });
});

describe("consulta do colaborador por instalador", () => {
  it("carrega projetos atribuídos sem consultar o catálogo global de pessoas", async () => {
    renderWithProviders(<InstallerProjectsPage />, { me: EXTERNAL_ME });
    expect(await screen.findByText("Obra A")).toBeInTheDocument();
    expect(api.listProjects).toHaveBeenCalledWith(expect.objectContaining({ is_active: true }));
  });

  it("usa exclusivamente os endpoints scoped de inventário e equipas", async () => {
    renderWithProviders(<InstallerInventoryPage />, { me: EXTERNAL_ME, route: "/inventory" });
    expect(await screen.findByText("Painel")).toBeInTheDocument();
    expect(api.listInstallerInventory).toHaveBeenCalledWith({ projectId: undefined, limit: 100, offset: 0 });

    renderWithProviders(<InstallerTeamsPage />, { me: EXTERNAL_ME, route: "/works/teams" });
    expect(await screen.findByText("Equipa A")).toBeInTheDocument();
    expect(api.listInstallerAccessTeams).toHaveBeenCalledTimes(1);
  });

  it("carrega o calendário scoped sem expor controlos de planeamento", async () => {
    renderWithProviders(<InstallerWorksPage />, { me: EXTERNAL_ME, route: "/works" });
    await waitFor(() => expect(api.getWorksCalendar).toHaveBeenCalledTimes(1));
    expect(screen.getByText(/Modo consulta/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /guardar|aplicar|arrastar/i })).not.toBeInTheDocument();
  });
});
