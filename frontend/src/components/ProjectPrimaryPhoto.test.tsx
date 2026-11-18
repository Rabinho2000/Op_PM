import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
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
    const hero = await screen.findByRole("region", { name: "Cabeçalho do projeto" });
    expect(hero).toHaveStyle({ backgroundImage: 'url("blob:photo-1")' });
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
    expect(await screen.findByText("Pré-visualização — por guardar")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Guardar fotografia" }));
    expect(await screen.findByText("Formato inválido. Utilize JPEG, PNG ou WebP.")).toBeInTheDocument();
    unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:photo-1");
  });

  it("revokes the authenticated photo blob URL when unmounted", async () => {
    const { unmount } = render(<ProjectPrimaryPhoto projectId="proj-1" hasPhoto canEdit={false} />);
    await screen.findByRole("region", { name: "Cabeçalho do projeto" });
    unmount();
    await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:photo-1"));
  });

  it("renders the photo as a header background and labels an unsaved preview", async () => {
    render(
      <ProjectPrimaryPhoto projectId="proj-1" hasPhoto canEdit>
        <h1>Projeto Solar</h1>
      </ProjectPrimaryPhoto>,
    );

    const hero = await screen.findByRole("region", { name: "Cabeçalho do projeto" });
    expect(hero).toHaveClass("project-primary-photo");
    expect(screen.getByRole("heading", { name: "Projeto Solar" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Selecionar fotografia"), {
      target: { files: [new File(["image"], "nova.jpg", { type: "image/jpeg" })] },
    });
    expect(await screen.findByText("Pré-visualização — por guardar")).toBeInTheDocument();
  });

  it("does not apply a late photo response after changing projects", async () => {
    let resolvePhoto!: (blob: Blob) => void;
    api.getProjectPhotoBlob.mockReturnValueOnce(new Promise<Blob>((resolve) => { resolvePhoto = resolve; }));
    const { rerender } = render(<ProjectPrimaryPhoto projectId="proj-1" hasPhoto canEdit={false} />);

    rerender(<ProjectPrimaryPhoto projectId="proj-2" hasPhoto={false} canEdit={false} />);
    resolvePhoto(new Blob(["old photo"], { type: "image/png" }));
    await waitFor(() => expect(screen.queryByRole("img")).not.toBeInTheDocument());
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it.each([
    ["success", (resolve: (blob: Blob) => void) => resolve(new Blob(["old photo"], { type: "image/png" }))],
    ["failure", (_resolve: (blob: Blob) => void, reject: (error: Error) => void) => reject(new Error("old project failed"))],
  ])("does not leak a late GET %s after changing projects", async (_label, settle) => {
    let resolvePhoto!: (blob: Blob) => void;
    let rejectPhoto!: (error: Error) => void;
    api.getProjectPhotoBlob.mockReturnValueOnce(new Promise<Blob>((resolve, reject) => {
      resolvePhoto = resolve;
      rejectPhoto = reject;
    }));
    const { rerender } = render(<ProjectPrimaryPhoto projectId="proj-1" hasPhoto canEdit={false} />);

    rerender(<ProjectPrimaryPhoto projectId="proj-2" hasPhoto={false} canEdit />);
    settle(resolvePhoto, rejectPhoto);
    await waitFor(() => expect(screen.getByRole("button", { name: "Carregar fotografia" })).toBeEnabled());
    expect(screen.queryByText("old project failed")).not.toBeInTheDocument();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it.each(["success", "failure"])("does not leak a late upload %s after changing projects", async (outcome) => {
    let settleUpload!: (value?: unknown) => void;
    let rejectUpload!: (error: Error) => void;
    api.uploadProjectPhoto.mockReturnValueOnce(new Promise((resolve, reject) => {
      settleUpload = resolve;
      rejectUpload = reject;
    }));
    const onPhotoChanged = vi.fn();
    const { rerender } = render(<ProjectPrimaryPhoto projectId="proj-1" hasPhoto={false} canEdit onPhotoChanged={onPhotoChanged} />);
    fireEvent.change(screen.getByLabelText("Selecionar fotografia"), {
      target: { files: [new File(["image"], "obra.jpg", { type: "image/jpeg" })] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Guardar fotografia" }));
    rerender(<ProjectPrimaryPhoto projectId="proj-2" hasPhoto={false} canEdit />);
    if (outcome === "success") settleUpload();
    else rejectUpload(new Error("old upload failed"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Carregar fotografia" })).toBeEnabled());
    expect(screen.queryByText("old upload failed")).not.toBeInTheDocument();
    expect(onPhotoChanged).not.toHaveBeenCalled();
  });

  it.each(["success", "failure"])("does not leak a late delete %s after changing projects", async (outcome) => {
    let settleDelete!: (value?: unknown) => void;
    let rejectDelete!: (error: Error) => void;
    api.deleteProjectPhoto.mockReturnValueOnce(new Promise((resolve, reject) => {
      settleDelete = resolve;
      rejectDelete = reject;
    }));
    const onPhotoChanged = vi.fn();
    const { rerender } = render(<ProjectPrimaryPhoto projectId="proj-1" hasPhoto canEdit onPhotoChanged={onPhotoChanged} />);
    fireEvent.click(await screen.findByRole("button", { name: "Remover fotografia" }));
    rerender(<ProjectPrimaryPhoto projectId="proj-2" hasPhoto={false} canEdit />);
    if (outcome === "success") settleDelete();
    else rejectDelete(new Error("old delete failed"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Carregar fotografia" })).toBeEnabled());
    expect(screen.queryByText("old delete failed")).not.toBeInTheDocument();
    expect(onPhotoChanged).not.toHaveBeenCalled();
  });

  it.each(["upload", "delete"])("does not leak a late %s after keyed unmount and remount", async (operation) => {
    let settle!: (value?: unknown) => void;
    let reject!: (error: Error) => void;
    const pending = new Promise((resolve, rejectPromise) => {
      settle = resolve;
      reject = rejectPromise;
    });
    if (operation === "upload") api.uploadProjectPhoto.mockReturnValueOnce(pending);
    else api.deleteProjectPhoto.mockReturnValueOnce(pending);

    const bState = { hasPhoto: operation === "delete" };
    const onPhotoChanged = vi.fn((hasPhoto: boolean) => {
      bState.hasPhoto = hasPhoto;
    });
    const currentProject = { id: "project-a", hasPhoto: operation === "delete" };
    const first = render(
      <ProjectPrimaryPhoto
        key={currentProject.id}
        projectId={currentProject.id}
        hasPhoto={currentProject.hasPhoto}
        canEdit
        onPhotoChanged={onPhotoChanged}
      />,
    );
    if (operation === "upload") {
      fireEvent.change(screen.getByLabelText("Selecionar fotografia"), {
        target: { files: [new File(["image"], "obra.jpg", { type: "image/jpeg" })] },
      });
      fireEvent.click(screen.getByRole("button", { name: "Guardar fotografia" }));
    } else {
      fireEvent.click(await screen.findByRole("button", { name: "Remover fotografia" }));
    }

    first.unmount();
    const second = render(
      <ProjectPrimaryPhoto key="project-b" projectId="project-b" hasPhoto={bState.hasPhoto} canEdit />,
    );
    operation === "upload" ? settle() : reject(new Error("old project failed"));
    await waitFor(() => expect(screen.getByRole("button", {
      name: bState.hasPhoto ? "Substituir fotografia" : "Carregar fotografia",
    })).toBeEnabled());
    expect(onPhotoChanged).not.toHaveBeenCalled();
    expect(bState.hasPhoto).toBe(operation === "delete");
    expect(screen.queryByText("old project failed")).not.toBeInTheDocument();
    second.unmount();
  });

  it("keeps photo text readable over a white photo and removes the photo from print", () => {
    const appCss = readFileSync("src/styles/app.css", "utf8");
    const detailCss = readFileSync("src/pages/ProjectDetail.css", "utf8");
    const alpha = [...appCss.matchAll(/--photo-scrim:\s*rgba\(0,\s*0,\s*0,\s*([\d.]+)\)/g)].map((match) => Number(match[1]));

    expect(alpha).toHaveLength(2);
    expect(Math.min(...alpha), "solid photo scrim over a white photo").toBeGreaterThanOrEqual(0.82);
    const worstCaseScrimmedWhite = 1 - Math.min(...alpha);
    expect(1.05 / (worstCaseScrimmedWhite + 0.05), "white photo with white photo text").toBeGreaterThanOrEqual(4.5);
    expect(appCss).toMatch(/--on-photo:\s*#ffffff/);
    expect(detailCss).toMatch(/\.project-primary-photo--has-image \.project-primary-photo__overlay\s*\{\s*background:\s*var\(--photo-scrim\);/);
    expect(detailCss).toMatch(/@media print[\s\S]*\.project-primary-photo--has-image\s*\{[\s\S]*background-image:\s*none\s*!important;/);
    expect(detailCss).toMatch(/@media print[\s\S]*\.project-primary-photo--has-image \.project-primary-photo__overlay\s*\{\s*background:\s*none;/);
  });
});

beforeEach(() => {
  let next = 0;
  vi.spyOn(URL, "createObjectURL").mockImplementation(() => `blob:photo-${++next}`);
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
});
