import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import type { AlertPhase, ProcessNotification } from "../api/processAlerts";
import { makeMe } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import ProcessAlerts from "./ProcessAlerts";

const api = vi.hoisted(() => ({
  getAlertSubscriptions: vi.fn(),
  saveAlertSubscriptions: vi.fn(),
  listProcessNotifications: vi.fn(),
  markProcessNotificationRead: vi.fn(),
  markAllProcessNotificationsRead: vi.fn(),
}));

vi.mock("../api/processAlerts", async () => {
  const actual = await vi.importActual<typeof import("../api/processAlerts")>("../api/processAlerts");
  return { ...actual, ...api };
});

function phases(subscribed: string[] = []): AlertPhase[] {
  const flag = (id: string) => subscribed.includes(id);
  return [
    {
      id: "phase-1",
      code: "FASE1",
      name: "Licenciamento",
      stages: [
        { id: "stage-a", code: "A", title: "Pedido de licença", subscribed: flag("stage-a") },
        { id: "stage-b", code: "B", title: "Parecer", subscribed: flag("stage-b") },
      ],
    },
    {
      id: "phase-2",
      code: "FASE2",
      name: "Execução",
      stages: [{ id: "stage-c", code: "C", title: "Montagem", subscribed: flag("stage-c") }],
    },
  ];
}

function notification(overrides: Partial<ProcessNotification> = {}): ProcessNotification {
  return {
    id: "notif-1",
    kind: "stage_completed",
    message: "Etapa concluída: Montagem — Projeto Sintético",
    project_id: "project-1",
    project_name: "Projeto Sintético",
    stage_id: "stage-c",
    stage_title: "Montagem",
    is_read: false,
    created_at: "2026-10-19T09:00:00Z",
    read_at: null,
    ...overrides,
  };
}

const ALERT_ME = makeMe({ permissions: ["process_alert.use"] });

beforeEach(() => {
  vi.clearAllMocks();
  api.getAlertSubscriptions.mockResolvedValue({ phases: phases(["stage-a"]) });
  api.saveAlertSubscriptions.mockImplementation(async (ids: string[]) => ({
    phases: phases(ids),
  }));
  api.listProcessNotifications.mockResolvedValue({ items: [notification()], total: 1, limit: 50, offset: 0 });
  api.markProcessNotificationRead.mockResolvedValue(notification({ is_read: true }));
  api.markAllProcessNotificationsRead.mockResolvedValue({ marked: 1 });
});

describe("ProcessAlerts (página Alertas)", () => {
  it("agrupa as etapas do catálogo por fase e marca as subscritas", async () => {
    renderWithProviders(<ProcessAlerts />, { me: ALERT_ME });

    const licensing = (await screen.findByText("Licenciamento")).closest("fieldset") as HTMLElement;
    const execution = screen.getByText("Execução").closest("fieldset") as HTMLElement;
    expect(within(licensing).getByRole("checkbox", { name: "Pedido de licença" })).toBeChecked();
    expect(within(licensing).getByRole("checkbox", { name: "Parecer" })).not.toBeChecked();
    expect(within(execution).getByRole("checkbox", { name: "Montagem" })).not.toBeChecked();
  });

  it("grava as subscrições com PUT apenas quando há alterações", async () => {
    renderWithProviders(<ProcessAlerts />, { me: ALERT_ME });
    await screen.findByText("Licenciamento");

    const save = screen.getByRole("button", { name: "Guardar subscrições" });
    expect(save).toBeDisabled();

    fireEvent.click(screen.getByRole("checkbox", { name: "Montagem" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Pedido de licença" }));
    fireEvent.click(screen.getByRole("button", { name: "Guardar subscrições" }));

    await waitFor(() => expect(api.saveAlertSubscriptions).toHaveBeenCalledWith(["stage-c"]));
    expect(await screen.findByText("Subscrições guardadas.")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Montagem" })).toBeChecked();
  });

  it("mostra o erro da API quando a gravação falha", async () => {
    api.saveAlertSubscriptions.mockRejectedValue(new ApiError(422, "Etapa do catálogo desconhecida."));
    renderWithProviders(<ProcessAlerts />, { me: ALERT_ME });
    await screen.findByText("Licenciamento");

    fireEvent.click(screen.getByRole("checkbox", { name: "Parecer" }));
    fireEvent.click(screen.getByRole("button", { name: "Guardar subscrições" }));

    expect(await screen.findByText("Etapa do catálogo desconhecida.")).toBeInTheDocument();
  });

  it("mostra erro com repetição quando o catálogo não carrega", async () => {
    api.getAlertSubscriptions.mockRejectedValueOnce(new ApiError(500, "Falha interna."));
    renderWithProviders(<ProcessAlerts />, { me: ALERT_ME });

    expect(await screen.findByRole("alert")).toHaveTextContent("Falha interna.");
    api.getAlertSubscriptions.mockResolvedValueOnce({ phases: phases() });
    fireEvent.click(screen.getByRole("button", { name: "Tentar novamente" }));
    expect(await screen.findByText("Licenciamento")).toBeInTheDocument();
  });

  it("histórico: pede só não lidas quando o filtro está ativo e marca como lida", async () => {
    renderWithProviders(<ProcessAlerts />, { me: ALERT_ME });
    expect(await screen.findByText("Etapa concluída: Montagem — Projeto Sintético")).toBeInTheDocument();
    expect(api.listProcessNotifications).toHaveBeenLastCalledWith({ unread_only: false, limit: 50, offset: 0 });

    fireEvent.click(screen.getByRole("checkbox", { name: "Só não lidas" }));
    await waitFor(() =>
      expect(api.listProcessNotifications).toHaveBeenLastCalledWith({ unread_only: true, limit: 50, offset: 0 })
    );

    fireEvent.click(screen.getByRole("button", { name: "Marcar como lida" }));
    await waitFor(() => expect(api.markProcessNotificationRead).toHaveBeenCalledWith("notif-1"));
  });

  it("histórico: mostra o erro quando a lista falha", async () => {
    api.listProcessNotifications.mockRejectedValue(new ApiError(500, "Histórico indisponível."));
    renderWithProviders(<ProcessAlerts />, { me: ALERT_ME });

    expect(await screen.findByText("Histórico indisponível.")).toBeInTheDocument();
  });
});
