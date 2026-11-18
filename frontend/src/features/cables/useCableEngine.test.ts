import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import type { CabosEngine } from "./engine";

const api = vi.hoisted(() => ({ getCableTool: vi.fn() }));
vi.mock("../../api/cableDesigns", async () => {
  const actual = await vi.importActual<typeof import("../../api/cableDesigns")>("../../api/cableDesigns");
  return { ...actual, getCableTool: api.getCableTool };
});

import { getCableEngine, resetCableEngineCache, sha256Script, useCableEngine } from "./useCableEngine";

const fakeEngine = {
  protocol: 1,
  engine_version: "cabos-fake@1",
} as unknown as CabosEngine;

let appendSpy: ReturnType<typeof vi.spyOn>;
let scriptEngine: CabosEngine = fakeEngine;
let shouldPublishScript = true;

function exposeScriptEngine(engine: CabosEngine = fakeEngine) {
  const script = `globalThis.CabosEngine = ${JSON.stringify(engine)};`;
  return { script, engine };
}

async function manifest(script: string) {
  return { engine_version: "cabos-fake@1", sha256: await sha256Script(script), script };
}

beforeEach(() => {
  resetCableEngineCache();
  api.getCableTool.mockReset();
  Reflect.deleteProperty(window as unknown as Record<string, unknown>, "CabosEngine");
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:cabos-fake") });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
  scriptEngine = fakeEngine;
  shouldPublishScript = true;
  appendSpy = vi.spyOn(document.head, "appendChild").mockImplementation((node) => {
    const script = node as HTMLScriptElement;
    if (script.tagName === "SCRIPT") {
      queueMicrotask(() => {
        try {
          const source = (script.src || "").length > 0;
          if (source && shouldPublishScript) {
            // The loader owns script execution in production; the test provides
            // the minimum equivalent before emitting the load event.
            (window as unknown as { CabosEngine?: CabosEngine }).CabosEngine = scriptEngine;
          }
          script.onload?.(new Event("load") as unknown as Event);
        } catch (error) {
          script.onerror?.(error as unknown as Event);
        }
      });
    }
    return node;
  });
});

afterEach(() => {
  appendSpy.mockRestore();
  resetCableEngineCache();
});

describe("carregador do motor CabosEngine", () => {
  it("verifica o SHA-256, executa um script blob e reutiliza o módulo", async () => {
    const { script } = exposeScriptEngine();
    api.getCableTool.mockResolvedValue(await manifest(script));
    const first = await getCableEngine();
    const second = await getCableEngine();
    expect(first).toBe(fakeEngine);
    expect(second).toBe(first);
    expect(api.getCableTool).toHaveBeenCalledTimes(1);
    expect(appendSpy).toHaveBeenCalledTimes(1);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:cabos-fake");
  });

  it("rejeita um script com SHA-256 inválido", async () => {
    const { script } = exposeScriptEngine();
    api.getCableTool.mockResolvedValue({ engine_version: "cabos-fake@1", sha256: "00", script });
    await expect(getCableEngine()).rejects.toThrow(/SHA-256.*falhou/i);
    expect(appendSpy).not.toHaveBeenCalled();
  });

  it("rejeita um script que não publica um objeto novo mesmo quando o global antigo existe", async () => {
    const oldEngine = { ...fakeEngine, engine_version: "cabos-fake@1" } as CabosEngine;
    (window as unknown as { CabosEngine?: CabosEngine }).CabosEngine = oldEngine;
    shouldPublishScript = false;
    const script = "/* sha válido, mas sem publicação */";
    api.getCableTool.mockResolvedValue(await manifest(script));

    await expect(getCableEngine()).rejects.toThrow(/não publicou window\.CabosEngine/i);
    expect((window as unknown as { CabosEngine?: CabosEngine }).CabosEngine).toBeUndefined();
  });

  it("exige que engine_version do objeto publicado corresponda ao manifesto", async () => {
    const { script } = exposeScriptEngine();
    api.getCableTool.mockResolvedValue({
      engine_version: "cabos-manifest@2",
      sha256: await sha256Script(script),
      script,
    });

    await expect(getCableEngine()).rejects.toThrow(/engine_version/i);
  });

  it("rejeita protocolo diferente de 1", async () => {
    scriptEngine = { protocol: 2, engine_version: "bad" } as unknown as CabosEngine;
    const script = "globalThis.CabosEngine = { protocol: 2, engine_version: 'bad' };";
    api.getCableTool.mockResolvedValue(await manifest(script));
    await expect(getCableEngine()).rejects.toThrow(/protocolo/i);
  });

  it.each([
    [503, "Ferramenta de cálculo indisponível"],
    [403, "Sem acesso à ferramenta de cálculo"],
  ])("traduz HTTP %s para a mensagem do editor", async (status, message) => {
    api.getCableTool.mockRejectedValue(new ApiError(status, "erro sintético"));
    const view = renderHook(() => useCableEngine());
    await waitFor(() => expect(view.result.current.status).toBe("error"));
    expect(view.result.current.error).toBe(message);
  });
});
