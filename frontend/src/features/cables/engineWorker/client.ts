import type { CabosEngine, Catalogs } from "../engine";
import {
  ENGINE_GROUPS,
  buildCallMessage,
  buildInitMessage,
  parseWorkerMessage,
  type EngineGroup,
  type EngineReadyMessage,
} from "./protocol";

/**
 * Canal para o anfitrião do motor: a interface mínima de um Worker, para o
 * cliente não saber se do outro lado está um iframe isolado (produção) ou um
 * worker de teste.
 */
export interface WorkerLike {
  postMessage(message: unknown): void;
  terminate(): void;
  onmessage: ((event: MessageEvent) => void) | null;
  onerror: ((event: ErrorEvent) => void) | null;
  onmessageerror: ((event: MessageEvent) => void) | null;
}
export type WorkerFactory = () => WorkerLike;

/**
 * Página estática (frontend/public) que aloja o motor num iframe `sandbox`
 * sem allow-same-origin. Fica numa URL própria para o nginx lhe dar a sua CSP
 * (sem rede; `unsafe-eval` só ali). O motor real precisa de `Image`, `canvas` e
 * `DOMParser` para exportar PDF/DOCX/PNG/DXF, o que um Web Worker não tem.
 */
export const CABLE_FRAME_URL = "/cable-engine-frame.html";

/**
 * Cria o iframe isolado e devolve-o como canal. Só se aceitam mensagens cujo
 * `source` é a janela deste iframe (a origem dele é opaca, "null"); as
 * mensagens para o iframe esperam pelo `load` e vão com targetOrigin "*", a
 * única possível para uma origem opaca (o iframe nunca navega: sem
 * allow-top-navigation/allow-popups/allow-forms).
 */
export function sandboxedFrameFactory(): WorkerLike {
  const frame = document.createElement("iframe");
  frame.setAttribute("sandbox", "allow-scripts");
  frame.setAttribute("referrerpolicy", "no-referrer");
  frame.title = "Motor de cálculo de cabos";
  frame.hidden = true;
  frame.tabIndex = -1;
  frame.setAttribute("aria-hidden", "true");

  const queue: unknown[] = [];
  let loaded = false;
  let closed = false;

  const channel: WorkerLike = {
    onmessage: null,
    onerror: null,
    onmessageerror: null,
    postMessage(message) {
      if (closed) return;
      if (!loaded) queue.push(message);
      else frame.contentWindow?.postMessage(message, "*");
    },
    terminate() {
      if (closed) return;
      closed = true;
      window.removeEventListener("message", onWindowMessage);
      frame.remove();
    },
  };

  function onWindowMessage(event: MessageEvent) {
    if (closed || !frame.contentWindow || event.source !== frame.contentWindow) return;
    channel.onmessage?.(event);
  }
  window.addEventListener("message", onWindowMessage);

  frame.addEventListener("load", () => {
    loaded = true;
    for (const message of queue.splice(0)) frame.contentWindow?.postMessage(message, "*");
  });
  frame.addEventListener("error", () => {
    channel.onerror?.({ message: "O iframe do motor não carregou.", preventDefault: () => undefined } as ErrorEvent);
  });
  frame.src = CABLE_FRAME_URL;
  document.body.appendChild(frame);
  return channel;
}

export interface CableEngineWorkerOptions {
  script: string;
  /** `engine_version` do manifesto: o motor tem de publicar o mesmo. */
  expectedEngineVersion: string;
  workerFactory?: WorkerFactory;
  readyTimeoutMs?: number;
  /** Chamado uma vez se o anfitrião morrer depois de pronto (erro/terminação). */
  onTerminated?: (reason: Error) => void;
}

export interface CableEngineHandle {
  engine: CabosEngine;
  dispose(): void;
}

const READY_TIMEOUT_MS = 30_000;

type Pending = { resolve: (value: unknown) => void; reject: (reason: Error) => void };

function buildCatalogs(ready: EngineReadyMessage): Catalogs {
  const images = ready.installModeImages;
  const lookup = (id: string): readonly string[] | null =>
    Object.prototype.hasOwnProperty.call(images, id) ? images[id] : null;
  return { ...ready.catalogs, installModeImage: lookup } as Catalogs;
}

