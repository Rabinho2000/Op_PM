import { describe, expect, it } from "vitest";
import { formatNumberPt } from "./numbers";

describe("formatNumberPt", () => {
  it("usa vírgula decimal e até 2 casas por omissão", () => {
    expect(formatNumberPt(1.5)).toBe("1,5");
    expect(formatNumberPt(3.14159)).toBe("3,14");
  });
  it("respeita máximo e mínimo de casas", () => {
    expect(formatNumberPt(2, { min: 2, max: 2 })).toBe("2,00");
    expect(formatNumberPt(2.345, { max: 1 })).toBe("2,3");
    expect(formatNumberPt(7.123, { max: 0 })).toBe("7");
  });
  it("mostra traço para valores em falta ou inválidos", () => {
    expect(formatNumberPt(null)).toBe("—");
    expect(formatNumberPt(undefined)).toBe("—");
    expect(formatNumberPt(Number.NaN)).toBe("—");
    expect(formatNumberPt(Number.POSITIVE_INFINITY)).toBe("—");
  });
});
