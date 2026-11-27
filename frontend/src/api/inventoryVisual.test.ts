import { beforeEach, describe, expect, it, vi } from "vitest";

const authMock = vi.hoisted(() => ({
  useMsal: false,
  getApiAccessToken: vi.fn().mockResolvedValue(null),
}));

vi.mock("../auth/msal", () => ({
  SessionExpiredError: class SessionExpiredError extends Error {},
  devLoginEnabled: true,
  getActiveMsalAccount: () => authMock.useMsal ? {} : null,
  getApiAccessToken: authMock.getApiAccessToken,
  logoutFromMicrosoft: vi.fn().mockResolvedValue(undefined),
}));

import {
  deleteInventoryCategoryImage,
  deleteInventoryItemPhoto,
  getInventoryCategoryImageBlob,
  getInventoryItemDocumentBlob,
  getInventoryItemPhotoBlob,
  listInventoryCategoryDetails,
  listInventoryItemDocuments,
  deleteInventoryItemDocument,
  setDevUser,
  uploadInventoryCategoryImage,
  uploadInventoryItemDocument,
  uploadInventoryItemPhoto,
} from "./client";

const fetchMock = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  authMock.useMsal = false;
  authMock.getApiAccessToken.mockResolvedValue(null);
  setDevUser("inventory.manager@example.invalid");
  vi.stubGlobal("fetch", fetchMock);
});

