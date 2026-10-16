import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Layout from "./Layout";
import { makeMe } from "../test/fixtures";
import { renderWithProviders } from "../test/render";

const EXTERNAL_ME = makeMe({
  email: "installer.a@example.invalid",
  person_id: "person-installer-a",
  display_name: "Installer A",
  roles: ["instalador_colaborador"],
  permissions: [
    "project.view_assigned_installer",
    "task.view_assigned_installer",
    "works_calendar.view_assigned_installer",
    "installer_team.view_assigned_installer",
    "inventory.view_assigned_installer",
    "time_bank.view_own",
  ],
});

describe("menu do colaborador de instalador", () => {
  it("não renderiza destinos staff-only no menu desktop nem na gaveta móvel", () => {
    renderWithProviders(
      <Layout>
        <div>Conteúdo scoped</div>
      </Layout>,
      { me: EXTERNAL_ME, route: "/projects" },
    );

    expect(screen.queryByRole("link", { name: "Férias e aniversários" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Estado do sistema" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Mais" }));

    expect(screen.queryByRole("link", { name: "Férias e aniversários" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Estado do sistema" })).not.toBeInTheDocument();
  });

  it("mantém os destinos staff-only para o menu staff existente", () => {
    renderWithProviders(
      <Layout>
        <div>Conteúdo staff</div>
      </Layout>,
      { me: makeMe(), route: "/" },
    );

    expect(screen.getByRole("link", { name: "Férias e aniversários" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Estado do sistema" })).toBeInTheDocument();
  });
});
