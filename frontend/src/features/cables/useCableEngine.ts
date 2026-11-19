import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../../api/client";
import { getCableTool } from "../../api/cableDesigns";
import type { CabosEngine } from "./engine";
import { startCableEngineWorker, type CableEngineHandle, type WorkerFactory } from "./engineWorker/client";

export type CableEngineStatus = "idle" | "loading" | "ready" | "error";

export interface CableEngineState {
  engine: CabosEngine | null;
  status: CableEngineStatus;
  error: string | null;
  loading: boolean;
  ready: boolean;
}

let enginePromise: Promise<CabosEngine> | null = null;
let engineHandle: CableEngineHandle | null = null;
let workerFactoryOverride: WorkerFactory | undefined;

function engineError(reason: unknown): Error {
  if (reason instanceof ApiError) {
    if (reason.status === 503) return new Error("Ferramenta de cálculo indisponível");
    if (reason.status === 403) return new Error("Sem acesso à ferramenta de cálculo");
    return new Error(reason.detail || "Não foi possível carregar a ferramenta de cálculo.");
  }
  if (reason instanceof Error) return reason;
  return new Error("Não foi possível carregar a ferramenta de cálculo.");
}

function bytesToHex(bytes: ArrayBuffer): string {
  return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function sha256Script(script: string): Promise<string> {
  if (typeof crypto === "undefined" || !crypto.subtle || typeof TextEncoder === "undefined") {
    throw new Error("O browser não suporta a verificação de integridade da ferramenta de cálculo.");
  }
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(script));
  return bytesToHex(digest);
}

/**
 * Carrega o motor uma vez por sessão do browser, dentro de um iframe `sandbox`
 * sem allow-same-origin (M2): o script nunca corre na página, por isso não vê
 * o DOM nem os tokens MSAL, e tem DOM próprio para as exportações. A UI recebe a fachada assíncrona `CabosEngine`.
 */
export function getCableEngine(): Promise<CabosEngine> {
  if (enginePromise) return enginePromise;

  const pending = (async () => {
    if (typeof document === "undefined" && !workerFactoryOverride) {
      throw new Error("A ferramenta de cálculo só pode ser carregada no browser.");
    }
    const manifest = await getCableTool();
    const actualHash = await sha256Script(manifest.script);
    if (actualHash.toLowerCase() !== manifest.sha256.trim().toLowerCase()) {
      throw new Error("A verificação SHA-256 da ferramenta de cálculo falhou.");
    }
    const handle = await startCableEngineWorker({
      script: manifest.script,
      expectedEngineVersion: manifest.engine_version,
      workerFactory: workerFactoryOverride,
      onTerminated: () => {
        // Worker morto (erro, falta de memória): o próximo uso recria-o.
        if (engineHandle === handle) resetCableEngineCache();
      },
    });
    engineHandle = handle;
    return handle.engine;
  })();

  enginePromise = pending;
  void pending.catch(() => {
    if (enginePromise === pending) enginePromise = null;
  });
  return pending;
}

export const loadCableEngine = getCableEngine;

/** Termina o worker e esquece o motor carregado (testes e fim de sessão). */
export function resetCableEngineCache(): void {
  const handle = engineHandle;
  engineHandle = null;
  enginePromise = null;
  handle?.dispose();
}

/** Só para testes: fábrica de workers alternativa. */
export function setCableWorkerFactoryForTests(factory: WorkerFactory | undefined): void {
  workerFactoryOverride = factory;
}

export function useCableEngine(enabled = true): CableEngineState & { retry: () => void } {
  const [state, setState] = useState<CableEngineState>({
    engine: null,
    status: enabled ? "loading" : "idle",
    error: null,
    loading: enabled,
    ready: false,
  });
  const [retryNonce, setRetryNonce] = useState(0);

  useEffect(() => {
    let active = true;
    if (!enabled) {
      setState({ engine: null, status: "idle", error: null, loading: false, ready: false });
      return () => {
        active = false;
      };
    }

    setState((current) => ({ ...current, status: "loading", error: null, loading: true, ready: false }));
    getCableEngine()
      .then((engine) => {
        if (active) setState({ engine, status: "ready", error: null, loading: false, ready: true });
      })
      .catch((reason) => {
        if (active) {
          const error = engineError(reason);
          setState({ engine: null, status: "error", error: error.message, loading: false, ready: false });
        }
      });

    return () => {
      active = false;
    };
  }, [enabled, retryNonce]);

  const retry = useCallback(() => setRetryNonce((nonce) => nonce + 1), []);
  return { ...state, retry };
}
