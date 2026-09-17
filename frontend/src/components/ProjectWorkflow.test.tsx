import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ProjectWorkflow as Workflow, WorkflowStage } from "../api/client";
import { renderWithProviders } from "../test/render";
import ProjectWorkflow from "./ProjectWorkflow";

const { setWorkflowSubtaskDone, setWorkflowContactDone } = vi.hoisted(() => ({
  setWorkflowSubtaskDone: vi.fn(),
  setWorkflowContactDone: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, setWorkflowSubtaskDone, setWorkflowContactDone };
});

function stage(overrides: Partial<WorkflowStage>): WorkflowStage {
  return {
    code: "etapa.01",
    number: 1,
    title: "Etapa sintética",
    phase_code: "handover",
    responsible_label: "PM",
    responsible_role_code: "project_manager",
    note: "",
    depends_on_number: null,
    start_day: 1,
    end_day: 1,
    planned_start: "2026-09-07",
    planned_end: "2026-09-07",
    status: "por_iniciar",
    done_count: 0,
    total_count: 1,
    subtasks: [{ code: "etapa.01.1", title: "Subtarefa sintética", is_client_contact: false, done: false, done_at: null }],
    contact_type: null,
    contact_note: "",
    contact_date: null,
    contact_done: false,
    contact_overdue: false,
    ...overrides,
  };
}

function makeWorkflow(overrides: Partial<Workflow> = {}): Workflow {
  return {
    project_id: "proj-1",
    start_date: "2026-09-07",
    planned_end: "2026-12-04",
    total_days: 65,
    progress_percent: 50,
    done_count: 1,
    total_count: 3,
    current_stage_number: 2,
    current_phase_code: "handover",
    overdue_stages_count: 1,
    pending_contacts_count: 1,
    can_edit: true,
    phases: [{ code: "handover", name: "Handover e arranque", color: "#2E75B6", done_count: 1, total_count: 3 }],
    stages: [
      stage({
        status: "concluida",
        done_count: 1,
        subtasks: [{ code: "etapa.01.1", title: "Primeira feita", is_client_contact: false, done: true, done_at: null }],
      }),
      stage({
        code: "etapa.02",
        number: 2,
        title: "Contacto com o cliente sintético",
        status: "atrasada",
        total_count: 2,
        subtasks: [
          { code: "etapa.02.1", title: "Enviar e-mail sintético", is_client_contact: true, done: false, done_at: null },
          { code: "etapa.02.2", title: "Registar resposta", is_client_contact: false, done: false, done_at: null },
        ],
        contact_type: "contacto",
        contact_note: "Apresentação",
        contact_date: "2026-09-08",
        contact_overdue: true,
      }),
    ],
    ...overrides,
  };
}

describe("ProjectWorkflow", () => {
  beforeEach(() => {
    setWorkflowSubtaskDone.mockReset();
    setWorkflowContactDone.mockReset();
  });

  it("mostra o resumo, as fases e abre a etapa atual", () => {
    renderWithProviders(<ProjectWorkflow projectId="proj-1" workflow={makeWorkflow()} onChange={() => undefined} />);

    expect(screen.getByText("Etapa atual: 2")).toBeInTheDocument();
    expect(screen.getByText("1 etapa em atraso")).toBeInTheDocument();
    expect(screen.getByText("Handover e arranque")).toBeInTheDocument();
    // A etapa atual (2) vem aberta; a 1 (concluída) não.
    expect(screen.getByLabelText("Enviar e-mail sintético")).toBeInTheDocument();
    expect(screen.queryByLabelText("Primeira feita")).not.toBeInTheDocument();
    expect(screen.getByText("· em atraso")).toBeInTheDocument();
  });

  it("marca uma subtarefa e devolve o percurso atualizado", async () => {
    const updated = makeWorkflow({ progress_percent: 67 });
    setWorkflowSubtaskDone.mockResolvedValue(updated);
    const onChange = vi.fn();
    renderWithProviders(<ProjectWorkflow projectId="proj-1" workflow={makeWorkflow()} onChange={onChange} />);

    fireEvent.click(screen.getByLabelText("Registar resposta"));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(updated));
    expect(setWorkflowSubtaskDone).toHaveBeenCalledWith("proj-1", "etapa.02.2", true);
  });

  it("marca o ponto de contacto da etapa", async () => {
    setWorkflowContactDone.mockResolvedValue(makeWorkflow());
    renderWithProviders(<ProjectWorkflow projectId="proj-1" workflow={makeWorkflow()} onChange={() => undefined} />);

    fireEvent.click(screen.getByRole("checkbox", { name: /Contacto com o cliente ·/ }));
    await waitFor(() => expect(setWorkflowContactDone).toHaveBeenCalledWith("proj-1", "etapa.02", true));
  });

  it("perfil só de leitura vê o percurso sem poder marcar", () => {
    renderWithProviders(
      <ProjectWorkflow projectId="proj-1" workflow={makeWorkflow({ can_edit: false })} onChange={() => undefined} />
    );
    expect(screen.getByText("Só leitura")).toBeInTheDocument();
    expect(screen.getByLabelText("Registar resposta")).toBeDisabled();
  });

  it("filtra etapas em atraso e abre/fecha etapas", () => {
    renderWithProviders(<ProjectWorkflow projectId="proj-1" workflow={makeWorkflow()} onChange={() => undefined} />);

    fireEvent.click(screen.getByRole("button", { name: "Em atraso" }));
    expect(screen.queryByText("Etapa sintética")).not.toBeInTheDocument();
    expect(screen.getByText("Contacto com o cliente sintético")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Todas" }));
    fireEvent.click(screen.getByRole("button", { name: /Etapa 1: Etapa sintética/ }));
    expect(screen.getByLabelText("Primeira feita")).toBeChecked();
  });
});
