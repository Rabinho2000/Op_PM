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
  });

  it("altera o estado com nota e avisa quando salta estados", async () => {
    const project = makeProject({ lifecycle_status: "preparacao", can_change_status: true });
    const changed = { ...project, lifecycle_status: "entregue_cliente" };
    changeProjectStatus.mockResolvedValue({ project: changed, warning: "Mudou a saltar 2 estados da sequência normal." });
    const onChanged = vi.fn();
    renderWithProviders(<LifecycleStatusControl project={project} statuses={STATUSES} onChanged={onChanged} />);

    fireEvent.click(screen.getByRole("button", { name: "Alterar estado" }));
    fireEvent.change(screen.getByLabelText("Novo estado *"), { target: { value: "entregue_cliente" } });
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

    fireEvent.click(screen.getByRole("button", { name: "Alterar estado" }));
    fireEvent.click(screen.getByRole("button", { name: "Guardar estado" }));

    expect(screen.getByText("Escolha um estado diferente do atual.")).toBeInTheDocument();
    expect(changeProjectStatus).not.toHaveBeenCalled();
  });

  it("mostra o erro do servidor e mantém o diálogo aberto", async () => {
    const project = makeProject({ lifecycle_status: "preparacao", can_change_status: true });
    const onChanged = vi.fn();
    renderWithProviders(<LifecycleStatusControl project={project} statuses={STATUSES} onChanged={onChanged} />);

    fireEvent.click(screen.getByRole("button", { name: "Alterar estado" }));
    fireEvent.change(screen.getByLabelText("Novo estado *"), { target: { value: "construcao" } });
    const { ApiError } = await vi.importActual<typeof import("../api/client")>("../api/client");
    changeProjectStatus.mockRejectedValue(new ApiError(403, "Sem permissão para alterar o estado deste projeto."));
    fireEvent.click(screen.getByRole("button", { name: "Guardar estado" }));

    expect(await screen.findByText("Sem permissão para alterar o estado deste projeto.")).toBeInTheDocument();
    expect(onChanged).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
