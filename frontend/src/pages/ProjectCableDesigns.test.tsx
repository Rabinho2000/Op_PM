import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import type { CableDesign, CableDesignListItem, CableTool } from "../api/cableDesigns";
import { makeMe } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import ProjectCableDesigns from "../components/ProjectCableDesigns";

const api = vi.hoisted(() => ({
  listCableDesigns: vi.fn(),
  createCableDesign: vi.fn(),
  getCableTool: vi.fn(),
  deactivateCableDesign: vi.fn(),
}));

vi.mock("../api/cableDesigns", async () => {
  const actual = await vi.importActual<typeof import("../api/cableDesigns")>("../api/cableDesigns");
  return { ...actual, ...api };
});

const item: CableDesignListItem = {
  id: "design-1",
  project_id: "project-1",
  title: "Estudo do Projeto A",
  status: "rascunho",
  current_revision: "A",
  version: 2,
  updated_at: "2026-10-19T09:00:00Z",
  unresolved_circuits: 1,
};

const createdDesign: CableDesign = {
  ...item,
  is_active: true,
  created_by_person_id: "person-1",
  created_at: "2026-10-19T09:00:00Z",
  revision: {
    id: "revision-1",
    design_id: "design-1",
    rev: "A",
    input_json: { format: 1 },
    result_json: { format: 1, circuits: [] },
    engine_version: "cabos-1",
    content_sha256: "hash",
    unresolved_circuits: 1,
    status: "rascunho",
    approved_by_person_id: null,
    approved_at: null,
    created_by_person_id: "person-1",
    created_at: "2026-10-19T09:00:00Z",
    updated_at: "2026-10-19T09:00:00Z",
  },
};

const tool: CableTool = { engine_version: "cabos-1", sha256: "tool-hash", script: "" };

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.listCableDesigns.mockResolvedValue([item]);
  api.createCableDesign.mockResolvedValue(createdDesign);
  api.getCableTool.mockResolvedValue(tool);
  api.deactivateCableDesign.mockResolvedValue(undefined);
});

describe("ProjectCableDesigns", () => {
  it("mostra a tabela e o estado vazio", async () => {
    const view = renderWithProviders(<ProjectCableDesigns projectId="project-1" />, { me: makeMe({ permissions: ["cable_design.view"] }) });
    expect(await screen.findByText("Estudo do Projeto A")).toBeInTheDocument();
    expect(screen.getByText("Rascunho")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();

    api.listCableDesigns.mockResolvedValue([]);
    view.unmount();
    renderWithProviders(<ProjectCableDesigns projectId="project-1" />, { me: makeMe({ permissions: ["cable_design.view"] }) });
    await waitFor(() => expect(screen.getByText(/ainda não há estudos de cabos/i)).toBeInTheDocument());
  });

  it("cria com a versão da ferramenta quando tem view_costs", async () => {
    renderWithProviders(<ProjectCableDesigns projectId="project-1" />, {
      me: makeMe({ permissions: ["cable_design.view", "cable_design.edit", "cable_design.view_costs"] }),
    });
    await screen.findByText("Estudo do Projeto A");
    fireEvent.click(screen.getByRole("button", { name: /novo estudo/i }));
    fireEvent.change(screen.getByLabelText(/título/i), { target: { value: "Novo estudo A" } });
    fireEvent.click(screen.getByRole("button", { name: /^criar estudo$/i }));

    await waitFor(() => expect(api.createCableDesign).toHaveBeenCalledWith("project-1", {
      title: "Novo estudo A",
      engine_version: "cabos-1",
    }));
  });

  it("cria sem acesso a custos usando n/a", async () => {
    renderWithProviders(<ProjectCableDesigns projectId="project-1" />, {
      me: makeMe({ permissions: ["cable_design.view", "cable_design.edit"] }),
    });
    await screen.findByText("Estudo do Projeto A");
    fireEvent.click(screen.getByRole("button", { name: /novo estudo/i }));
    fireEvent.change(screen.getByLabelText(/título/i), { target: { value: "Novo estudo sem ferramenta" } });
    fireEvent.click(screen.getByRole("button", { name: /^criar estudo$/i }));

    await waitFor(() => expect(api.createCableDesign).toHaveBeenCalledWith("project-1", {
      title: "Novo estudo sem ferramenta",
      engine_version: "n/a",
    }));
    expect(api.getCableTool).not.toHaveBeenCalled();
  });

  it("não mostra ações de escrita sem edit e desativa com confirmação", async () => {
    renderWithProviders(<ProjectCableDesigns projectId="project-1" />, {
      me: makeMe({ permissions: ["cable_design.view"] }),
    });
    await screen.findByText("Estudo do Projeto A");
    expect(screen.queryByRole("button", { name: /novo estudo/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /desativar/i })).not.toBeInTheDocument();

    // A separate editable render exercises the destructive confirmation.
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderWithProviders(<ProjectCableDesigns projectId="project-1" />, {
      me: makeMe({ permissions: ["cable_design.view", "cable_design.edit"] }),
    });
    const deactivate = await screen.findByRole("button", { name: /desativar estudo do projeto a/i });
    fireEvent.click(deactivate);
    await waitFor(() => expect(api.deactivateCableDesign).toHaveBeenCalledWith("design-1", 2));
    vi.restoreAllMocks();
  });

  it("mostra erro claro quando o âmbito devolve 404", async () => {
    api.listCableDesigns.mockRejectedValue(new ApiError(404, "Projeto ou estudos fora do âmbito."));
    renderWithProviders(<ProjectCableDesigns projectId="project-1" />, { me: makeMe({ permissions: ["cable_design.view"] }) });
    expect(await screen.findByText(/não estão no seu âmbito/i)).toBeInTheDocument();
  });
});
