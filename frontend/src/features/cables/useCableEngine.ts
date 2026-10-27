import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../../api/client";
import { getCableTool } from "../../api/cableDesigns";
import type { CabosEngine } from "./engine";

export type CableEngineStatus = "idle" | "loading" | "ready" | "error";

export interface CableEngineState {
  engine: CabosEngine | null;
  status: CableEngineStatus;
  error: string | null;
  loading: boolean;
  ready: boolean;
}

type CableEngineWindow = Window & typeof globalThis & { CabosEngine?: CabosEngine };

let enginePromise: Promise<CabosEngine> | null = null;

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

async function executeEngineScript(script: string, expectedEngineVersion: string): Promise<CabosEngine> {
  if (typeof window === "undefined" || typeof document === "undefined") {
    throw new Error("A ferramenta de cálculo só pode ser carregada no browser.");
  }

  const hostWindow = window as CableEngineWindow;
  Reflect.deleteProperty(hostWindow, "CabosEngine");
  if (hostWindow.CabosEngine !== undefined) {
    try {
      hostWindow.CabosEngine = undefined;
    } catch {
      // The value is checked below; fail closed if a page-owned global cannot be cleared.
    }
  }
  if (hostWindow.CabosEngine !== undefined) {
    throw new Error("Não foi possível limpar o objeto global anterior da ferramenta de cálculo.");
  }

  const blobUrl = URL.createObjectURL(new Blob([script], { type: "text/javascript" }));
  const element = document.createElement("script");
  element.async = false;
  element.src = blobUrl;

  return new Promise<CabosEngine>((resolve, reject) => {
    let settled = false;
    const cleanup = () => {
      element.onload = null;
      element.onerror = null;
      element.remove();
      URL.revokeObjectURL(blobUrl);
    };
    const finish = (callback: () => void) => {
      if (settled) return;
      settled = true;
      cleanup();
      callback();
    };

    element.onload = () => {
      finish(() => {
        const loaded = hostWindow.CabosEngine;
        if (!loaded || typeof loaded !== "object") {
          reject(new Error("A ferramenta de cálculo não publicou window.CabosEngine."));
          return;
        }
        if (loaded.protocol !== 1) {
          reject(new Error("Versão de protocolo da ferramenta de cálculo não suportada."));
          return;
        }
        if (loaded.engine_version !== expectedEngineVersion) {
          reject(new Error("A versão engine_version da ferramenta de cálculo não corresponde ao manifesto."));
          return;
        }
        resolve(loaded);
      });
    };
    element.onerror = () => finish(() => reject(new Error("Não foi possível executar a ferramenta de cálculo.")));

    try {
      document.head.appendChild(element);
    } catch (reason) {
      finish(() => reject(reason instanceof Error ? reason : new Error("Não foi possível executar a ferramenta de cálculo.")));
    }
  });
}

/** Loads the engine once per browser session and keeps the global surface untouched. */
export function getCableEngine(): Promise<CabosEngine> {
  if (enginePromise) return enginePromise;

  const pending = (async () => {
    const manifest = await getCableTool();
    const actualHash = await sha256Script(manifest.script);
    if (actualHash.toLowerCase() !== manifest.sha256.trim().toLowerCase()) {
      throw new Error("A verificação SHA-256 da ferramenta de cálculo falhou.");
    }
    const loaded = await executeEngineScript(manifest.script, manifest.engine_version);
    if (loaded.protocol !== 1) {
      throw new Error("Versão de protocolo da ferramenta de cálculo não suportada.");
    }
    return loaded;
  })();

  enginePromise = pending;
  void pending.catch(() => {
    if (enginePromise === pending) enginePromise = null;
  });
  return pending;
}

export const loadCableEngine = getCableEngine;

/** Test/support reset; no production code calls this. */
export function resetCableEngineCache(): void {
  enginePromise = null;
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
