// Alarmes de etapas do processo (D-104): subscrições do próprio utilizador e
// notificações in-app. Tipos espelham exatamente os schemas Pydantic em
// backend/app/schemas/process_alerts.py e as rotas em
// backend/app/api/routes_process_alerts.py (prefixo /api/me).
import { apiGet, apiPost, apiPut } from "./client";

export interface AlertStage {
  id: string;
  code: string;
  title: string;
  subscribed: boolean;
}

export interface AlertPhase {
  id: string;
  code: string;
  name: string;
  stages: AlertStage[];
}

export interface AlertSubscriptions {
  phases: AlertPhase[];
}

export interface ProcessNotification {
  id: string;
  kind: string;
  message: string;
  project_id: string | null;
  project_name: string | null;
  stage_id: string | null;
  stage_title: string | null;
  is_read: boolean;
  created_at: string;
  read_at: string | null;
}

export interface ProcessNotificationPage {
  items: ProcessNotification[];
  total: number;
  limit: number;
  offset: number;
}

export interface ProcessNotificationFilters {
  unread_only?: boolean;
  limit?: number;
  offset?: number;
}

export interface UnreadCount {
  unread: number;
}

export interface MarkAllRead {
  marked: number;
}

export const getAlertSubscriptions = () =>
  apiGet<AlertSubscriptions>("/api/me/process-alerts/subscriptions");

// Substitui o conjunto completo de subscrições (idempotente no backend).
export const saveAlertSubscriptions = (stageIds: string[]) =>
  apiPut<AlertSubscriptions>("/api/me/process-alerts/subscriptions", { stage_ids: stageIds });

function notificationQuery(filters: ProcessNotificationFilters): string {
  const params = new URLSearchParams();
  if (filters.unread_only !== undefined) params.set("unread_only", String(filters.unread_only));
  if (filters.limit !== undefined) params.set("limit", String(filters.limit));
  if (filters.offset !== undefined) params.set("offset", String(filters.offset));
  const query = params.toString();
  return query ? `?${query}` : "";
}

export const listProcessNotifications = (filters: ProcessNotificationFilters = {}) =>
  apiGet<ProcessNotificationPage>(`/api/me/notifications${notificationQuery(filters)}`);

export const getUnreadProcessNotificationCount = () =>
  apiGet<UnreadCount>("/api/me/notifications/unread-count");

export const markProcessNotificationRead = (id: string) =>
  apiPost<ProcessNotification>(`/api/me/notifications/${encodeURIComponent(id)}/read`);

export const markAllProcessNotificationsRead = () =>
  apiPost<MarkAllRead>("/api/me/notifications/read-all");
