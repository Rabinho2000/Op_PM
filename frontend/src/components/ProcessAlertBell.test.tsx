import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import type { ProcessNotification, ProcessNotificationPage } from "../api/processAlerts";
import { makeMe } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import ProcessAlertBell from "./ProcessAlertBell";
import type { Perm } from "../generated/permissions";

const api = vi.hoisted(() => ({
  getUnreadProcessNotificationCount: vi.fn(),
  listProcessNotifications: vi.fn(),
  markProcessNotificationRead: vi.fn(),
  markAllProcessNotificationsRead: vi.fn(),
}));

vi.mock("../api/processAlerts", async () => {
  const actual = await vi.importActual<typeof import("../api/processAlerts")>("../api/processAlerts");
  return { ...actual, ...api };
});

const ALERT_PERMISSION: { permissions: Perm[] } = { permissions: ["process_alert.use"] };

function notification(overrides: Partial<ProcessNotification> = {}): ProcessNotification {
  return {
    id: "notif-1",
    kind: "stage_completed",
    message: "Etapa concluída: Montagem — Projeto Sintético",
    project_id: "project-1",
    project_name: "Projeto Sintético",
    stage_id: "stage-1",
    stage_title: "Montagem",
    is_read: false,
    created_at: "2026-10-19T09:00:00Z",
    read_at: null,
    ...overrides,
  };
}

function page(items: ProcessNotification[]): ProcessNotificationPage {
  return { items, total: items.length, limit: 20, offset: 0 };
}

beforeEach(() => {
  vi.clearAllMocks();
  api.getUnreadProcessNotificationCount.mockResolvedValue({ unread: 2 });
  api.listProcessNotifications.mockResolvedValue(page([notification()]));
  api.markProcessNotificationRead.mockResolvedValue(notification({ is_read: true, read_at: "2026-10-19T10:00:00Z" }));
  api.markAllProcessNotificationsRead.mockResolvedValue({ marked: 2 });
});

describe("ProcessAlertBell", () => {
  it("mostra a contagem de não lidas", async () => {
    renderWithProviders(<ProcessAlertBell />, { me: makeMe(ALERT_PERMISSION) });

    expect(await screen.findByRole("button", { name: "Alarmes do processo, 2 por ler" })).toHaveTextContent("2");
    expect(api.getUnreadProcessNotificationCount).toHaveBeenCalledTimes(1);
  });

  it("não mostra o sino sem process_alert.use", () => {
    renderWithProviders(<ProcessAlertBell />, { me: makeMe({ permissions: [] }) });

    expect(screen.queryByRole("button", { name: /Alarmes do processo/ })).not.toBeInTheDocument();
    expect(api.getUnreadProcessNotificationCount).not.toHaveBeenCalled();
  });

  it("não mostra o sino quando a API responde 403 (instalador externo)", async () => {
    api.getUnreadProcessNotificationCount.mockRejectedValue(new ApiError(403, "Sem permissão para alarmes do processo."));
    renderWithProviders(<ProcessAlertBell />, { me: makeMe(ALERT_PERMISSION) });

    await waitFor(() => expect(api.getUnreadProcessNotificationCount).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /Alarmes do processo/ })).not.toBeInTheDocument()
    );
  });

  it("abre o painel com a lista, ligação ao projeto e marca uma notificação como lida", async () => {
    renderWithProviders(<ProcessAlertBell />, { me: makeMe(ALERT_PERMISSION) });

    fireEvent.click(await screen.findByRole("button", { name: /Alarmes do processo/ }));
    const panel = await screen.findByRole("region", { name: "Alarmes do processo" });
    expect(await within(panel).findByText("Etapa concluída: Montagem — Projeto Sintético")).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "Ver projeto" })).toHaveAttribute("href", "/projects/project-1");

    fireEvent.click(within(panel).getByRole("button", { name: "Marcar como lida" }));
    await waitFor(() => expect(api.markProcessNotificationRead).toHaveBeenCalledWith("notif-1"));
    await waitFor(() => expect(within(panel).queryByRole("button", { name: "Marcar como lida" })).not.toBeInTheDocument());
    expect(within(panel).getByText(/lida$/)).toBeInTheDocument();
  });

  it("marca todas como lidas e atualiza a contagem", async () => {
    api.getUnreadProcessNotificationCount
      .mockResolvedValueOnce({ unread: 2 })
      .mockResolvedValue({ unread: 0 });
    renderWithProviders(<ProcessAlertBell />, { me: makeMe(ALERT_PERMISSION) });

    fireEvent.click(await screen.findByRole("button", { name: "Alarmes do processo, 2 por ler" }));
    const panel = await screen.findByRole("region", { name: "Alarmes do processo" });
    fireEvent.click(within(panel).getByRole("button", { name: "Marcar todas como lidas" }));

    await waitFor(() => expect(api.markAllProcessNotificationsRead).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole("button", { name: "Alarmes do processo" })).toBeInTheDocument();
  });

  it("mostra o estado vazio quando não há notificações", async () => {
    api.getUnreadProcessNotificationCount.mockResolvedValue({ unread: 0 });
    api.listProcessNotifications.mockResolvedValue(page([]));
    renderWithProviders(<ProcessAlertBell />, { me: makeMe(ALERT_PERMISSION) });

    fireEvent.click(await screen.findByRole("button", { name: "Alarmes do processo" }));
    expect(await screen.findByText("Sem alarmes.")).toBeInTheDocument();
  });
});
