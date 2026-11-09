import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { InventoryCategoryImage, InventoryItemPhoto } from "./InventoryVisuals";

const api = vi.hoisted(() => ({
  getInventoryCategoryImageBlob: vi.fn(),
  uploadInventoryCategoryImage: vi.fn(),
  deleteInventoryCategoryImage: vi.fn(),
  getInventoryItemPhotoBlob: vi.fn(),
  uploadInventoryItemPhoto: vi.fn(),
  deleteInventoryItemPhoto: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, ...api };
});

beforeEach(() => {
  vi.clearAllMocks();
  let next = 0;
  vi.spyOn(URL, "createObjectURL").mockImplementation(() => `blob:inventory-${++next}`);
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  api.getInventoryCategoryImageBlob.mockResolvedValue(new Blob(["category"], { type: "image/png" }));
  api.uploadInventoryCategoryImage.mockResolvedValue({ name: "Inversores", has_custom_image: true, image_version: "v2", content_type: "image/png" });
  api.deleteInventoryCategoryImage.mockResolvedValue(undefined);
  api.getInventoryItemPhotoBlob.mockResolvedValue(new Blob(["item"], { type: "image/jpeg" }));
  api.uploadInventoryItemPhoto.mockResolvedValue({ has_photo: true, content_type: "image/jpeg" });
  api.deleteInventoryItemPhoto.mockResolvedValue(undefined);
});

describe("imagens do inventário", () => {
  it("só pede imagem de categoria quando has_custom_image é verdadeiro e revoga o blob ao desmontar", async () => {
    const { rerender, unmount } = render(
      <InventoryCategoryImage category="Inversores" hasCustomImage={false} imageVersion={null} accountKey="user-a" />,
    );
    expect(screen.getByTestId("category-illustration")).toBeInTheDocument();
    expect(api.getInventoryCategoryImageBlob).not.toHaveBeenCalled();

    rerender(<InventoryCategoryImage category="Inversores" hasCustomImage imageVersion="v1" accountKey="user-a" />);
    const image = await screen.findByRole("presentation");
    expect(api.getInventoryCategoryImageBlob).toHaveBeenCalledWith("Inversores", "v1");
    expect(image).toHaveAttribute("src", "blob:inventory-1");
    unmount();
    await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:inventory-1"));
  });

  it("não oferece gestão de imagem de categoria sem manage_catalog e permite preview, upload e remoção com permissão", async () => {
    const onImageChanged = vi.fn();
    const { rerender } = render(
      <InventoryCategoryImage category="Inversores" hasCustomImage={false} imageVersion={null} accountKey="user-a" canManage={false} />,
    );
    expect(screen.queryByRole("button", { name: /imagem de categoria/i })).not.toBeInTheDocument();

    rerender(
      <InventoryCategoryImage category="Inversores" hasCustomImage imageVersion="v1" accountKey="user-a" canManage onImageChanged={onImageChanged} />,
    );
    await screen.findByRole("presentation");
    fireEvent.change(screen.getByLabelText("Selecionar imagem de categoria"), {
      target: { files: [new File(["png"], "category.png", { type: "image/png" })] },
    });
    expect(await screen.findByRole("presentation")).toHaveAttribute("src", "blob:inventory-2");
    fireEvent.click(screen.getByRole("button", { name: "Guardar imagem de categoria" }));
    await waitFor(() => expect(api.uploadInventoryCategoryImage).toHaveBeenCalledWith("Inversores", expect.any(File)));
    expect(onImageChanged).toHaveBeenCalledWith({ name: "Inversores", has_custom_image: true, image_version: "v2", content_type: "image/png" });

    fireEvent.click(screen.getByRole("button", { name: "Remover imagem de categoria" }));
    await waitFor(() => expect(api.deleteInventoryCategoryImage).toHaveBeenCalledWith("Inversores"));
    expect(onImageChanged).toHaveBeenLastCalledWith({ name: "Inversores", has_custom_image: false, image_version: null });
  });

  it("só carrega fotografia se has_photo vier ativo e apresenta erro de upload", async () => {
    const { rerender } = render(
      <InventoryItemPhoto itemId="item-1" itemName="Módulo" category="Painéis" hasPhoto={false} canManage={false} accountKey="user-a" />,
    );
    expect(screen.getByTestId("category-illustration")).toBeInTheDocument();
    expect(api.getInventoryItemPhotoBlob).not.toHaveBeenCalled();

    api.uploadInventoryItemPhoto.mockRejectedValue(new ApiError(400, "Formato inválido. Utilize JPEG, PNG ou WebP."));
    rerender(<InventoryItemPhoto itemId="item-1" itemName="Módulo" category="Painéis" hasPhoto canManage accountKey="user-a" />);
    expect(await screen.findByRole("img", { name: "Fotografia de Módulo" })).toHaveAttribute("src", "blob:inventory-1");
    expect(api.getInventoryItemPhotoBlob).toHaveBeenCalledWith("item-1");
    fireEvent.change(screen.getByLabelText("Selecionar fotografia do artigo"), {
      target: { files: [new File(["img"], "item.jpg", { type: "image/jpeg" })] },
    });
    expect(await screen.findByRole("img", { name: "Pré-visualização da fotografia de Módulo" })).toHaveAttribute("src", "blob:inventory-2");
    fireEvent.click(screen.getByRole("button", { name: "Guardar fotografia" }));
    expect(await screen.findByText("Formato inválido. Utilize JPEG, PNG ou WebP.")).toBeInTheDocument();
  });

  it("remover fotografia volta à ilustração e revoga os URLs criados", async () => {
    const onPhotoChanged = vi.fn();
    const { unmount } = render(
      <InventoryItemPhoto itemId="item-2" itemName="Inversor" category="Inversores" hasPhoto canManage accountKey="user-b" onPhotoChanged={onPhotoChanged} />,
    );
    await screen.findByRole("img", { name: "Fotografia de Inversor" });
    fireEvent.click(screen.getByRole("button", { name: "Remover fotografia" }));
    await waitFor(() => expect(api.deleteInventoryItemPhoto).toHaveBeenCalledWith("item-2"));
    expect(onPhotoChanged).toHaveBeenCalledWith(false);
    expect(screen.getByTestId("category-illustration")).toBeInTheDocument();
    unmount();
    await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalled());
  });
});
