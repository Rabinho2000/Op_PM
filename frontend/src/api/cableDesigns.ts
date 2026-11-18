import { apiDelete, apiGet, apiPost, apiPut } from "./client";

/** JSON object fields are deliberately kept as objects, never serialized text. */
export type CableJsonObject = Record<string, unknown>;

export interface CableDesignRevision {
  id: string;
  design_id: string;
  rev: string;
  input_json: CableJsonObject;
  result_json: CableJsonObject;
  engine_version: string;
  content_sha256: string;
  unresolved_circuits: number;
  status: string;
  approved_by_person_id: string | null;
  approved_at: string | null;
  created_by_person_id: string;
  created_at: string;
  updated_at: string;
}

export interface CableDesignListItem {
  id: string;
  project_id: string;
  title: string;
  status: string;
  current_revision: string;
  version: number;
  updated_at: string;
  unresolved_circuits: number;
}

export interface CableDesign extends CableDesignListItem {
  is_active: boolean;
  created_by_person_id: string;
  created_at: string;
  revision: CableDesignRevision;
}

export interface CableDesignHistoryEntry {
  id: string;
  design_id: string;
  action: string;
  actor_person_id: string;
  rev: string;
  old_value: CableJsonObject | null;
  new_value: CableJsonObject | null;
  created_at: string;
}

export interface CableTool {
  engine_version: string;
  sha256: string;
  script: string;
}

export interface CableDesignCreateInput {
  title: string;
  input_json?: CableJsonObject;
  engine_version: string;
}

export interface CableDesignRevisionUpdateInput {
  expected_version: number;
  title?: string;
  input: CableJsonObject;
  result: CableJsonObject;
  engine_version: string;
}

export interface CableDesignExpectedVersionInput {
  expected_version: number;
}

// Names mirroring the backend DTOs are exported as aliases for API consumers.
export type CableDesignListRead = CableDesignListItem;
export type CableDesignRead = CableDesign;
export type CableDesignRevisionRead = CableDesignRevision;
export type CableDesignRevisionListRead = CableDesignRevision;
export type CableDesignHistoryRead = CableDesignHistoryEntry;
export type CableToolRead = CableTool;

function idPath(id: string): string {
  return encodeURIComponent(id);
}

export const listCableDesigns = (projectId: string) =>
  apiGet<CableDesignListItem[]>(`/api/projects/${idPath(projectId)}/cable-designs`);

export const createCableDesign = (projectId: string, payload: CableDesignCreateInput) =>
  apiPost<CableDesign>(`/api/projects/${idPath(projectId)}/cable-designs`, payload);

export const getCableDesign = (id: string) => apiGet<CableDesign>(`/api/cable-designs/${idPath(id)}`);

export const saveCableRevision = (id: string, payload: CableDesignRevisionUpdateInput) =>
  apiPut<CableDesign>(`/api/cable-designs/${idPath(id)}/revisions/current`, payload);

export const approveCableDesign = (id: string, expectedVersion: number) =>
  apiPost<CableDesign>(`/api/cable-designs/${idPath(id)}/approve`, { expected_version: expectedVersion });

export const newCableRevision = (id: string, expectedVersion: number) =>
  apiPost<CableDesign>(`/api/cable-designs/${idPath(id)}/new-revision`, { expected_version: expectedVersion });

export const deactivateCableDesign = (id: string, expectedVersion: number) =>
  apiDelete<void>(`/api/cable-designs/${idPath(id)}?expected_version=${encodeURIComponent(String(expectedVersion))}`);

export const listCableRevisions = (id: string) =>
  apiGet<CableDesignRevision[]>(`/api/cable-designs/${idPath(id)}/revisions`);

export const listCableHistory = (id: string) =>
  apiGet<CableDesignHistoryEntry[]>(`/api/cable-designs/${idPath(id)}/history`);

export const getCableTool = () => apiGet<CableTool>("/api/cable-tool");
