import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthenticatedBlob, useObjectUrl } from "./useAuthenticatedBlob";

let counter = 0;
const created: string[] = [];
const revoked: string[] = [];

beforeEach(() => {
  counter = 0;
  created.length = 0;
  revoked.length = 0;
  vi.spyOn(URL, "createObjectURL").mockImplementation(() => {
    counter += 1;
    const url = `blob:teste-${counter}`;
    created.push(url);
    return url;
  });
  vi.spyOn(URL, "revokeObjectURL").mockImplementation((url) => { revoked.push(url); });
});

afterEach(() => {
  vi.restoreAllMocks();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

describe("useAuthenticatedBlob", () => {
  it("cria o object URL e revoga-o ao desmontar", async () => {
    const view = renderHook(() => useAuthenticatedBlob(() => Promise.resolve(new Blob(["a"])), ["a"]));
    await waitFor(() => expect(view.result.current).toBe("blob:teste-1"));
    expect(revoked).toEqual([]);
    view.unmount();
    expect(revoked).toEqual(["blob:teste-1"]);
  });

  it("revoga o URL anterior quando as dependências mudam", async () => {
    const view = renderHook(({ id }) => useAuthenticatedBlob(() => Promise.resolve(new Blob([id])), [id]), { initialProps: { id: "1" } });
    await waitFor(() => expect(view.result.current).toBe("blob:teste-1"));
    view.rerender({ id: "2" });
    await waitFor(() => expect(view.result.current).toBe("blob:teste-2"));
    expect(revoked).toEqual(["blob:teste-1"]);
    view.unmount();
    expect(revoked).toEqual(["blob:teste-1", "blob:teste-2"]);
  });

  it("descarta uma resposta que chega depois do unmount, sem criar URL", async () => {
    const pending = deferred<Blob>();
    const view = renderHook(() => useAuthenticatedBlob(() => pending.promise, []));
    view.unmount();
    await act(async () => { pending.resolve(new Blob(["tarde"])); await pending.promise; });
    expect(created).toEqual([]);
    expect(revoked).toEqual([]);
  });

  it("descarta uma resposta ultrapassada por uma mudança de dependências", async () => {
    const first = deferred<Blob>();
    const second = deferred<Blob>();
    const view = renderHook(({ id }) => useAuthenticatedBlob(() => (id === "1" ? first.promise : second.promise), [id]), { initialProps: { id: "1" } });
    view.rerender({ id: "2" });
    await act(async () => { second.resolve(new Blob(["2"])); await second.promise; });
    await act(async () => { first.resolve(new Blob(["1"])); await first.promise; });
    expect(view.result.current).toBe("blob:teste-1");
    expect(created).toEqual(["blob:teste-1"]); // só o da resposta atual
  });

  it("não pede nada quando está desativado e devolve null", async () => {
    const load = vi.fn(() => Promise.resolve(new Blob(["x"])));
    const view = renderHook(() => useAuthenticatedBlob(load, [], { enabled: false }));
    expect(view.result.current).toBeNull();
    expect(load).not.toHaveBeenCalled();
  });

  it("chama onError se o pedido falhar enquanto interessa, e não depois do unmount", async () => {
    const onError = vi.fn();
    const failure = new Error("falhou");
    const view = renderHook(() => useAuthenticatedBlob(() => Promise.reject(failure), [], { onError }));
    await waitFor(() => expect(onError).toHaveBeenCalledWith(failure));
    expect(view.result.current).toBeNull();

    const late = deferred<Blob>();
    const lateOnError = vi.fn();
    const second = renderHook(() => useAuthenticatedBlob(() => late.promise, [], { onError: lateOnError }));
    second.unmount();
    await act(async () => { late.reject(new Error("tarde")); await late.promise.catch(() => undefined); });
    expect(lateOnError).not.toHaveBeenCalled();
  });
});

describe("useObjectUrl", () => {
  it("cria o URL do ficheiro e revoga-o ao mudar de ficheiro e ao desmontar", () => {
    const fileA = new Blob(["a"]);
    const fileB = new Blob(["b"]);
    const view = renderHook(({ file }) => useObjectUrl(file), { initialProps: { file: fileA as Blob | null } });
    expect(view.result.current).toBe("blob:teste-1");
    view.rerender({ file: fileB });
    expect(view.result.current).toBe("blob:teste-2");
    expect(revoked).toEqual(["blob:teste-1"]);
    view.rerender({ file: null });
    expect(view.result.current).toBeNull();
    expect(revoked).toEqual(["blob:teste-1", "blob:teste-2"]);
    view.unmount();
    expect(revoked).toHaveLength(2);
  });
});
