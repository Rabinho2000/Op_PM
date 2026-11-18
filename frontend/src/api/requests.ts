import { apiGet, apiPost } from "./client";

export type RequestStatus = "open" | "resolved";
export type RequestListStatus = RequestStatus | "all";
export type RequestScope = "mine" | "all";

export interface RequestListItem {
  id: string;
  status: RequestStatus;
  page_path: string | null;
  created_at: string;
  updated_at: string;
  author_name: string;
  message_count: number;
  last_message_preview: string;
  last_message_is_staff: boolean;
}

export interface RequestListPage {
  items: RequestListItem[];
  total: number;
}

export interface RequestMessage {
  id: string;
  author_name: string;
  is_staff_reply: boolean;
  is_mine: boolean;
  body: string;
  created_at: string;
}

export interface RequestThread {
  id: string;
  status: RequestStatus;
  page_path: string | null;
  created_at: string;
  updated_at: string;
  author_name: string;
  messages: RequestMessage[];
}

export interface RequestSummary {
  open: number;
}

export interface RequestListFilters {
  scope?: RequestScope;
  status?: RequestListStatus;
  limit?: number;
  offset?: number;
}

export interface CreateRequestInput {
  body: string;
  page_path?: string | null;
}

function queryString(filters: RequestListFilters): string {
  const params = new URLSearchParams();
  if (filters.scope) params.set("scope", filters.scope);
  if (filters.status) params.set("status", filters.status);
  if (filters.limit !== undefined) params.set("limit", String(filters.limit));
  if (filters.offset !== undefined) params.set("offset", String(filters.offset));
  const query = params.toString();
  return query ? `?${query}` : "";
}

export const listRequests = (filters: RequestListFilters = {}) =>
  apiGet<RequestListPage>(`/api/requests${queryString(filters)}`);

export const getRequestsSummary = () => apiGet<RequestSummary>("/api/requests/summary");

export const createRequest = (payload: CreateRequestInput) =>
  apiPost<RequestThread>("/api/requests", payload);

export const getRequest = (id: string) =>
  apiGet<RequestThread>(`/api/requests/${encodeURIComponent(id)}`);

export const postRequestMessage = (id: string, body: string) =>
  apiPost<RequestMessage>(`/api/requests/${encodeURIComponent(id)}/messages`, { body });

export const setRequestStatus = (id: string, status: RequestStatus) =>
  apiPost<RequestThread>(`/api/requests/${encodeURIComponent(id)}/status`, { status });
