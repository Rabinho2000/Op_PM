import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  approveClientReportSend,
  discardClientReportSend,
  getClientReport,
  previewClientReport,
  sendClientReportNow,
  updateClientReport,
} from "../api/client";
import { makeMe } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import ClientReport from "./ClientReport";

const api = { getClientReport, updateClientReport, previewClientReport, sendClientReportNow, approveClientReportSend, discardClientReportSend };

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    getClientReport: vi.fn(),
    updateClientReport: vi.fn(),
    previewClientReport: vi.fn(),
    sendClientReportNow: vi.fn(),
    approveClientReportSend: vi.fn(),
    discardClientReportSend: vi.fn(),
  };
});

const report = {
  enabled: true,
  review_before_send: true,
  weekday: 0,
  send_time: "09:00",
  to_emails: ["cliente@example.invalid"],
  cc_emails: ["pm@example.invalid"],
  weekly_note: "Nota sintética",
  can_manage: true,
  delivery_mode: "local" as const,
  next_send_at: "2026-09-28T08:00:00Z",
  warnings: ["Atenção sintética"],
  last_sends: [
    {
      id: "send-1",
      iso_week: "2026-W39",
      status: "pending_review" as const,
      trigger: "scheduled",
      subject: "Relatório semanal",
      to_emails: ["cliente@example.invalid"],
      cc_emails: [],
      sent_at: null,
      created_at: "2026-09-27T08:00:00Z",
      error: null,
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.getClientReport).mockResolvedValue(report);
  vi.mocked(api.updateClientReport).mockResolvedValue(report);
  vi.mocked(api.previewClientReport).mockResolvedValue({
    subject: "Relatório semanal",
    body_html: "<h1>Conteúdo sintético</h1>",
    from_email: "noreply@example.invalid",
    to: ["cliente@example.invalid"],
    cc: ["pm@example.invalid"],
  });
  vi.mocked(api.sendClientReportNow).mockResolvedValue(report.last_sends[0]);
  vi.mocked(api.approveClientReportSend).mockResolvedValue({ ...report.last_sends[0], status: "sent" });
  vi.mocked(api.discardClientReportSend).mockResolvedValue({ ...report.last_sends[0], status: "discarded" });
});

describe("ClientReport", () => {
  it("guarda a configuração com os valores editados", async () => {
    renderWithProviders(<ClientReport projectId="proj-1" />, { me: makeMe({ permissions: ["client_report.manage"] }) });
    await screen.findByText("Configuração");

    fireEvent.click(screen.getByLabelText("Ativar relatório semanal"));
    fireEvent.change(screen.getByLabelText("Dia da semana"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Hora"), { target: { value: "11:30" } });
    fireEvent.change(screen.getByLabelText("Para 1"), { target: { value: "outro@example.invalid" } });
    fireEvent.change(screen.getByLabelText("Nota da semana"), { target: { value: "Nota nova" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar configuração" }));

    await waitFor(() =>
      expect(api.updateClientReport).toHaveBeenCalledWith("proj-1", {
        enabled: false,
        review_before_send: true,
        weekday: 2,
        send_time: "11:30",
        to_emails: ["outro@example.invalid"],
        cc_emails: ["pm@example.invalid"],
        weekly_note: "Nota nova",
      })
    );
  });

  it("valida endereços de email antes de guardar", async () => {
    renderWithProviders(<ClientReport projectId="proj-1" />, { me: makeMe() });
    await screen.findByText("Configuração");
    fireEvent.change(screen.getByLabelText("Para 1"), { target: { value: "email-invalido" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar configuração" }));

    expect(await screen.findByText(/endereço de email inválido/)).toBeInTheDocument();
    expect(api.updateClientReport).not.toHaveBeenCalled();
  });

  it("não mostra ações sem can_manage", async () => {
    vi.mocked(api.getClientReport).mockResolvedValue({ ...report, can_manage: false });
    renderWithProviders(<ClientReport projectId="proj-1" />, { me: makeMe() });
    await screen.findByText("Configuração");

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Hora")).toBeDisabled();
  });

  it("mostra o modo de teste e usa iframe sandbox na pré-visualização", async () => {
    renderWithProviders(<ClientReport projectId="proj-1" />, { me: makeMe() });
    expect(await screen.findByText(/Modo de teste — nenhum email é entregue ao cliente/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pré-visualizar email" }));

    const iframe = await screen.findByTitle("Conteúdo do email");
    expect(iframe).toHaveAttribute("sandbox", "");
    expect(iframe).toHaveAttribute("srcdoc", "<h1>Conteúdo sintético</h1>");
  });

  it("pede confirmação antes de enviar agora", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderWithProviders(<ClientReport projectId="proj-1" />, { me: makeMe() });
    await screen.findByText("Configuração");
    fireEvent.click(screen.getByRole("button", { name: "Enviar agora" }));

    expect(confirm).toHaveBeenCalledWith("Enviar o relatório desta semana agora?");
    expect(api.sendClientReportNow).not.toHaveBeenCalled();
    confirm.mockRestore();
  });

  it("aprova e descarta rascunhos pendentes", async () => {
    renderWithProviders(<ClientReport projectId="proj-1" />, { me: makeMe() });
    await screen.findByText("A aguardar aprovação");
    fireEvent.click(screen.getByRole("button", { name: "Aprovar" }));
    await waitFor(() => expect(api.approveClientReportSend).toHaveBeenCalledWith("send-1"));

    // O reload mantém o fixture pendente; ambos os comandos devem continuar disponíveis.
    fireEvent.click(screen.getByRole("button", { name: "Descartar" }));
    await waitFor(() => expect(api.discardClientReportSend).toHaveBeenCalledWith("send-1"));
  });
});
