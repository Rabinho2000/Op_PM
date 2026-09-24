import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ProcessRead } from "../api/client";
import { renderWithProviders } from "../test/render";
import ProcessOpenTasks, { pendingProcessTasks } from "./ProcessOpenTasks";

const { setProcessSubtaskDone } = vi.hoisted(() => ({ setProcessSubtaskDone: vi.fn() }));
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, setProcessSubtaskDone };
});

const sub = (id: string, title: string, done: boolean) => ({
  id, code: id, title, done, done_at: null, done_by_display_name: null, source: "ui" as const,
});

function process(overrides: Partial<ProcessRead> = {}): ProcessRead {
  return {
    project_id: "p-1",
    start_date: "2026-05-04",
    has_catalog: true,
    can_update: true,
    phases: [
      {
        id: "ph", code: "ph", name: "Fase", color: "#000", done_count: 1, total_count: 3,
        stages: [
          {
            id: "st-1", code: "etapa-01", title: "Etapa 01 (exemplo)", note: "",
            responsible: { rule: "pm", label: "PM do projeto", names: ["PM Um"], unresolved: false, delegated: false },
            depends_on_code: null, start_day: 1, end_day: 5, planned_start: "2026-05-04", planned_end: "2026-05-08",
            status: "active", done_count: 1, total_count: 3, contact: null,
            subtasks: [sub("s1", "Feita", true), sub("s2", "Por fazer A", false), sub("s3", "Por fazer B", false)],
          },
        ],
      },
    ],
    summary: { done: 1, total: 3, percent: 33, stages_done: 0, stages_total: 1, overdue_stages: 0, overdue_contacts: 0 },
    ...overrides,
  };
}

describe("ProcessOpenTasks", () => {
  beforeEach(() => {
    setProcessSubtaskDone.mockReset();
  });

  it("conta e mostra só as tarefas do processo por concluir, com etapa e responsável", () => {
    expect(pendingProcessTasks(process())).toBe(2);
    expect(pendingProcessTasks(null)).toBe(0);
    renderWithProviders(<ProcessOpenTasks projectId="p-1" process={process()} onChange={() => {}} />);
    expect(screen.getByText("Por fazer A")).toBeInTheDocument();
    expect(screen.queryByText("Feita")).not.toBeInTheDocument();
    expect(screen.getByText("PM do projeto: PM Um", { exact: false })).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Mostrar concluídas"));
    expect(screen.getByText("Feita")).toBeInTheDocument();
  });

  it("marca uma tarefa como concluída e devolve o processo atualizado", async () => {
    const updated = process({ summary: { ...process().summary, done: 2 } });
    setProcessSubtaskDone.mockResolvedValue(updated);
    const onChange = vi.fn();
    renderWithProviders(<ProcessOpenTasks projectId="p-1" process={process()} onChange={onChange} />);
    fireEvent.click(screen.getByLabelText("Por fazer A"));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(updated));
    expect(setProcessSubtaskDone).toHaveBeenCalledWith("p-1", "s2", true);
  });

  it("sem permissão as caixas ficam desativadas e sem catálogo não mostra nada", () => {
    const { container, rerender } = renderWithProviders(
      <ProcessOpenTasks projectId="p-1" process={process({ can_update: false })} onChange={() => {}} />
    );
    expect(screen.getByLabelText("Por fazer A")).toBeDisabled();
    rerender(<ProcessOpenTasks projectId="p-1" process={process({ has_catalog: false })} onChange={() => {}} />);
    expect(container.textContent).not.toContain("Tarefas do processo");
  });
});
