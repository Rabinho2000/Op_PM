// Planeamento: vista de semana por omissão, filtros (todos/meus/PM/
// projeto/responsável), criação/reagendamento e deteção de conflitos de
// horário para o mesmo responsável.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CalendarEvent, Person, Project } from "../api/client";
import { makeMe, makeProject } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import { todayIsoLisbon } from "../utils/dates";
import Planning from "./Planning";

const api = vi.hoisted(() => ({
  listCalendarEvents: vi.fn(),
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

const TODAY = todayIsoLisbon();

function event(overrides: Partial<CalendarEvent> = {}): CalendarEvent {
  return {
    id: "evt-1",
    visit_id: null,
    project_id: "proj-1",
    task_id: null,
    assigned_to_person_id: "p-pm",
    title: "Visita técnica sintética",
    starts_at: `${TODAY}T09:00:00`,
    ends_at: `${TODAY}T10:00:00`,
    status: "rascunho",
    graph_event_id: null,
    created_at: `${TODAY}T08:00:00`,
    project_name: "Instalação Sintética de Teste",
    task_title: null,
    assigned_to_display_name: "PM Sintético Um",
    can_manage: true,
    ...overrides,
  };
}

function person(overrides: Partial<Person> = {}): Person {
  return { id: "p-pm", display_name: "PM Sintético Um", email: null, is_active: true, ...overrides };
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.listCalendarEvents.mockResolvedValue([event()]);
  api.listProjects.mockResolvedValue([makeProject() as Project]);
  api.listPeople.mockResolvedValue([person()]);
  api.listTasks.mockResolvedValue([]);
});

describe("Planeamento", () => {
  it("mostra os eventos do período na vista de semana", async () => {
    renderWithProviders(<Planning />, { me: makeMe({ permissions: ["calendar.view", "calendar.manage"] }) });
    expect(await screen.findByText("Visita técnica sintética")).toBeInTheDocument();
    expect(api.listCalendarEvents).toHaveBeenCalledWith(
      expect.objectContaining({ mine_only: false, project_id: undefined, assigned_to_person_id: undefined })
    );
  });

  it("muda para a vista de lista e agrupa por dia", async () => {
    renderWithProviders(<Planning />, { me: makeMe({ permissions: ["calendar.view", "calendar.manage"] }) });
    await screen.findByText("Visita técnica sintética");

    fireEvent.change(screen.getByLabelText("Vista"), { target: { value: "list" } });
    await waitFor(() => expect(screen.getByText(/09:00–10:00 · Visita técnica sintética/)).toBeInTheDocument());
  });

  it("filtra por responsável ao escolher o âmbito 'Por responsável'", async () => {
    renderWithProviders(<Planning />, { me: makeMe({ permissions: ["calendar.view", "calendar.manage"] }) });
    await screen.findByText("Visita técnica sintética");
    api.listCalendarEvents.mockClear();

    fireEvent.change(screen.getByLabelText("Ver"), { target: { value: "responsible" } });
    fireEvent.change(await screen.findByLabelText("Responsável"), { target: { value: "p-pm" } });

    await waitFor(() =>
      expect(api.listCalendarEvents).toHaveBeenLastCalledWith(expect.objectContaining({ assigned_to_person_id: "p-pm" }))
    );
  });

  it("cria um novo evento", async () => {
    renderWithProviders(<Planning />, { me: makeMe({ permissions: ["calendar.view", "calendar.manage"] }) });
    await screen.findByText("Visita técnica sintética");

    fireEvent.click(screen.getByRole("button", { name: /^novo evento$/i }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Título *"), { target: { value: "Comissionamento sintético" } });
    fireEvent.change(within(dialog).getByLabelText("Início *"), { target: { value: `${TODAY}T14:00` } });
    fireEvent.change(within(dialog).getByLabelText("Fim *"), { target: { value: `${TODAY}T15:00` } });

    api.createCalendarEvent.mockResolvedValue(event({ id: "evt-2" }));
    fireEvent.click(within(dialog).getByRole("button", { name: /^guardar$/i }));

    await waitFor(() =>
      expect(api.createCalendarEvent).toHaveBeenCalledWith(
        expect.objectContaining({ title: "Comissionamento sintético" })
      )
    );
  });

  it.each([
    ["Verão (WEST, UTC+1)", "2099-07-15", "2099-07-15T08:00:00.000Z", "2099-07-15T09:30:00.000Z"],
    ["Inverno (WET, UTC+0)", "2099-01-15", "2099-01-15T09:00:00.000Z", "2099-01-15T10:30:00.000Z"],
  ])("envia as horas de Lisboa como instantes com offset — %s", async (_label, day, startsAt, endsAt) => {
    renderWithProviders(<Planning />, { me: makeMe({ permissions: ["calendar.view", "calendar.manage"] }) });
    await screen.findByText("Visita técnica sintética");

    fireEvent.click(screen.getByRole("button", { name: /^novo evento$/i }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Título *"), { target: { value: "Evento com offset" } });
    fireEvent.change(within(dialog).getByLabelText("Início *"), { target: { value: `${day}T09:00` } });
    fireEvent.change(within(dialog).getByLabelText("Fim *"), { target: { value: `${day}T10:30` } });

    api.createCalendarEvent.mockResolvedValue(event({ id: "evt-3" }));
    fireEvent.click(within(dialog).getByRole("button", { name: /^guardar$/i }));

    // Nunca "…T09:00:00" sem offset: o servidor (timestamptz) leria-o como UTC
    // e, no Verão, o evento apareceria 1 hora mais tarde do que o escolhido.
    await waitFor(() =>
      expect(api.createCalendarEvent).toHaveBeenCalledWith(
        expect.objectContaining({ title: "Evento com offset", starts_at: startsAt, ends_at: endsAt })
      )
    );
  });

  it("pede ao servidor o intervalo visível como instantes com offset", async () => {
    renderWithProviders(<Planning />, { me: makeMe({ permissions: ["calendar.view", "calendar.manage"] }) });
    await screen.findByText("Visita técnica sintética");
    const call = api.listCalendarEvents.mock.calls[0][0] as { starts_from: string; starts_to: string };
    expect(call.starts_from).toMatch(/Z$/);
    expect(call.starts_to).toMatch(/Z$/);
    expect(new Date(call.starts_from).getTime()).toBeLessThan(new Date(call.starts_to).getTime());
  });

  it("deteta sobreposição de horário para o mesmo responsável e exige confirmação", async () => {
    renderWithProviders(<Planning />, { me: makeMe({ permissions: ["calendar.view", "calendar.manage"] }) });
    await screen.findByText("Visita técnica sintética");

    fireEvent.click(screen.getByRole("button", { name: /^novo evento$/i }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Título *"), { target: { value: "Outro evento sobreposto" } });
    fireEvent.change(within(dialog).getByLabelText("Início *"), { target: { value: `${TODAY}T09:30` } });
    fireEvent.change(within(dialog).getByLabelText("Fim *"), { target: { value: `${TODAY}T10:30` } });
    fireEvent.change(within(dialog).getByLabelText("Responsável"), { target: { value: "p-pm" } });

    expect(within(dialog).getByText(/Sobreposição de horário/)).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: /guardar mesmo assim/i }));
    expect(api.createCalendarEvent).not.toHaveBeenCalled();
    expect(within(dialog).getByText(/confirme para continuar/)).toBeInTheDocument();

    fireEvent.click(within(dialog).getByLabelText(/Confirmo que quero continuar/));
    api.createCalendarEvent.mockResolvedValue(event({ id: "evt-3" }));
    fireEvent.click(within(dialog).getByRole("button", { name: /guardar mesmo assim/i }));

    await waitFor(() => expect(api.createCalendarEvent).toHaveBeenCalled());
  });

  it("permite reagendar e cancelar um evento existente a partir do detalhe", async () => {
    renderWithProviders(<Planning />, { me: makeMe({ permissions: ["calendar.view", "calendar.manage"] }) });
    fireEvent.click(await screen.findByText("Visita técnica sintética"));

    const detail = await screen.findByRole("dialog");
    expect(within(detail).getByText("rascunho")).toBeInTheDocument();

    api.cancelCalendarEvent.mockResolvedValue(event({ status: "cancelado" }));
    fireEvent.click(within(detail).getByRole("button", { name: /cancelar evento/i }));

    await waitFor(() => expect(api.cancelCalendarEvent).toHaveBeenCalledWith("evt-1"));
  });
});
