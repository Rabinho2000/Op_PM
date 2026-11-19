import { afterEach, describe, expect, it, vi } from "vitest";
import { CABLE_FRAME_URL, sandboxedFrameFactory } from "./client";

afterEach(() => {
  document.body.innerHTML = "";
});

function frameOf(): HTMLIFrameElement {
  const frame = document.querySelector("iframe");
  if (!frame) throw new Error("sem iframe");
  return frame;
}

describe("iframe isolado do motor", () => {
  it("cria um iframe sandbox só com allow-scripts (sem same-origin, popups, forms, navegação ou downloads), escondido", () => {
    sandboxedFrameFactory();
    const frame = frameOf();
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts");
    expect(frame.getAttribute("src")).toBe(CABLE_FRAME_URL);
    expect(frame.hidden).toBe(true);
    expect(frame.getAttribute("referrerpolicy")).toBe("no-referrer");
  });

  it("guarda as mensagens até o iframe carregar e depois envia-as com targetOrigin '*'", () => {
    const channel = sandboxedFrameFactory();
    const frame = frameOf();
    const posted = vi.fn();
    Object.defineProperty(frame, "contentWindow", { configurable: true, value: { postMessage: posted } });
    channel.postMessage({ n: 1 });
    channel.postMessage({ n: 2 });
    expect(posted).not.toHaveBeenCalled();
    frame.dispatchEvent(new Event("load"));
    expect(posted.mock.calls).toEqual([[{ n: 1 }, "*"], [{ n: 2 }, "*"]]);
    channel.postMessage({ n: 3 });
    expect(posted).toHaveBeenLastCalledWith({ n: 3 }, "*");
  });

  it("só aceita mensagens vindas da janela do próprio iframe", () => {
    const channel = sandboxedFrameFactory();
    const frame = frameOf();
    const guest = { postMessage: vi.fn() } as unknown as Window;
    Object.defineProperty(frame, "contentWindow", { configurable: true, value: guest });
    const received: unknown[] = [];
    channel.onmessage = (event) => received.push(event.data);
    window.dispatchEvent(new MessageEvent("message", { data: "da página", source: window }));
    window.dispatchEvent(new MessageEvent("message", { data: "de outra janela", source: null }));
    window.dispatchEvent(new MessageEvent("message", { data: "do iframe", source: guest }));
    expect(received).toEqual(["do iframe"]);
  });

  it("terminate remove o iframe e deixa de ouvir e de enviar", () => {
    const channel = sandboxedFrameFactory();
    const frame = frameOf();
    const guest = { postMessage: vi.fn() } as unknown as Window;
    Object.defineProperty(frame, "contentWindow", { configurable: true, value: guest });
    const received: unknown[] = [];
    channel.onmessage = (event) => received.push(event.data);
    channel.terminate();
    expect(document.querySelector("iframe")).toBeNull();
    window.dispatchEvent(new MessageEvent("message", { data: "tarde", source: guest }));
    channel.postMessage({ n: 1 });
    expect(received).toEqual([]);
    expect(guest.postMessage).not.toHaveBeenCalled();
  });
});
