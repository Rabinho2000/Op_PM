import { readFileSync } from "node:fs";
import { act, fireEvent, screen, within, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { HealthResponse, MeResponse } from "../api/client";
import { COMERCIAL_ME, makeMe } from "../test/fixtures";
import { isInstallerCollaborator } from "../session/installerAccess";
import { renderWithProviders } from "../test/render";
import Layout, { ADMIN_NAV_ITEMS, NAV_ITEMS } from "./Layout";

const requestsApi = vi.hoisted(() => ({
  getRequestsSummary: vi.fn(),
}));

vi.mock("../api/requests", async () => {
  const actual = await vi.importActual<typeof import("../api/requests")>("../api/requests");
  return { ...actual, ...requestsApi };
});

function renderLayout(route: string, me = makeMe(), health: HealthResponse | null = null) {
  return renderWithProviders(
    <Layout>
      <p>Conteúdo da página</p>
    </Layout>,
    { me, route, health }
  );
}

const INSTALLER_NAV_PATHS = new Set([
  "/projects",
  "/tasks",
  "/inventory",
  "/works",
  "/works/teams",
  "/time-bank",
]);

function expectedNavPaths(me: MeResponse): string[] {
  const canShow = (item: (typeof NAV_ITEMS)[number] | (typeof ADMIN_NAV_ITEMS)[number]) => {
    if (isInstallerCollaborator(me) && !INSTALLER_NAV_PATHS.has(item.to)) return false;
    if (item.roles?.some((role) => me.roles.includes(role))) return true;
    if (!item.permission) return true;
    const codes = Array.isArray(item.permission) ? item.permission : [item.permission];
    return codes.some((permission) => me.permissions.includes(permission));
  };

  return [
    ...NAV_ITEMS.filter((item) => !(isInstallerCollaborator(me) && item.to === "/")).filter(canShow),
    ...ADMIN_NAV_ITEMS.filter(canShow),
  ].map((item) => item.to);
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("Layout (rail compacto)", () => {
  it("apresenta tooltip ao focar e esconde-o em blur ou Escape", () => {
    renderLayout("/");
    const nav = screen.getByRole("navigation", { name: "Navegação principal" });
    const tasks = within(nav).getByRole("link", { name: "Tarefas" });
    const appCss = readFileSync("src/styles/app.css", "utf8");

    expect(document.getElementById("menu-principal")).toHaveClass("sidebar--compact");
    expect(tasks).toHaveAttribute("aria-label", "Tarefas");
    expect(tasks).toHaveAttribute("data-tooltip", "Tarefas");
    act(() => tasks.focus());
    expect(tasks).toHaveFocus();
    expect(screen.getByRole("tooltip")).toHaveTextContent("Tarefas");
    expect(tasks).toHaveAttribute("aria-describedby", screen.getByRole("tooltip").id);
    expect(appCss).toMatch(/\.sidebar-tooltip\s*\{[^}]*position:\s*fixed;/);

    act(() => tasks.blur());
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    act(() => tasks.focus());
    expect(screen.getByRole("tooltip")).toHaveTextContent("Tarefas");
    fireEvent.keyDown(tasks, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(within(nav).getByRole("separator", { name: "Administração" })).toBeInTheDocument();
  });

  it("apresenta e remove tooltip ao passar o rato pelo rail compacto", () => {
    renderLayout("/");
    const tasks = within(screen.getByRole("navigation", { name: "Navegação principal" }))
      .getByRole("link", { name: "Tarefas" });

    fireEvent.mouseEnter(tasks);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Tarefas");
    fireEvent.mouseLeave(tasks);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("reposiciona o tooltip do link focado quando o rail faz scroll", () => {
    requestsApi.getRequestsSummary.mockResolvedValue({ open: 0 });
    renderLayout("/", makeMe({ permissions: ["requests.manage"] }));
    const nav = screen.getByRole("navigation", { name: "Navegação principal" });
    const requests = within(nav).getByRole("link", { name: "Pedidos" });
    const makeRect = (top: number, right: number, height = 40): DOMRect => ({
      x: 0,
      y: top,
      top,
      right,
      bottom: top + height,
      left: 0,
      width: right,
      height,
      toJSON: () => ({}),
    });
    let linkRect = makeRect(450, 88);
    vi.spyOn(requests, "getBoundingClientRect").mockImplementation(() => linkRect);
    vi.spyOn(nav, "getBoundingClientRect").mockReturnValue(makeRect(100, 240, 400));
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      callback(0);
      return 1;
    });

    act(() => requests.focus());
    expect(screen.getByRole("tooltip").style).toMatchObject({ left: "97px", top: "470px" });
    expect(requests).toHaveAttribute("aria-describedby", "sidebar-tooltip");

    linkRect = makeRect(170, 104);
    act(() => fireEvent.scroll(nav));

    expect(screen.getByRole("tooltip").style).toMatchObject({ left: "113px", top: "190px" });
    expect(requests).toHaveAttribute("aria-describedby", "sidebar-tooltip");

    linkRect = makeRect(510, 104);
    act(() => fireEvent.scroll(nav));
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(requests).not.toHaveAttribute("aria-describedby");
  });

  it("esconde o tooltip e remove aria-describedby ao navegar pelo rail", () => {
    requestsApi.getRequestsSummary.mockResolvedValue({ open: 0 });
    renderLayout("/", makeMe({ permissions: ["requests.manage"] }));
    const nav = screen.getByRole("navigation", { name: "Navegação principal" });
    const requests = within(nav).getByRole("link", { name: "Pedidos" });

    act(() => requests.focus());
    expect(screen.getByRole("tooltip")).toHaveTextContent("Pedidos");
    expect(requests).toHaveAttribute("aria-describedby", "sidebar-tooltip");

    fireEvent.click(requests);

    expect(screen.getByRole("banner")).toHaveTextContent("Pedidos");
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(requests).not.toHaveAttribute("aria-describedby");
  });

  it("mantém labels acessíveis sem largura visual e impede overflow horizontal no rail", () => {
    renderLayout("/");
    const nav = screen.getByRole("navigation", { name: "Navegação principal" });
    const tasks = within(nav).getByRole("link", { name: "Tarefas" });
    const label = within(tasks).getByText("Tarefas");
    const appCss = readFileSync("src/styles/app.css", "utf8");
    const navRules = Array.from(appCss.matchAll(/\.sidebar__nav\s*\{([^}]*)\}/g), (match) => match[1]).join("\n");

    expect(label).toBeInTheDocument();
    expect(tasks).toHaveAccessibleName("Tarefas");
    expect(appCss).toMatch(/\.sidebar--compact\s+\.nav-link__label\s*\{[^}]*position:\s*absolute;[^}]*width:\s*1px;[^}]*height:\s*1px;/);
    expect(navRules).toMatch(/min-width:\s*0;[^}]*overflow-x:\s*hidden;[^}]*overflow-y:\s*auto;[^}]*scrollbar-width:\s*thin;/);
  });

  it("expande e recolhe a navegação persistindo a preferência por conta", () => {
    window.localStorage.clear();
    const { unmount } = renderLayout("/");
    fireEvent.click(screen.getByRole("button", { name: "Expandir navegação" }));
    expect(document.getElementById("menu-principal")).toHaveClass("sidebar--expanded");
    expect(window.localStorage.getItem("op_pm_nav_rail_expanded_v1:u-chefe")).toBe("true");

    unmount();
    renderLayout("/");
    expect(document.getElementById("menu-principal")).toHaveClass("sidebar--expanded");
    fireEvent.click(screen.getByRole("button", { name: "Recolher navegação" }));
    expect(document.getElementById("menu-principal")).toHaveClass("sidebar--compact");
    expect(window.localStorage.getItem("op_pm_nav_rail_expanded_v1:u-chefe")).toBe("false");
  });

  it("renderiza exatamente os destinos atuais permitidos e preserva Administração", () => {
    const me = makeMe();
    renderLayout("/", me);
    const nav = screen.getByRole("navigation", { name: "Navegação principal" });
    const actualPaths = Array.from(nav.querySelectorAll<HTMLAnchorElement>("a")).map((link) => link.getAttribute("href"));

    expect(actualPaths).toEqual(expectedNavPaths(me));
    expect(within(nav).getByRole("separator", { name: "Administração" })).toBeInTheDocument();
  });

  it("usa um ícone diferente em cada destino visível ao Chefe no rail", () => {
    const allItems = [...NAV_ITEMS, ...ADMIN_NAV_ITEMS];
    const permissions = Array.from(new Set(allItems.flatMap((item) =>
      item.permission ? (Array.isArray(item.permission) ? item.permission : [item.permission]) : []
    )));
    const me = makeMe({ roles: ["chefe_operacoes", "suporte_operacoes"], permissions });
    renderLayout("/", me);
    const nav = screen.getByRole("navigation", { name: "Navegação principal" });
    const links = Array.from(nav.querySelectorAll<HTMLAnchorElement>("a.nav-link"));
    const iconNames = links.map((link) => link.dataset.icon);

    expect(links.map((link) => link.getAttribute("href"))).toEqual(expectedNavPaths(me));
    expect(iconNames).toHaveLength(links.length);
    expect(iconNames.every(Boolean)).toBe(true);
    expect(new Set(iconNames).size).toBe(links.length);
  });

  it("mantém ações globais de alertas, pedidos, tema e utilizador no cabeçalho", () => {
    renderLayout("/tasks", makeMe({ permissions: ["process_alert.use", "requests.create"] }));
    const header = screen.getByRole("banner");

    expect(within(header).getByRole("button", { name: "Alarmes do processo" })).toBeInTheDocument();
    expect(within(header).getByRole("button", { name: "Pedidos" })).toBeInTheDocument();
    expect(within(header).getByRole("combobox", { name: "Aparência no cabeçalho" })).toBeInTheDocument();
    expect(within(header).getByText("Chefe Sintético")).toBeInTheDocument();
    expect(within(header).getByRole("button", { name: "Terminar sessão" })).toBeInTheDocument();
  });
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

  it("mantém o indicador do ambiente fora da árvore acessível", () => {
    renderLayout("/");
    expect(document.querySelector(".sidebar__environment")).toHaveAttribute("aria-hidden", "true");
  });

  it("usa a barra inferior e a gaveta nas regras de viewport móvel", () => {
    renderLayout("/tasks");
    const appCss = readFileSync("src/styles/app.css", "utf8");
    const mobileRules = Array.from(appCss.matchAll(/@media\s*\(max-width:\s*760px\)\s*\{([\s\S]*?)\n\}/g))
      .map((match) => match[1])
      .join("\n");
    const sidebar = document.getElementById("menu-principal");
    const bottom = screen.getByRole("navigation", { name: "Navegação rápida" });

    expect(bottom).toHaveClass("bottom-nav");
    expect(sidebar).toHaveClass("sidebar--compact");
    expect(mobileRules).toMatch(/\.bottom-nav\s*\{\s*display:\s*flex;/);
    expect(mobileRules).toMatch(/\.sidebar\s*\{\s*transform:\s*translateX\(-100%\);/);
    expect(mobileRules).toMatch(/\.sidebar\.open\s*\{\s*transform:\s*translateX\(0\);/);
    expect(mobileRules).toMatch(/\.backdrop\.open\s*\{\s*display:\s*block;/);

    fireEvent.click(within(bottom).getByRole("button", { name: "Mais" }));
    expect(sidebar).toHaveClass("open");
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

  it.each([
    ["/projects/import", "Importar notas iniciais"],
    ["/projects/project-123", "Detalhe do projeto"],
    ["/projects/deleted", "Projetos apagados"],
    ["/projects/import/unknown", "Detalhe do projeto"],
    ["/unknown-route", "Solcor Operações"],
  ])("uses the correct topbar and document title for %s", (route, title) => {
    renderLayout(route);

    expect(within(screen.getByRole("banner")).getByText(title)).toBeInTheDocument();
    expect(document.title).toBe(`${title} · Solcor Operações`);
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

  it("mostra Pedidos e a contagem de abertos a quem tem requests.manage", async () => {
    requestsApi.getRequestsSummary.mockResolvedValue({ open: 3 });
    renderLayout("/", makeMe({ permissions: ["requests.manage"] }));

    const link = await screen.findByRole("link", { name: /Pedidos/ });
    expect(link).toHaveAttribute("href", "/requests");
    expect(link).toHaveAccessibleName("Pedidos, 3 pedidos abertos");
    expect(within(link).getByText("3")).toHaveAttribute("aria-hidden", "true");
  });

  it("não mostra badge no rail quando a contagem de pedidos é zero", async () => {
    requestsApi.getRequestsSummary.mockResolvedValue({ open: 0 });
    renderLayout("/", makeMe({ permissions: ["requests.manage"] }));
    await act(async () => { await Promise.resolve(); });

    const requestsLink = within(screen.getByRole("navigation", { name: "Navegação principal" }))
      .getByRole("link", { name: "Pedidos" });
    expect(requestsLink.querySelector(".nav-link__badge")).toBeNull();
  });

  it("preserva opções e persistência do seletor de tema no cabeçalho compacto", () => {
    renderLayout("/tasks");
    const header = screen.getByRole("banner");
    const theme = within(header).getByRole("combobox", { name: "Aparência no cabeçalho" }) as HTMLSelectElement;
    const appCss = readFileSync("src/styles/app.css", "utf8");

    expect(Array.from(theme.options, (option) => [option.value, option.textContent])).toEqual([
      ["light", "Claro"],
      ["dark", "Escuro"],
      ["system", "Sistema"],
    ]);
    fireEvent.change(theme, { target: { value: "dark" } });
    expect(theme).toHaveValue("dark");
    expect(window.localStorage.getItem("op_pm_theme_v1")).toBe("dark");
    fireEvent.change(theme, { target: { value: "system" } });
    expect(window.localStorage.getItem("op_pm_theme_v1")).toBe("system");
    expect(appCss).toMatch(/@media\s*\(max-width:\s*1100px\)[\s\S]*?\.theme-toggle--header\s*>\s*span\s*\{[^}]*display:\s*none;/);
    expect(appCss).toMatch(/@media\s*\(max-width:\s*760px\)[\s\S]*?\.theme-toggle--header select\s*\{[^}]*width:\s*100px;[^}]*min-height:\s*44px;/);
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

  it("tem ligação para saltar para o conteúdo e botão Mais acessível", () => {
    renderLayout("/");
    expect(screen.getByRole("link", { name: "Saltar para o conteúdo" })).toHaveAttribute("href", "#conteudo");
    const more = screen.getByRole("button", { name: "Mais" });
    expect(more).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(more);
    expect(more).toHaveAttribute("aria-expanded", "true");
  });

  it("abre e fecha a gaveta com Mais e Escape devolve o foco ao trigger", () => {
    renderLayout("/tasks");
    const trigger = screen.getByRole("button", { name: "Mais" });
    trigger.focus();
    fireEvent.click(trigger);
    expect(document.getElementById("menu-principal")).toHaveClass("open");
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    fireEvent.keyDown(document, { key: "Escape" });
    expect(document.getElementById("menu-principal")).not.toHaveClass("open");
    expect(document.querySelector(".backdrop")).not.toHaveClass("open");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveFocus();

    fireEvent.click(trigger);
    expect(document.getElementById("menu-principal")).toHaveClass("open");
    fireEvent.click(document.querySelector(".backdrop") as HTMLElement);
    expect(document.getElementById("menu-principal")).not.toHaveClass("open");
  });
});
