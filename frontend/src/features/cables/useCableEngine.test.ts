import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { created, FAKE_ENGINE_SCRIPT, nodeWorkerFactory } from "./engineWorker/testWorker";

const api = vi.hoisted(() => ({ getCableTool: vi.fn() }));
vi.mock("../../api/cableDesigns", async () => {
  const actual = await vi.importActual<typeof import("../../api/cableDesigns")>("../../api/cableDesigns");
  return { ...actual, getCableTool: api.getCableTool };
});

import { getCableEngine, resetCableEngineCache, setCableWorkerFactoryForTests, sha256Script, useCableEngine } from "./useCableEngine";

async function manifest(script: string, engineVersion = "cabos-fake@1") {
  return { engine_version: engineVersion, sha256: await sha256Script(script), script };
}

beforeEach(() => {
  resetCableEngineCache();
  api.getCableTool.mockReset();
  created.length = 0;
  setCableWorkerFactoryForTests(nodeWorkerFactory);
});

afterEach(() => {
  resetCableEngineCache();
  setCableWorkerFactoryForTests(undefined);
});

describe("carregador do motor CabosEngine (Web Worker)", () => {
  it("verifica o SHA-256, executa o motor num worker e reutiliza-o", async () => {
    api.getCableTool.mockResolvedValue(await manifest(FAKE_ENGINE_SCRIPT));
    const first = await getCableEngine();
    const second = await getCableEngine();
    expect(second).toBe(first);
    expect(first.engine_version).toBe("cabos-fake@1");
    expect(api.getCableTool).toHaveBeenCalledTimes(1);
    expect(created).toHaveLength(1);
    expect(await first.newState()).toEqual({ proj: "novo" });
  });

  it("não cria o worker nem executa nada se o SHA-256 não corresponde", async () => {
    api.getCableTool.mockResolvedValue({ engine_version: "cabos-fake@1", sha256: "00", script: FAKE_ENGINE_SCRIPT });
    await expect(getCableEngine()).rejects.toThrow(/SHA-256.*falhou/i);
    expect(created).toHaveLength(0);
  });

  it("não deixa nenhum global do motor na janela da página", async () => {
    api.getCableTool.mockResolvedValue(await manifest(FAKE_ENGINE_SCRIPT));
    await getCableEngine();
    expect((window as unknown as { CabosEngine?: unknown }).CabosEngine).toBeUndefined();
    expect((globalThis as unknown as { CabosEngine?: unknown }).CabosEngine).toBeUndefined();
  });

  it("exige que engine_version do motor corresponda ao manifesto", async () => {
    api.getCableTool.mockResolvedValue(await manifest(FAKE_ENGINE_SCRIPT, "cabos-manifest@2"));
    await expect(getCableEngine()).rejects.toThrow(/engine_version/i);
  });

  it("rejeita protocolo diferente de 1", async () => {
    const script = "globalThis.CabosEngine = { protocol: 2, engine_version: 'cabos-fake@1' };";
    api.getCableTool.mockResolvedValue(await manifest(script));
    await expect(getCableEngine()).rejects.toThrow(/protocolo/i);
  });

  it("rejeita um script que não publica o motor", async () => {
    const script = "/* sha válido, mas sem publicação */";
    api.getCableTool.mockResolvedValue(await manifest(script));
    await expect(getCableEngine()).rejects.toThrow(/não publicou CabosEngine/i);
  });

  it("depois de uma falha volta a tentar em vez de guardar o erro", async () => {
    api.getCableTool.mockRejectedValueOnce(new ApiError(503, "indisponível"));
    await expect(getCableEngine()).rejects.toBeInstanceOf(ApiError);
    api.getCableTool.mockResolvedValue(await manifest(FAKE_ENGINE_SCRIPT));
    expect((await getCableEngine()).engine_version).toBe("cabos-fake@1");
  });

  it("recria o worker depois de resetCableEngineCache (que termina o anterior)", async () => {
    api.getCableTool.mockResolvedValue(await manifest(FAKE_ENGINE_SCRIPT));
    const first = await getCableEngine();
    resetCableEngineCache();
    await expect(first.newState()).rejects.toThrow(/terminada/);
    const second = await getCableEngine();
    expect(second).not.toBe(first);
    expect(created).toHaveLength(2);
  });

  it("o hook entrega o motor pronto", async () => {
    api.getCableTool.mockResolvedValue(await manifest(FAKE_ENGINE_SCRIPT));
    const view = renderHook(() => useCableEngine());
    await waitFor(() => expect(view.result.current.status).toBe("ready"));
    expect(view.result.current.engine?.engine_version).toBe("cabos-fake@1");
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
