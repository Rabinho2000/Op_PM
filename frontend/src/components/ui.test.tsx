import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StrictMode, useState } from "react";
import { describe, expect, it } from "vitest";
import { Modal } from "./ui";

function SiblingModalHarness() {
  const [firstOpen, setFirstOpen] = useState(false);
  const [secondOpen, setSecondOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setFirstOpen(true)}>
        Abrir primeiro
      </button>
      <button type="button" onClick={() => setSecondOpen(true)}>
        Abrir segundo
      </button>
      {firstOpen && (
        <Modal title="Primeiro" onClose={() => setFirstOpen(false)}>
          <button type="button">Controlo primeiro</button>
        </Modal>
      )}
      {secondOpen && (
        <Modal title="Segundo" onClose={() => setSecondOpen(false)}>
          <button type="button">Controlo segundo</button>
        </Modal>
      )}
    </>
  );
}

describe("Modal", () => {
  it("fecha apenas o modal irmão superior e limpa listeners sob StrictMode", async () => {
    const view = render(
      <StrictMode>
        <SiblingModalHarness />
      </StrictMode>
    );

    fireEvent.click(screen.getByRole("button", { name: "Abrir primeiro" }));
    fireEvent.click(screen.getByRole("button", { name: "Abrir segundo" }));
    expect(screen.getAllByRole("dialog")).toHaveLength(2);

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.getByRole("dialog", { name: "Primeiro" })).toBeInTheDocument());
    expect(screen.queryByRole("dialog", { name: "Segundo" })).not.toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Primeiro" })).not.toBeInTheDocument());

    // Mount/unmount again after StrictMode's setup/cleanup cycle: a stale
    // document listener must not close a later sibling twice.
    fireEvent.click(screen.getByRole("button", { name: "Abrir primeiro" }));
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Primeiro" })).not.toBeInTheDocument());
    view.unmount();
  });
});