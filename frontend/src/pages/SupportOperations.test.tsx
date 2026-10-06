import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Person, SupportDelegation } from "../api/client";
import { makeMe } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import SupportOperations from "./SupportOperations";

const { listPeople, listSupportDelegations, saveSupportDelegation, deleteSupportDelegation } = vi.hoisted(() => ({
  listPeople: vi.fn(),
  listSupportDelegations: vi.fn(),
  saveSupportDelegation: vi.fn(),
  deleteSupportDelegation: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, listPeople, listSupportDelegations, saveSupportDelegation, deleteSupportDelegation };
});

const people: Person[] = [
  { id: "pm-1", display_name: "PM Um", email: null, is_active: true },
  { id: "support-1", display_name: "Suporte Um", email: null, is_active: true },
  { id: "inactive", display_name: "Pessoa Inativa", email: null, is_active: false },
];
const delegation: SupportDelegation = {
  pm_person_id: "pm-1", pm_display_name: "PM Um", support_person_id: "support-1", support_display_name: "Suporte Um",
};

const manager = () => makeMe({ roles: ["chefe_operacoes"], permissions: [] });

describe("SupportOperations", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listPeople.mockResolvedValue(people);
    listSupportDelegations.mockResolvedValue([delegation]);
    saveSupportDelegation.mockResolvedValue(delegation);
    deleteSupportDelegation.mockResolvedValue(undefined);
  });

  it("bloqueia claramente utilizadores sem o papel de gestão", () => {
    renderWithProviders(<SupportOperations />, { me: makeMe({ roles: ["comercial"], permissions: [] }) });
    expect(screen.getByText("Não tem permissão para gerir delegações de suporte.")).toBeInTheDocument();
    expect(listSupportDelegations).not.toHaveBeenCalled();
  });

  it("cria, edita e remove delegações usando as APIs", async () => {
    renderWithProviders(<SupportOperations />, { me: manager() });
    const delegationRow = await screen.findByRole("row", { name: /PM Um\s+Suporte Um/ });

    fireEvent.click(within(delegationRow).getByRole("button", { name: "Editar" }));
    expect(screen.getByRole("combobox", { name: "PM" })).toBeDisabled();
    fireEvent.change(screen.getByRole("combobox", { name: "Pessoa de suporte" }), { target: { value: "pm-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Atualizar delegação" }));
    await waitFor(() => expect(saveSupportDelegation).toHaveBeenCalledWith({ pm_person_id: "pm-1", support_person_id: "pm-1" }));

    const updatedDelegationRow = await screen.findByRole("row", { name: /PM Um\s+Suporte Um/ });
    fireEvent.click(within(updatedDelegationRow).getByRole("button", { name: "Remover" }));
    await waitFor(() => expect(deleteSupportDelegation).toHaveBeenCalledWith("pm-1"));
  });

  it("mostra o estado vazio", async () => {
    listSupportDelegations.mockResolvedValue([]);
    renderWithProviders(<SupportOperations />, { me: manager() });
    expect(await screen.findByText("Não existem delegações configuradas.")).toBeInTheDocument();
  });

  it("cria uma delegação", async () => {
    listSupportDelegations.mockResolvedValue([]);
    renderWithProviders(<SupportOperations />, { me: manager() });
    await screen.findByText("Não existem delegações configuradas.");
    fireEvent.change(screen.getByRole("combobox", { name: "PM" }), { target: { value: "pm-1" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Pessoa de suporte" }), { target: { value: "support-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar delegação" }));
    await waitFor(() => expect(saveSupportDelegation).toHaveBeenCalledWith({ pm_person_id: "pm-1", support_person_id: "support-1" }));
  });
});
