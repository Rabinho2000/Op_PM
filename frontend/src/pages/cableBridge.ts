import type { CableJsonObject } from "../api/cableDesigns";

export const CABLE_BRIDGE_SOURCE = "op-pm-cable" as const;
export const CABLE_BRIDGE_PROTOCOL = 1 as const;
export const CABLE_SHELL_TO_TOOL_TYPES = ["cable:init", "cable:snapshot-request", "cable:snapshot-saved"] as const;
export const CABLE_TOOL_TO_SHELL_TYPES = ["cable:ready", "cable:dirty", "cable:snapshot", "cable:error"] as const;

export interface CableMeta {
  projectName: string;
  clientName: string;
  address: string;
  studyTitle: string;
  rev: string;
  status: string;
}

export interface CableInitMessage {
  source: typeof CABLE_BRIDGE_SOURCE;
  protocol: typeof CABLE_BRIDGE_PROTOCOL;
  type: "cable:init";
  state: CableJsonObject | null;
  readOnly: boolean;
  meta: CableMeta;
}

export interface CableSnapshotRequestMessage {
  source: typeof CABLE_BRIDGE_SOURCE;
  protocol: typeof CABLE_BRIDGE_PROTOCOL;
  type: "cable:snapshot-request";
  requestId: string;
}

export interface CableSnapshotSavedMessage {
  source: typeof CABLE_BRIDGE_SOURCE;
  protocol: typeof CABLE_BRIDGE_PROTOCOL;
  type: "cable:snapshot-saved";
  requestId: string;
}

export interface CableReadyMessage {
  source: typeof CABLE_BRIDGE_SOURCE;
  protocol: typeof CABLE_BRIDGE_PROTOCOL;
  type: "cable:ready";
}

export interface CableDirtyMessage {
  source: typeof CABLE_BRIDGE_SOURCE;
  protocol: typeof CABLE_BRIDGE_PROTOCOL;
  type: "cable:dirty";
  dirty: boolean;
}

export interface CableSnapshotMessage {
  source: typeof CABLE_BRIDGE_SOURCE;
  protocol: typeof CABLE_BRIDGE_PROTOCOL;
  type: "cable:snapshot";
  requestId: string;
  input: CableJsonObject;
  result: CableJsonObject;
  engine_version: string;
}

export interface CableErrorMessage {
  source: typeof CABLE_BRIDGE_SOURCE;
  protocol: typeof CABLE_BRIDGE_PROTOCOL;
  type: "cable:error";
  message: string;
}

export type CableToolMessage = CableReadyMessage | CableDirtyMessage | CableSnapshotMessage | CableErrorMessage;
export type CableShellMessage = CableInitMessage | CableSnapshotRequestMessage | CableSnapshotSavedMessage;
export type CableMessageListener = (event: MessageEvent, message: CableToolMessage) => void | boolean;

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

export function buildCableInitMessage({
  state,
  readOnly,
  meta,
}: {
  state: CableJsonObject | null;
  readOnly: boolean;
  meta: CableMeta;
}): CableInitMessage {
  return {
    source: CABLE_BRIDGE_SOURCE,
    protocol: CABLE_BRIDGE_PROTOCOL,
    type: "cable:init",
    state,
    readOnly,
    meta,
  };
}

export function buildCableSnapshotRequestMessage(requestId: string): CableSnapshotRequestMessage {
  return {
    source: CABLE_BRIDGE_SOURCE,
    protocol: CABLE_BRIDGE_PROTOCOL,
    type: "cable:snapshot-request",
    requestId,
  };
}

export function buildCableSnapshotSavedMessage(requestId: string): CableSnapshotSavedMessage {
  return {
    source: CABLE_BRIDGE_SOURCE,
    protocol: CABLE_BRIDGE_PROTOCOL,
    type: "cable:snapshot-saved",
    requestId,
  };
}