/**
 * Cria o worker, espera pelo `ready` e devolve a fachada assíncrona do motor.
 * Rejeita se o worker não arrancar, a versão não corresponder ao manifesto ou
 * o protocolo for outro.
 */
export function startCableEngineWorker(options: CableEngineWorkerOptions): Promise<CableEngineHandle> {
  const factory = options.workerFactory ?? sandboxedFrameFactory;
  const timeoutMs = options.readyTimeoutMs ?? READY_TIMEOUT_MS;

  return new Promise<CableEngineHandle>((resolve, reject) => {
    let worker: WorkerLike;
    try {
      worker = factory();
    } catch (reason) {
      reject(reason instanceof Error ? reason : new Error("Não foi possível executar a ferramenta de cálculo."));
      return;
    }

    const pending = new Map<number, Pending>();
    let nextId = 1;
    let ready = false;
    let dead = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const die = (reason: Error, notify: boolean) => {
      if (dead) return;
      dead = true;
      if (timer !== undefined) clearTimeout(timer);
      worker.onmessage = null;
      worker.onerror = null;
      worker.onmessageerror = null;
      try { worker.terminate(); } catch { /* já terminado */ }
      for (const call of pending.values()) call.reject(reason);
      pending.clear();
      if (!ready) reject(reason);
      else if (notify) options.onTerminated?.(reason);
    };

    const call = (path: string[], args: unknown[]): Promise<unknown> => {
      if (dead) return Promise.reject(new Error("A ferramenta de cálculo foi terminada."));
      const id = nextId;
      nextId += 1;
      return new Promise<unknown>((resolveCall, rejectCall) => {
        pending.set(id, { resolve: resolveCall, reject: rejectCall });
        try {
          worker.postMessage(buildCallMessage(id, path, args));
        } catch (reason) {
          pending.delete(id);
          rejectCall(reason instanceof Error ? reason : new Error("Não foi possível enviar o pedido ao motor de cálculo."));
        }
      });
    };

    const buildEngine = (message: EngineReadyMessage): CabosEngine => {
      const catalogs = buildCatalogs(message);
      const engine: Record<string, unknown> = {
        protocol: 1,
        engine_version: message.engine_version,
        templates: message.templates,
        catalogs,
        installModeImage: catalogs.installModeImage,
      };
      for (const name of message.surface.root) engine[name] = (...args: unknown[]) => call([name], args);
      for (const group of ENGINE_GROUPS) {
        const members: Record<string, unknown> = {};
        for (const name of message.surface[group as EngineGroup]) {
          members[name] = (...args: unknown[]) => call([group, name], args);
        }
        engine[group] = members;
      }
      return engine as unknown as CabosEngine;
    };

    worker.onmessage = (event) => {
      const message = parseWorkerMessage(event.data);
      if (!message) return; // não cumpre o protocolo: ignorada
      if (message.type === "ready") {
        if (ready || dead) return;
        if (message.engine_version !== options.expectedEngineVersion) {
          die(new Error("A versão engine_version da ferramenta de cálculo não corresponde ao manifesto."), false);
          return;
        }
        ready = true;
        if (timer !== undefined) clearTimeout(timer);
        resolve({ engine: buildEngine(message), dispose: () => die(new Error("A ferramenta de cálculo foi terminada."), false) });
        return;
      }
      if (message.type === "fatal") {
        die(new Error(message.message), true);
        return;
      }
      if (!ready) return;
      const entry = pending.get(message.id);
      if (!entry) return; // resposta sem pedido pendente: ignorada
      pending.delete(message.id);
      if (message.type === "result") entry.resolve(message.value);
      else entry.reject(new Error(message.message));
    };
    worker.onerror = (event) => {
      event.preventDefault?.();
      die(new Error("Não foi possível executar a ferramenta de cálculo."), true);
    };
    worker.onmessageerror = () => die(new Error("O worker da ferramenta de cálculo enviou uma mensagem ilegível."), true);

    timer = setTimeout(() => die(new Error("A ferramenta de cálculo não arrancou a tempo."), false), timeoutMs);
    try {
      worker.postMessage(buildInitMessage(options.script));
    } catch (reason) {
      die(reason instanceof Error ? reason : new Error("Não foi possível enviar a ferramenta de cálculo ao worker."), false);
    }
  });
}
