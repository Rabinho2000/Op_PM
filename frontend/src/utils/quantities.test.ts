import { describe, expect, it } from "vitest";
import { formatQuantity } from "./quantities";

describe("formatQuantity", () => {
  it("remove zeros decimais de quantidades inteiras contadas à unidade", () => {
    expect(formatQuantity("1.000", "un")).toBe("1");
    expect(formatQuantity("0.000", "unidade")).toBe("0");
    expect(formatQuantity("2.000", "un.")).toBe("2");
  });

  it("preserva a precisão recebida nas unidades fracionárias", () => {
    expect(formatQuantity("1.500", "km")).toBe("1.500");
    expect(formatQuantity("0.250", "kg")).toBe("0.250");
  });

  it("não arredonda um valor fracionário marcado como unidade", () => {
    expect(formatQuantity("1.500", "un")).toBe("1.500");
  });

  it("mantém valores inválidos visíveis em vez de os converter em zero", () => {
    expect(formatQuantity("abc", "un")).toBe("abc");
    expect(formatQuantity(null, "un")).toBe("—");
  });
});