describe("API de imagens de inventário", () => {
  it("carrega os detalhes das categorias com autenticação de sessão", async () => {
    const payload = [{ name: "Inversores", has_custom_image: true, image_version: "2026-10-22T12:00:00Z" }];
    fetchMock.mockResolvedValue(new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } }));
    await expect(listInventoryCategoryDetails()).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/inventory/categories/details", expect.objectContaining({
      headers: expect.objectContaining({ "X-Dev-User-Email": "inventory.manager@example.invalid" }),
    }));
  });

  it("pede blobs autenticados sem cache e inclui a versão da imagem de categoria", async () => {
    fetchMock.mockResolvedValue(new Response(new Blob(["image"], { type: "image/png" }), { status: 200 }));
    await getInventoryCategoryImageBlob("Inversores", "version 2");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/inventory/categories/Inversores/image?version=version%202");
    expect((init.headers as Record<string, string>)["X-Dev-User-Email"]).toBe("inventory.manager@example.invalid");
    expect(init.cache).toBe("no-store");
  });

  it("envia e remove fotografias autenticadas sem fixar manualmente multipart Content-Type", async () => {
    fetchMock
      .mockResolvedValueOnce(new Response(JSON.stringify({ has_photo: true, content_type: "image/jpeg" }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(new Blob(["image"], { type: "image/jpeg" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ name: "Inversores", has_custom_image: true, image_version: "v1", content_type: "image/png" }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    const itemFile = new File(["item"], "item.jpg", { type: "image/jpeg" });
    const categoryFile = new File(["category"], "category.png", { type: "image/png" });

    await uploadInventoryItemPhoto("item-1", itemFile);
    await deleteInventoryItemPhoto("item-1");
    await getInventoryItemPhotoBlob("item-1");
    await uploadInventoryCategoryImage("Inversores", categoryFile);
    await deleteInventoryCategoryImage("Inversores");

    const [itemUrl, itemUpload] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(itemUrl).toContain("/api/inventory/items/item-1/photo");
    expect(itemUpload.method).toBe("POST");
    expect((itemUpload.body as FormData).get("file")).toBe(itemFile);
    expect((itemUpload.headers as Record<string, string>)["X-Dev-User-Email"]).toBe("inventory.manager@example.invalid");
    expect((itemUpload.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      expect.stringContaining("/api/inventory/items/item-1/photo"),
      expect.stringContaining("/api/inventory/items/item-1/photo"),
      expect.stringContaining("/api/inventory/items/item-1/photo"),
      expect.stringContaining("/api/inventory/categories/Inversores/image"),
      expect.stringContaining("/api/inventory/categories/Inversores/image"),
    ]);
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: "DELETE" });
    expect(fetchMock.mock.calls[3][1]).toMatchObject({ method: "POST" });
    expect(fetchMock.mock.calls[4][1]).toMatchObject({ method: "DELETE" });
  });

  it("lista documentos do artigo com o identificador codificado e a autenticação de sessão", async () => {
    const payload = [{
      id: "doc-1", item_id: "item/ 1", kind: "datasheet", title: "Ficha técnica",
      filename: "ficha.pdf", content_type: "application/pdf", size: 123,
      created_by_person_id: "person-1", created_at: "2026-10-22T12:00:00Z",
    }];
    fetchMock.mockResolvedValue(new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } }));

    await expect(listInventoryItemDocuments("item/ 1")).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/inventory/items/item%2F%201/documents",
      expect.objectContaining({ headers: expect.objectContaining({ "X-Dev-User-Email": "inventory.manager@example.invalid" }) }),
    );
  });

  it("obtém o documento como blob por fetch autenticado, sem abrir um link direto", async () => {
    // Corpo em texto: o `Response` do Node (undici) não reconhece o `Blob` do
    // jsdom e, no Node 22, serializa-o como "[object Blob]".
    fetchMock.mockResolvedValue(
      new Response("pdf", { status: 200, headers: { "Content-Type": "application/pdf" } }),
    );

    const blob = await getInventoryItemDocumentBlob("item-1", "doc-2");

    // Sem `toBeInstanceOf(Blob)` nem `blob.text()`: conforme a versão do Node,
    // o Blob vem do realm do Node ou do jsdom (este último sem `text()`).
    expect(blob.type).toBe("application/pdf");
    expect(blob.size).toBe(3);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/inventory/items/item-1/documents/doc-2/download",
      expect.objectContaining({
        headers: expect.objectContaining({ "X-Dev-User-Email": "inventory.manager@example.invalid" }),
        cache: "no-store",
      }),
    );
  });

  it("usa Bearer token MSAL no download autenticado de documentos", async () => {
    authMock.useMsal = true;
    authMock.getApiAccessToken.mockResolvedValue("access-token-123");
    fetchMock.mockResolvedValue(new Response(new Blob(["pdf"], { type: "application/pdf" }), { status: 200 }));

    await getInventoryItemDocumentBlob("item-1", "doc-4");

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer access-token-123");
    expect((init.headers as Record<string, string>)["X-Dev-User-Email"]).toBeUndefined();
  });

  it("envia upload multipart tipado e remoção autenticada sem fixar Content-Type", async () => {
    const uploaded = {
      id: "doc-3", item_id: "item-1", kind: "manual", title: "Manual",
      filename: "manual.pdf", content_type: "application/pdf", size: 8,
      created_by_person_id: "person-1", created_at: "2026-10-22T12:00:00Z",
    };
    fetchMock
      .mockResolvedValueOnce(new Response(JSON.stringify(uploaded), { status: 201, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    const file = new File(["%PDF-1.7"], "manual.pdf", { type: "application/pdf" });

    await expect(uploadInventoryItemDocument("item-1", "manual", "Manual", file)).resolves.toEqual(uploaded);
    await deleteInventoryItemDocument("item-1", "doc-3");

    const [uploadUrl, uploadInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    const form = uploadInit.body as FormData;
    expect(uploadUrl).toContain("/api/inventory/items/item-1/documents");
    expect(form.get("kind")).toBe("manual");
    expect(form.get("title")).toBe("Manual");
    expect(form.get("file")).toBe(file);
    expect((uploadInit.headers as Record<string, string>)["X-Dev-User-Email"]).toBe("inventory.manager@example.invalid");
    expect((uploadInit.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
    expect(fetchMock.mock.calls[1][0]).toContain("/api/inventory/items/item-1/documents/doc-3");
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: "DELETE" });
  });
});
