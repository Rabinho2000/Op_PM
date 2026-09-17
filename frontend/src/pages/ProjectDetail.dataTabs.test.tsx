// Tabs "Dados da instalação" e "Licenciamento" no detalhe do projeto:
// visíveis só a quem tem permissão, edição só a quem tem a permissão de
// escrita correspondente.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  ProjectCommunicationData,
  ProjectInstallationData,
  ProjectLicensingData,
} from "../api/client";
import { makeMe, makeProject, makeTask } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import ProjectDetail from "./ProjectDetail";

const api = vi.hoisted(() => ({
  getProject: vi.fn(),
  getProjectHistory: vi.fn(),
  listTasks: vi.fn(),
  listPeople: vi.fn(),
  getProjectInstallationData: vi.fn(),
  getProjectLicensingData: vi.fn(),
  getProjectCommunicationData: vi.fn(),
  updateProjectInstallationData: vi.fn(),
  updateProjectLicensingData: vi.fn(),
  updateProjectCommunicationData: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, ...api };
});

function installation(overrides: Partial<ProjectInstallationData> = {}): ProjectInstallationData {
  return {
    project_id: "proj-1",
    client_nif: "500111222",
    contact_person_name: null,
    contact_person_role: null,
    contact_email: null,
    contact_phone: "912000000",
    address: null,
    district: null,
    municipality: null,
    power_kwp: 9.5,
    panel_count: 20,
    panel_power_wp: 450,
    inverters: null,
    batteries: null,
    has_backup: null,
    ev_chargers: null,
    installation_type: null,
    injection_type: null,
    om_notes: null,
    notes: "",
    updated_at: null,
    ...overrides,
  };
}

function licensing(overrides: Partial<ProjectLicensingData> = {}): ProjectLicensingData {
  return {
    project_id: "proj-1",
    upac_number: "UPAC-001",
    dgeg_number: null,
    cadastro_number: null,
    licensing_status: null,
    registration_date: null,
    certification_request_date: null,
    inspecting_entity: null,
    inspection_date: null,
    certificate_date: null,
    installer: null,
    commercializer: null,
    annual_production_kwh: null,
    comments: "",
    updated_at: null,
    ...overrides,
  };
}

function communication(overrides: Partial<ProjectCommunicationData> = {}): ProjectCommunicationData {
  return {
    project_id: "proj-1",
    operator: "Operador Teste",
    gsm_m2m_number: "911000000",
    card_identifier: null,
    communication_status: null,
    notes: "",
    updated_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.getProject.mockResolvedValue(makeProject());
  api.getProjectHistory.mockResolvedValue([]);
  api.listTasks.mockResolvedValue([makeTask()]);
  api.listPeople.mockResolvedValue([]);
  api.getProjectInstallationData.mockResolvedValue(installation());
  api.getProjectLicensingData.mockResolvedValue(licensing());
  api.getProjectCommunicationData.mockResolvedValue(communication());
});

describe("Detalhe do projeto — dados de instalação/licenciamento", () => {
  it("esconde as tabs sem permissão de visualização", async () => {
    renderWithProviders(<ProjectDetail />, {
      me: makeMe({ permissions: ["project.view_all"] }),
      route: "/projects/proj-1",
      path: "/projects/:projectId",
    });
    await screen.findByRole("heading", { level: 1, name: makeProject().name });
    expect(screen.queryByRole("tab", { name: /dados da instalação/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /licenciamento/i })).not.toBeInTheDocument();
  });

  it("mostra os dados de instalação e permite editar com permissão", async () => {
    renderWithProviders(<ProjectDetail />, {
      me: makeMe({
        permissions: ["project.view_all", "project.edit_all", "project.view_installation_data", "project.edit_installation_data"],
      }),
      route: "/projects/proj-1",
      path: "/projects/:projectId",
    });
    await screen.findByRole("heading", { level: 1, name: makeProject().name });
    fireEvent.click(screen.getByRole("tab", { name: /dados da instalação/i }));

    expect(await screen.findByText("500111222")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /editar/i }));

    const nifInput = screen.getByLabelText("NIF") as HTMLInputElement;
    fireEvent.change(nifInput, { target: { value: "999888777" } });

    api.updateProjectInstallationData.mockResolvedValue(installation({ client_nif: "999888777" }));
    fireEvent.click(screen.getByRole("button", { name: /^guardar$/i }));

    await waitFor(() => expect(api.updateProjectInstallationData).toHaveBeenCalled());
    const [calledProjectId, calledChanges] = api.updateProjectInstallationData.mock.calls[0];
    expect(calledProjectId).toBe("proj-1");
    expect(calledChanges).toMatchObject({ client_nif: "999888777" });
  });

  it("mostra dados de licenciamento sem edição sem permissão de escrita", async () => {
    renderWithProviders(<ProjectDetail />, {
      me: makeMe({ permissions: ["project.view_all", "project.view_licensing_data"] }),
      route: "/projects/proj-1",
      path: "/projects/:projectId",
    });
    await screen.findByRole("heading", { level: 1, name: makeProject().name });
    fireEvent.click(screen.getByRole("tab", { name: /licenciamento/i }));

    expect(await screen.findByText("UPAC-001")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /editar/i })).not.toBeInTheDocument();
  });

  it("esconde a comunicação/M2M sem permissão dedicada mesmo vendo licenciamento", async () => {
    renderWithProviders(<ProjectDetail />, {
      me: makeMe({ permissions: ["project.view_all", "project.view_licensing_data"] }),
      route: "/projects/proj-1",
      path: "/projects/:projectId",
    });
    await screen.findByRole("heading", { level: 1, name: makeProject().name });
    fireEvent.click(screen.getByRole("tab", { name: /licenciamento/i }));

    await screen.findByText("UPAC-001");
    expect(screen.getByText(/sem permiss.o para ver estes dados/i)).toBeInTheDocument();
    expect(screen.queryByText("911000000")).not.toBeInTheDocument();
  });
});
