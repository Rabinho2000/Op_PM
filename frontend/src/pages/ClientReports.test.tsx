import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { listClientReports } from "../api/client";
import { makeMe } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import ClientReports from "./ClientReports";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, listClientReports: vi.fn() };
});

const rows = [
  {
    project_id: "proj-1",
    project_name: "Projeto Sintético Um",
    client_name: "Cliente Sintético Um",
    pm: "PM Sintético Um",
    lifecycle_status: "construcao",
    status_label: "Construção",
    enabled: true,
    next_send_at: "2026-09-28T08:00:00Z",
    last_send: {
      id: "send-1",
      iso_week: "2026-W39",
      status: "sent" as const,
      to_emails: ["cliente1@example.invalid"],
      cc_emails: [],
      sent_at: "2026-09-21T08:00:00Z",
      created_at: "2026-09-21T08:00:00Z",
    },
    pending_review_count: 2,
  },
  {
    project_id: "proj-2",
    project_name: "Projeto Sintético Dois",
    client_name: "Cliente Sintético Dois",
    pm: "PM Sintético Dois",
    lifecycle_status: "concluido",
    status_label: "Concluído",
    enabled: false,
    next_send_at: null,
    last_send: null,
    pending_review_count: 0,
    to_emails: ["cliente2@example.invalid"],
    cc_emails: [],
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listClientReports).mockResolvedValue(rows);
});

describe("ClientReports", () => {
  it("lista projetos, mostra rascunhos e filtra por estado e PM", async () => {
    renderWithProviders(<ClientReports />, { me: makeMe({ permissions: ["client_report.view"] }) });
    expect(await screen.findByText("Projeto Sintético Um")).toBeInTheDocument();
    expect(screen.getByText("Projeto Sintético Dois")).toBeInTheDocument();
    expect(screen.getAllByRole("status")[0]).toHaveTextContent("2 rascunho(s)");
    expect(screen.getByText("cliente1@example.invalid")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Filtrar por estado"), { target: { value: "enabled" } });
    expect(screen.queryByText("Projeto Sintético Dois")).not.toBeInTheDocument();
    expect(screen.getByText("Projeto Sintético Um")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Filtrar por PM"), { target: { value: "PM Sintético Dois" } });
    await waitFor(() => expect(screen.getByText("Nenhum relatório corresponde aos filtros")).toBeInTheDocument());
  });

  it("preserva os filtros no URL e liga ao separador do projeto", async () => {
    renderWithProviders(<ClientReports />, {
      me: makeMe({ permissions: ["client_report.view"] }),
      route: "/client-reports?status=construcao&pm=PM%20Sint%C3%A9tico%20Um",
    });
    await screen.findByText("Projeto Sintético Um");
    expect(screen.queryByText("Projeto Sintético Dois")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Projeto Sintético Um" })).toHaveAttribute(
      "href",
      "/projects/proj-1?tab=relatorio"
    );
  });

  it("mostra estado vazio quando não há projetos", async () => {
    vi.mocked(listClientReports).mockResolvedValue([]);
    renderWithProviders(<ClientReports />, { me: makeMe({ permissions: ["client_report.view"] }) });
    expect(await screen.findByText("Ainda não há relatórios a clientes")).toBeInTheDocument();
  });
});
