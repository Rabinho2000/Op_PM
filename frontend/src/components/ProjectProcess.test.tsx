import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ProcessRead, ProcessStage } from "../api/client";
import { renderWithProviders } from "../test/render";
import ProjectProcess, { responsibleText } from "./ProjectProcess";

const { getProjectProcess, setProcessSubtaskDone, setProcessContactDone } = vi.hoisted(() => ({
  getProjectProcess: vi.fn(),
  setProcessSubtaskDone: vi.fn(),
  setProcessContactDone: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, getProjectProcess, setProcessSubtaskDone, setProcessContactDone };
});

function stage(overrides: Partial<ProcessStage> = {}): ProcessStage {
  return {
    id: "st-1",
    code: "etapa-01",
    title: "Etapa 01 (exemplo)",
    note: "",
    responsible: { rule: "pm", label: "PM do projeto", names: ["PM Um"], unresolved: false, delegated: false },
    depends_on_code: null,
    start_day: 1,
    end_day: 5,
    planned_start: "2026-05-04",
    planned_end: "2026-05-08",
    status: "active",
    done_count: 1,
    total_count: 2,
    contact: null,
    subtasks: [
      { id: "sub-1", code: "etapa-01.0", title: "Primeira subtarefa", done: true, done_at: "2026-05-05T10:00:00Z", done_by_display_name: "Chefe", source: "ui" },
      { id: "sub-2", code: "etapa-01.1", title: "Segunda subtarefa", done: false, done_at: null, done_by_display_name: null, source: "ui" },
    ],
    ...overrides,
  };
}

function process(overrides: Partial<ProcessRead> = {}, stages: ProcessStage[] = [stage()]): ProcessRead {
  return {
    project_id: "p-1",
    start_date: "2026-05-04",
    has_catalog: true,
    can_update: true,
    phases: [{ id: "ph-1", code: "handover", name: "Fase 1 — Arranque", color: "#2E75B6", done_count: 1, total_count: 2, stages }],
    summary: { done: 1, total: 2, percent: 50, stages_done: 0, stages_total: 1, overdue_stages: 0, overdue_contacts: 0 },
    ...overrides,
  };
}

describe("responsibleText", () => {
  it("nomeia quem faz, ou diz que falta atribuir", () => {
    expect(responsibleText({ rule: "pm", label: "PM do projeto", names: ["Ana"], unresolved: false, delegated: false })).toBe("PM do projeto: Ana");
    expect(responsibleText({ rule: "installer", label: "Subempreiteiro", names: [], unresolved: true, delegated: false })).toBe("Subempreiteiro — por atribuir");
    expect(responsibleText({ rule: "role", label: "Chefe do departamento", names: [], unresolved: false, delegated: false })).toBe("Chefe do departamento");
    expect(responsibleText({ rule: "role", label: "Comercial", names: ["A", "B"], unresolved: false, delegated: false })).toBe("Comercial: A, B");
  });
});

