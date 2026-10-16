import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  CalendarEvent,
  CalendarEventCategory,
  Person,
  PlanningProcessOption,
  Project,
} from "../api/client";
import { makeMe, makeProject } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import { lisbonWallClockToIso, todayIsoLisbon } from "../utils/dates";
import Planning from "./Planning";

const api = vi.hoisted(() => ({
  listCalendarEvents: vi.fn(),
  listProcessCalendarEvents: vi.fn(),
  listPlanningEventCategories: vi.fn(),
  getPlanningPreferences: vi.fn(),
  updatePlanningPreferences: vi.fn(),
  getPlanningProcessOptions: vi.fn(),
  createCalendarEvent: vi.fn(),
  updateCalendarEvent: vi.fn(),
  cancelCalendarEvent: vi.fn(),
  listProjects: vi.fn(),
  listPeople: vi.fn(),
  listTasks: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, ...api };
});

const FIXED_NOW = new Date("2026-10-15T12:00:00.000Z");
const TODAY = todayIsoLisbon(FIXED_NOW);
const EVENT_START = lisbonWallClockToIso(`${TODAY}T09:00`);
const EVENT_END = lisbonWallClockToIso(`${TODAY}T10:00`);
const EVENT_CREATED_AT = lisbonWallClockToIso(`${TODAY}T08:00`);
const CATEGORIES: CalendarEventCategory[] = [
  { code: "meeting", label: "Reunião", color: "#2563eb" },
  { code: "technical_visit", label: "Visita técnica", color: "#0e7490" },
  { code: "commissioning", label: "Comissionamento", color: "#7c3aed" },
  { code: "final_inspection", label: "Inspeção final", color: "#15803d" },
  { code: "pending", label: "Pendência", color: "#b45309" },
  { code: "work", label: "Obra", color: "#475569" },
  { code: "other", label: "Outro", color: "#64748b" },
];

function event(overrides: Partial<CalendarEvent> = {}): CalendarEvent {
  return {
    id: "evt-1",
    visit_id: null,
    project_id: "proj-1",
    task_id: null,
    assigned_to_person_id: "p-pm",
    assigned_to_person_ids: ["p-pm"],
    title: "Visita técnica sintética",
    category: "technical_visit",
    starts_at: EVENT_START,
    ends_at: EVENT_END,
    status: "rascunho",
    graph_event_id: null,
    created_at: EVENT_CREATED_AT,
    project_name: "Instalação Sintética de Teste",
    project_url: "/projects/proj-1",
    task_title: null,
    assigned_to_display_name: "PM Sintético Um",
    assigned_to_display_names: ["PM Sintético Um"],
    responsible_person_ids: [],
    responsible_display_names: [],
    source: "manual",
    source_id: "evt-1",
    category_label: "Visita técnica",
    category_color: "#0e7490",
    can_manage: true,
    ...overrides,
  };
}

function person(overrides: Partial<Person> = {}): Person {
  return { id: "p-pm", display_name: "PM Sintético Um", email: null, is_active: true, ...overrides };
}

