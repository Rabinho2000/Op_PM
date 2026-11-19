import type { Catalogs, Template } from "../engine";

/**
 * Protocolo de mensagens entre a página e o Web Worker que executa o motor de
 * cabos (versão 1). O motor é um script privado, sem acesso à página, ao DOM,
 * ao `sessionStorage` (tokens MSAL) nem à rede; só comunica por estas
 * mensagens, validadas dos dois lados (aqui, e em `public/cable-engine-worker.js`).
 */
export const ENGINE_MESSAGE_SOURCE = "op-pm-cable-engine" as const;
export const ENGINE_PROTOCOL = 1 as const;

export const ENGINE_ROOT_METHODS = ["newState", "migrate", "solve", "summarize", "persistedResult"] as const;
export const ENGINE_GROUPS = ["views", "actions", "exports", "compare"] as const;
export type EngineGroup = (typeof ENGINE_GROUPS)[number];

/** Nomes que o motor publica de facto, calculados pelo worker no arranque. */
export interface EngineSurface {
  root: string[];
  views: string[];
  actions: string[];
  exports: string[];
  compare: string[];
}

interface Envelope {
  source: typeof ENGINE_MESSAGE_SOURCE;
  protocol: typeof ENGINE_PROTOCOL;
}

/** página -> worker, uma só vez: o script do motor (SHA-256 já verificado). */
export interface EngineInitMessage extends Envelope {
  type: "init";
  script: string;
}

/** página -> worker */
export interface EngineCallMessage extends Envelope {
  type: "call";
  id: number;
  path: string[];
  args: unknown[];
}

export interface EngineReadyMessage extends Envelope {
  type: "ready";
  engine_version: string;
  templates: Template[];
  catalogs: Omit<Catalogs, "installModeImage">;
  installModeImages: Record<string, string[] | null>;
  surface: EngineSurface;
}
export interface EngineResultMessage extends Envelope {
  type: "result";
  id: number;
  value: unknown;
}
export interface EngineErrorMessage extends Envelope {
  type: "error";
  id: number;
  message: string;
}
export interface EngineFatalMessage extends Envelope {
  type: "fatal";
  message: string;
}
/** worker -> página */
export type EngineWorkerMessage = EngineReadyMessage | EngineResultMessage | EngineErrorMessage | EngineFatalMessage;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStringList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string" && item.length > 0 && item.length <= 120);
}

function isPendingId(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 1;
}

function parseSurface(value: unknown): EngineSurface | null {
  if (!isRecord(value)) return null;
  const { root, views, actions, exports, compare } = value;
  if (![root, views, actions, exports, compare].every(isStringList)) return null;
  return { root, views, actions, exports, compare } as EngineSurface;
}

export function buildInitMessage(script: string): EngineInitMessage {
  return { source: ENGINE_MESSAGE_SOURCE, protocol: ENGINE_PROTOCOL, type: "init", script };
}

export function buildCallMessage(id: number, path: string[], args: unknown[]): EngineCallMessage {
  return { source: ENGINE_MESSAGE_SOURCE, protocol: ENGINE_PROTOCOL, type: "call", id, path, args };
}

/**
 * Valida uma mensagem vinda do worker. Devolve `null` para tudo o que não
 * cumpre o protocolo (a página ignora-o): forma errada, `source`/`protocol`
 * diferentes, tipos inesperados.
 */
export function parseWorkerMessage(data: unknown): EngineWorkerMessage | null {
  if (!isRecord(data)) return null;
  if (data.source !== ENGINE_MESSAGE_SOURCE || data.protocol !== ENGINE_PROTOCOL) return null;
  const base: Envelope = { source: ENGINE_MESSAGE_SOURCE, protocol: ENGINE_PROTOCOL };
  switch (data.type) {
    case "ready": {
      const surface = parseSurface(data.surface);
      if (!surface) return null;
      if (typeof data.engine_version !== "string" || data.engine_version.length === 0 || data.engine_version.length > 64) return null;
      if (!Array.isArray(data.templates) || !isRecord(data.catalogs) || !isRecord(data.installModeImages)) return null;
      const images: Record<string, string[] | null> = {};
      for (const [key, value] of Object.entries(data.installModeImages)) {
        if (value === null) images[key] = null;
        else if (Array.isArray(value) && value.every((item) => typeof item === "string")) images[key] = value;
        else return null;
      }
      return {
        ...base,
        type: "ready",
        engine_version: data.engine_version,
        templates: data.templates as Template[],
        catalogs: data.catalogs as unknown as EngineReadyMessage["catalogs"],
        installModeImages: images,
        surface,
      };
    }
    case "result":
      return isPendingId(data.id) ? { ...base, type: "result", id: data.id, value: data.value } : null;
    case "error":
      return isPendingId(data.id) && typeof data.message === "string"
        ? { ...base, type: "error", id: data.id, message: data.message.slice(0, 300) }
        : null;
    case "fatal":
      return typeof data.message === "string" ? { ...base, type: "fatal", message: data.message.slice(0, 300) } : null;
    default:
      return null;
  }
}
