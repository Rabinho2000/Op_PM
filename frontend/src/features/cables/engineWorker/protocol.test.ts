import { describe, expect, it } from "vitest";
import { buildCallMessage, ENGINE_MESSAGE_SOURCE, ENGINE_PROTOCOL, parseWorkerMessage } from "./protocol";

const base = { source: ENGINE_MESSAGE_SOURCE, protocol: ENGINE_PROTOCOL };
const surface = { root: ["solve"], views: ["sld"], actions: ["addPerc"], exports: [], compare: [] };
const ready = {
  ...base,
  type: "ready",
  engine_version: "cabos@1",
  templates: [],
  catalogs: { regions: [] },
  installModeImages: { "13": ["<svg/>"], "14": null },
  surface,
};

describe("protocolo do worker do motor", () => {
  it("constrói chamadas com source e protocolo", () => {
    expect(buildCallMessage(3, ["views", "sld"], [1, 2])).toEqual({ ...base, type: "call", id: 3, path: ["views", "sld"], args: [1, 2] });
  });

  it("aceita mensagens válidas de cada tipo", () => {
    expect(parseWorkerMessage(ready)?.type).toBe("ready");
    expect(parseWorkerMessage({ ...base, type: "result", id: 1, value: { a: 1 } })).toMatchObject({ type: "result", id: 1, value: { a: 1 } });
    expect(parseWorkerMessage({ ...base, type: "error", id: 2, message: "x" })).toMatchObject({ type: "error", id: 2, message: "x" });
    expect(parseWorkerMessage({ ...base, type: "fatal", message: "x" })).toMatchObject({ type: "fatal" });
  });

  it.each([
    ["não objeto", "texto"],
    ["null", null],
    ["array", []],
    ["sem source", { protocol: 1, type: "fatal", message: "x" }],
    ["source de outro", { source: "outro", protocol: 1, type: "fatal", message: "x" }],
    ["protocolo 2", { ...base, protocol: 2, type: "fatal", message: "x" }],
    ["tipo desconhecido", { ...base, type: "eval", code: "alert(1)" }],
    ["result sem id", { ...base, type: "result", value: 1 }],
    ["result com id 0", { ...base, type: "result", id: 0, value: 1 }],
    ["result com id fracionário", { ...base, type: "result", id: 1.5, value: 1 }],
    ["error sem mensagem", { ...base, type: "error", id: 1 }],
    ["fatal sem mensagem", { ...base, type: "fatal" }],
    ["ready sem surface", { ...ready, surface: undefined }],
    ["ready com surface inválida", { ...ready, surface: { ...surface, views: [1] } }],
    ["ready com nome de método vazio", { ...ready, surface: { ...surface, actions: [""] } }],
    ["ready sem catálogos", { ...ready, catalogs: [] }],
    ["ready com versão vazia", { ...ready, engine_version: "" }],
    ["ready com versão enorme", { ...ready, engine_version: "x".repeat(65) }],
    ["ready com imagens inválidas", { ...ready, installModeImages: { a: [1] } }],
  ])("ignora %s", (_name, message) => {
    expect(parseWorkerMessage(message)).toBeNull();
  });

  it("corta mensagens de erro demasiado longas", () => {
    const parsed = parseWorkerMessage({ ...base, type: "error", id: 1, message: "e".repeat(1000) });
    expect(parsed?.type === "error" && parsed.message.length).toBe(300);
  });
});
