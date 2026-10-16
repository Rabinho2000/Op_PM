import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ProjectDetailOverlay from "./ProjectDetailOverlay";

vi.mock("../pages/ProjectDetail", async () => {
  const { useState } = await import("react");
  const { Modal } = await import("./ui");
  return {
    default: function MockProjectDetail() {
      const [editing, setEditing] = useState(false);
      return (
        <>
          <div>Detalhe carregado</div>
          <button type="button" onClick={() => setEditing(true)}>
            Editar projeto
          </button>
          {editing && (
            <Modal title="Editar projeto" onClose={() => setEditing(false)}>
              <button type="button">Campo editável</button>
            </Modal>
          )}
        </>
      );
    },
  };
});

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}{location.search}</output>;
}

describe("ProjectDetailOverlay", () => {
  beforeEach(() => {
    document.body.style.overflow = "";
  });

  it("fecha e regressa ao Works preservando filtros e janela", async () => {
    const refresh = vi.fn();
    window.addEventListener("op:works-project-refresh", refresh);
    render(
      <MemoryRouter
        initialEntries={[
          { pathname: "/works", search: "?zoom=month_days&pm=p-pm&estado=construcao&from=2026-10-01" },
          {
            pathname: "/projects/p-1",
            state: {
              backgroundLocation: {
                pathname: "/works",
                search: "?zoom=month_days&pm=p-pm&estado=construcao&from=2026-10-01",
              },
            },
          },
        ]}
        initialIndex={1}
      >
        <Routes>
          <Route path="/projects/:projectId" element={<ProjectDetailOverlay />} />
          <Route path="/works" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Detalhe carregado")).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");

    fireEvent.click(screen.getByRole("button", { name: "Fechar" }));
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/works?zoom=month_days&pm=p-pm&estado=construcao&from=2026-10-01"));
    expect(document.body.style.overflow).toBe("");
    expect(refresh).toHaveBeenCalledTimes(1);
    window.removeEventListener("op:works-project-refresh", refresh);
  });

  it("fecha só o editor aninhado com Escape e mantém o detalhe até ao segundo Escape", async () => {
    const refresh = vi.fn();
    window.addEventListener("op:works-project-refresh", refresh);
    render(
      <MemoryRouter
        initialEntries={[
          { pathname: "/works", search: "?zoom=month_days&pm=p-pm" },
          { pathname: "/projects/p-1", state: { backgroundLocation: { pathname: "/works", search: "?zoom=month_days&pm=p-pm" } } },
        ]}
        initialIndex={1}
      >
        <Routes>
          <Route path="/projects/:projectId" element={<ProjectDetailOverlay />} />
          <Route path="/works" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    );

    const editButton = screen.getByRole("button", { name: "Editar projeto" });
    editButton.focus();
    fireEvent.click(editButton);
    const editor = screen.getByRole("dialog", { name: "Editar projeto" });
    expect(editor).toBeInTheDocument();
    const editorClose = within(editor).getByRole("button", { name: "Fechar" });
    expect(editorClose).toHaveFocus();
    const field = within(editor).getByRole("button", { name: "Campo editável" });
    field.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(editorClose).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.getAllByRole("dialog")).toHaveLength(1));
    expect(screen.getByRole("dialog", { name: "Detalhe do projeto" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Editar projeto" })).toHaveFocus();
    expect(document.body.style.overflow).toBe("hidden");
    expect(refresh).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Editar projeto" }));
    const innerBackdrop = document.querySelectorAll(".modal-backdrop")[1];
    expect(innerBackdrop).toBeTruthy();
    fireEvent.mouseDown(innerBackdrop as HTMLElement);
    await waitFor(() => expect(screen.getAllByRole("dialog")).toHaveLength(1));
    expect(screen.getByRole("dialog", { name: "Detalhe do projeto" })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/works?zoom=month_days&pm=p-pm"));
    expect(screen.queryAllByRole("dialog")).toHaveLength(0);
    expect(document.body.style.overflow).toBe("");
    expect(refresh).toHaveBeenCalledTimes(1);
    window.removeEventListener("op:works-project-refresh", refresh);
  });
});
