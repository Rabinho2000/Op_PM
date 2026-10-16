import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { LifecycleStatus } from "../api/client";
import LifecycleMultiSelect from "./LifecycleMultiSelect";

const STATUSES: LifecycleStatus[] = [
  { code: "preparacao", label: "Preparação", flow_position: 1 },
  { code: "construcao", label: "Construção", flow_position: 2 },
];

function renderFilter(onChange = vi.fn()) {
  return {
    onChange,
    ...render(<LifecycleMultiSelect id="lifecycle" label="Estado da obra" value={[]} onChange={onChange} statuses={STATUSES} />),
  };
}

describe("LifecycleMultiSelect", () => {
  it("fecha ao clicar fora e devolve o foco ao botão", () => {
    renderFilter();
    const trigger = screen.getByRole("button", { name: "Todos" });
    fireEvent.click(trigger);
    expect(screen.getByRole("group", { name: "Estado da obra" })).toBeInTheDocument();

    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("group", { name: "Estado da obra" })).not.toBeInTheDocument();
    expect(document.activeElement).toBe(trigger);
  });

  it("fecha com Escape e não deixa listeners duplicados após rerender", () => {
    const { onChange, rerender } = renderFilter();
    const trigger = screen.getByRole("button", { name: "Todos" });
    fireEvent.click(trigger);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("group", { name: "Estado da obra" })).not.toBeInTheDocument();
    expect(document.activeElement).toBe(trigger);

    rerender(<LifecycleMultiSelect id="lifecycle" label="Estado da obra" value={[]} onChange={onChange} statuses={STATUSES} />);
    fireEvent.click(screen.getByRole("button", { name: "Todos" }));
    fireEvent.click(screen.getByLabelText("Construção"));
    expect(onChange).toHaveBeenCalledTimes(1);
  });
});
