// @vitest-environment node
import { afterEach, describe, expect, it } from "vitest";
import workerSource from "../../../../public/cable-engine-frame.js?raw";
import { buildCallMessage, buildInitMessage, ENGINE_MESSAGE_SOURCE, ENGINE_PROTOCOL } from "./protocol";
import { startCableEngineWorker, type CableEngineHandle } from "./client";
import { FAKE_ENGINE_SCRIPT, nodeWorkerFactory } from "./testWorker";

const handles: CableEngineHandle[] = [];

async function until(condition: () => boolean, timeoutMs = 3000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (!condition() && Date.now() < deadline) await new Promise((resolve) => setTimeout(resolve, 10));
}

async function start(script = FAKE_ENGINE_SCRIPT, expectedEngineVersion = "cabos-fake@1") {
  const handle = await startCableEngineWorker({ script, expectedEngineVersion, workerFactory: nodeWorkerFactory });
  handles.push(handle);
  return handle;
}

afterEach(() => {
  for (const handle of handles.splice(0)) handle.dispose();
});

describe("worker do motor de cabos (worker real do Node)", () => {
  it("publica dados estáticos e executa chamadas assíncronas", async () => {
    const { engine } = await start();
    expect(engine.protocol).toBe(1);
    expect(engine.engine_version).toBe("cabos-fake@1");
    expect(engine.templates).toEqual([{ id: "tpl", label: "Modelo", description: "Modelo de teste" }]);
    expect(engine.catalogs.regions).toHaveLength(1);
    // installModeImage é função no motor; na página é uma tabela de dados.
    expect(engine.installModeImage("13")).toEqual(["<svg/>"]);
    expect(engine.catalogs.installModeImage("img13")).toEqual(["<svg/>"]);
    expect(engine.installModeImage("inexistente")).toBeNull();

    expect(await engine.newState()).toEqual({ proj: "novo" });
    const solved = await engine.solve({ proj: "A", extra: 1 } as never);
    expect(solved.result).toEqual({ total: 2 });
    const actions = engine.actions as unknown as { rename: (state: unknown, args: unknown) => Promise<unknown> };
    expect(await actions.rename({ proj: "A" }, { name: "B" })).toEqual({ proj: "B" });
    expect(await engine.views.sld({ proj: "X" } as never, {} as never)).toContain("X");
    expect(await engine.exports.copyTable({} as never, {} as never)).toBe("a\tb");
    // não existe no motor sintético: a fachada só tem o que o motor publica
    expect((engine.exports as Record<string, unknown>).sldSvg).toBeUndefined();
  });

  it("devolve Blobs dos exports e preserva a ordem das respostas", async () => {
    const { engine } = await start();
    const exportsApi = engine.exports as unknown as { file: () => Promise<{ blob: Blob; filename: string }> };
    const file = await exportsApi.file();
    expect(file.filename).toBe("x.txt");
    expect(file.blob.size).toBe(1);
    const results = await Promise.all([1, 2, 3, 4, 5].map((n) => engine.solve({ [`k${n}`]: n } as never)));
    expect(results.map((entry) => Object.keys(entry.state)[0])).toEqual(["k1", "k2", "k3", "k4", "k5"]);
  });

  it("o motor não vê a página: sem window, document, storage, rede nem o global CabosEngine", async () => {
    const { engine } = await start();
    const probe = await (engine.views as unknown as { probe: () => Promise<Record<string, string>> }).probe();
    expect(probe).toEqual({
      window: "undefined",
      document: "undefined",
      localStorage: "undefined",
      sessionStorage: "undefined",
      fetch: "undefined",
      xhr: "undefined",
      webSocket: "undefined",
      indexedDB: "undefined",
      importScripts: "undefined",
      global: "undefined",
    });
  });

  it("propaga erros do motor como rejeição, sem stack, e continua utilizável", async () => {
    const { engine } = await start();
    const views = engine.views as unknown as { boom: () => Promise<unknown>; nonCloneable: () => Promise<unknown> };
    await expect(views.boom()).rejects.toThrow("falha do motor");
    await expect(views.nonCloneable()).rejects.toThrow(/não é transferível/);
    expect(await engine.newState()).toEqual({ proj: "novo" });
  });

  it("só executa o que o motor publica e ignora mensagens fora do protocolo", async () => {
    const { engine } = await start();
    const { created } = await import("./testWorker");
    const worker = created[created.length - 1];
    const seen: unknown[] = [];
    const previous = worker.onmessage;
    worker.onmessage = (event) => { seen.push(event.data); previous?.(event); };

    // caminhos fora da lista fechada: erro explícito
    worker.postMessage(buildCallMessage(900, ["constructor"], []));
    worker.postMessage(buildCallMessage(901, ["views", "__proto__"], []));
    worker.postMessage(buildCallMessage(902, ["actions", "toString"], []));
    // lixo: não responde
    worker.postMessage({ type: "call", id: 903, path: ["solve"], args: [] }); // sem source/protocol
    worker.postMessage({ source: ENGINE_MESSAGE_SOURCE, protocol: 2, type: "call", id: 904, path: ["solve"], args: [{}] });
    worker.postMessage({ source: ENGINE_MESSAGE_SOURCE, protocol: ENGINE_PROTOCOL, type: "call", id: -1, path: ["solve"], args: [] });
    worker.postMessage({ source: ENGINE_MESSAGE_SOURCE, protocol: ENGINE_PROTOCOL, type: "call", id: 905, path: ["a", "b", "c"], args: [] });
    worker.postMessage("texto");
    worker.postMessage(null);
    // e uma chamada válida a seguir: confirma que o worker não ficou preso
    expect(await engine.newState()).toEqual({ proj: "novo" });
    await new Promise((resolve) => setTimeout(resolve, 50));

    const answered = (seen as Array<{ id?: number; type: string; message?: string }>).filter((message) => message.id !== undefined && message.id >= 900);
    expect(answered.map((message) => [message.id, message.type]).sort()).toEqual([[900, "error"], [901, "error"], [902, "error"]]);
    expect(answered[0].message).toMatch(/Operação desconhecida/);
  });

  it("termina com mensagem clara se o script não publica o motor, publica outro protocolo ou outra versão", async () => {
    await expect(start("/* nada */")).rejects.toThrow(/não publicou CabosEngine/);
    await expect(start("globalThis.CabosEngine = { protocol: 2, engine_version: 'x' };")).rejects.toThrow(/protocolo/);
    await expect(start("globalThis.CabosEngine = { protocol: 1 };")).rejects.toThrow(/engine_version/);
    await expect(start(FAKE_ENGINE_SCRIPT, "cabos-outra@9")).rejects.toThrow(/não corresponde ao manifesto/);
  });

  it("rejeita se o script do motor lança uma exceção ao carregar", async () => {
    await expect(start("throw new Error('rebentou');")).rejects.toThrow(/executar a ferramenta/);
  });

  it("o ficheiro estático do worker é autónomo (sem imports) e não executa nada antes do init", () => {
    expect(workerSource).not.toMatch(/^\s*(import|export)\s/m);
    expect(workerSource).not.toMatch(/importScripts\(/);
    // só o init arranca o motor: chamadas anteriores são ignoradas
    expect(workerSource.indexOf('"init"')).toBeGreaterThan(-1);
  });

  it("ignora chamadas antes do init e um segundo init (o motor não é substituído)", async () => {
    const { nodeWorkerFactory } = await import("./testWorker");
    const worker = nodeWorkerFactory();
    const seen: Array<{ type: string; engine_version?: string; id?: number }> = [];
    worker.onmessage = (event) => seen.push(event.data as never);
    worker.postMessage(buildCallMessage(1, ["solve"], [{}])); // antes do init: ignorada
    worker.postMessage(buildInitMessage(FAKE_ENGINE_SCRIPT));
    await until(() => seen.length >= 1);
    worker.postMessage(buildInitMessage("globalThis.CabosEngine = { protocol: 1, engine_version: 'outro' };"));
    worker.postMessage(buildCallMessage(2, ["newState"], []));
    await until(() => seen.length >= 2);
    worker.terminate();
    expect(seen.map((message) => message.type)).toEqual(["ready", "result"]);
    expect(seen[0].engine_version).toBe("cabos-fake@1");
    expect(seen[1].id).toBe(2);
  });

  it("rejeita um init com script vazio ou demasiado grande sem executar nada", async () => {
    const { nodeWorkerFactory } = await import("./testWorker");
    const worker = nodeWorkerFactory();
    const seen: unknown[] = [];
    worker.onmessage = (event) => seen.push(event.data);
    worker.postMessage(buildInitMessage(""));
    worker.postMessage({ source: ENGINE_MESSAGE_SOURCE, protocol: ENGINE_PROTOCOL, type: "init", script: 42 });
    worker.postMessage(buildInitMessage(" ".repeat(9 * 1024 * 1024 + 1)));
    // ainda aceita um init válido depois: os anteriores não o consumiram
    worker.postMessage(buildInitMessage(FAKE_ENGINE_SCRIPT));
    await until(() => seen.length >= 1);
    await new Promise((resolve) => setTimeout(resolve, 100));
    worker.terminate();
    expect(seen.map((message) => (message as { type: string }).type)).toEqual(["ready"]);
  });

  it("depois de dispose, as chamadas rejeitam", async () => {
    const handle = await start();
    handle.dispose();
    await expect(handle.engine.newState()).rejects.toThrow(/terminada/);
  });
});
