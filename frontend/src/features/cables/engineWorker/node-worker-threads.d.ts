// Tipos mínimos de `node:worker_threads`, só para `testWorker.ts` (apoio aos
// testes). Evita acrescentar @types/node ao projeto do browser.
declare module "node:worker_threads" {
  export class Worker {
    constructor(source: string, options?: { eval?: boolean });
    postMessage(message: unknown): void;
    terminate(): Promise<number>;
    on(event: "message", listener: (data: unknown) => void): this;
    on(event: "error", listener: (error: Error) => void): this;
  }
}
