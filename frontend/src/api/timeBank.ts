import { apiGet, apiPost, apiUpload } from "./client";

export type TimeBankCalculationMode = "standard" | "saturday" | "manual" | "imported";
export type TimeBankAdjustmentKind = "correction" | "consumption" | "opening";
// The backend deliberately exposes JSON objects for flags/provenance. Keep
// them as data, not as an open-ended DTO escape hatch on every response type.
export type TimeBankJsonObject = Record<string, unknown>;

export interface TimeBankPerson {
  id: string;
  display_name: string;
  is_active: boolean;
}

export interface TimeBankWarning {
  code: string;
  message: string;
}

export interface TimeBankSummaryPerson {
  person_id: string;
  display_name: string;
  opening_seconds: number;
  credited_seconds: number;
  debited_seconds: number;
  balance_seconds: number;
  period_seconds: number;
  needs_review_count: number;
  warnings: TimeBankWarning[];
}

export interface TimeBankSummary {
  people: TimeBankSummaryPerson[];
}

export type TimeBankProvenance = TimeBankJsonObject;

export interface TimeBankEntryRead {
  id: string;
  person_id: string;
  work_date: string;
  start_minute: number | null;
  end_minute: number | null;
  lunch_taken: boolean | null;
  calculation_mode: string;
  balance_seconds: number;
  calculated_seconds: number | null;
  needs_review: boolean;
  review_flags: TimeBankJsonObject;
  reason: string | null;
  provenance: TimeBankProvenance;
  source_key: string | null;
  created_by_user_id: string;
  occurred_at: string;
  reversal_of_id: string | null;
}

export interface TimeBankAdjustmentRead {
  id: string;
  person_id: string;
  effective_date: string;
  delta_seconds: number;
  kind: string;
  reason: string;
  provenance: TimeBankProvenance;
  source_key: string | null;
  created_by_user_id: string;
  occurred_at: string;
  reversal_of_id: string | null;
}

export interface TimeBankPage<T> {
  items: T[];
  total: number;
}

export interface TimeBankEntryCreateInput {
  person_id: string;
  work_date: string;
  start_minute: number | null;
  end_minute: number | null;
  lunch_taken: boolean | null;
  calculation_mode: Exclude<TimeBankCalculationMode, "imported">;
  manual_balance_seconds?: number | null;
  reason?: string | null;
}

export interface TimeBankAdjustmentCreateInput {
  person_id: string;
  effective_date: string;
  delta_seconds: number;
  kind: Exclude<TimeBankAdjustmentKind, "opening">;
  reason: string;
}

export interface TimeBankImportCandidate {
  id: string;
  display_name: string;
}

export interface TimeBankImportPerson {
  source_label: string;
  person_id: string | null;
  candidates: TimeBankImportCandidate[];
}

export interface TimeBankImportIssue {
  code: string;
  message: string;
  blocking: boolean;
  sheet: string | null;
  row: number | null;
}

export interface TimeBankImportRead {
  id: string;
  status: "pending" | "applied";
  sha256: string;
  source_year: number | null;
  counts: {
    entries: number;
    openings: number;
    needs_review: number;
    source_rows?: number;
    quarantined?: number;
  };
  people: TimeBankImportPerson[];
  issues: TimeBankImportIssue[];
  applied_counts: { entries: number; openings: number } | null;
}

export interface TimeBankFilters {
  personId?: string | null;
  fromDate?: string;
  toDate?: string;
  limit?: number;
  offset?: number;
}

function queryString(values: Record<string, string | number | null | undefined>): string {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  });
  const result = params.toString();
  return result ? `?${result}` : "";
}

export const listTimeBankPeople = () => apiGet<TimeBankPerson[]>("/api/time-bank/people");

export const getTimeBankSummary = ({
  personId,
  year,
  month,
}: {
  personId?: string | null;
  year: number;
  month?: number | null;
}) =>
  apiGet<TimeBankSummary>(
    `/api/time-bank/summary${queryString({ person_id: personId, year, month })}`
  );

export const listTimeBankEntries = (filters: TimeBankFilters = {}) =>
  apiGet<TimeBankPage<TimeBankEntryRead>>(
    `/api/time-bank/entries${queryString({
      person_id: filters.personId,
      from_date: filters.fromDate,
      to_date: filters.toDate,
      limit: filters.limit ?? 100,
      offset: filters.offset ?? 0,
    })}`
  );

