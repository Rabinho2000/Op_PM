import { describe, expect, it } from "vitest";
import { ApiError, NETWORK_ERROR_MESSAGE, errorMessage } from "../api/client";
import { errorDetail } from "./errors";

describe("mensagens de erro", () => {
  it("errorMessage usa o detail da API ou o texto de reserva", () => {
    expect(errorMessage(new ApiError(409, "Conflito"), "reserva")).toBe("Conflito");
    expect(errorMessage(new Error("interno"), "reserva")).toBe("reserva");
    expect(errorMessage("texto", "reserva")).toBe("reserva");
    expect(errorMessage(undefined)).toBe(NETWORK_ERROR_MESSAGE);
  });

  it("errorDetail acrescenta a mensagem de um Error genérico", () => {
    expect(errorDetail(new ApiError(422, "Inválido"), "reserva")).toBe("Inválido");
    expect(errorDetail(new Error("Nome em falta"), "reserva")).toBe("Nome em falta");
    expect(errorDetail(new Error(""), "reserva")).toBe("reserva");
    expect(errorDetail(null, "reserva")).toBe("reserva");
  });
});
