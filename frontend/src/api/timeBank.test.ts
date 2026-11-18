import { describe, expect, it, vi } from "vitest";

const client = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiUpload: vi.fn(),
}));

vi.mock("./client", () => client);

import {
  createMyTimeBankEntry,
  formatSignedTimeBankDuration,
  hasBlockingTimeBankImportIssues,
  inferTimeBankMode,
  listTimeBankEntries,
  listTimeBankAdjustments,
  parseClockMinute,
  parseSignedTimeBankDuration,
  previewMyTimeBankEntry,
  reverseMyTimeBankEntry,
  timeBankDateRange,
  listTimeBankNotes,
  createTimeBankNote,
} from "./timeBank";
import type { TimeBankImportRead } from "./timeBank";

describe("Banco de Horas — valores inteiros e datas", () => {
  it("preserva saldos positivos, negativos e segundos sem passar por horas decimais", () => {
    expect(parseSignedTimeBankDuration("+02:30")).toBe(9000);
    expect(parseSignedTimeBankDuration("-01:15:30")).toBe(-4530);
    expect(formatSignedTimeBankDuration(9000)).toBe("+02:30");
    expect(formatSignedTimeBankDuration(-4530)).toBe("-01:15:30");
  });

  it("recusa formatos ambíguos e mantém 24:00 apenas como fim de dia", () => {
    expect(parseSignedTimeBankDuration("1.5")).toBeNull();
    expect(parseSignedTimeBankDuration("-2:60")).toBeNull();
    expect(parseClockMinute("24:00")).toBe(1440);
    expect(parseClockMinute("24:01")).toBeNull();
    expect(parseClockMinute("09:30")).toBe(570);
  });

  it("infere sábado e domingo por data civil, sem depender do fuso horário do browser", () => {
    expect(inferTimeBankMode("2026-10-16")).toBe("standard");
    expect(inferTimeBankMode("2026-10-17")).toBe("saturday");
    expect(inferTimeBankMode("2026-10-18")).toBe("manual");
  });

  it("constrói limites inclusivos para mês e ano selecionados", () => {
    expect(timeBankDateRange(2026, 2)).toEqual({ fromDate: "2026-02-01", toDate: "2026-02-28" });
    expect(timeBankDateRange(2024, 2)).toEqual({ fromDate: "2024-02-01", toDate: "2024-02-29" });
    expect(timeBankDateRange(2026, null)).toEqual({ fromDate: "2026-01-01", toDate: "2026-12-31" });
  });

  it("bloqueia apenas problemas de aplicação, não anomalias needs_review preserváveis", () => {
    const batch: TimeBankImportRead = {
      id: "batch-1",
      status: "pending",
      sha256: "synthetic",
      source_year: 2026,
      counts: { entries: 1, openings: 0, needs_review: 1 },
      people: [{ source_label: "Pessoa sintética", person_id: null, candidates: [] }],
      issues: [{ code: "missing_time", message: "Horário em falta", blocking: false, sheet: null, row: null }],
      applied_counts: null,
    };
    expect(hasBlockingTimeBankImportIssues(batch)).toBe(true);
    expect(hasBlockingTimeBankImportIssues(batch, { "Pessoa sintética": "p-1" })).toBe(false);
    expect(hasBlockingTimeBankImportIssues({ ...batch, issues: [{ ...batch.issues[0], blocking: true }] }, { "Pessoa sintética": "p-1" })).toBe(true);
  });

  it("serializes includeAnnulled false and true for both ledger endpoints", async () => {
    client.apiGet.mockResolvedValue({ items: [], total: 0 });
    await listTimeBankEntries({ includeAnnulled: false });
    await listTimeBankEntries({ includeAnnulled: true });
    await listTimeBankAdjustments({ includeAnnulled: false });
    await listTimeBankAdjustments({ includeAnnulled: true });
    expect(client.apiGet.mock.calls.map(([url]) => url)).toEqual([
      "/api/time-bank/entries?limit=100&offset=0&include_annulled=false",
      "/api/time-bank/entries?limit=100&offset=0&include_annulled=true",
      "/api/time-bank/adjustments?limit=100&offset=0&include_annulled=false",
      "/api/time-bank/adjustments?limit=100&offset=0&include_annulled=true",
    ]);
  });

  it("uses explicit person scope for independent note reads and creates", async () => {
    client.apiGet.mockResolvedValue({ items: [], total: 0 });
    client.apiPost.mockResolvedValue({});
    await listTimeBankNotes("person 1", 20, 40);
    await createTimeBankNote("person 1", "nota");
    expect(client.apiGet).toHaveBeenCalledWith("/api/time-bank/notes?person_id=person+1&limit=20&offset=40");
    expect(client.apiPost).toHaveBeenCalledWith("/api/time-bank/notes", { person_id: "person 1", body: "nota" });
  });

  it("chama os endpoints self-service com o corpo e o caminho do contrato", async () => {
    const body = {
      work_date: "2026-10-16",
      start_minute: 540,
      end_minute: 840,
      lunch_taken: true,
    };
    const preview = {
      work_date: body.work_date,
      calculation_mode: "standard",
      balance_seconds: 1800,
      warnings: [],
      duplicate: false,
    };
    client.apiPost.mockResolvedValueOnce(preview).mockResolvedValueOnce({ id: "entry-1" }).mockResolvedValueOnce({ id: "reverse-1" });

    await expect(previewMyTimeBankEntry(body)).resolves.toEqual(preview);
    await expect(createMyTimeBankEntry(body)).resolves.toEqual({ id: "entry-1" });
    await expect(reverseMyTimeBankEntry("entry/1", "Correção sintética")).resolves.toEqual({ id: "reverse-1" });

    expect(client.apiPost).toHaveBeenNthCalledWith(1, "/api/time-bank/my-entries/preview", body);
    expect(client.apiPost).toHaveBeenNthCalledWith(2, "/api/time-bank/my-entries", body);
    expect(client.apiPost).toHaveBeenNthCalledWith(3, "/api/time-bank/my-entries/entry%2F1/reverse", { reason: "Correção sintética" });
  });
});
