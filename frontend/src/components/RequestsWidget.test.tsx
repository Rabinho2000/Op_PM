import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { RequestListPage, RequestThread } from "../api/requests";
import { makeMe } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import RequestsWidget from "./RequestsWidget";

const api = vi.hoisted(() => ({
  createRequest: vi.fn(),
  listRequests: vi.fn(),
  getRequest: vi.fn(),
  postRequestMessage: vi.fn(),
}));

vi.mock("../api/requests", async () => {
  const actual = await vi.importActual<typeof import("../api/requests")>("../api/requests");
  return { ...actual, ...api };
});

function thread(overrides: Partial<RequestThread> = {}): RequestThread {
  return {
    id: "request-1",
    status: "open",
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
        body: "Preciso de ajuda",
        created_at: "2026-10-19T09:00:00Z",
      },
      {
        id: "message-2",
        author_name: "Equipa Sintética",
        is_staff_reply: true,
        is_mine: false,
        body: "Resposta da equipa",
        created_at: "2026-10-19T09:05:00Z",
      },
    ],
    ...overrides,
  };
}

function listPage(overrides: Partial<RequestListPage> = {}): RequestListPage {
  return {
    items: [
      {
        id: "request-1",
        status: "open",
        page_path: "/tasks",
        created_at: "2026-10-19T09:00:00Z",
        updated_at: "2026-10-19T09:05:00Z",
        author_name: "Utilizador Sintético",
        message_count: 2,
        last_message_preview: "Resposta da equipa",
        last_message_is_staff: true,
      },
    ],
    total: 1,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState({}, "", "/tasks");
  api.listRequests.mockResolvedValue(listPage());
  api.getRequest.mockResolvedValue(thread());
  api.postRequestMessage.mockResolvedValue(thread());
  api.createRequest.mockResolvedValue(thread());
});

describe("RequestsWidget", () => {
  it("não aparece sem requests.create", () => {
    renderWithProviders(<RequestsWidget />, { me: makeMe({ permissions: [] }) });

    expect(screen.queryByRole("button", { name: "Pedidos" })).not.toBeInTheDocument();
  });

  it("cria um pedido com a página atual e mostra confirmação", async () => {
    renderWithProviders(<RequestsWidget />, {
      me: makeMe({ permissions: ["requests.create"] }),
    });

    fireEvent.click(screen.getByRole("button", { name: "Pedidos" }));
    fireEvent.change(screen.getByLabelText("Descreve o pedido"), { target: { value: "Preciso de ajuda" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));

    await waitFor(() =>
      expect(api.createRequest).toHaveBeenCalledWith({ body: "Preciso de ajuda", page_path: "/tasks" })
    );
    expect(await screen.findByText("Pedido enviado.")).toBeInTheDocument();
  });

  it("lista os meus pedidos, abre a conversa e identifica uma resposta da equipa", async () => {
    renderWithProviders(<RequestsWidget />, {
      me: makeMe({ permissions: ["requests.create"] }),
    });

    fireEvent.click(screen.getByRole("button", { name: "Pedidos" }));
    fireEvent.click(screen.getByRole("tab", { name: "Os meus pedidos" }));
    expect(await screen.findByRole("button", { name: /Preciso de ajuda|Resposta da equipa/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Preciso de ajuda|Resposta da equipa/ }));

    expect(await screen.findByText("Resposta da equipa")).toBeInTheDocument();
    expect(screen.getByText("Equipa")).toBeInTheDocument();
  });

  it("fecha o painel com Escape", () => {
    renderWithProviders(<RequestsWidget />, {
      me: makeMe({ permissions: ["requests.create"] }),
    });

    fireEvent.click(screen.getByRole("button", { name: "Pedidos" }));
    expect(screen.getByRole("dialog", { name: "Pedidos" })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByRole("dialog", { name: "Pedidos" })).not.toBeInTheDocument();
  });
});
