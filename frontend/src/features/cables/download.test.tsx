import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ToastProvider } from "../../components/Toast";
import { downloadExport, useExportRunner } from "./download";

const file = () => ({ blob: new Blob(["conteúdo"], { type: "text/plain" }), filename: "estudo.txt" });

describe("downloads do editor de cabos", () => {
  it("cria um link download, clica nele e revoga o URL", async () => {
    const notify = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const create = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:estudo");
    const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);

    await expect(downloadExport(Promise.resolve(file()), { notify })).resolves.toMatchObject({ filename: "estudo.txt" });

    expect(click).toHaveBeenCalledTimes(1);
    expect(create).toHaveBeenCalledWith(expect.any(Blob));
    expect(revoke).toHaveBeenCalledWith("blob:estudo");
    expect(notify).toHaveBeenCalledWith("Ficheiro descarregado.", "success");
    expect(document.querySelector('a[download="estudo.txt"]')).toBeNull();

    click.mockRestore();
    create.mockRestore();
    revoke.mockRestore();
  });

  it("converte uma falha do exportador em notificação de erro", async () => {
    const notify = vi.fn();
    await expect(downloadExport(() => Promise.reject(new Error("falha")), { notify })).resolves.toBeNull();
    expect(notify).toHaveBeenCalledWith("Não foi possível gerar o ficheiro.", "error");
  });

  it("expõe o estado a gerar enquanto o exportador está pendente", async () => {
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    let resolve: ((value: ReturnType<typeof file>) => void) | undefined;
    const pending = new Promise<ReturnType<typeof file>>((done) => { resolve = done; });
    const view = renderHook(() => useExportRunner(), {
      wrapper: ({ children }) => <ToastProvider>{children}</ToastProvider>,
    });

    let run: Promise<unknown> | undefined;
    act(() => { run = view.result.current.run(pending); });
    await waitFor(() => expect(view.result.current.isGenerating).toBe(true));
    expect(view.result.current.label).toBe("A gerar…");
    resolve?.(file());
    await act(async () => { await run; });
    await waitFor(() => expect(view.result.current.isGenerating).toBe(false));
  });
});
