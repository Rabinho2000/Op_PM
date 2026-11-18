import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { RequestListPage, RequestThread } from "../api/requests";
import { makeMe } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import Requests from "./Requests";

const api = vi.hoisted(() => ({
  listRequests: vi.fn(),
  getRequest: vi.fn(),
  postRequestMessage: vi.fn(),
  setRequestStatus: vi.fn(),
}));

vi.mock("../api/requests", async () => {
  const actual = await vi.importActual<typeof import("../api/requests")>("../api/requests");
  return { ...actual, ...api };
});

function listPage(status: "open" | "resolved" = "open"): RequestListPage {
  return {
    items: [
      {
        id: "request-1",
        status,
        page_path: "/tasks",
        created_at: "2026-10-19T09:00:00Z",
        updated_at: "2026-10-19T09:05:00Z",
        author_name: "Utilizador Sintético",
        message_count: 1,
        last_message_preview: "Pedido sobre uma tarefa",
        last_message_is_staff: false,
      },
    ],
    total: 1,
  };
}

function thread(status: "open" | "resolved" = "open"): RequestThread {
  return {
    id: "request-1",
    status,
    page_path: "/tasks",
    created_at: "2026-10-19T09:00:00Z",
    updated_at: "2026-10-19T09:05:00Z",
    author_name: "Utilizador Sintético",
    messages: [
      {
        id: "message-1",
        author_name: "Utilizador Sintético",
        is_staff_reply: false,
        is_mine: true,
        body: "Pedido sobre uma tarefa",
        created_at: "2026-10-19T09:00:00Z",
      },
    ],
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  api.listRequests.mockResolvedValue(listPage());
  api.getRequest.mockResolvedValue(thread());
  api.postRequestMessage.mockResolvedValue({
    id: "message-2",
    author_name: "Chefe Sintético",
    is_staff_reply: true,
    is_mine: true,
    body: "Resposta sintética",
    created_at: "2026-10-19T09:10:00Z",
  });
  api.setRequestStatus.mockResolvedValue(thread("resolved"));
});

describe("Requests", () => {
  it("carrega a caixa com abertos e chama a API ao trocar o filtro", async () => {
    renderWithProviders(<Requests />, { me: makeMe({ permissions: ["requests.manage"] }) });
    expect(await screen.findByText("Pedido sobre uma tarefa")).toBeInTheDocument();
    expect(api.listRequests).toHaveBeenCalledWith({ scope: "all", status: "open", limit: 50, offset: 0 });

    fireEvent.change(screen.getByLabelText("Filtrar por estado"), { target: { value: "resolved" } });
    await waitFor(() =>
      expect(api.listRequests).toHaveBeenLastCalledWith({ scope: "all", status: "resolved", limit: 50, offset: 0 })
    );
  });

  it("abre a conversa, responde e resolve ou reabre o pedido", async () => {
    renderWithProviders(<Requests />, { me: makeMe({ permissions: ["requests.manage"] }) });
    const row = await screen.findByRole("button", { name: /Pedido sobre uma tarefa/ });
    fireEvent.click(row);
    expect(await screen.findByRole("heading", { name: "Conversa" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Responder ao pedido"), { target: { value: "Resposta sintética" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar resposta" }));
    await waitFor(() => expect(api.postRequestMessage).toHaveBeenCalledWith("request-1", "Resposta sintética"));

    fireEvent.click(screen.getByRole("button", { name: "Marcar como resolvido" }));
    await waitFor(() => expect(api.setRequestStatus).toHaveBeenCalledWith("request-1", "resolved"));

    fireEvent.click(screen.getByRole("button", { name: "Reabrir" }));
    await waitFor(() => expect(api.setRequestStatus).toHaveBeenCalledWith("request-1", "open"));
  });

  it("mostra estados vazio e de erro da listagem", async () => {
    api.listRequests.mockResolvedValueOnce({ items: [], total: 0 });
    renderWithProviders(<Requests />, { me: makeMe({ permissions: ["requests.manage"] }) });
    expect(await screen.findByText("Não há pedidos neste filtro.")).toBeInTheDocument();

    api.listRequests.mockRejectedValueOnce(new Error("falha sintética"));
    renderWithProviders(<Requests />, { me: makeMe({ permissions: ["requests.manage"] }) });
    expect(await screen.findByText("Não foi possível contactar o servidor.")).toBeInTheDocument();
  });
});
