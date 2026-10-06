import { screen, fireEvent, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { MyProcessStage } from "../api/client";
import { makeMe } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import MyProcess from "./MyProcess";

const { getMyProcessStages } = vi.hoisted(() => ({ getMyProcessStages: vi.fn() }));
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, getMyProcessStages };
});

const stage: MyProcessStage = {
  project_id: "project-1", project_name: "Projeto Delegado", stage_id: "stage-1", stage_code: "support_delegate",
  stage_title: "Licenciamento", responsible_rule: "support_delegate", status: "pending", planned_start: "2026-09-01",
  planned_end: "2026-09-30", done_count: 1, total_count: 3,
};

describe("MyProcess", () => {
  beforeEach(() => vi.resetAllMocks());

  it("apresenta apenas o resultado autorizado pela API", async () => {
    getMyProcessStages.mockResolvedValue([stage]);
    renderWithProviders(<MyProcess />, { me: makeMe() });
    expect(await screen.findByText("Projeto Delegado")).toBeInTheDocument();
    expect(screen.getByText("Licenciamento")).toBeInTheDocument();
    expect(screen.getByText("1/3")).toBeInTheDocument();
  });

  it("mostra o estado vazio sem repetir o pedido", async () => {
    getMyProcessStages.mockResolvedValueOnce([]).mockResolvedValueOnce([stage]);
    renderWithProviders(<MyProcess />, { me: makeMe() });
    expect(await screen.findByText("Não tem etapas pendentes.")).toBeInTheDocument();
    // O pedido só é repetido através do erro; a lista vazia é um estado terminal válido.
    expect(getMyProcessStages).toHaveBeenCalledTimes(1);
  });

  it("mostra erro e recarrega", async () => {
    getMyProcessStages.mockRejectedValue(new Error("falha"));
    renderWithProviders(<MyProcess />, { me: makeMe() });
    const errorState = await screen.findByRole("alert");
    expect(errorState).toHaveTextContent("Não foi possível carregar os dados");
    getMyProcessStages.mockResolvedValueOnce([stage]);
    fireEvent.click(within(errorState).getByRole("button", { name: "Tentar novamente" }));
    await waitFor(() => expect(getMyProcessStages).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("Projeto Delegado")).toBeInTheDocument();
  });
});