describe("ProjectProcess", () => {
  beforeEach(() => {
    [getProjectProcess, setProcessSubtaskDone, setProcessContactDone].forEach((m) => m.mockReset());
    getProjectProcess.mockResolvedValue(process());
  });

  it("mostra o progresso, as fases e as etapas com responsável e datas", async () => {
    renderWithProviders(<ProjectProcess projectId="p-1" />);
    expect(await screen.findByText("Fase 1 — Arranque")).toBeInTheDocument();
    expect(screen.getByText(/1 de 2 subtarefas · 0 de 1 etapas concluídas/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Progresso do processo" })).toBeInTheDocument();
    expect(screen.getByText("Etapa 01 (exemplo)")).toBeInTheDocument();
    expect(screen.getByText("PM do projeto: PM Um")).toBeInTheDocument();
    expect(screen.getByText(/04\/05\/2026 a 08\/05\/2026/)).toBeInTheDocument();
    expect(screen.getByText("Em curso")).toBeInTheDocument();
    expect(getProjectProcess).toHaveBeenCalledWith("p-1");
  });

  it("abre por omissão as etapas em curso ou em atraso e fecha as outras", async () => {
    getProjectProcess.mockResolvedValue(
      process({}, [
        stage({ id: "a", code: "etapa-01", title: "Em curso", status: "active" }),
        stage({ id: "b", code: "etapa-02", title: "Futura", status: "upcoming", subtasks: [{ id: "x", code: "etapa-02.0", title: "Tarefa futura", done: false, done_at: null, done_by_display_name: null, source: "ui" }] }),
        stage({ id: "c", code: "etapa-03", title: "Feita", status: "done", subtasks: [{ id: "y", code: "etapa-03.0", title: "Tarefa feita", done: true, done_at: null, done_by_display_name: null, source: "ui" }] }),
      ])
    );
    renderWithProviders(<ProjectProcess projectId="p-1" />);
    await screen.findByText("Fase 1 — Arranque");
    expect(screen.getByText("Primeira subtarefa")).toBeInTheDocument();
    expect(screen.queryByText("Tarefa futura")).not.toBeInTheDocument();
    expect(screen.queryByText("Tarefa feita")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Futura/ }));
    expect(screen.getByText("Tarefa futura")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Futura/ })).toHaveAttribute("aria-expanded", "true");
  });

  it("marca uma subtarefa e mostra o resultado devolvido pelo servidor", async () => {
    const updated = process(
      { summary: { done: 2, total: 2, percent: 100, stages_done: 1, stages_total: 1, overdue_stages: 0, overdue_contacts: 0 } },
      [stage({ status: "done", done_count: 2, subtasks: [
        { id: "sub-1", code: "etapa-01.0", title: "Primeira subtarefa", done: true, done_at: "2026-05-05T10:00:00Z", done_by_display_name: "Chefe", source: "ui" },
        { id: "sub-2", code: "etapa-01.1", title: "Segunda subtarefa", done: true, done_at: "2026-05-06T09:00:00Z", done_by_display_name: "Ana", source: "ui" },
      ] })]
    );
    setProcessSubtaskDone.mockResolvedValue(updated);
    renderWithProviders(<ProjectProcess projectId="p-1" />);
    await screen.findByText("Segunda subtarefa");

    fireEvent.click(screen.getByLabelText("Segunda subtarefa"));
    await waitFor(() => expect(setProcessSubtaskDone).toHaveBeenCalledWith("p-1", "sub-2", true));
    expect(await screen.findByText(/2 de 2 subtarefas · 1 de 1 etapas concluídas/)).toBeInTheDocument();
    expect(screen.getByText("Concluída")).toBeInTheDocument();
    expect(screen.getByText(/Ana · 06\/05\/2026/)).toBeInTheDocument();
  });

  it("desmarca uma subtarefa feita", async () => {
    setProcessSubtaskDone.mockResolvedValue(process());
    renderWithProviders(<ProjectProcess projectId="p-1" />);
    await screen.findByText("Primeira subtarefa");
    fireEvent.click(screen.getByLabelText("Primeira subtarefa"));
    await waitFor(() => expect(setProcessSubtaskDone).toHaveBeenCalledWith("p-1", "sub-1", false));
  });

  it("só consulta quando o servidor não permite marcar", async () => {
    getProjectProcess.mockResolvedValue(process({ can_update: false }));
    renderWithProviders(<ProjectProcess projectId="p-1" />);
    await screen.findByText("Segunda subtarefa");
    expect(screen.getByLabelText("Segunda subtarefa")).toBeDisabled();
    expect(screen.getByText(/Só consulta/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Segunda subtarefa"));
    expect(setProcessSubtaskDone).not.toHaveBeenCalled();
  });

  it("mostra o ponto de contacto em atraso e permite marcá-lo", async () => {
    const withContact = stage({
      contact: { day: 9, kind: "contacto", note: "Apresentação", planned_date: "2026-05-14", done: false, done_at: null, overdue: true, source: "ui" },
    });
    getProjectProcess.mockResolvedValue(process({ summary: { done: 1, total: 2, percent: 50, stages_done: 0, stages_total: 1, overdue_stages: 0, overdue_contacts: 1 } }, [withContact]));
    setProcessContactDone.mockResolvedValue(process({}, [stage({ contact: { ...withContact.contact!, done: true, overdue: false } })]));
    renderWithProviders(<ProjectProcess projectId="p-1" />);

    expect(await screen.findByText("1 contactos por fazer")).toBeInTheDocument();
    const contact = screen.getByText("Contacto").closest("label") as HTMLElement;
    expect(within(contact).getByText("por fazer")).toBeInTheDocument();
    expect(contact).toHaveTextContent("até 14/05/2026");
    fireEvent.click(within(contact).getByRole("checkbox"));
    await waitFor(() => expect(setProcessContactDone).toHaveBeenCalledWith("p-1", "st-1", true));
    await waitFor(() => expect(screen.queryByText("1 contactos por fazer")).not.toBeInTheDocument());
  });

  it("assinala responsáveis por atribuir e a delegação", async () => {
    getProjectProcess.mockResolvedValue(
      process({}, [
        stage({ id: "a", code: "etapa-05", title: "Suporte", responsible: { rule: "support_delegate", label: "Suporte", names: ["Pessoa de suporte"], unresolved: false, delegated: true } }),
        stage({ id: "b", code: "etapa-14", title: "Acompanhamento", responsible: { rule: "team_leader", label: "Chefe de equipa", names: [], unresolved: true, delegated: false } }),
      ])
    );
    renderWithProviders(<ProjectProcess projectId="p-1" />);
    expect(await screen.findByText("Suporte: Pessoa de suporte")).toBeInTheDocument();
    expect(screen.getByText("delegado")).toBeInTheDocument();
    expect(screen.getByText("Chefe de equipa — por atribuir")).toHaveClass("text-danger");
  });

  it("avisa quando o projeto não tem data de início", async () => {
    getProjectProcess.mockResolvedValue(process({ start_date: null }, [stage({ status: "no_date", planned_start: null, planned_end: null })]));
    renderWithProviders(<ProjectProcess projectId="p-1" />);
    expect(await screen.findByText(/não tem data de início/)).toBeInTheDocument();
    expect(screen.getByText("Sem data")).toBeInTheDocument();
  });

  it("mostra 'importado do legado' (sem inventar autor nem data) para o progresso vindo do legado", async () => {
    getProjectProcess.mockResolvedValue(
      process({}, [
        stage({
          contact: { day: 9, kind: "contacto", note: "", planned_date: "2026-05-14", done: true, done_at: null, overdue: false, source: "legacy" },
          subtasks: [
            { id: "a", code: "etapa-01.0", title: "Feita no legado", done: true, done_at: null, done_by_display_name: null, source: "legacy" },
            { id: "b", code: "etapa-01.1", title: "Feita na aplicação", done: true, done_at: "2026-05-06T09:00:00Z", done_by_display_name: "Ana", source: "ui" },
          ],
        }),
      ])
    );
    renderWithProviders(<ProjectProcess projectId="p-1" />);
    await screen.findByText("Feita no legado");
    expect(screen.getAllByText("importado do legado")).toHaveLength(1);
    expect(screen.getByText("(importado do legado)")).toBeInTheDocument(); // o contacto
    expect(screen.getByText(/Ana · 06\/05\/2026/)).toBeInTheDocument();
  });

  it("mostra 'Por concluir' (e não 'Em atraso') numa etapa de um projeto já entregue", async () => {
    getProjectProcess.mockResolvedValue(
      process({}, [
        stage({ id: "a", code: "etapa-17", title: "Fecho", status: "done" }),
        stage({ id: "b", code: "etapa-18", title: "Inspeção e certificado", status: "pending", done_count: 0, subtasks: [{ id: "z", code: "etapa-18.0", title: "Pedir a inspeção", done: false, done_at: null, done_by_display_name: null, source: "ui" }] }),
      ])
    );
    renderWithProviders(<ProjectProcess projectId="p-1" />);
    await screen.findByText("Inspeção e certificado");
    expect(screen.getByText("Por concluir")).toBeInTheDocument();
    expect(screen.queryByText("Em atraso")).not.toBeInTheDocument();
    expect(screen.queryByText(/em atraso/)).not.toBeInTheDocument(); // nem no resumo
  });

  it("mostra 'concluída por regra' para o que foi concluído por regra num projeto entregue", async () => {
    getProjectProcess.mockResolvedValue(
      process({}, [
        stage({
          contact: { day: 9, kind: "contacto", note: "", planned_date: "2026-05-14", done: true, done_at: null, overdue: false, source: "inferred" },
          subtasks: [{ id: "a", code: "etapa-01.0", title: "Concluída pela regra", done: true, done_at: null, done_by_display_name: null, source: "inferred" }],
          status: "active",
        }),
      ])
    );
    renderWithProviders(<ProjectProcess projectId="p-1" />);
    await screen.findByText("Concluída pela regra");
    expect(screen.getByText("concluída por regra (projeto entregue)")).toBeInTheDocument();
    expect(screen.getByText("(concluído por regra)")).toBeInTheDocument();
    expect(screen.queryByText("importado do legado")).not.toBeInTheDocument();
  });

  it("estado vazio quando o catálogo ainda não foi carregado", async () => {
    getProjectProcess.mockResolvedValue(process({ has_catalog: false, phases: [] }));
    renderWithProviders(<ProjectProcess projectId="p-1" />);
    expect(await screen.findByText("O processo ainda não foi carregado.")).toBeInTheDocument();
  });

  it("mostra o erro do servidor ao carregar e ao gravar", async () => {
    const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
    getProjectProcess.mockRejectedValueOnce(new actual.ApiError(404, "Projeto não encontrado ou sem permissão para o ver."));
    renderWithProviders(<ProjectProcess projectId="p-1" />);
    expect(await screen.findByText("Projeto não encontrado ou sem permissão para o ver.")).toBeInTheDocument();
  });

  it("mostra o erro ao gravar e mantém o estado anterior", async () => {
    const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
    setProcessSubtaskDone.mockRejectedValue(new actual.ApiError(403, "Sem permissão para marcar o progresso deste projeto."));
    renderWithProviders(<ProjectProcess projectId="p-1" />);
    await screen.findByText("Segunda subtarefa");
    fireEvent.click(screen.getByLabelText("Segunda subtarefa"));
    expect(await screen.findByText("Sem permissão para marcar o progresso deste projeto.")).toBeInTheDocument();
    expect(screen.getByLabelText("Segunda subtarefa")).not.toBeChecked();
    expect(screen.getByText(/1 de 2 subtarefas/)).toBeInTheDocument();
  });
});