// Aliases keep the constructors discoverable for consumers that use create/make naming.
export const createCableInitMessage = buildCableInitMessage;
export const createCableSnapshotRequestMessage = buildCableSnapshotRequestMessage;
export const createCableSnapshotSavedMessage = buildCableSnapshotSavedMessage;
export const makeCableInitMessage = buildCableInitMessage;
export const makeCableSnapshotRequestMessage = buildCableSnapshotRequestMessage;
export const makeCableSnapshotSavedMessage = buildCableSnapshotSavedMessage;

export function validateCableToolMessage(value: unknown): CableToolMessage | null {
  if (!isObject(value)) return null;
  if (value.source !== CABLE_BRIDGE_SOURCE || value.protocol !== CABLE_BRIDGE_PROTOCOL) return null;

  switch (value.type) {
    case "cable:ready":
      return { source: CABLE_BRIDGE_SOURCE, protocol: CABLE_BRIDGE_PROTOCOL, type: "cable:ready" };
    case "cable:dirty":
      return typeof value.dirty === "boolean"
        ? { source: CABLE_BRIDGE_SOURCE, protocol: CABLE_BRIDGE_PROTOCOL, type: "cable:dirty", dirty: value.dirty }
        : null;
    case "cable:snapshot":
      return isNonEmptyString(value.requestId) &&
        isObject(value.input) &&
        isObject(value.result) &&
        isNonEmptyString(value.engine_version)
        ? {
            source: CABLE_BRIDGE_SOURCE,
            protocol: CABLE_BRIDGE_PROTOCOL,
            type: "cable:snapshot",
            requestId: value.requestId,
            input: value.input,
            result: value.result,
            engine_version: value.engine_version,
          }
        : null;
    case "cable:error":
      return typeof value.message === "string"
        ? { source: CABLE_BRIDGE_SOURCE, protocol: CABLE_BRIDGE_PROTOCOL, type: "cable:error", message: value.message }
        : null;
    default:
      return null;
  }
}

export const parseCableToolMessage = validateCableToolMessage;

function newRequestId(): string {
  const cryptoObject = typeof globalThis.crypto !== "undefined" ? globalThis.crypto : undefined;
  if (cryptoObject?.randomUUID) return cryptoObject.randomUUID();
  return `cable-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

/**
 * Ask the embedded tool for a snapshot and wait for the matching response.
 * The editor remains responsible for checking event.source against its iframe.
 */
export function requestSnapshot(
  iframeWindow: Window,
  listener?: CableMessageListener,
  timeoutMs = 5000,
): Promise<CableSnapshotMessage> {
  const requestId = newRequestId();
  const message = buildCableSnapshotRequestMessage(requestId);
  const ownerWindow = typeof window !== "undefined" ? window : null;

  return new Promise<CableSnapshotMessage>((resolve, reject) => {
    let finished = false;
    let timeout: number | undefined;

    const cleanup = () => {
      if (ownerWindow) ownerWindow.removeEventListener("message", onMessage);
      if (timeout !== undefined) window.clearTimeout(timeout);
    };
    const finish = (callback: () => void) => {
      if (finished) return;
      finished = true;
      cleanup();
      callback();
    };
    const onMessage = (event: MessageEvent) => {
      // jsdom does not populate source; a real cross-window source is still checked.
      if (event.source !== null && event.source !== iframeWindow) return;
      const parsed = validateCableToolMessage(event.data);
      if (!parsed) return;
      const listenerResult = listener?.(event, parsed);
      if (parsed.type !== "cable:snapshot" || parsed.requestId !== requestId || listenerResult === false) return;
      finish(() => resolve(parsed));
    };

    if (!ownerWindow) {
      reject(new Error("Não foi possível comunicar com a ferramenta de cabos."));
      return;
    }

    ownerWindow.addEventListener("message", onMessage);
    timeout = window.setTimeout(() => {
      finish(() => reject(new Error("A ferramenta de cabos não respondeu ao pedido de snapshot a tempo.")));
    }, Math.max(0, timeoutMs));

    try {
      iframeWindow.postMessage(message, "*");
    } catch {
      finish(() => reject(new Error("Não foi possível pedir um snapshot à ferramenta de cabos.")));
    }
  });
}
