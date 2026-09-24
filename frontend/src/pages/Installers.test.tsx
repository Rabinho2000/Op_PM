import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Installer } from "../api/client";
import { makeMe } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import Installers from "./Installers";

const { listInstallers, createInstaller, createInstallerTeam, updateInstaller, updateInstallerTeam } = vi.hoisted(() => ({
  listInstallers: vi.fn(),
  createInstaller: vi.fn(),
  createInstallerTeam: vi.fn(),
  updateInstaller: vi.fn(),
  updateInstallerTeam: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, listInstallers, createInstaller, createInstallerTeam, updateInstaller, updateInstallerTeam };
});

const DATA: Installer[] = [
  {
    id: "i-vm",
    name: "Verde Milenar",
    is_active: true,
    project_count: 1,
    teams: [
      { id: "t-1", name: "Equipa 1", leader_name: "Chefe Um", leader_phone: "+351 910 000 001", is_active: true, project_count: 1 },
      { id: "t-2", name: "Equipa 2", leader_name: null, leader_phone: null, is_active: false, project_count: 0 },
    ],
  },
  { id: "i-x", name: "Sem Equipas Lda", is_active: false, project_count: 0, teams: [] },
];

const manager = () => makeMe({ permissions: ["project.view_all", "installer.manage"] });

describe("Installers", () => {
  beforeEach(() => {
    [listInstallers, createInstaller, createInstallerTeam, updateInstaller, updateInstallerTeam].forEach((m) => m.mockReset());
    listInstallers.mockResolvedValue(DATA);
  });

  it("lista instaladores, equipas, chefes e nº de obras", async () => {
    renderWithProviders(<Installers />, { me: manager() });
    expect(await screen.findByText("Verde Milenar")).toBeInTheDocument();
    expect(screen.getByText("1 obra ativa")).toBeInTheDocument();
    expect(screen.getByText("Chefe Um")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "+351 910 000 001" })).toHaveAttribute("href", "tel:+351910000001");
    expect(screen.getByText("Inativa")).toBeInTheDocument(); // Equipa 2
    expect(screen.getByText("Inativo")).toBeInTheDocument(); // Sem Equipas Lda
    expect(screen.getByText("Sem equipas registadas.")).toBeInTheDocument();
  });

  it("sem permissão de gestão não mostra criar nem editar", async () => {
    renderWithProviders(<Installers />, { me: makeMe({ permissions: ["project.view_all"] }) });
    await screen.findByText("Verde Milenar");
    expect(screen.queryByRole("button", { name: /Novo instalador/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Editar/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Nova equipa/ })).not.toBeInTheDocument();
  });

  it("cria um instalador e recarrega a lista", async () => {
    createInstaller.mockResolvedValue({ ...DATA[1], id: "i-new", name: "Novo Instalador" });
    renderWithProviders(<Installers />, { me: manager() });
    await screen.findByText("Verde Milenar");

    fireEvent.click(screen.getByRole("button", { name: /Novo instalador/ }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Criar instalador" }));
    expect(within(dialog).getByText("Indique o nome do instalador.")).toBeInTheDocument();

    fireEvent.change(within(dialog).getByLabelText("Nome *"), { target: { value: "  Novo Instalador " } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Criar instalador" }));
    await waitFor(() => expect(createInstaller).toHaveBeenCalledWith("Novo Instalador"));
    expect(await screen.findByText("Instalador «Novo Instalador» criado.")).toBeInTheDocument();
    expect(listInstallers.mock.calls.length).toBeGreaterThan(1);
  });

  it("cria uma equipa com chefe e valida o telefone", async () => {
    createInstallerTeam.mockResolvedValue(DATA[0]);
    renderWithProviders(<Installers />, { me: manager() });
    await screen.findByText("Verde Milenar");

    fireEvent.click(screen.getAllByRole("button", { name: "Nova equipa" })[0]);
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Nome da equipa *"), { target: { value: "Equipa 3" } });
    fireEvent.change(within(dialog).getByLabelText("Telefone do chefe"), { target: { value: "abc" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Guardar equipa" }));
    expect(within(dialog).getByText(/Telefone inválido/)).toBeInTheDocument();
    expect(createInstallerTeam).not.toHaveBeenCalled();

    fireEvent.change(within(dialog).getByLabelText("Telefone do chefe"), { target: { value: "" } });
    fireEvent.change(within(dialog).getByLabelText("Chefe de equipa"), { target: { value: "Chefe Três" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Guardar equipa" }));
    await waitFor(() =>
      expect(createInstallerTeam).toHaveBeenCalledWith("i-vm", { name: "Equipa 3", leader_name: "Chefe Três", leader_phone: null })
    );
    expect(await screen.findByText("Equipa «Equipa 3» criada.")).toBeInTheDocument();
  });

  it("edita e desativa uma equipa", async () => {
    updateInstallerTeam.mockResolvedValue(DATA[0]);
    renderWithProviders(<Installers />, { me: manager() });
    await screen.findByText("Verde Milenar");

    fireEvent.click(screen.getByRole("button", { name: "Editar Equipa 1 de Verde Milenar" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("Chefe de equipa")).toHaveValue("Chefe Um");
    fireEvent.click(within(dialog).getByLabelText(/Equipa ativa/));
    fireEvent.click(within(dialog).getByRole("button", { name: "Guardar equipa" }));

    await waitFor(() => expect(updateInstallerTeam).toHaveBeenCalled());
    expect(updateInstallerTeam).toHaveBeenCalledWith("i-vm", "t-1", {
      name: "Equipa 1",
      leader_name: "Chefe Um",
      leader_phone: "+351 910 000 001",
      is_active: false,
    });
  });

  it("desativa e reativa um instalador", async () => {
    updateInstaller.mockResolvedValue(DATA[0]);
    renderWithProviders(<Installers />, { me: manager() });
    await screen.findByText("Verde Milenar");
    fireEvent.click(screen.getByRole("button", { name: "Desativar" }));
    await waitFor(() => expect(updateInstaller).toHaveBeenCalledWith("i-vm", { is_active: false }));
    fireEvent.click(screen.getByRole("button", { name: "Reativar" }));
    await waitFor(() => expect(updateInstaller).toHaveBeenCalledWith("i-x", { is_active: true }));
  });
});
