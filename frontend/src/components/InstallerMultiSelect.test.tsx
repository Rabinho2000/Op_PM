import { useState } from "react";
import { createEvent, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Installer } from "../api/client";
import InstallerMultiSelect from "./InstallerMultiSelect";

const installers: Installer[] = [
  { id: "i-a", name: "Instalador A", is_active: true, project_count: 0, teams: [] },
  { id: "i-b", name: "Instalador B", is_active: true, project_count: 0, teams: [] },
];

function ControlledInstallerMultiSelect() {
  const [value, setValue] = useState<string[]>([]);
  return (
    <InstallerMultiSelect
      id="installer-filter"
      label="Instalador"
      value={value}
      onChange={setValue}
      installers={installers}
    />
  );
}

describe("InstallerMultiSelect accessible name and keyboard behavior", () => {
  it("announces the selection and opens/closes with Enter/Escape restoring focus", () => {
    render(<ControlledInstallerMultiSelect />);
    const trigger = screen.getByRole("button", { name: "Instalador: Todos" });

    trigger.focus();
    fireEvent.keyDown(trigger, { key: "Enter" });
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    fireEvent.keyDown(trigger, { key: "Escape" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveFocus();

    fireEvent.keyDown(trigger, { key: " " });
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    fireEvent.keyDown(trigger, { key: " " });
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    fireEvent.keyDown(trigger, { key: "Enter" });
    fireEvent.click(screen.getByRole("checkbox", { name: "Instalador A" }));
    expect(screen.getByRole("button", { name: "Instalador: Instalador A" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox", { name: "Instalador B" }));
    expect(screen.getByRole("button", { name: "Instalador: 2 instaladores selecionados" })).toBeInTheDocument();
  });

  it("navigates options with arrows and selects with native Space before Escape restores focus", () => {
    render(<ControlledInstallerMultiSelect />);
    const trigger = screen.getByRole("button", { name: "Instalador: Todos" });

    trigger.focus();
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    const first = screen.getByRole("checkbox", { name: "Instalador A" });
    const second = screen.getByRole("checkbox", { name: "Instalador B" });
    expect(first).toHaveFocus();

    const firstSpace = createEvent.keyDown(first, { key: " ", code: "Space" });
    fireEvent(first, firstSpace);
    expect(firstSpace.defaultPrevented).toBe(false);
    // jsdom does not synthesize the browser's native Space activation.
    fireEvent.click(first);
    expect(first).toBeChecked();
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    fireEvent.keyDown(first, { key: "ArrowDown" });
    expect(second).toHaveFocus();
    const secondSpace = createEvent.keyDown(second, { key: " ", code: "Space" });
    fireEvent(second, secondSpace);
    expect(secondSpace.defaultPrevented).toBe(false);
    fireEvent.click(second);
    expect(second).toBeChecked();

    fireEvent.keyDown(second, { key: "Escape" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveFocus();
  });

  it("supports first/last option navigation and leaves empty lists and Tab untrapped", () => {
    const { rerender } = render(<InstallerMultiSelect
      id="installer-filter"
      label="Instalador"
      value={[]}
      onChange={() => undefined}
      installers={installers}
    />);
    const trigger = screen.getByRole("button", { name: "Instalador: Todos" });
    trigger.focus();
    fireEvent.keyDown(trigger, { key: "ArrowUp" });
    const second = screen.getByRole("checkbox", { name: "Instalador B" });
    expect(second).toHaveFocus();
    fireEvent.keyDown(second, { key: "Home" });
    expect(screen.getByRole("checkbox", { name: "Instalador A" })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("checkbox", { name: "Instalador A" }), { key: "End" });
    expect(second).toHaveFocus();
    const tab = createEvent.keyDown(second, { key: "Tab" });
    fireEvent(second, tab);
    expect(tab.defaultPrevented).toBe(false);

    rerender(<InstallerMultiSelect
      id="installer-filter"
      label="Instalador"
      value={[]}
      onChange={() => undefined}
      installers={[]}
    />);
    const emptyTrigger = screen.getByRole("button", { name: "Instalador: Todos" });
    emptyTrigger.focus();
    fireEvent.keyDown(emptyTrigger, { key: "ArrowDown" });
    expect(emptyTrigger).toHaveAttribute("aria-expanded", "true");
    expect(emptyTrigger).toHaveFocus();
    const emptyTab = createEvent.keyDown(emptyTrigger, { key: "Tab" });
    fireEvent(emptyTrigger, emptyTab);
    expect(emptyTab.defaultPrevented).toBe(false);
  });

  it("does not close or steal focus for Escape pressed outside the multi-select", () => {
    render(
      <>
        <ControlledInstallerMultiSelect />
        <button type="button">Outra ação</button>
      </>,
    );
    const trigger = screen.getByRole("button", { name: "Instalador: Todos" });
    fireEvent.keyDown(trigger, { key: "Enter" });
    const outside = screen.getByRole("button", { name: "Outra ação" });
    outside.focus();

    const escape = createEvent.keyDown(outside, { key: "Escape" });
    fireEvent(outside, escape);
    expect(escape.defaultPrevented).toBe(false);
    expect(outside).toHaveFocus();
    expect(trigger).toHaveAttribute("aria-expanded", "true");
  });
});
