import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { makeProject } from "../test/fixtures";
import { ToastProvider } from "./Toast";
import PmInlineSelect from "./PmInlineSelect";

const { updateProject } = vi.hoisted(() => ({ updateProject: vi.fn() }));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, updateProject };
});

const PEOPLE = [
  { id: "p-pm-a", display_name: "PM A", email: null, is_active: true },
  { id: "p-pm-b", display_name: "PM B", email: null, is_active: true },
];

describe("PmInlineSelect", () => {
  beforeEach(() => {
    updateProject.mockReset();
  });

  it("mostra só o nome, sem controlo, quando o servidor não autoriza editar pm_person_id", () => {
    const project = makeProject({ editable_fields: [], pm_display_name: "Alguém", pm_person_id: "p-x" });
    render(
      <ToastProvider>
        <PmInlineSelect project={project} people={PEOPLE} onChanged={() => undefined} />
      </ToastProvider>
    );
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.getByText("Alguém")).toBeInTheDocument();
  });

  it("mostra um dropdown quando o servidor autoriza editar pm_person_id e grava ao escolher", async () => {
    const project = makeProject({ editable_fields: ["pm_person_id"], pm_display_name: null, pm_person_id: null });
    const updated = { ...project, pm_person_id: "p-pm-a", pm_display_name: "PM A" };
    updateProject.mockResolvedValue(updated);
    const onChanged = vi.fn();

    render(
      <ToastProvider>
        <PmInlineSelect project={project} people={PEOPLE} onChanged={onChanged} />
      </ToastProvider>
    );

    const select = screen.getByRole("combobox");
    fireEvent.change(select, { target: { value: "p-pm-a" } });

    await waitFor(() => expect(updateProject).toHaveBeenCalledWith(project.id, { pm_person_id: "p-pm-a" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalledWith(updated));
  });

  it("lista PM A e PM B como opções escolhíveis", () => {
    const project = makeProject({ editable_fields: ["pm_person_id"], pm_person_id: null, pm_display_name: null });
    render(
      <ToastProvider>
        <PmInlineSelect project={project} people={PEOPLE} onChanged={() => undefined} />
      </ToastProvider>
    );
    expect(screen.getByRole("option", { name: "PM A" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "PM B" })).toBeInTheDocument();
  });
});
