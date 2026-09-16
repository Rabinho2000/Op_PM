import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { HealthResponse } from "../api/client";
import { COMERCIAL_ME, makeMe } from "../test/fixtures";
import { renderWithProviders } from "../test/render";
import Layout from "./Layout";

function renderLayout(route: string, me = makeMe(), health: HealthResponse | null = null) {
  return renderWithProviders(
    <Layout>
      <p>Conteúdo da página</p>
    </Layout>,
    { me, route, health }
  );
}

describe("Layout (navegação principal)", () => {
  it("mostra as secções principais com ligações corretas", () => {
    renderLayout("/");
    const nav = screen.getByRole("navigation", { name: "Navegação principal" });
    const links = Array.from(nav.querySelectorAll("a")).map((a) => [a.textContent, a.getAttribute("href")]);
    expect(links).toEqual(
      expect.arrayContaining([
        ["Painel", "/"],
        ["Projetos", "/projects"],
        ["Tarefas", "/tasks"],
        ["Férias e aniversários", "/vacations"],
        ["Estado do sistema", "/status"],
      ])
    );
    expect(screen.getByText("Conteúdo da página")).toBeInTheDocument();
  });

  it("assinala a página atual e mostra o título no cabeçalho", () => {
    renderLayout("/tasks");
    expect(screen.getByRole("link", { name: "Tarefas" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Painel" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("banner")).toHaveTextContent("Tarefas");
  });

  it("mostra o utilizador atual e o seu papel", () => {
    renderLayout("/");
    expect(screen.getByText("Chefe Sintético")).toBeInTheDocument();
    expect(screen.getByText("Chefe de Operações")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Terminar sessão" })).toBeInTheDocument();
  });

  it("só mostra a reconciliação de PM a quem tem migration.view", () => {
    const { unmount } = renderLayout("/");
    expect(screen.getByRole("link", { name: "Reconciliação de PM" })).toBeInTheDocument();
    unmount();

    renderLayout("/", COMERCIAL_ME);
    expect(screen.queryByRole("link", { name: "Reconciliação de PM" })).not.toBeInTheDocument();
  });

  it("mostra o aviso de modo demonstração quando o servidor o indica", () => {
    renderLayout("/", makeMe(), {
      status: "ok",
      app_env: "local",
      database_dialect: "sqlite",
      integrations: {},
      demo_mode: true,
      dev_login_available: true,
    });
    expect(screen.getByRole("note")).toHaveTextContent("dados apresentados são sintéticos");
  });

  it("tem ligação para saltar para o conteúdo e menu acessível por teclado", () => {
    renderLayout("/");
    expect(screen.getByRole("link", { name: "Saltar para o conteúdo" })).toHaveAttribute("href", "#conteudo");
    const toggle = screen.getByRole("button", { name: "Abrir menu" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Fechar menu" })).toHaveAttribute("aria-expanded", "true");
  });
});
