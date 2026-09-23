import { describe, expect, it } from "vitest";
import { daysUntilLabel, formatDatePt, isIsoDateInRange, lisbonWallClockToIso } from "./dates";

describe("formatDatePt", () => {
  it("converts an ISO date to dd/mm/yyyy", () => {
    expect(formatDatePt("2026-09-30")).toBe("30/09/2026");
  });

  it("returns a dash for null", () => {
    expect(formatDatePt(null)).toBe("—");
  });

  it("returns the original string when it cannot be parsed", () => {
    expect(formatDatePt("not-a-date")).toBe("not-a-date");
  });
});

describe("isIsoDateInRange", () => {
  it("is true when the date falls within the range (inclusive)", () => {
    expect(isIsoDateInRange("2026-09-16", "2026-09-14", "2026-09-20")).toBe(true);
    expect(isIsoDateInRange("2026-09-14", "2026-09-14", "2026-09-20")).toBe(true);
    expect(isIsoDateInRange("2026-09-20", "2026-09-14", "2026-09-20")).toBe(true);
  });

  it("is false outside the range", () => {
    expect(isIsoDateInRange("2026-09-21", "2026-09-14", "2026-09-20")).toBe(false);
    expect(isIsoDateInRange("2026-09-13", "2026-09-14", "2026-09-20")).toBe(false);
  });

  it("is false for a null date", () => {
    expect(isIsoDateInRange(null, "2026-09-14", "2026-09-20")).toBe(false);
  });
});

describe("daysUntilLabel", () => {
  it("labels today and tomorrow specially", () => {
    expect(daysUntilLabel(0)).toBe("hoje");
    expect(daysUntilLabel(1)).toBe("amanhã");
  });

  it("labels other offsets generically", () => {
    expect(daysUntilLabel(5)).toBe("daqui a 5 dias");
  });
});

describe("lisbonWallClockToIso", () => {
  it("Inverno (WET, UTC+0): a hora de Lisboa é igual à UTC", () => {
    expect(lisbonWallClockToIso("2026-01-15T09:00")).toBe("2026-01-15T09:00:00.000Z");
  });

  it("Verão (WEST, UTC+1): 09:00 em Lisboa são 08:00 UTC", () => {
    expect(lisbonWallClockToIso("2026-07-15T09:00")).toBe("2026-07-15T08:00:00.000Z");
  });

  it("virada de dia no Verão: 00:30 em Lisboa é 23:30 UTC do dia anterior", () => {
    expect(lisbonWallClockToIso("2026-07-15T00:30")).toBe("2026-07-14T23:30:00.000Z");
  });

  it("dia da mudança para Verão (29/03/2026, 01:00 UTC): antes = UTC+0, depois = UTC+1", () => {
    expect(lisbonWallClockToIso("2026-03-29T00:30")).toBe("2026-03-29T00:30:00.000Z");
    expect(lisbonWallClockToIso("2026-03-29T02:30")).toBe("2026-03-29T01:30:00.000Z");
  });

  it("rejeita valores que não são datetime-local", () => {
    expect(() => lisbonWallClockToIso("amanhã")).toThrow();
  });
});
