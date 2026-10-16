import { describe, expect, it } from "vitest";
import {
  formatSignedTimeBankDuration,
  hasBlockingTimeBankImportIssues,
  inferTimeBankMode,
  parseClockMinute,
  parseSignedTimeBankDuration,
  timeBankDateRange,
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
});
