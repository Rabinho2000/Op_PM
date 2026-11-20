import { describe, expect, it, vi } from "vitest";
import { startCableEngineWorker, type WorkerLike } from "./client";
import { ENGINE_MESSAGE_SOURCE, ENGINE_PROTOCOL } from "./protocol";

const base = { source: ENGINE_MESSAGE_SOURCE, protocol: ENGINE_PROTOCOL };

class FakeWorker implements WorkerLike {
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: ErrorEvent) => void) | null = null;
  onmessageerror: ((event: MessageEvent) => void) | null = null;
  sent: Array<{ id: number; path: string[]; args: unknown[] }> = [];
  terminated = false;
  postMessage(message: unknown) { this.sent.push(message as never); }
  terminate() { this.terminated = true; }
  emit(data: unknown) { this.onmessage?.({ data } as MessageEvent); }
  ready(overrides: Record<string, unknown> = {}) {
    this.emit({
      ...base,
      type: "ready",
      engine_version: "cabos@1",
      templates: [{ id: "t", label: "T", description: "" }],
      catalogs: { regions: [] },
      installModeImages: { "13": ["a"] },
      surface: { root: ["solve"], views: ["sld"], actions: [], exports: [], compare: [] },
      ...overrides,
    });
  }
}

function setup(options: { expected?: string; timeoutMs?: number; onTerminated?: (reason: Error) => void } = {}) {
  const worker = new FakeWorker();
  const promise = startCableEngineWorker({
    script: "/*motor*/",
    expectedEngineVersion: options.expected ?? "cabos@1",
    readyTimeoutMs: options.timeoutMs,
    onTerminated: options.onTerminated,
    workerFactory: () => worker,
  });
  return { worker, promise };
}

describe("cliente do worker do motor", () => {
  it("entrega o script ao worker e constrói a fachada a partir de ready", async () => {
    const { worker, promise } = setup();
    // a primeira mensagem para o worker é o init, com o script do motor
    expect(worker.sent[0]).toMatchObject({ source: ENGINE_MESSAGE_SOURCE, protocol: ENGINE_PROTOCOL, type: "init", script: "/*motor*/" });
    worker.sent.length = 0;
    worker.ready();
    const { engine } = await promise;
    expect(engine.engine_version).toBe("cabos@1");
    expect(engine.templates).toHaveLength(1);
    expect(engine.installModeImage("13")).toEqual(["a"]);
    expect(typeof engine.solve).toBe("function");
    expect(typeof engine.views.sld).toBe("function");
    expect((engine.actions as Record<string, unknown>).addPerc).toBeUndefined();
  });

  it("correlaciona respostas por id e ignora respostas desconhecidas ou inválidas", async () => {
    const { worker, promise } = setup();
    worker.ready();
    const { engine } = await promise;
    worker.sent.length = 0; // o init
    const first = engine.solve({ a: 1 } as never);
    const second = engine.views.sld({} as never, {} as never);
    expect(worker.sent.map((call) => [call.id, call.path])).toEqual([[1, ["solve"]], [2, ["views", "sld"]]]);

    worker.emit({ ...base, type: "result", id: 99, value: "órfã" }); // sem pedido
    worker.emit({ source: "intruso", protocol: 1, type: "result", id: 1, value: "falsa" }); // outro source
    worker.emit({ ...base, type: "result", id: "1", value: "falsa" }); // id inválido
    worker.emit(undefined);
    worker.emit({ ...base, type: "result", id: 2, value: "<svg/>" });
    worker.emit({ ...base, type: "result", id: 1, value: { ok: true } });
    await expect(first).resolves.toEqual({ ok: true });
    await expect(second).resolves.toBe("<svg/>");
  });

  it("rejeita o pedido quando o worker responde com erro", async () => {
    const { worker, promise } = setup();
    worker.ready();
    const { engine } = await promise;
    const call = engine.solve({} as never);
    worker.emit({ ...base, type: "error", id: 1, message: "estado inválido" });
    await expect(call).rejects.toThrow("estado inválido");
  });

  it("rejeita o arranque se a versão não corresponde ao manifesto e termina o worker", async () => {
    const { worker, promise } = setup({ expected: "cabos@2" });
    worker.ready();
    await expect(promise).rejects.toThrow(/não corresponde ao manifesto/);
    expect(worker.terminated).toBe(true);
  });

  it("rejeita o arranque em fatal, erro do worker e timeout", async () => {
    const a = setup();
    a.worker.emit({ ...base, type: "fatal", message: "sem motor" });
    await expect(a.promise).rejects.toThrow("sem motor");

    const b = setup();
    b.worker.onerror?.({ message: "x", preventDefault: vi.fn() } as unknown as ErrorEvent);
    await expect(b.promise).rejects.toThrow(/executar a ferramenta/);

    vi.useFakeTimers();
    try {
      const c = setup({ timeoutMs: 1000 });
      const assertion = expect(c.promise).rejects.toThrow(/a tempo/);
      await vi.advanceTimersByTimeAsync(1001);
      await assertion;
      expect(c.worker.terminated).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("se o worker morrer depois de pronto, rejeita pendentes e avisa uma vez", async () => {
    const onTerminated = vi.fn();
    const { worker, promise } = setup({ onTerminated });
    worker.ready();
    const { engine } = await promise;
    const pending = engine.solve({} as never);
    worker.onerror?.({ message: "oom", preventDefault: vi.fn() } as unknown as ErrorEvent);
    await expect(pending).rejects.toThrow(/executar a ferramenta/);
    await expect(engine.solve({} as never)).rejects.toThrow(/terminada/);
    expect(onTerminated).toHaveBeenCalledTimes(1);
    expect(worker.terminated).toBe(true);
  });

  it("um segundo ready não substitui a fachada", async () => {
    const { worker, promise } = setup();
    worker.ready();
    const { engine } = await promise;
    worker.ready({ engine_version: "cabos@1", surface: { root: [], views: [], actions: [], exports: [], compare: [] } });
    expect(typeof engine.solve).toBe("function");
  });
});