export const listTimeBankAdjustments = (filters: TimeBankFilters = {}) =>
  apiGet<TimeBankPage<TimeBankAdjustmentRead>>(
    `/api/time-bank/adjustments${queryString({
      person_id: filters.personId,
      from_date: filters.fromDate,
      to_date: filters.toDate,
      limit: filters.limit ?? 100,
      offset: filters.offset ?? 0,
    })}`
  );

export const createTimeBankEntry = (payload: TimeBankEntryCreateInput) =>
  apiPost<TimeBankEntryRead>("/api/time-bank/entries", payload);

export const reverseTimeBankEntry = (id: string, payload: { reason: string }) =>
  apiPost<TimeBankEntryRead>(`/api/time-bank/entries/${encodeURIComponent(id)}/reverse`, payload);

export const createTimeBankAdjustment = (payload: TimeBankAdjustmentCreateInput) =>
  apiPost<TimeBankAdjustmentRead>("/api/time-bank/adjustments", payload);

export const reverseTimeBankAdjustment = (id: string, payload: { reason: string }) =>
  apiPost<TimeBankAdjustmentRead>(`/api/time-bank/adjustments/${encodeURIComponent(id)}/reverse`, payload);

export const previewTimeBankImport = (file: File) => {
  const form = new FormData();
  form.append("file", file);
  return apiUpload<TimeBankImportRead>("/api/time-bank/imports/preview", form);
};

export const getTimeBankImport = (id: string) =>
  apiGet<TimeBankImportRead>(`/api/time-bank/imports/${encodeURIComponent(id)}`);

export const resolveTimeBankImport = (id: string, payload: { person_mapping: Record<string, string> }) =>
  apiPost<TimeBankImportRead>(`/api/time-bank/imports/${encodeURIComponent(id)}/resolve`, payload);

export const applyTimeBankImport = (id: string) =>
  apiPost<TimeBankImportRead>(`/api/time-bank/imports/${encodeURIComponent(id)}/apply`, {});

export function parseClockMinute(value: string): number | null {
  const match = /^(\d{1,2}):(\d{2})$/.exec(value.trim());
  if (!match) return null;
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  if (!Number.isInteger(hour) || !Number.isInteger(minute) || minute > 59 || hour > 24) return null;
  if (hour === 24 && minute !== 0) return null;
  return hour * 60 + minute;
}

export function formatClockMinute(value: number | null): string {
  if (value === null || !Number.isInteger(value) || value < 0 || value > 1440) return "—";
  return `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;
}

/** Parse a signed duration without converting it through floating-point hours. */
export function parseSignedTimeBankDuration(value: string): number | null {
  const match = /^([+-])?(\d{1,3}):(\d{2})(?::(\d{2}))?$/.exec(value.trim());
  if (!match) return null;
  const hours = Number(match[2]);
  const minutes = Number(match[3]);
  const seconds = match[4] === undefined ? 0 : Number(match[4]);
  if (minutes > 59 || seconds > 59) return null;
  const total = hours * 3600 + minutes * 60 + seconds;
  return match[1] === "-" ? -total : total;
}

export function formatSignedTimeBankDuration(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isInteger(value)) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  const absolute = Math.abs(value);
  const hours = Math.floor(absolute / 3600);
  const minutes = Math.floor((absolute % 3600) / 60);
  const seconds = absolute % 60;
  const suffix = seconds ? `:${String(seconds).padStart(2, "0")}` : "";
  return `${sign}${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}${suffix}`;
}

export function timeBankDateRange(year: number, month?: number | null): { fromDate: string; toDate: string } {
  const validMonth = month && month >= 1 && month <= 12 ? month : null;
  const fromDate = `${String(year).padStart(4, "0")}-${validMonth ? String(validMonth).padStart(2, "0") : "01"}-01`;
  const endMonth = validMonth ?? 12;
  const lastDay = new Date(Date.UTC(year, endMonth, 0)).getUTCDate();
  return { fromDate, toDate: `${String(year).padStart(4, "0")}-${String(endMonth).padStart(2, "0")}-${String(lastDay).padStart(2, "0")}` };
}

export function inferTimeBankMode(workDate: string): Exclude<TimeBankCalculationMode, "imported"> {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(workDate);
  if (!match) return "manual";
  const weekday = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]))).getUTCDay();
  if (weekday === 6) return "saturday";
  if (weekday === 0) return "manual";
  return "standard";
}

export function hasBlockingTimeBankImportIssues(batch: TimeBankImportRead, mapping: Record<string, string> = {}): boolean {
  if (batch.issues.some((issue) => issue.blocking)) return true;
  return batch.people.some((person) => !person.person_id && !mapping[person.source_label]);
}
