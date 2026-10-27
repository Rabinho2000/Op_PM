import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import type { TimeBankAdjustmentRead, TimeBankEntryRead, TimeBankSummary } from "../api/timeBank";
import { makeMe } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import { TimeBankRoute } from "../App";
import MyTimeBank from "./MyTimeBank";

const api = vi.hoisted(() => ({
  getTimeBankSummary: vi.fn(),
  listTimeBankPeople: vi.fn(),
  listTimeBankEntries: vi.fn(),
  listTimeBankAdjustments: vi.fn(),
  previewMyTimeBankEntry: vi.fn(),
  createMyTimeBankEntry: vi.fn(),
  reverseMyTimeBankEntry: vi.fn(),
}));

vi.mock("../api/timeBank", async () => {
  const actual = await vi.importActual<typeof import("../api/timeBank")>("../api/timeBank");
  return { ...actual, ...api };
});

function summary(overrides: Partial<TimeBankSummary> = {}): TimeBankSummary {
  return {
    people: [
      {
        person_id: "p-reader",
        display_name: "Pessoa Sintética",
        opening_seconds: 3600,
        credited_seconds: 7200,
        debited_seconds: 1800,
        balance_seconds: 9000,
        period_seconds: 5400,
        needs_review_count: 1,
        warnings: [{ code: "daily_limit", message: "Limite diário ultrapassado (aviso)." }],
      },
    ],
    ...overrides,
  };
}

function entry(overrides: Partial<TimeBankEntryRead> = {}): TimeBankEntryRead {
  return {
    id: "entry-1",
    person_id: "p-reader",
    work_date: "2026-10-16",
    start_minute: 540,
    end_minute: 840,
    lunch_taken: true,
    calculation_mode: "standard",
    balance_seconds: 1800,
    calculated_seconds: 1800,
    needs_review: false,
    review_flags: {},
    reason: null,
    provenance: { source: "self_service" },
    source_key: null,
    created_by_user_id: "u-reader",
    occurred_at: "2026-10-16T17:00:00Z",
    reversal_of_id: null,
    ...overrides,
  };
}

function adjustment(overrides: Partial<TimeBankAdjustmentRead> = {}): TimeBankAdjustmentRead {
  return {
    id: "adjustment-1",
    person_id: "p-reader",
    effective_date: "2026-10-01",
    delta_seconds: -1800,
    kind: "correction",
    reason: "Correção sintética",
    provenance: {},
    source_key: null,
    created_by_user_id: "u-manager",
    occurred_at: "2026-10-01T10:00:00Z",
    reversal_of_id: null,
    ...overrides,
  };
}

function configureData() {
  api.getTimeBankSummary.mockResolvedValue(summary());
  api.listTimeBankPeople.mockResolvedValue([{ id: "p-reader", display_name: "Pessoa Sintética", is_active: true }]);
  api.listTimeBankEntries.mockResolvedValue({ items: [entry()], total: 1 });
  api.listTimeBankAdjustments.mockResolvedValue({ items: [adjustment()], total: 1 });
  api.previewMyTimeBankEntry.mockResolvedValue({
    work_date: "2026-10-19",
    calculation_mode: "standard",
    balance_seconds: 1800,
    warnings: [],
    duplicate: false,
  });
  api.createMyTimeBankEntry.mockResolvedValue(entry());
  api.reverseMyTimeBankEntry.mockResolvedValue(entry({ id: "reverse-1", reversal_of_id: "entry-1", balance_seconds: -1800 }));
}

function renderPage() {
  return renderWithProviders(<MyTimeBank />, {
    me: makeMe({ person_id: "p-reader", permissions: ["time_bank.view_own"] }),
  });
}

async function waitForPreviewCall() {
  await waitFor(() => expect(api.previewMyTimeBankEntry).toHaveBeenCalled(), { timeout: 1200 });
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-19T12:00:00+01:00"));
  Object.values(api).forEach((fn) => fn.mockReset());
});

