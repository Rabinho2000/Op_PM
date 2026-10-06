import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
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

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("Layout (barra inferior no telemóvel, D-079)", () => {
  it("mostra os destinos diários e um botão Mais que abre o menu completo", () => {
    renderLayout("/tasks");
    const bottom = within(screen.getByRole("navigation", { name: "Navegação rápida" }));
    const links = bottom.getAllByRole("link").map((a) => [a.textContent, a.getAttribute("href")]);
    expect(links).toEqual(
      expect.arrayContaining([
        ["Painel", "/"],
        ["Projetos", "/projects"],
        ["Tarefas", "/tasks"],
      ])
    );
    expect(bottom.getByRole("link", { name: "Tarefas" })).toHaveAttribute("aria-current", "page");
    const more = bottom.getByRole("button", { name: "Mais" });
    expect(more).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(more);
    expect(more).toHaveAttribute("aria-expanded", "true");
    expect(document.getElementById("menu-principal")).toHaveClass("open");
  });

  it("não mostra na barra inferior destinos sem permissão", () => {
    renderLayout("/", makeMe({ permissions: [] }));
    const bottom = within(screen.getByRole("navigation", { name: "Navegação rápida" }));
    expect(bottom.queryByRole("link", { name: "Agenda" })).not.toBeInTheDocument();
  });
});

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
    const nav = within(screen.getByRole("navigation", { name: "Navegação principal" }));
    expect(nav.getByRole("link", { name: "Tarefas" })).toHaveAttribute("aria-current", "page");
    expect(nav.getByRole("link", { name: "Painel" })).not.toHaveAttribute("aria-current");
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

  it("mostra o suporte de operações ao chefe de operações mesmo sem admin.manage_users", () => {
    renderLayout("/", makeMe({ permissions: [] }));
    expect(screen.getByRole("link", { name: "Suporte de operações" })).toBeInTheDocument();
  });

  it("não mostra o suporte de operações a outros perfis sem administração", () => {
    renderLayout("/", COMERCIAL_ME);
    expect(screen.queryByRole("link", { name: "Suporte de operações" })).not.toBeInTheDocument();
  });

  it("mostra as minhas etapas ao Suporte de Operações", () => {
    renderLayout("/", makeMe({ roles: ["suporte_operacoes"], permissions: [] }));
    expect(screen.getByRole("link", { name: "As minhas etapas" })).toBeInTheDocument();
  });

  it("só mostra relatórios a clientes com permissão de consulta ou gestão", () => {
    const { unmount } = renderLayout("/", makeMe({ permissions: ["client_report.view"] }));
    expect(screen.getByRole("link", { name: "Relatórios a clientes" })).toHaveAttribute("href", "/client-reports");
    unmount();

    renderLayout("/", COMERCIAL_ME);
    expect(screen.queryByRole("link", { name: "Relatórios a clientes" })).not.toBeInTheDocument();
  });

  it("mostra o aviso de modo demonstração quando o servidor o indica", () => {
    renderLayout("/", makeMe(), {
      status: "ok",
      app_env: "local",
      database_dialect: "sqlite",
      integrations: {},
      demo_mode: true,
      demo_real_data: false,
      dev_login_available: true,
    });
    expect(screen.getByRole("note")).toHaveTextContent("dados apresentados são sintéticos");
  });

  it("mantém o aviso sintético quando a flag real é explicitamente false", () => {
    vi.stubEnv("VITE_REAL_DATA_INSTANCE", "false");
    renderLayout("/", makeMe(), {
      status: "ok",
      app_env: "local",
      database_dialect: "sqlite",
      integrations: {},
      demo_mode: true,
      demo_real_data: false,
      dev_login_available: true,
    });

    const note = screen.getByRole("note");
    expect(note).toHaveTextContent("Modo demonstração — todos os dados apresentados são sintéticos.");
    expect(note).not.toHaveTextContent("Instância interna");
  });

  it("classifica a instância como real pelo health mesmo com a flag false", () => {
    vi.stubEnv("VITE_REAL_DATA_INSTANCE", "false");
    renderLayout("/", makeMe(), {
      status: "ok",
      app_env: "local",
      database_dialect: "sqlite",
      integrations: {},
      demo_mode: false,
      demo_real_data: true,
      dev_login_available: true,
    });

    expect(screen.getByRole("note")).toHaveTextContent(
      "Instância interna — contém dados operacionais reais. As integrações externas continuam inativas."
    );
  });

  it("classifica a instância como real pela configuração Vite", () => {
    vi.stubEnv("VITE_REAL_DATA_INSTANCE", "true");
    renderLayout("/", makeMe(), {
      status: "ok",
      app_env: "local",
      database_dialect: "sqlite",
      integrations: {},
      demo_mode: false,
      demo_real_data: false,
      dev_login_available: true,
    });

    expect(screen.getByRole("note")).toHaveTextContent(
      "Instância interna — contém dados operacionais reais. As integrações externas continuam inativas."
    );
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
