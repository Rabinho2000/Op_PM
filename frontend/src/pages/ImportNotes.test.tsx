// Upload e preview de notas iniciais: pré-visualização, conflitos,
// confirmação bloqueada até resolver tudo.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { FieldImportBatch } from "../api/client";
import { makeMe } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import ImportNotes from "./ImportNotes";

const api = vi.hoisted(() => ({
  previewNotesImport: vi.fn(),
  getImportBatch: vi.fn(),
  resolveImportConflict: vi.fn(),
  applyNotesImport: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, ...api };
});

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, useNavigate: () => vi.fn() };
});

function batch(overrides: Partial<FieldImportBatch> = {}): FieldImportBatch {
  return {
    id: "batch-1",
    source_type: "notes_json",
    source_filename: "notas-teste.json",
    form_version: "12",
    status: "pending_confirmation",
    started_by_person_id: "p-comercial",
    started_at: "2026-09-17T10:00:00Z",
    applied_by_person_id: null,
    applied_at: null,
    records: [
      {
        id: "record-1",
        target_project_id: null,
        is_new_project: true,
        match_strategy: "none",
        status: "pending",
        promoted_project_id: null,
        candidate_projects: [],
        mapped_fields: {
          project: { client_name: "Cliente Sintético de Teste" },
          installation: { panel_count: 18 },
        },
        conflicts: [],
      },
    ],
    ...overrides,
  };
}

function makeFile(): File {
  return new File([JSON.stringify({ cliente: "x" })], "notas.json", { type: "application/json" });
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
});

describe("Importar notas iniciais", () => {
  it("mostra a pré-visualização depois de escolher um ficheiro", async () => {
    api.previewNotesImport.mockResolvedValue(batch());
    renderWithProviders(<ImportNotes />, { me: makeMe({ permissions: ["import.notes"] }) });

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [makeFile()] } });

    expect(await screen.findByText("Cliente Sintético de Teste")).toBeInTheDocument();
    expect(screen.getByText(/será criado um novo projeto/i)).toBeInTheDocument();
  });

  it("bloqueia a confirmação enquanto há conflitos por resolver", async () => {
    api.previewNotesImport.mockResolvedValue(
      batch({
        records: [
          {
            ...batch().records[0],
            is_new_project: false,
            target_project_id: "proj-1",
            match_strategy: "email",
            conflicts: [
              {
                id: "conflict-1",
                target_entity: "project",
                field_name: "power_kwp",
                old_value: "1.0",
                new_value: "8.28",
                resolution: "pending",
                resolved_by_person_id: null,
                resolved_at: null,
              },
            ],
          },
        ],
      })
    );
    renderWithProviders(<ImportNotes />, { me: makeMe({ permissions: ["import.notes"] }) });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [makeFile()] } });

    await screen.findByText("Potência (kWp)");
    const confirmButton = screen.getByRole("button", { name: /confirmar e importar/i });
    expect(confirmButton).toBeDisabled();
  });

  it("permite confirmar depois de resolver todos os conflitos", async () => {
    const withConflict = batch({
      records: [
        {
          ...batch().records[0],
          is_new_project: false,
          target_project_id: "proj-1",
          match_strategy: "email",
          conflicts: [
            {
              id: "conflict-1",
              target_entity: "project",
              field_name: "power_kwp",
              old_value: "1.0",
              new_value: "8.28",
              resolution: "pending",
              resolved_by_person_id: null,
              resolved_at: null,
            },
          ],
        },
      ],
    });
    const resolved = {
      ...withConflict,
      records: [{ ...withConflict.records[0], conflicts: [{ ...withConflict.records[0].conflicts[0], resolution: "use_new" as const }] }],
    };
    api.previewNotesImport.mockResolvedValue(withConflict);
    api.getImportBatch.mockResolvedValue(resolved);
    api.resolveImportConflict.mockResolvedValue(resolved.records[0].conflicts[0]);
    api.applyNotesImport.mockResolvedValue({ project_id: "proj-1", project_name: "X", created_new_project: false });

    renderWithProviders(<ImportNotes />, { me: makeMe({ permissions: ["import.notes"] }) });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [makeFile()] } });

    await screen.findByText("Potência (kWp)");
    fireEvent.click(screen.getByRole("button", { name: /usar novo/i }));

    await waitFor(() => expect(screen.getByRole("button", { name: /confirmar e importar/i })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: /confirmar e importar/i }));

    await waitFor(() => expect(api.applyNotesImport).toHaveBeenCalledWith("batch-1"));
  });
});
