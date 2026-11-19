import { ApiError } from "../api/client";

/**
 * Texto de erro para o utilizador, quando também interessa a mensagem de um
 * `Error` genérico (ex. falha de validação local): o `detail` da API, senão a
 * mensagem do erro, senão o texto de reserva. Para erros que só vêm da API
 * (sem `Error` local), `errorMessage` de `api/client` chega.
 */
export function errorDetail(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.detail;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}
