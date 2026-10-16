import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { makeMe } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import IsolatedTimeBank from "./IsolatedTimeBank";
import type { TimeBankImportRead, TimeBankSummary, TimeBankEntryRead, TimeBankAdjustmentRead } from "../api/timeBank";

const api = vi.hoisted(() => ({
  listTimeBankPeople: vi.fn(),
  getTimeBankSummary: vi.fn(),
  listTimeBankEntries: vi.fn(),
  listTimeBankAdjustments: vi.fn(),
  createTimeBankEntry: vi.fn(),
  createTimeBankAdjustment: vi.fn(),
  reverseTimeBankEntry: vi.fn(),
  reverseTimeBankAdjustment: vi.fn(),
  previewTimeBankImport: vi.fn(),
  getTimeBankImport: vi.fn(),
  resolveTimeBankImport: vi.fn(),
  applyTimeBankImport: vi.fn(),
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
    end_minute: 1110,
    lunch_taken: true,
    calculation_mode: "standard",
    balance_seconds: 1800,
    calculated_seconds: 1800,
    needs_review: false,
    review_flags: {},
    reason: null,
    provenance: {},
    source_key: null,
    created_by_user_id: "u-manager",
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

function configureReader() {
  api.listTimeBankPeople.mockResolvedValue([{ id: "p-reader", display_name: "Pessoa Sintética", is_active: true }]);
  api.getTimeBankSummary.mockResolvedValue(summary());
  api.listTimeBankEntries.mockResolvedValue({ items: [entry()], total: 1 });
  api.listTimeBankAdjustments.mockResolvedValue({ items: [adjustment()], total: 1 });
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
});

describe("Banco de Horas", () => {
  it("mantém o âmbito próprio do leitor, mostra saldo assinado e avisos sem bloquear", async () => {
    configureReader();
    renderWithProviders(<IsolatedTimeBank />, {
      me: makeMe({ person_id: "p-reader", display_name: "Pessoa Sintética", permissions: ["time_bank.view_own"] }),
    });

    expect(await screen.findByText("+02:30")).toBeInTheDocument();
    expect(screen.getByText("Limite diário ultrapassado (aviso).")).toBeInTheDocument();
    expect(screen.getAllByText("Pessoa Sintética").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: /registar jornada/i })).not.toBeInTheDocument();
    expect(api.listTimeBankPeople).not.toHaveBeenCalled();
    expect(api.getTimeBankSummary).toHaveBeenCalledWith(expect.objectContaining({ personId: "p-reader" }));
  });

  it("preserva review_flags como detalhe JSON quando o backend devolve um objeto aninhado", async () => {
    configureReader();
    api.listTimeBankEntries.mockResolvedValue({
      items: [entry({
        needs_review: true,
        review_flags: {
          weekday_mismatch: { expected: "saturday", observed: "standard" },
          formula: { detail: "valor histórico preservado" },
        },
      })],
      total: 1,
    });
    renderWithProviders(<IsolatedTimeBank />, {
      me: makeMe({ person_id: "p-reader", display_name: "Pessoa Sintética", permissions: ["time_bank.view_own"] }),
    });

    expect(await screen.findByText(/weekday_mismatch: \{"expected":"saturday","observed":"standard"\}/)).toBeInTheDocument();
    expect(screen.getByText(/formula: \{"detail":"valor histórico preservado"\}/)).toBeInTheDocument();
  });

  it("permite ao gestor registar uma sexta-feira com saldo inteiro em segundos", async () => {
    const manager = makeMe({ permissions: ["time_bank.view_all", "time_bank.manage_all"] });
    api.listTimeBankPeople.mockResolvedValue([
      { id: "p-chefe", display_name: "Chefe Sintético", is_active: true },
      { id: "p-two", display_name: "Pessoa Dois", is_active: true },
    ]);
    api.getTimeBankSummary.mockResolvedValue(summary({ people: [] }));
    api.listTimeBankEntries.mockResolvedValue({ items: [], total: 0 });
    api.listTimeBankAdjustments.mockResolvedValue({ items: [], total: 0 });
    api.createTimeBankEntry.mockResolvedValue(entry({ person_id: "p-two" }));

    renderWithProviders(<IsolatedTimeBank />, { me: manager });
    await screen.findByRole("button", { name: /registar jornada/i });
    fireEvent.click(screen.getByRole("button", { name: /registar jornada/i }));

    fireEvent.change(screen.getByLabelText("Pessoa", { exact: true }), { target: { value: "p-two" } });
    fireEvent.change(screen.getByLabelText(/data de trabalho/i), { target: { value: "2026-10-16" } });
    fireEvent.change(screen.getByLabelText(/entrada/i), { target: { value: "09:00" } });
    fireEvent.change(screen.getByLabelText(/saída/i), { target: { value: "14:00" } });
    fireEvent.click(screen.getByLabelText(/almoço descontado/i));
    fireEvent.click(screen.getByRole("button", { name: /guardar jornada/i }));

    await waitFor(() => expect(api.createTimeBankEntry).toHaveBeenCalledWith(expect.objectContaining({
      person_id: "p-two",
      work_date: "2026-10-16",
      start_minute: 540,
      end_minute: 840,
      calculation_mode: "standard",
      lunch_taken: false,
    })));
    expect(api.createTimeBankEntry.mock.calls[0][0].manual_balance_seconds).toBeUndefined();
  });

  it("exige motivo para anular e mostra o lançamento original depois da compensação", async () => {
    configureReader();
    api.reverseTimeBankEntry.mockResolvedValue(entry({ id: "reverse-1", reversal_of_id: "entry-1", balance_seconds: -1800 }));
    renderWithProviders(<IsolatedTimeBank />, {
      me: makeMe({ person_id: "p-reader", permissions: ["time_bank.view_own", "time_bank.manage_all"] }),
    });

    await screen.findAllByText("+00:30");
    fireEvent.click(screen.getByRole("button", { name: /anular lançamento/i }));
    expect(screen.getByRole("button", { name: /confirmar anulação/i })).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/motivo da anulação/i), { target: { value: "Correção sintética" } });
    expect(screen.getByRole("button", { name: /confirmar anulação/i })).not.toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /confirmar anulação/i }));

    await waitFor(() => expect(api.reverseTimeBankEntry).toHaveBeenCalledWith("entry-1", { reason: "Correção sintética" }));
    expect(await screen.findByText(/correção por anulação e novo lançamento/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /anular lançamento/i })).not.toBeInTheDocument();
  });

  it("não repete uma anulação conhecida e expõe o conflito 409 do backend", async () => {
    configureReader();
    api.reverseTimeBankEntry.mockRejectedValue(new ApiError(409, "Este lançamento já tem uma compensação."));
    renderWithProviders(<IsolatedTimeBank />, {
      me: makeMe({ person_id: "p-reader", permissions: ["time_bank.view_own", "time_bank.manage_all"] }),
    });

    await screen.findAllByText("+00:30");
    fireEvent.click(screen.getByRole("button", { name: /anular lançamento/i }));
    fireEvent.change(screen.getByLabelText(/motivo da anulação/i), { target: { value: "Tentativa duplicada" } });
    fireEvent.click(screen.getByRole("button", { name: /confirmar anulação/i }));

    expect(await screen.findByText("Este lançamento já tem uma compensação.")).toBeInTheDocument();
  });

  it("expõe o total e pagina a resposta bounded sem esconder lançamentos além dos 100", async () => {
    const manager = makeMe({ permissions: ["time_bank.view_all", "time_bank.manage_all"] });
    api.listTimeBankPeople.mockResolvedValue([{ id: "p-reader", display_name: "Pessoa Sintética", is_active: true }]);
    api.getTimeBankSummary.mockResolvedValue(summary({ people: [] }));
    api.listTimeBankAdjustments.mockResolvedValue({ items: [], total: 0 });
    api.listTimeBankEntries.mockImplementation(({ offset = 0 }: { offset?: number }) => Promise.resolve({
      items: [entry({ id: offset === 0 ? "entry-1" : "entry-101", work_date: offset === 0 ? "2026-01-01" : "2026-10-16" })],
      total: 101,
    }));

    renderWithProviders(<IsolatedTimeBank />, { me: manager });

    expect(await screen.findByText("Lançamentos (101)")).toBeInTheDocument();
    expect(screen.getByText("1–1 de 101")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /próxima página de lançamentos/i }));
    expect(await screen.findByText("101–101 de 101")).toBeInTheDocument();
    expect(api.listTimeBankEntries).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 100, limit: 100 }));
    expect(screen.getByText("16/10/2026")).toBeInTheDocument();
  });

  it("não aplica preview com pessoa por mapear e só confirma depois do readback", async () => {
    const manager = makeMe({ permissions: ["time_bank.view_all", "time_bank.manage_all"] });
    api.listTimeBankPeople.mockResolvedValue([
      { id: "p-chefe", display_name: "Chefe Sintético", is_active: true },
      { id: "p-two", display_name: "Pessoa Dois", is_active: true },
    ]);
    api.getTimeBankSummary.mockResolvedValue(summary({ people: [] }));
    api.listTimeBankEntries.mockResolvedValue({ items: [], total: 0 });
    api.listTimeBankAdjustments.mockResolvedValue({ items: [], total: 0 });
    const pending: TimeBankImportRead = {
      id: "import-1",
      status: "pending",
      sha256: "hash-sintetico",
      source_year: 2026,
      counts: { entries: 2, openings: 1, needs_review: 1, source_rows: 3, quarantined: 1 },
      people: [{ source_label: "Pessoa do Excel", person_id: null, candidates: [{ id: "p-two", display_name: "Pessoa Dois" }] }],
      issues: [{ code: "missing_time", message: "Horário em falta.", blocking: false, sheet: "Folha", row: 4 }],
      applied_counts: null,
    };
    const resolved: TimeBankImportRead = { ...pending, people: [{ ...pending.people[0], person_id: "p-two" }] };
    const applied: TimeBankImportRead = { ...resolved, status: "applied", applied_counts: { entries: 2, openings: 1 } };
    api.previewTimeBankImport.mockResolvedValue(pending);
    api.resolveTimeBankImport.mockResolvedValue(resolved);
    api.applyTimeBankImport.mockResolvedValue(applied);
    api.getTimeBankImport.mockResolvedValue(applied);

    renderWithProviders(<IsolatedTimeBank />, { me: manager });
    await screen.findByRole("button", { name: /importar excel/i });
    const input = screen.getByLabelText(/ficheiro excel/i);
    const file = new File(["xlsx-sintético"], "horas-sinteticas.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
    fireEvent.change(input, { target: { files: [file] } });

    expect(await screen.findByText("Pessoa do Excel")).toBeInTheDocument();
    expect(screen.getByText(/3 linhas de origem · 2 lançamentos · 1 em quarentena/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /aplicar importação/i })).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/pessoa do excel/i), { target: { value: "p-two" } });
    fireEvent.click(screen.getByRole("button", { name: /guardar mapeamento/i }));
    await waitFor(() => expect(api.resolveTimeBankImport).toHaveBeenCalledWith("import-1", { person_mapping: { "Pessoa do Excel": "p-two" } }));
    await waitFor(() => expect(screen.getByRole("button", { name: /aplicar importação/i })).not.toBeDisabled());

    fireEvent.click(screen.getByRole("button", { name: /aplicar importação/i }));
    fireEvent.click(screen.getByRole("button", { name: /confirmar aplicação/i }));
    await waitFor(() => expect(api.applyTimeBankImport).toHaveBeenCalledWith("import-1"));
    await waitFor(() => expect(api.getTimeBankImport).toHaveBeenCalledWith("import-1"));
    expect(await screen.findByText(/importação aplicada: 2 lançamentos/i)).toBeInTheDocument();
  });
});
