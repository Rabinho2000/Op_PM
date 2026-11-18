import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CABLE_BRIDGE_PROTOCOL,
  CABLE_BRIDGE_SOURCE,
  buildCableInitMessage,
  buildCableSnapshotRequestMessage,
  buildCableSnapshotSavedMessage,
  requestSnapshot,
  validateCableToolMessage,
} from "./cableBridge";

const meta = {
  projectName: "Projeto A",
  clientName: "Cliente A",
  address: "Morada A",
  studyTitle: "Estudo A",
  rev: "A",
  status: "rascunho",
};

afterEach(() => vi.restoreAllMocks());

describe("ponte de cabos", () => {
  it("constrói as mensagens shell → ferramenta com o envelope da versão 1", () => {
    expect(buildCableInitMessage({ state: { circuits: [] }, readOnly: false, meta })).toEqual({
      source: CABLE_BRIDGE_SOURCE,
      protocol: CABLE_BRIDGE_PROTOCOL,
      type: "cable:init",
      state: { circuits: [] },
      readOnly: false,
      meta,
    });
    expect(buildCableSnapshotRequestMessage("req-1")).toEqual({
      source: CABLE_BRIDGE_SOURCE,
      protocol: CABLE_BRIDGE_PROTOCOL,
      type: "cable:snapshot-request",
      requestId: "req-1",
    });
    expect(buildCableSnapshotSavedMessage("req-1")).toEqual({
      source: CABLE_BRIDGE_SOURCE,
      protocol: CABLE_BRIDGE_PROTOCOL,
      type: "cable:snapshot-saved",
      requestId: "req-1",
    });
  });

  it("aceita apenas mensagens conhecidas com campos válidos", () => {
    expect(validateCableToolMessage({ source: CABLE_BRIDGE_SOURCE, protocol: 1, type: "cable:ready" })).toEqual({
      source: CABLE_BRIDGE_SOURCE,
      protocol: 1,
      type: "cable:ready",
    });
    expect(validateCableToolMessage({ source: CABLE_BRIDGE_SOURCE, protocol: 1, type: "cable:dirty", dirty: true })).toEqual({
      source: CABLE_BRIDGE_SOURCE,
      protocol: 1,
      type: "cable:dirty",
      dirty: true,
    });
    expect(validateCableToolMessage({
      source: CABLE_BRIDGE_SOURCE,
      protocol: 1,
      type: "cable:snapshot",
      requestId: "req-1",
      input: { format: 1, state: { circuits: [] } },
      result: { format: 1, circuits: [] },
      engine_version: "cabos-1",
    })).toMatchObject({ type: "cable:snapshot", requestId: "req-1" });
    expect(validateCableToolMessage({ source: "outro", protocol: 1, type: "cable:ready" })).toBeNull();
    expect(validateCableToolMessage({ source: CABLE_BRIDGE_SOURCE, protocol: 2, type: "cable:ready" })).toBeNull();
    expect(validateCableToolMessage({ source: CABLE_BRIDGE_SOURCE, protocol: 1, type: "cable:dirty", dirty: "sim" })).toBeNull();
    expect(validateCableToolMessage({ source: CABLE_BRIDGE_SOURCE, protocol: 1, type: "cable:snapshot", requestId: "req-1", input: [], result: {}, engine_version: "cabos-1" })).toBeNull();
    expect(validateCableToolMessage(null)).toBeNull();
  });

  it("envia o pedido e resolve o snapshot correspondente", async () => {
    const iframeWindow = { postMessage: vi.fn() } as unknown as Window;
    const promise = requestSnapshot(iframeWindow, undefined, 100);
    const sent = iframeWindow.postMessage as unknown as ReturnType<typeof vi.fn>;
    const requestId = sent.mock.calls[0][0].requestId as string;
    expect(sent.mock.calls[0][1]).toBe("*");

    window.dispatchEvent(new MessageEvent("message", {
      data: {
        source: CABLE_BRIDGE_SOURCE,
        protocol: 1,
        type: "cable:snapshot",
        requestId,
        input: { format: 1, state: { circuits: [] } },
        result: { format: 1, circuits: [] },
        engine_version: "cabos-1",
      },
    }));

    await expect(promise).resolves.toMatchObject({ type: "cable:snapshot", requestId });
  });

  it("rejeita em português quando a ferramenta não responde", async () => {
    const iframeWindow = { postMessage: vi.fn() } as unknown as Window;
    await expect(requestSnapshot(iframeWindow, undefined, 1)).rejects.toThrow(/snapshot.*tempo/i);
  });
});
