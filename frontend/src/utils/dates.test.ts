import { describe, expect, it } from "vitest";
import { daysUntilLabel, formatDatePt, isIsoDateInRange } from "./dates";

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
