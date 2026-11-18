import { useCallback, useEffect, useRef, useState } from "react";
import type { CableDesign, CableJsonObject } from "../../api/cableDesigns";
import type { Project } from "../../api/client";
import type { CabosEngine, JsonObject, JsonValue, Result, State } from "./engine";

export interface CableStudyStore {
  state: State;
  result: Result;
  savedHash: string;
  dirty: boolean;
}

export type CableStudyUpdater = (state: State) => State;

export type CableStudyAction =
  | { type: "replace"; state: State; result: Result; hash?: string; dirty?: boolean }
  | { type: "markSaved"; state: State; hash: string }
  | { type: "setDirty"; dirty: boolean };

export function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  const object = value as Record<string, unknown>;
  const entries = Object.keys(object)
    .filter((key) => object[key] !== undefined)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${canonicalJson(object[key])}`);
  return `{${entries.join(",")}}`;
}

export async function hashCanonical(value: unknown): Promise<string> {
  const serialized = canonicalJson(value);
  if (typeof crypto !== "undefined" && crypto.subtle && typeof TextEncoder !== "undefined") {
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(serialized));
    return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
  }
  // This only serves non-browser test environments without Web Crypto. The
  // browser path above is the persisted content identity.
  let hash = 2166136261;
  for (let index = 0; index < serialized.length; index += 1) {
    hash ^= serialized.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `fallback-${(hash >>> 0).toString(16).padStart(8, "0")}`;
}

export function studyReducer(store: CableStudyStore, action: CableStudyAction): CableStudyStore {
  switch (action.type) {
    case "replace":
      return {
        state: action.state,
        result: action.result,
        savedHash: action.hash ?? store.savedHash,
        dirty: action.dirty ?? store.dirty,
      };
    case "markSaved":
      return { ...store, state: action.state, savedHash: action.hash, dirty: false };
    case "setDirty":
      return { ...store, dirty: action.dirty };
    default:
      return store;
  }
}

function objectRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function isJsonValue(value: unknown): value is JsonValue {
  if (value === null || typeof value === "string" || typeof value === "number" || typeof value === "boolean") return true;
  if (Array.isArray(value)) return value.every(isJsonValue);
  if (typeof value !== "object") return false;
  return Object.values(value as Record<string, unknown>).every(isJsonValue);
}

function initialState(engine: CabosEngine, design: CableDesign, project: Project | null): State {
  const rawState = objectRecord(design.revision.input_json)?.state;
  if (rawState !== undefined) {
    if (!isJsonValue(rawState)) throw new Error("O estado guardado contém valores JSON inválidos.");
    return engine.migrate(rawState);
  }

  const next = engine.newState();
  const obra = { ...(next.obra ?? ({} as State["obra"])) };
  return {
    ...next,
    proj: project?.name ?? next.proj,
    obra: {
      ...obra,
      cliente: project?.client_name ?? obra.cliente ?? "",
      morada: project?.address ?? obra.morada ?? "",
    },
  };
}

function isApprovedStatus(status: string): boolean {
  return status === "aprovado" || status === "aprovada";
}

function isApprovedDesign(design: CableDesign): boolean {
  return isApprovedStatus(design.status) || isApprovedStatus(design.revision.status);
}

export async function initializeCableStudy(
  engine: CabosEngine,
  design: CableDesign,
  project: Project | null,
): Promise<CableStudyStore | null> {
  if (isApprovedDesign(design)) return null;
  const solved = engine.solve(initialState(engine, design, project));
  const savedHash = await hashCanonical(solved.state);
  return { state: solved.state, result: solved.result, savedHash, dirty: false };
}

export interface CableSavePayload {
  input: CableJsonObject;
  result: CableJsonObject;
  engine_version: string;
}

export function buildCableSavePayload(engine: CabosEngine, store: CableStudyStore): CableSavePayload {
  return {
    input: { format: 1, state: store.state } as unknown as CableJsonObject,
    result: engine.persistedResult(store.state, store.result) as unknown as CableJsonObject,
    engine_version: engine.engine_version,
  };
}

export function buildCablePresentationState(
  engine: CabosEngine,
  state: State,
  design: CableDesign,
  peopleById: ReadonlyMap<string, string>,
): State {
  const approvedByPersonId = design.revision.approved_by_person_id;
  const approvedAt = design.revision.approved_at;
  const approvedName = approvedByPersonId ? peopleById.get(approvedByPersonId)?.trim() : undefined;
  const approval = approvedByPersonId && approvedAt && approvedName
    ? { id: approvedByPersonId, nome: approvedName, em: approvedAt }
    : null;
  const workData: JsonObject = { rev: design.current_revision, aprov: approval };
  // `state` comes from solve() in useCableStudy; setWorkData copies that
  // normalized state without feeding metadata synchronization back into dirty.
  return engine.actions.setWorkData(state, workData);
}

export interface UseCableStudyResult {
  store: CableStudyStore | null;
  state: State | null;
  result: Result | null;
  savedHash: string;
  dirty: boolean;
  loading: boolean;
  error: string | null;
  apply: (updater: CableStudyUpdater, options?: { debounce?: boolean }) => void;
  flush: () => CableStudyStore | null;
  markSaved: (state?: State) => Promise<void>;
  savePayload: CableSavePayload | null;
}

export function useCableStudy(
  engine: CabosEngine | null,
  design: CableDesign | null,
  project: Project | null,
): UseCableStudyResult {
  const [store, setStore] = useState<CableStudyStore | null>(null);
  const [loading, setLoading] = useState(Boolean(engine && design));
  const [error, setError] = useState<string | null>(null);
  const storeRef = useRef<CableStudyStore | null>(null);
  const savedHashRef = useRef("");
  const pendingUpdaterRef = useRef<CableStudyUpdater | null>(null);
  const debounceRef = useRef<number | null>(null);
  const revisionKey = design ? `${design.id}:${design.version}:${design.revision.id}` : "none";

  useEffect(() => {
    let active = true;
    if (!engine || !design) {
      storeRef.current = null;
      savedHashRef.current = "";
      setStore(null);
      setLoading(false);
      setError(null);
      return () => {
        active = false;
      };
    }

    setLoading(true);
    setError(null);
    void initializeCableStudy(engine, design, project)
      .then((initial) => {
        if (!active) return;
        storeRef.current = initial;
        savedHashRef.current = initial?.savedHash ?? "";
        pendingUpdaterRef.current = null;
        setStore(initial);
        setLoading(false);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        storeRef.current = null;
        setStore(null);
        setError(reason instanceof Error ? reason.message : "Não foi possível preparar o estudo de cabos.");
        setLoading(false);
      });

    return () => {
      active = false;
      if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
      debounceRef.current = null;
      pendingUpdaterRef.current = null;
    };
  }, [engine, project, revisionKey]);

  const commit = useCallback((updater: CableStudyUpdater): CableStudyStore | null => {
    if (!engine || !storeRef.current) return null;
    const current = storeRef.current;
    const solved = engine.solve(updater(current.state));
    const next: CableStudyStore = { ...current, state: solved.state, result: solved.result, dirty: true };
    storeRef.current = next;
    setStore(next);
    const currentHash = savedHashRef.current;
    void hashCanonical(solved.state).then((hash) => {
      if (storeRef.current !== next) return;
      if (hash === currentHash) {
        const clean = { ...next, savedHash: hash, dirty: false };
        storeRef.current = clean;
        setStore(clean);
      }
    });
    return next;
  }, [engine]);

  const flush = useCallback((): CableStudyStore | null => {
    if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
    debounceRef.current = null;
    const updater = pendingUpdaterRef.current;
    pendingUpdaterRef.current = null;
    return updater ? commit(updater) : storeRef.current;
  }, [commit]);

  const apply = useCallback((updater: CableStudyUpdater, options: { debounce?: boolean } = {}) => {
    if (!options.debounce) {
      flush();
      commit(updater);
      return;
    }
    if (storeRef.current) {
      storeRef.current = { ...storeRef.current, dirty: true };
      setStore(storeRef.current);
    }
    const previous = pendingUpdaterRef.current;
    pendingUpdaterRef.current = previous
      ? (state) => updater(previous(state))
      : updater;
    if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      debounceRef.current = null;
      const pending = pendingUpdaterRef.current;
      pendingUpdaterRef.current = null;
      if (pending) commit(pending);
    }, 180);
  }, [commit, flush]);

  const markSaved = useCallback(async (savedState = storeRef.current?.state) => {
    if (!savedState || !storeRef.current) return;
    const hash = await hashCanonical(savedState);
    savedHashRef.current = hash;
    const current = storeRef.current;
    const sameState = canonicalJson(current.state) === canonicalJson(savedState);
    const next = { ...current, savedHash: hash, dirty: !sameState || pendingUpdaterRef.current !== null };
    storeRef.current = next;
    setStore(next);
  }, []);

  const savePayload = engine && store ? buildCableSavePayload(engine, store) : null;
  return {
    store,
    state: store?.state ?? null,
    result: store?.result ?? null,
    savedHash: store?.savedHash ?? "",
    dirty: store?.dirty ?? false,
    loading,
    error,
    apply,
    flush,
    markSaved,
    savePayload,
  };
}
