import { beforeEach, describe, expect, it, vi } from "vitest";

const client = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
}));

vi.mock("./client", () => client);

import {
  approveCableDesign,
  createCableDesign,
  deactivateCableDesign,
  getCableDesign,
  getCableTool,
  listCableHistory,
  listCableRevisions,
  listCableDesigns,
  newCableRevision,
  saveCableRevision,
} from "./cableDesigns";
import type {
  CableDesign,
  CableDesignHistoryEntry,
  CableDesignListItem,
  CableDesignRevision,
  CableTool,
} from "./cableDesigns";

const designListItem: CableDesignListItem = {
  id: "design-1",
  project_id: "project-1",
  title: "Estudo do Projeto A",
  status: "rascunho",
  current_revision: "A",
  version: 1,
  updated_at: "2026-10-19T09:00:00Z",
  unresolved_circuits: 0,
};

const revision: CableDesignRevision = {
  id: "revision-1",
  design_id: "design-1",
  rev: "A",
  input_json: { format: 1, state: { circuits: [] } },
  result_json: { format: 1, circuits: [], totals: { circuits: 0, review: 0, inverters: 0 } },
  engine_version: "cabos-1",
  content_sha256: "abcdef1234567890",
  unresolved_circuits: 0,
  status: "rascunho",
  approved_by_person_id: null,
  approved_at: null,
  created_by_person_id: "person-1",
  created_at: "2026-10-19T09:00:00Z",
  updated_at: "2026-10-19T09:00:00Z",
};

const design: CableDesign = {
  ...designListItem,
  is_active: true,
  created_by_person_id: "person-1",
  created_at: "2026-10-19T09:00:00Z",
  revision,
};

const tool: CableTool = { engine_version: "cabos-1", sha256: "hash", script: "" };
const history: CableDesignHistoryEntry = {
  id: "history-1",
  design_id: "design-1",
  action: "created",
  actor_person_id: "person-1",
  rev: "A",
  old_value: null,
  new_value: { version: 1, title: "Estudo do Projeto A", status: "rascunho", rev: "A", hash: "hash", unresolved_circuits: 0 },
  created_at: "2026-10-19T09:00:00Z",
};

beforeEach(() => {
  Object.values(client).forEach((fn) => fn.mockReset());
});

describe("API de estudos de cabos", () => {
  it("usa os caminhos e corpos exatos do contrato", async () => {
    client.apiGet
      .mockResolvedValueOnce([designListItem])
      .mockResolvedValueOnce(design)
      .mockResolvedValueOnce([revision])
      .mockResolvedValueOnce([history])
      .mockResolvedValueOnce(tool);
    client.apiPost.mockResolvedValueOnce(design).mockResolvedValueOnce(design).mockResolvedValueOnce(design);
    client.apiPut.mockResolvedValue(design);
    client.apiDelete.mockResolvedValue(undefined);

    await expect(listCableDesigns("project-1")).resolves.toEqual([designListItem]);
    await expect(createCableDesign("project-1", { title: "Estudo do Projeto A", engine_version: "cabos-1" })).resolves.toBe(design);
    await expect(getCableDesign("design-1")).resolves.toBe(design);
    await expect(saveCableRevision("design-1", {
      expected_version: 1,
      title: "Estudo do Projeto A",
      input: { format: 1, state: { circuits: [] } },
      result: { format: 1, circuits: [], totals: { circuits: 0, review: 0, inverters: 0 } },
      engine_version: "cabos-1",
    })).resolves.toBe(design);
    await expect(approveCableDesign("design-1", 1)).resolves.toBe(design);
    await expect(newCableRevision("design-1", 2)).resolves.toBe(design);
    await expect(deactivateCableDesign("design-1", 3)).resolves.toBeUndefined();
    await expect(listCableRevisions("design-1")).resolves.toEqual([revision]);
    await expect(listCableHistory("design-1")).resolves.toEqual([history]);
    await expect(getCableTool()).resolves.toBe(tool);

    expect(client.apiGet).toHaveBeenNthCalledWith(1, "/api/projects/project-1/cable-designs");
    expect(client.apiPost).toHaveBeenNthCalledWith(1, "/api/projects/project-1/cable-designs", {
      title: "Estudo do Projeto A",
      engine_version: "cabos-1",
    });
    expect(client.apiGet).toHaveBeenNthCalledWith(2, "/api/cable-designs/design-1");
    expect(client.apiPut).toHaveBeenCalledWith("/api/cable-designs/design-1/revisions/current", expect.objectContaining({ expected_version: 1 }));
    expect(client.apiPost).toHaveBeenNthCalledWith(2, "/api/cable-designs/design-1/approve", { expected_version: 1 });
    expect(client.apiPost).toHaveBeenNthCalledWith(3, "/api/cable-designs/design-1/new-revision", { expected_version: 2 });
    expect(client.apiDelete).toHaveBeenCalledWith("/api/cable-designs/design-1?expected_version=3");
    expect(client.apiGet).toHaveBeenNthCalledWith(3, "/api/cable-designs/design-1/revisions");
    expect(client.apiGet).toHaveBeenNthCalledWith(4, "/api/cable-designs/design-1/history");
    expect(client.apiGet).toHaveBeenNthCalledWith(5, "/api/cable-tool");
  });
});
