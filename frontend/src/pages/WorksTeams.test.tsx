import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Installer, TeamLocationAssignment, TeamsView } from "../api/client";
import { makeMe } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import { todayIsoLisbon } from "../utils/dates";
import WorksTeams from "./WorksTeams";

const { getWorksTeams, listInstallers, getLifecycleStatuses } = vi.hoisted(() => ({
  getWorksTeams: vi.fn(),
  listInstallers: vi.fn(),
  getLifecycleStatuses: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, getWorksTeams, listInstallers, getLifecycleStatuses };
});

const INSTALLERS: Installer[] = [
  {
    id: "installer-sintetico",
    name: "Instalador Sintético",
    is_active: true,
    project_count: 2,
    teams: [
      { id: "team-livre", name: "Equipa Livre", leader_name: "Chefe Livre", leader_phone: "910 000 001", is_active: true, project_count: 0 },
      { id: "team-ocupada", name: "Equipa Ocupada", leader_name: null, leader_phone: null, is_active: true, project_count: 1 },
      { id: "team-invisivel", name: "Equipa Reservada", leader_name: null, leader_phone: null, is_active: true, project_count: 0 },
    ],
  },
];

const visibleAssignment: TeamLocationAssignment = {
  id: "assignment-visible",
  project_id: "project-visible",
  project_name: "Obra Visível Sintética",
  address: "Rua Sintética, 1",
  lat: 38.7,
  lon: -9.1,
  pm_person_id: "person-pm",
  pm_display_name: "PM Sintético",
  lifecycle_status: "construcao",
  start_date: "2026-10-05",
  end_date: "2026-10-11",
  note: "",
  conflict: true,
};

const VIEW: TeamsView = {
  date: "2026-10-05",
  days: 14,
  installers: [
    {
      id: "installer-sintetico",
      name: "Instalador Sintético",
      teams: [
        { id: "team-livre", installer_id: "installer-sintetico", name: "Equipa Livre", status: "livre", free: true, assignments: [] },
        { id: "team-ocupada", installer_id: "installer-sintetico", name: "Equipa Ocupada", status: "ocupada", free: false, assignments: [visibleAssignment] },
        { id: "team-invisivel", installer_id: "installer-sintetico", name: "Equipa Reservada", status: "ocupada_noutra_obra", free: false, assignments: [] },
      ],
    },
  ],
};

const ME = makeMe({ permissions: ["project.view_all"] });

beforeEach(() => {
  getWorksTeams.mockReset().mockResolvedValue(VIEW);
  listInstallers.mockReset().mockResolvedValue(INSTALLERS);
  getLifecycleStatuses.mockReset().mockResolvedValue([{ code: "construcao", label: "Construção", flow_position: 2 }]);
});

describe("WorksTeams", () => {
  it("agrupa por instalador/equipa e mostra livre, ocupada noutra obra e conflito", async () => {
    renderWithProviders(<WorksTeams />, {
      me: ME,
      route: "/works/teams?date=2026-10-05&days=14&installer_id=installer-sintetico",
      path: "/works/teams",
    });

    await waitFor(() => expect(getWorksTeams).toHaveBeenLastCalledWith({ date: "2026-10-05", days: 14, installer_id: "installer-sintetico" }));
    expect(await screen.findByRole("heading", { name: "Instalador Sintético" })).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /Equipa Livre.*Livre/ })).toBeInTheDocument();
    expect(screen.getAllByText("Ocupada noutra obra").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole("link", { name: "Obra Visível Sintética" })).toHaveAttribute("href", "/projects/project-visible");
    expect(screen.getByText("Rua Sintética, 1")).toBeInTheDocument();
    expect(screen.getByText(/PM PM Sintético/)).toBeInTheDocument();
    expect(screen.getByText("Conflito")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Ver no mapa/ })).toHaveAttribute("href", "/map");
    expect(screen.queryByText("Obra invisível")).not.toBeInTheDocument();
  });

  it("lê o período do URL, ignora valores inválidos e actualiza os parâmetros ao filtrar", async () => {
    renderWithProviders(<WorksTeams />, {
      me: ME,
      route: "/works/teams?date=inválida&days=999&installer_id=desconhecido",
      path: "/works/teams",
    });

    expect(await screen.findByRole("heading", { name: "Instalador Sintético" })).toBeInTheDocument();
    await waitFor(() => expect(getWorksTeams).toHaveBeenLastCalledWith({ date: todayIsoLisbon(), days: 1, installer_id: undefined }));

    fireEvent.change(screen.getByLabelText("Data"), { target: { value: "2026-10-06" } });
    fireEvent.click(screen.getByRole("button", { name: "2 semanas" }));
    fireEvent.change(screen.getByLabelText("Instalador"), { target: { value: "installer-sintetico" } });
    await waitFor(() => expect(getWorksTeams).toHaveBeenLastCalledWith({ date: "2026-10-06", days: 14, installer_id: "installer-sintetico" }));
  });
});