const PROCESS_OPTIONS: PlanningProcessOption[] = [
  {
    project_id: "proj-1",
    stage_id: "stage-1",
    stage_code: "etapa-01",
    stage_title: "Etapa de visita",
    planned_start: "2026-09-01",
    planned_end: "2026-09-02",
    responsible_person_ids: ["p-pm"],
    responsible_display_names: ["PM Sintético Um"],
    subtasks: [{ id: "subtask-1", code: "sub-01", title: "Subtarefa sem datas", planned_start: null, planned_end: null }],
  },
];

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(FIXED_NOW);
  Object.values(api).forEach((fn) => fn.mockReset());
  api.listCalendarEvents.mockResolvedValue([event()]);
  api.listProcessCalendarEvents.mockResolvedValue([]);
  api.listPlanningEventCategories.mockResolvedValue(CATEGORIES);
  api.getPlanningPreferences.mockResolvedValue({ view: "month", hide_weekends: false });
  api.updatePlanningPreferences.mockResolvedValue({ view: "week", hide_weekends: true });
  api.getPlanningProcessOptions.mockResolvedValue(PROCESS_OPTIONS);
  api.listProjects.mockResolvedValue([
    makeProject({ id: "proj-10", name: "123.10 — Projeto Dez" }) as Project,
    makeProject({ id: "proj-2", name: "123.2 — Projeto Dois" }) as Project,
    makeProject({ id: "proj-1", name: "Instalação Sintética de Teste" }) as Project,
  ]);
  api.listPeople.mockResolvedValue([
    person(),
    person({ id: "p-second", display_name: "Pessoa Dois" }),
    person({ id: "p-third", display_name: "Pessoa Três" }),
  ]);
  api.listTasks.mockResolvedValue([]);
});

afterEach(() => {
  vi.useRealTimers();
});

const permissions = ["calendar.view", "calendar.manage", "project.view_all", "task.view_all"];

function renderPlanning() {
  return renderWithProviders(<Planning />, { me: makeMe({ permissions }) });
}

