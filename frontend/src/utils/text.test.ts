import { describe, expect, it } from "vitest";
import { normalizeSearchText } from "./text";

describe("normalizeSearchText", () => {
  it("tira acentos, passa a minúsculas e apara", () => {
    expect(normalizeSearchText("  Instalação Elétrica Ç  ")).toBe("instalacao eletrica c");
  });
  it("mantém dígitos e pontuação", () => {
    expect(normalizeSearchText("PV-100/2")).toBe("pv-100/2");
  });
  it("aceita texto vazio", () => {
    expect(normalizeSearchText("")).toBe("");
  });
});
