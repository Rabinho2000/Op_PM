import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { COMERCIAL_ME, makeMe, makeSummary } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import { todayIsoLisbon } from "../utils/dates";
import Vacations from "./Vacations";

const api = vi.hoisted(() => ({
  listAbsences: vi.fn(),
  getDashboardSummary: vi.fn(),
  listHolidays: vi.fn(),
  createHoliday: vi.fn(),
  updateHoliday: vi.fn(),
  deleteHoliday: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, ...api };
});

function holiday(date: string) {
  return {
    id: "holiday-1",
    date,
    name: "Feriado de teste",
    scope: "municipal" as const,
    is_active: true,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.listAbsences.mockResolvedValue([]);
  api.getDashboardSummary.mockResolvedValue(
    makeSummary({
      upcoming_birthdays: [
        {
          person_id: "p-birthday",
          person_display_name: "Pessoa Aniversariante",
          birth_date: "1990-01-01",
          days_until: 0,
        },
      ],
    })
  );
  api.listHolidays.mockResolvedValue([holiday(todayIsoLisbon())]);
});

describe("Calendário de férias — feriados e aniversários", () => {
  it("marca feriados e aniversários na grelha e distingue visualmente o feriado", async () => {
    renderWithProviders(<Vacations />, { me: COMERCIAL_ME });

    const cell = await screen.findByRole("gridcell", {
      name: /Feriado de teste.*Aniversário de Pessoa Aniversariante/,
    });
    expect(within(cell).getByTitle("Feriado de teste")).toHaveClass("calendar__event--holiday");
    expect(within(cell).getByTitle("Aniversário: Pessoa Aniversariante")).toHaveClass("tone-warning");
    expect(screen.getByText("Feriado", { selector: ".legend span" })).toBeInTheDocument();
    expect(screen.getByText("🎂 Aniversário", { selector: ".legend span" })).toBeInTheDocument();
  });

  it("esconde a gestão no fluxo principal e permite gerir feriados no modal apenas com holiday.manage", async () => {
    const currentYear = Number(todayIsoLisbon().slice(0, 4));
    api.listHolidays.mockResolvedValue([
      holiday(todayIsoLisbon()),
      { ...holiday(`${currentYear - 1}-12-25`), id: "holiday-previous", name: "Feriado anterior" },
    ]);
    renderWithProviders(
      <Vacations />,
      { me: makeMe({ permissions: ["absence.view_all", "absence.manage_all", "absence.approve", "holiday.manage"] }) }
    );

    const openManagement = await screen.findByRole("button", { name: "Gerir feriados" });
    expect(screen.queryByRole("dialog", { name: "Gerir feriados" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Nome do feriado")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Desativar" })).not.toBeInTheDocument();
    const calendar = screen.getByRole("grid", { name: "Calendário de ausências" });
    expect(calendar.closest(".card")?.querySelector(".list__title")).toBeNull();
    await waitFor(() => expect(api.listHolidays).toHaveBeenCalledWith(undefined, undefined, true));

    openManagement.focus();
    fireEvent.click(openManagement);
    const management = await screen.findByRole("dialog", { name: "Gerir feriados" });
    expect(within(management).getByLabelText("Ano")).toHaveValue(String(currentYear));
    expect(within(management).getByText("Feriado de teste")).toBeInTheDocument();
    expect(within(management).queryByText("Feriado anterior")).not.toBeInTheDocument();
    fireEvent.change(within(management).getByLabelText("Ano"), { target: { value: String(currentYear - 1) } });
    expect(within(management).getByText("Feriado anterior")).toBeInTheDocument();
    expect(within(management).queryByText("Feriado de teste")).not.toBeInTheDocument();
    fireEvent.change(within(management).getByLabelText("Ano"), { target: { value: String(currentYear) } });
    expect(within(management).queryByLabelText("Nome do feriado")).not.toBeInTheDocument();

    fireEvent.click(within(management).getByRole("button", { name: "Adicionar feriado" }));
    fireEvent.change(within(management).getByLabelText("Nome do feriado"), { target: { value: "Feriado municipal" } });
    fireEvent.change(within(management).getByLabelText("Data do feriado"), { target: { value: "2026-06-13" } });
    fireEvent.change(within(management).getByLabelText("Âmbito"), { target: { value: "municipal" } });
    fireEvent.click(within(management).getByRole("button", { name: "Guardar feriado" }));

    await waitFor(() =>
      expect(api.createHoliday).toHaveBeenCalledWith({
        date: "2026-06-13",
        name: "Feriado municipal",
        scope: "municipal",
      })
    );
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Gerir feriados" })).not.toBeInTheDocument());
    expect(openManagement).toHaveFocus();
  });

  it("pede confirmação antes de desativar um feriado existente", async () => {
    renderWithProviders(
      <Vacations />,
      { me: makeMe({ permissions: ["absence.view_all", "absence.manage_all", "absence.approve", "holiday.manage"] }) }
    );
    fireEvent.click(await screen.findByRole("button", { name: "Gerir feriados" }));
    const management = await screen.findByRole("dialog", { name: "Gerir feriados" });
    fireEvent.click(within(management).getByRole("button", { name: "Desativar Feriado de teste" }));

    const confirmation = await screen.findByRole("dialog", { name: "Desativar feriado?" });
    expect(api.deleteHoliday).not.toHaveBeenCalled();
    fireEvent.click(within(confirmation).getByRole("button", { name: "Sim, desativar" }));
    await waitFor(() => expect(api.deleteHoliday).toHaveBeenCalledWith("holiday-1"));
  });

  it("não apresenta ação nem controlos de gestão sem holiday.manage", async () => {
    renderWithProviders(<Vacations />, { me: COMERCIAL_ME });
    expect(await screen.findByRole("grid", { name: "Calendário de ausências" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Gerir feriados" })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Gerir feriados" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Nome do feriado")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Adicionar feriado" })).not.toBeInTheDocument();
  });
});