describe("Planeamento", () => {
  it("restaura a vista e o período a partir da preferência mensal do servidor", async () => {
    renderPlanning();

    expect(await screen.findByText("Visita técnica sintética")).toBeInTheDocument();
    expect(api.getPlanningPreferences).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Vista")).toHaveValue("month");
    expect(api.listCalendarEvents).toHaveBeenCalledWith(
      expect.objectContaining({ mine_only: false, project_id: undefined, assigned_to_person_id: undefined })
    );
  });

  it("mostra os eventos do período na grelha da vista de semana", async () => {
    renderPlanning();
    await screen.findByText("Visita técnica sintética");

    fireEvent.change(screen.getByLabelText("Vista"), { target: { value: "week" } });
    await waitFor(() => expect(screen.getAllByTestId("planning-day")).toHaveLength(7));

    expect(screen.getByRole("button", { name: /Visita técnica sintética/ })).toBeInTheDocument();
    expect(api.listCalendarEvents).toHaveBeenLastCalledWith(
      expect.objectContaining({ mine_only: false, project_id: undefined, assigned_to_person_id: undefined })
    );
  });

  it("muda para a vista de lista, ordena e agrupa uma fonte multi-dia sem mostrar fins de semana ocultos", async () => {
    api.listCalendarEvents.mockResolvedValue([
      event({
        id: "evt-early",
        title: "Evento cedo",
        starts_at: lisbonWallClockToIso(`${TODAY}T09:00`),
        ends_at: lisbonWallClockToIso(`${TODAY}T10:00`),
      }),
      event({
        id: "evt-multi",
        title: "Evento multi-dia",
        starts_at: lisbonWallClockToIso(`${TODAY}T16:00`),
        ends_at: lisbonWallClockToIso("2026-10-17T11:00"),
      }),
      event({
        id: "evt-weekend",
        title: "Evento de fim de semana",
        starts_at: lisbonWallClockToIso("2026-10-17T12:00"),
        ends_at: lisbonWallClockToIso("2026-10-17T13:00"),
      }),
    ]);
    renderPlanning();
    await screen.findByText("Evento cedo");

    fireEvent.change(screen.getByLabelText("Vista"), { target: { value: "list" } });
    await waitFor(() => expect(screen.getAllByTestId("planning-day")).toHaveLength(3));
    fireEvent.click(screen.getByLabelText("Ocultar fins de semana"));

    await waitFor(() => expect(screen.getAllByTestId("planning-day")).toHaveLength(2));
    const days = screen.getAllByTestId("planning-day");
    expect(days[0]).toHaveTextContent("quinta-feira");
    expect(days[1]).toHaveTextContent("sexta-feira");
    expect(within(days[0]).getByText("Evento cedo")).toBeInTheDocument();
    expect(within(days[0]).getByText("Evento multi-dia")).toBeInTheDocument();
    expect(within(days[1]).getByText("Evento multi-dia")).toBeInTheDocument();
    expect((days[0].textContent ?? "").indexOf("Evento cedo")).toBeLessThan(
      (days[0].textContent ?? "").indexOf("Evento multi-dia")
    );
    expect(screen.queryByText("Evento de fim de semana")).not.toBeInTheDocument();
    expect(screen.queryByText(/sábado/)).not.toBeInTheDocument();

    const eventRow = within(days[0]).getByRole("button", { name: /Evento cedo/ });
    expect(eventRow.querySelector("button")).toBeNull();

    fireEvent.click(eventRow);
    const clickDialog = await screen.findByRole("dialog");
    expect(within(clickDialog).getByRole("heading", { name: "Evento cedo" })).toBeInTheDocument();
    fireEvent.click(within(clickDialog).getByRole("button", { name: "Fechar" }));

    fireEvent.keyDown(eventRow, { key: "Enter", code: "Enter" });
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("filtra por responsável ao escolher o âmbito 'Por responsável' e mostra o resultado", async () => {
    renderPlanning();
    await screen.findByText("Visita técnica sintética");
    api.listCalendarEvents.mockClear();

    fireEvent.change(screen.getByLabelText("Ver"), { target: { value: "responsible" } });
    fireEvent.change(await screen.findByLabelText("Responsável"), { target: { value: "p-pm" } });

    await waitFor(() =>
      expect(api.listCalendarEvents).toHaveBeenLastCalledWith(expect.objectContaining({ assigned_to_person_id: "p-pm" }))
    );
    expect(screen.getByText("Visita técnica sintética")).toBeInTheDocument();
  });

  it("guarda a vista atual e o ocultar de fins de semana por utilizador", async () => {
    renderPlanning();
    await screen.findByText("Visita técnica sintética");

    fireEvent.change(screen.getByLabelText("Vista"), { target: { value: "week" } });
    fireEvent.click(screen.getByLabelText("Ocultar fins de semana"));
    fireEvent.click(screen.getByRole("button", { name: /fixar vista/i }));

    await waitFor(() =>
      expect(api.updatePlanningPreferences).toHaveBeenCalledWith({ view: "week", hide_weekends: true })
    );
  });

  it("ordena projetos numericamente e só seleciona um projeto real na pesquisa", async () => {
    renderPlanning();
    await screen.findByText("Visita técnica sintética");

    fireEvent.change(screen.getByLabelText("Ver"), { target: { value: "project" } });
    fireEvent.change(screen.getByLabelText("Projeto"), { target: { value: "123" } });
    const options = await screen.findAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual(
      expect.arrayContaining(["123.2 — Projeto Dois", "123.10 — Projeto Dez"])
    );
    expect(options.findIndex((option) => option.textContent?.includes("123.2"))).toBeLessThan(
      options.findIndex((option) => option.textContent?.includes("123.10"))
    );

    fireEvent.change(screen.getByLabelText("Projeto"), { target: { value: "123.2" } });
    fireEvent.keyDown(screen.getByLabelText("Projeto"), { key: "Enter" });
    await waitFor(() =>
      expect(api.listCalendarEvents).toHaveBeenLastCalledWith(expect.objectContaining({ project_id: "proj-2" }))
    );
  });

  it("não envia uma pesquisa fantasma como projeto e permite limpar explicitamente", async () => {
    renderPlanning();
    await screen.findByText("Visita técnica sintética");

    fireEvent.change(screen.getByLabelText("Ver"), { target: { value: "project" } });
    const project = screen.getByLabelText("Projeto");
    fireEvent.change(project, { target: { value: "projeto que não existe" } });
    await waitFor(() =>
      expect(api.listCalendarEvents).toHaveBeenLastCalledWith(expect.objectContaining({ project_id: undefined }))
    );
    expect(project).toHaveAttribute("data-selected-id", "");

    fireEvent.click(screen.getByRole("button", { name: "Limpar Projeto" }));
    expect(project).toHaveValue("");
    expect(project).toHaveAttribute("data-selected-id", "");
  });

  it("oculta fins de semana na apresentação sem encurtar o intervalo pedido ao servidor", async () => {
    renderPlanning();
    await screen.findByText("Visita técnica sintética");
    fireEvent.change(screen.getByLabelText("Vista"), { target: { value: "week" } });
    await waitFor(() => expect(screen.getAllByTestId("planning-day")).toHaveLength(7));
    const callsBefore = api.listCalendarEvents.mock.calls;
    const call = callsBefore[callsBefore.length - 1]?.[0] as { starts_from: string; starts_to: string };
    expect(call.starts_from).toMatch(/Z$/);
    expect(call.starts_to).toMatch(/Z$/);
    expect(new Date(call.starts_from).getTime()).toBeLessThan(new Date(call.starts_to).getTime());

    fireEvent.click(screen.getByLabelText("Ocultar fins de semana"));
    await waitFor(() => expect(screen.getAllByTestId("planning-day")).toHaveLength(5));
    const callsAfter = api.listCalendarEvents.mock.calls;
    const hiddenCall = callsAfter[callsAfter.length - 1]?.[0] as { starts_from: string; starts_to: string };
    expect(hiddenCall.starts_from).toBe(call.starts_from);
    expect(hiddenCall.starts_to).toBe(call.starts_to);
  });

  it("mantém tarefas normais separadas da ligação a etapa/subtarefa do Processo e envia vários responsáveis", async () => {
    renderPlanning();
    await screen.findByText("Visita técnica sintética");
    fireEvent.click(screen.getByRole("button", { name: /^novo evento$/i }));
    const dialog = await screen.findByRole("dialog");

    const project = within(dialog).getByLabelText("Projeto");
    fireEvent.change(project, { target: { value: "instalação sintética" } });
    fireEvent.keyDown(project, { key: "Enter" });
    expect(await within(dialog).findByLabelText("Etapa do Processo")).toBeInTheDocument();

    fireEvent.change(within(dialog).getByLabelText("Título *"), { target: { value: "Reunião com equipa" } });
    fireEvent.change(within(dialog).getByLabelText("Categoria"), { target: { value: "meeting" } });
    fireEvent.change(within(dialog).getByLabelText("Início *"), { target: { value: `${TODAY}T14:00` } });
    fireEvent.change(within(dialog).getByLabelText("Fim *"), { target: { value: `${TODAY}T15:00` } });
    fireEvent.click(within(dialog).getByLabelText("PM Sintético Um"));
    fireEvent.click(within(dialog).getByLabelText("Pessoa Dois"));
    fireEvent.change(within(dialog).getByLabelText("Etapa do Processo"), { target: { value: "stage-1" } });
    fireEvent.change(within(dialog).getByLabelText("Subtarefa do Processo"), { target: { value: "subtask-1" } });

    api.createCalendarEvent.mockResolvedValue(event({ id: "evt-new" }));
    fireEvent.click(within(dialog).getByRole("button", { name: /^guardar$/i }));
    await waitFor(() =>
      expect(api.createCalendarEvent).toHaveBeenCalledWith(
        expect.objectContaining({
          project_id: "proj-1",
          task_id: null,
          category: "meeting",
          assigned_to_person_id: "p-pm",
          assigned_to_person_ids: ["p-pm", "p-second"],
          process_stage_id: "stage-1",
          process_subtask_id: "subtask-1",
        })
      )
    );
  });

  it("deteta conflitos quando há qualquer participante e conserva a atribuição dos dois após confirmar", async () => {
    api.listCalendarEvents.mockResolvedValue([
      event({ assigned_to_person_ids: ["p-pm", "p-second"], assigned_to_display_names: ["PM Sintético Um", "Pessoa Dois"] }),
    ]);
    renderPlanning();
    await screen.findByText("Visita técnica sintética");
    fireEvent.click(screen.getByRole("button", { name: /^novo evento$/i }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Título *"), { target: { value: "Conflito sintético" } });
    fireEvent.change(within(dialog).getByLabelText("Início *"), { target: { value: `${TODAY}T09:30` } });
    fireEvent.change(within(dialog).getByLabelText("Fim *"), { target: { value: `${TODAY}T10:30` } });
    fireEvent.click(within(dialog).getByLabelText("Pessoa Dois"));

    expect(within(dialog).getByText(/Sobreposição de horário/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: /guardar mesmo assim/i }));
    expect(api.createCalendarEvent).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByLabelText(/Confirmo que quero continuar/));
    api.createCalendarEvent.mockResolvedValue(event({ id: "evt-3" }));
    fireEvent.click(within(dialog).getByRole("button", { name: /guardar mesmo assim/i }));
    await waitFor(() =>
      expect(api.createCalendarEvent).toHaveBeenCalledWith(
        expect.objectContaining({ assigned_to_person_ids: ["p-second"], assigned_to_person_id: "p-second" })
      )
    );
  });

  it("mostra categoria, todos os responsáveis e ligação read-only ao Processo", async () => {
    const projected = event({
      id: "process-1",
      source: "process",
      source_id: "process-1",
      status: "projected",
      can_manage: false,
      category: "commissioning",
      category_label: "Comissionamento",
      category_color: "#7c3aed",
      title: "Etapa projetada",
      assigned_to_person_ids: ["p-pm", "p-second"],
      assigned_to_display_names: ["PM Sintético Um", "Pessoa Dois"],
      responsible_person_ids: ["p-pm", "p-second"],
      responsible_display_names: ["PM Sintético Um", "Pessoa Dois"],
      process_stage_id: "stage-1",
      process_stage_code: "etapa-01",
      process_stage_title: "Etapa de visita",
      project_url: "/projects/proj-1?tab=processo",
    });
    api.listProcessCalendarEvents.mockResolvedValue([projected]);
    api.listCalendarEvents.mockResolvedValue([]);
    renderPlanning();
    fireEvent.click(await screen.findByText("Etapa projetada"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Comissionamento")).toBeInTheDocument();
    expect(within(dialog).getByText("PM Sintético Um")).toBeInTheDocument();
    expect(within(dialog).getByText("Pessoa Dois")).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: /abrir processo/i })).toHaveAttribute(
      "href",
      "/projects/proj-1?tab=processo"
    );
    expect(within(dialog).queryByRole("button", { name: /reagendar|cancelar evento/i })).not.toBeInTheDocument();
  });

  it("envia as horas de Lisboa como instantes com offset no verão e no inverno", async () => {
    for (const [day, startsAt, endsAt] of [
      ["2099-07-15", "2099-07-15T08:00:00.000Z", "2099-07-15T09:30:00.000Z"],
      ["2099-01-15", "2099-01-15T09:00:00.000Z", "2099-01-15T10:30:00.000Z"],
    ]) {
      cleanup();
      renderPlanning();
      await screen.findByText("Visita técnica sintética");
      fireEvent.click(screen.getByRole("button", { name: /^novo evento$/i }));
      const dialog = await screen.findByRole("dialog");
      fireEvent.change(within(dialog).getByLabelText("Título *"), { target: { value: "Evento com offset" } });
      fireEvent.change(within(dialog).getByLabelText("Início *"), { target: { value: `${day}T09:00` } });
      fireEvent.change(within(dialog).getByLabelText("Fim *"), { target: { value: `${day}T10:30` } });
      api.createCalendarEvent.mockResolvedValue(event({ id: `evt-${day}` }));
      fireEvent.click(within(dialog).getByRole("button", { name: /^guardar$/i }));
      await waitFor(() =>
        expect(api.createCalendarEvent).toHaveBeenLastCalledWith(
          expect.objectContaining({ title: "Evento com offset", starts_at: startsAt, ends_at: endsAt })
        )
      );
    }
  });

  it("reagenda um evento manual, preserva responsáveis e referências do Processo e recarrega sem criar nem cancelar", async () => {
    const scheduled = event({
      id: "evt-reschedule",
      title: "Evento reagendável",
      assigned_to_person_ids: ["p-pm", "p-second"],
      assigned_to_display_names: ["PM Sintético Um", "Pessoa Dois"],
      process_stage_id: "stage-1",
      process_subtask_id: "subtask-1",
    });
    api.listCalendarEvents.mockResolvedValue([scheduled]);
    renderPlanning();
    fireEvent.click(await screen.findByText("Evento reagendável"));

    const detail = await screen.findByRole("dialog");
    fireEvent.click(within(detail).getByRole("button", { name: /^editar$/i }));
    const editDialog = await screen.findByRole("dialog");
    const newStartsAt = `${TODAY}T11:00`;
    const newEndsAt = `${TODAY}T12:30`;
    const expectedStartsAt = lisbonWallClockToIso(newStartsAt);
    const expectedEndsAt = lisbonWallClockToIso(newEndsAt);
    expect(expectedStartsAt).toMatch(/Z$/);
    expect(expectedEndsAt).toMatch(/Z$/);
    fireEvent.change(within(editDialog).getByLabelText("Início *"), { target: { value: newStartsAt } });
    fireEvent.change(within(editDialog).getByLabelText("Fim *"), { target: { value: newEndsAt } });

    api.updateCalendarEvent.mockResolvedValue(event({
      id: "evt-reschedule",
      title: "Evento reagendável",
      starts_at: expectedStartsAt,
      ends_at: expectedEndsAt,
      assigned_to_person_ids: ["p-pm", "p-second"],
      assigned_to_display_names: ["PM Sintético Um", "Pessoa Dois"],
      process_stage_id: "stage-1",
      process_subtask_id: "subtask-1",
    }));
    const calendarCallsBeforeSave = api.listCalendarEvents.mock.calls.length;
    fireEvent.click(within(editDialog).getByRole("button", { name: /^guardar$/i }));

    await waitFor(() =>
      expect(api.updateCalendarEvent).toHaveBeenCalledWith(
        "evt-reschedule",
        expect.objectContaining({
          title: "Evento reagendável",
          starts_at: expectedStartsAt,
          ends_at: expectedEndsAt,
          project_id: "proj-1",
          task_id: null,
          assigned_to_person_id: "p-pm",
          assigned_to_person_ids: ["p-pm", "p-second"],
          category: "technical_visit",
          process_stage_id: "stage-1",
          process_subtask_id: "subtask-1",
        })
      )
    );
    expect(api.createCalendarEvent).not.toHaveBeenCalled();
    expect(api.cancelCalendarEvent).not.toHaveBeenCalled();
    await waitFor(() => expect(api.listCalendarEvents.mock.calls.length).toBeGreaterThan(calendarCallsBeforeSave));
  });

  it("mantém filtros de responsável e a confirmação ao editar/cancelar um evento manual", async () => {
    renderPlanning();
    fireEvent.click(await screen.findByText("Visita técnica sintética"));
    const detail = await screen.findByRole("dialog");
    expect(within(detail).getByText("rascunho")).toBeInTheDocument();
    api.cancelCalendarEvent.mockResolvedValue(event({ status: "cancelado" }));
    fireEvent.click(within(detail).getByRole("button", { name: /cancelar evento/i }));
    await waitFor(() => expect(api.cancelCalendarEvent).toHaveBeenCalledWith("evt-1"));
  });
});
