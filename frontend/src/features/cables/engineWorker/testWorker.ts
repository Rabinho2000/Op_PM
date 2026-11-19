// Apoio aos testes: corre o script do worker (o mesmo que corre no browser) num
// worker REAL do Node (`worker_threads`), com a API mínima de um Web Worker.
// Não é código de produção nem é importado pela aplicação.
import { Worker as NodeWorker } from "node:worker_threads";
import workerSource from "../../../../public/cable-engine-worker.js?raw";
import type { WorkerFactory, WorkerLike } from "./client";

const WEB_WORKER_SHIM = `
  const { parentPort } = require("node:worker_threads");
  globalThis.self = globalThis;
  globalThis.postMessage = (message) => parentPort.postMessage(message);
  parentPort.on("message", (data) => {
    if (typeof globalThis.onmessage === "function") globalThis.onmessage({ data });
  });
`;

export interface TestWorkerHandle extends WorkerLike {
  /** Mensagens sem protocolo (para testar a validação). */
  raw: NodeWorker;
}

export const created: TestWorkerHandle[] = [];

export const nodeWorkerFactory: WorkerFactory = () => {
  const node = new NodeWorker(`${WEB_WORKER_SHIM}\n;\n${workerSource}`, { eval: true });
  const worker: TestWorkerHandle = {
    raw: node,
    onmessage: null,
    onerror: null,
    onmessageerror: null,
    postMessage: (message) => node.postMessage(message),
    terminate: () => { void node.terminate(); },
  };
  node.on("message", (data) => worker.onmessage?.({ data } as MessageEvent));
  node.on("error", (error) => worker.onerror?.({ message: error.message, preventDefault: () => undefined } as ErrorEvent));
  created.push(worker);
  return worker;
};

/** Motor sintético (protocolo 1) com uma sonda do ambiente em que corre. */
export const FAKE_ENGINE_SCRIPT = `
globalThis.CabosEngine = {
  protocol: 1,
  engine_version: "cabos-fake@1",
  templates: [{ id: "tpl", label: "Modelo", description: "Modelo de teste" }],
  catalogs: {
    regions: [{ id: "Porto", label: "Porto", tair: 25, tsoil: 20, tmin: -3 }],
    installModes: [{ id: "13", label: "Ref. 13", description: "", method: "EF", group: "g", imageId: "img13" }],
    installModeImage: function (id) { return id === "13" || id === "img13" ? ["<svg/>"] : null; },
  },
  newState: function () { return { proj: "novo" }; },
  migrate: function (raw) { return Object.assign({}, raw, { migrated: true }); },
  solve: function (state) { return { state: state, result: { total: Object.keys(state).length } }; },
  summarize: function (result) { return { circuits: result.total }; },
  persistedResult: function (state) { return { format: 1, proj: state.proj }; },
  views: {
    sld: function (state) { return "<svg><title>" + state.proj + "</title></svg>"; },
    boom: function () { throw new Error("falha do motor"); },
    nonCloneable: function () { return { fn: function () {} }; },
    probe: function () {
      return {
        window: typeof window, document: typeof document, localStorage: typeof localStorage,
        sessionStorage: typeof sessionStorage, fetch: typeof fetch, xhr: typeof XMLHttpRequest,
        webSocket: typeof WebSocket, indexedDB: typeof indexedDB, importScripts: typeof importScripts,
        global: typeof globalThis.CabosEngine,
      };
    },
  },
  actions: { rename: function (state, args) { return Object.assign({}, state, { proj: args.name }); } },
  exports: { copyTable: function () { return "a\\tb"; }, file: function () { return { blob: new Blob(["x"]), filename: "x.txt" }; } },
  compare: { variants: function () { return []; }, apply: function (state) { return state; } },
};
`;
