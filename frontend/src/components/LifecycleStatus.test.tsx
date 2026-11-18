import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { makeProject } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import { LifecycleStatusControl } from "./LifecycleStatus";

const { changeProjectStatus } = vi.hoisted(() => ({ changeProjectStatus: vi.fn() }));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, changeProjectStatus };
});

const STATUSES = [
  { code: "on_hold_cliente", label: "On hold pelo cliente", flow_position: null },
  { code: "preparacao", label: "Preparação", flow_position: 1 },
  { code: "construcao", label: "Construção", flow_position: 2 },
  { code: "entregue_cliente", label: "Entregue ao cliente", flow_position: 4 },
];

describe("LifecycleStatusControl", () => {
  beforeEach(() => {
    changeProjectStatus.mockReset();
  });

  it("só oferece a alteração quando o servidor o permite", () => {
    const project = makeProject({ lifecycle_status: "construcao", can_change_status: false });
    renderWithProviders(<LifecycleStatusControl project={project} statuses={STATUSES} onChanged={vi.fn()} />);

    expect(screen.getByText("Construção")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Alterar estado" })).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Estado do projeto" })).not.toBeInTheDocument();
  });

  it("offers statuses immediately in a native dropdown and preselects the chosen state in the audit dialog", () => {
    const project = makeProject({ lifecycle_status: "preparacao", can_change_status: true });
    renderWithProviders(<LifecycleStatusControl project={project} statuses={STATUSES} onChanged={vi.fn()} />);

    const select = screen.getByRole("combobox", { name: "Estado do projeto" });
    expect(select).toHaveValue("preparacao");
    fireEvent.change(select, { target: { value: "construcao" } });

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText("Novo estado *")).toHaveValue("construcao");
  });

  it("shows an honest placeholder for an unknown current state and disables an empty catalog", () => {
    const project = makeProject({ lifecycle_status: "legacy_state", can_change_status: true });
    const { rerender } = renderWithProviders(<LifecycleStatusControl project={project} statuses={STATUSES} onChanged={vi.fn()} />);

    expect(screen.getByRole("combobox", { name: "Estado do projeto" })).toHaveValue("legacy_state");
    expect(screen.getByRole("option", { name: "Estado atual: legacy_state (desconhecido)" })).toBeDisabled();

    rerender(<LifecycleStatusControl project={{ ...project, lifecycle_status: null }} statuses={[]} onChanged={vi.fn()} />);
    const select = screen.getByRole("combobox", { name: "Estado do projeto" });
    expect(select).toBeDisabled();
    expect(select).toHaveValue("");
    expect(screen.getByRole("option", { name: "— estado atual: sem estado —" })).toBeDisabled();
  });

  it("altera o estado com nota e avisa quando salta estados", async () => {
    const project = makeProject({ lifecycle_status: "preparacao", can_change_status: true });
    const changed = { ...project, lifecycle_status: "entregue_cliente" };
    changeProjectStatus.mockResolvedValue({ project: changed, warning: "Mudou a saltar 2 estados da sequência normal." });
    const onChanged = vi.fn();
    renderWithProviders(<LifecycleStatusControl project={project} statuses={STATUSES} onChanged={onChanged} />);

    fireEvent.change(screen.getByRole("combobox", { name: "Estado do projeto" }), { target: { value: "entregue_cliente" } });
    fireEvent.change(screen.getByLabelText("Nota (opcional)"), { target: { value: "  Entrega antecipada. " } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar estado" }));

    await waitFor(() => expect(onChanged).toHaveBeenCalledWith(changed));
    expect(changeProjectStatus).toHaveBeenCalledWith(project.id, "entregue_cliente", "Entrega antecipada.");
    expect(await screen.findByText("Mudou a saltar 2 estados da sequência normal.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("não envia sem escolher um estado diferente do atual", () => {
    const project = makeProject({ lifecycle_status: "preparacao", can_change_status: true });
    renderWithProviders(<LifecycleStatusControl project={project} statuses={STATUSES} onChanged={vi.fn()} />);

    fireEvent.change(screen.getByRole("combobox", { name: "Estado do projeto" }), { target: { value: "preparacao" } });

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(changeProjectStatus).not.toHaveBeenCalled();
  });

  it("mostra o erro do servidor e mantém o diálogo aberto", async () => {
    const project = makeProject({ lifecycle_status: "preparacao", can_change_status: true });
    const onChanged = vi.fn();
    renderWithProviders(<LifecycleStatusControl project={project} statuses={STATUSES} onChanged={onChanged} />);

    fireEvent.change(screen.getByRole("combobox", { name: "Estado do projeto" }), { target: { value: "construcao" } });
    const { ApiError } = await vi.importActual<typeof import("../api/client")>("../api/client");
    changeProjectStatus.mockRejectedValue(new ApiError(403, "Sem permissão para alterar o estado deste projeto."));
    fireEvent.click(screen.getByRole("button", { name: "Guardar estado" }));

    expect(await screen.findByText("Sem permissão para alterar o estado deste projeto.")).toBeInTheDocument();
    expect(onChanged).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
