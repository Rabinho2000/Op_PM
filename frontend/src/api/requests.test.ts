import { describe, expect, it, vi } from "vitest";

const client = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
}));

vi.mock("./client", () => client);

import {
  createRequest,
  getRequest,
  getRequestsSummary,
  listRequests,
  postRequestMessage,
  setRequestStatus,
} from "./requests";
import type { RequestListPage, RequestMessage, RequestSummary, RequestThread } from "./requests";

const page: RequestListPage = { items: [], total: 0 };
const summary: RequestSummary = { open: 2 };
const thread: RequestThread = {
  id: "request/1",
  status: "open",
  page_path: "/tasks",
  created_at: "2026-10-19T09:00:00Z",
  updated_at: "2026-10-19T09:05:00Z",
  author_name: "Utilizador Sintético",
  messages: [],
};
const message: RequestMessage = {
  id: "message-1",
  author_name: "Equipa Sintética",
  is_staff_reply: true,
  is_mine: false,
  body: "Resposta sintética",
  created_at: "2026-10-19T09:05:00Z",
};

describe("API de pedidos", () => {
  it("constrói a listagem e os endpoints do contrato", async () => {
    client.apiGet.mockResolvedValueOnce(page).mockResolvedValueOnce(summary).mockResolvedValueOnce(thread);
    client.apiPost.mockResolvedValueOnce(thread).mockResolvedValueOnce(message).mockResolvedValueOnce(thread);

    await expect(listRequests({ scope: "all", status: "open", limit: 25, offset: 50 })).resolves.toBe(page);
    await expect(getRequestsSummary()).resolves.toBe(summary);
    await expect(createRequest({ body: "Pedido sintético", page_path: "/tasks" })).resolves.toBe(thread);
    await expect(getRequest("request/1")).resolves.toBe(thread);
    await expect(postRequestMessage("request/1", "Resposta sintética")).resolves.toBe(message);
    await expect(setRequestStatus("request/1", "resolved")).resolves.toBe(thread);

    expect(client.apiGet).toHaveBeenNthCalledWith(1, "/api/requests?scope=all&status=open&limit=25&offset=50");
    expect(client.apiGet).toHaveBeenNthCalledWith(2, "/api/requests/summary");
    expect(client.apiGet).toHaveBeenNthCalledWith(3, "/api/requests/request%2F1");
    expect(client.apiPost).toHaveBeenNthCalledWith(1, "/api/requests", { body: "Pedido sintético", page_path: "/tasks" });
    expect(client.apiPost).toHaveBeenNthCalledWith(2, "/api/requests/request%2F1/messages", { body: "Resposta sintética" });
    expect(client.apiPost).toHaveBeenNthCalledWith(3, "/api/requests/request%2F1/status", { status: "resolved" });
  });

  it("omite filtros ausentes sem inventar valores", async () => {
    client.apiGet.mockResolvedValue(page);

    await listRequests({});

    expect(client.apiGet).toHaveBeenCalledWith("/api/requests");
  });
});