afterEach(() => {
  vi.useRealTimers();
});

describe("MyTimeBank", () => {
  it("aplica as predefinições seg–qui, sexta e sábado sem perder horas ainda não editadas", () => {
    configureData();
    renderPage();

    expect(screen.getByLabelText("Entrada")).toHaveValue("09:00");
    expect(screen.getByLabelText("Saída")).toHaveValue("18:30");

    fireEvent.change(screen.getByLabelText("Data"), { target: { value: "2026-10-16" } });
    expect(screen.getByLabelText("Entrada")).toHaveValue("09:00");
    expect(screen.getByLabelText("Saída")).toHaveValue("14:00");

    fireEvent.change(screen.getByLabelText("Data"), { target: { value: "2026-10-17" } });
    expect(screen.getByLabelText("Entrada")).toHaveValue("09:00");
    expect(screen.getByLabelText("Saída")).toHaveValue("13:00");

    fireEvent.change(screen.getByLabelText("Entrada"), { target: { value: "08:30" } });
    fireEvent.change(screen.getByLabelText("Data"), { target: { value: "2026-10-15" } });
    expect(screen.getByLabelText("Entrada")).toHaveValue("08:30");
    expect(screen.getByLabelText("Saída")).toHaveValue("13:00");
  });

  it("pré-visualiza com o corpo do contrato e mostra o saldo do dia", async () => {
    configureData();
    api.previewMyTimeBankEntry.mockResolvedValue({
      work_date: "2026-10-16",
      calculation_mode: "standard",
      balance_seconds: 1800,
      warnings: [{ code: "daily_limit", message: "Limite diário ultrapassado (aviso)." }],
      duplicate: false,
    });
    renderPage();
    fireEvent.change(screen.getByLabelText("Data"), { target: { value: "2026-10-16" } });

    await waitFor(() => expect(api.previewMyTimeBankEntry).toHaveBeenCalledWith({
      work_date: "2026-10-16",
      start_minute: 540,
      end_minute: 840,
      lunch_taken: true,
    }), { timeout: 1200 });
    expect(await screen.findByText("Saldo deste dia: +00:30")).toBeInTheDocument();
    expect(screen.getAllByText("Limite diário ultrapassado (aviso).")).toHaveLength(2);
  });

  it("desativa o guardar quando o preview assinala duplicado", async () => {
    configureData();
    api.previewMyTimeBankEntry.mockResolvedValue({
      work_date: "2026-10-19",
      calculation_mode: "standard",
      balance_seconds: 1800,
      warnings: [],
      duplicate: true,
    });
    renderPage();

    await waitForPreviewCall();
    expect(screen.getByRole("button", { name: "Guardar jornada" })).toBeDisabled();
    expect(screen.getByText(/Já existe um lançamento ativo para este dia/i)).toBeInTheDocument();
  });

  it("explica e bloqueia domingos e datas futuras", () => {
    configureData();
    renderPage();
    const save = screen.getByRole("button", { name: "Guardar jornada" });

    fireEvent.change(screen.getByLabelText("Data"), { target: { value: "2026-10-18" } });
    expect(screen.getByText(/Domingos e feriados só podem ser lançados/i)).toBeInTheDocument();
    expect(save).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Data"), { target: { value: "2026-10-20" } });
    expect(screen.getByText(/A data não pode ser futura/i)).toBeInTheDocument();
    expect(save).toBeDisabled();
  });

  it("guarda a jornada, mostra confirmação e recarrega saldo e histórico", async () => {
    configureData();
    renderPage();
    fireEvent.change(screen.getByLabelText("Data"), { target: { value: "2026-10-16" } });
    await waitFor(() => expect(api.previewMyTimeBankEntry).toHaveBeenCalledWith({
      work_date: "2026-10-16",
      start_minute: 540,
      end_minute: 840,
      lunch_taken: true,
    }), { timeout: 1200 });
    await waitFor(() => expect(screen.getByRole("button", { name: "Guardar jornada" })).not.toBeDisabled());
    const beforeSummaryCalls = api.getTimeBankSummary.mock.calls.length;

    fireEvent.click(screen.getByRole("button", { name: "Guardar jornada" }));
    await waitFor(() => expect(api.createMyTimeBankEntry).toHaveBeenCalledWith({
      work_date: "2026-10-16",
      start_minute: 540,
      end_minute: 840,
      lunch_taken: true,
    }));
    expect(await screen.findByText("Jornada guardada.")).toBeInTheDocument();
    await waitFor(() => expect(api.getTimeBankSummary.mock.calls.length).toBeGreaterThan(beforeSummaryCalls));
    expect(api.listTimeBankEntries.mock.calls.length).toBeGreaterThan(1);
    expect(api.listTimeBankAdjustments.mock.calls.length).toBeGreaterThan(1);
  });

  it("só mostra anular para self-service sem compensação e exige motivo", async () => {
    configureData();
    const reversedOriginal = entry({ id: "entry-2", provenance: { source: "self_service" } });
    const compensation = entry({ id: "entry-3", reversal_of_id: "entry-2", balance_seconds: -1800 });
    const managed = entry({ id: "entry-4", provenance: { source: "import" } });
    api.listTimeBankEntries.mockResolvedValue({ items: [entry(), reversedOriginal, compensation, managed], total: 4 });
    renderPage();

    const reverseButtons = await screen.findAllByRole("button", { name: "Anular" });
    expect(reverseButtons).toHaveLength(1);
    expect(screen.getByText("anulado")).toBeInTheDocument();
    expect(screen.getByText("anulação")).toBeInTheDocument();

    fireEvent.click(reverseButtons[0]);
    expect(screen.getByText("Tens a certeza?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirmar anulação" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Motivo da anulação *"), { target: { value: "Correção sintética" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar anulação" }));

    await waitFor(() => expect(api.reverseMyTimeBankEntry).toHaveBeenCalledWith("entry-1", "Correção sintética"));
    expect(screen.queryByRole("button", { name: "Anular" })).not.toBeInTheDocument();
  });

  it("mostra os estados de carregamento e erro da API", async () => {
    api.getTimeBankSummary.mockReturnValue(new Promise(() => undefined));
    api.listTimeBankEntries.mockReturnValue(new Promise(() => undefined));
    api.listTimeBankAdjustments.mockReturnValue(new Promise(() => undefined));
    api.previewMyTimeBankEntry.mockReturnValue(new Promise(() => undefined));
    renderPage();
    expect(screen.getAllByTestId("loading-state").length).toBeGreaterThan(0);

    api.getTimeBankSummary.mockReset();
    api.listTimeBankEntries.mockReset();
    api.listTimeBankAdjustments.mockReset();
    api.getTimeBankSummary.mockRejectedValue(new ApiError(503, "Falha sintética no saldo."));
    api.listTimeBankEntries.mockResolvedValue({ items: [], total: 0 });
    api.listTimeBankAdjustments.mockResolvedValue({ items: [], total: 0 });
    renderPage();
    expect(await screen.findByText("Falha sintética no saldo.")).toBeInTheDocument();
  });

  it("encaminha staff sem manage_all para self-service e mantém a gestão com manage_all", async () => {
    configureData();
    const scoped = renderWithProviders(<TimeBankRoute />, {
      me: makeMe({ permissions: ["project.view_all", "time_bank.view_own"] }),
    });
    expect(await screen.findByRole("heading", { name: "Registar jornada" })).toBeInTheDocument();
    scoped.unmount();

    configureData();
    renderWithProviders(<TimeBankRoute />, {
      me: makeMe({ permissions: ["project.view_all", "time_bank.view_all", "time_bank.manage_all"] }),
    });
    expect(await screen.findByRole("button", { name: /registar ajuste/i })).toBeInTheDocument();
  });
});
