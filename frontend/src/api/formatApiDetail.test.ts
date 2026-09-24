import { describe, expect, it } from "vitest";
import { formatApiDetail } from "./client";

describe("formatApiDetail", () => {
  it("mantém o texto simples", () => {
    expect(formatApiDetail("Fornecedor não encontrado.")).toBe("Fornecedor não encontrado.");
  });

  it("junta as mensagens de validação do FastAPI e tira o prefixo técnico", () => {
    expect(
      formatApiDetail([
        { type: "value_error", loc: ["body", "email"], msg: "Value error, Email inválido." },
        { type: "value_error", loc: ["body", "phone"], msg: "Value error, Telefone inválido." },
      ])
    ).toBe("Email inválido. Telefone inválido.");
  });

  it("devolve null quando não há nada legível (o chamador usa o statusText)", () => {
    expect(formatApiDetail(undefined)).toBeNull();
    expect(formatApiDetail([])).toBeNull();
    expect(formatApiDetail([{ foo: 1 }])).toBeNull();
  });
});
