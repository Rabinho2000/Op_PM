import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import ProjectPrimaryPhoto from "./ProjectPrimaryPhoto";

const api = vi.hoisted(() => ({
  getProjectPhotoBlob: vi.fn(),
  uploadProjectPhoto: vi.fn(),
  deleteProjectPhoto: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, ...api };
});

describe("ProjectPrimaryPhoto", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getProjectPhotoBlob.mockResolvedValue(new Blob(["photo"], { type: "image/png" }));
    api.uploadProjectPhoto.mockResolvedValue({ has_project_photo: true, content_type: "image/jpeg" });
    api.deleteProjectPhoto.mockResolvedValue(undefined);
  });

  it("shows upload and remove controls only when server grants photo-edit permission", async () => {
    const { rerender } = render(
      <ProjectPrimaryPhoto projectId="proj-1" hasPhoto canEdit={false} />,
    );
    await screen.findByRole("img", { name: "Fotografia principal da instalação" });
    expect(screen.queryByRole("button", { name: "Substituir fotografia" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remover fotografia" })).not.toBeInTheDocument();

    rerender(<ProjectPrimaryPhoto projectId="proj-1" hasPhoto={false} canEdit />);
    expect(await screen.findByRole("button", { name: "Carregar fotografia" })).toBeInTheDocument();
  });

  it("previews selected images and displays upload errors", async () => {
    api.uploadProjectPhoto.mockRejectedValue(new ApiError(400, "Formato inválido. Utilize JPEG, PNG ou WebP."));
    const { unmount } = render(<ProjectPrimaryPhoto projectId="proj-1" hasPhoto={false} canEdit />);
    fireEvent.change(screen.getByLabelText("Selecionar fotografia"), {
      target: { files: [new File(["image"], "obra.jpg", { type: "image/jpeg" })] },
    });
    expect(await screen.findByRole("img", { name: "Pré-visualização da fotografia principal" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Guardar fotografia" }));
    expect(await screen.findByText("Formato inválido. Utilize JPEG, PNG ou WebP.")).toBeInTheDocument();
    unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:photo-1");
  });

  it("revokes the authenticated photo blob URL when unmounted", async () => {
    const { unmount } = render(<ProjectPrimaryPhoto projectId="proj-1" hasPhoto canEdit={false} />);
    await screen.findByRole("img", { name: "Fotografia principal da instalação" });
    unmount();
    await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:photo-1"));
  });
});

beforeEach(() => {
  let next = 0;
  vi.spyOn(URL, "createObjectURL").mockImplementation(() => `blob:photo-${++next}`);
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
});
