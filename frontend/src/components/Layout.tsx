// Estrutura das páginas autenticadas: sidebar de navegação, cabeçalho com
// o utilizador atual, banner do modo demonstração e área de conteúdo.
import { ReactNode, useEffect, useRef, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { SolcorLogo } from "./SolcorLogo";
import { getDevUser, getSessionDisplayName, logoutCurrentSession } from "../api/client";
import { useSession } from "../session/SessionContext";
import Icon, { IconName } from "./Icon";
import { Avatar } from "./ui";
import { observeTableCardLabels } from "./tableCardLabels";

interface NavItem {
  to: string;
  label: string;
  icon: IconName;
  // Só aparece a quem tem pelo menos uma destas permissões (o servidor
  // volta sempre a validar em cada pedido — isto é só para não mostrar um
  // link que levaria a um 403).
  permission?: string | string[];
  end?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Painel", icon: "dashboard", end: true },
  { to: "/projects", label: "Projetos", icon: "folder" },
  { to: "/tasks", label: "Tarefas", icon: "tasks" },
  { to: "/inventory", label: "Inventário", icon: "database", permission: "inventory.view" },
  { to: "/suppliers", label: "Fornecedores", icon: "truck", permission: ["supplier.view", "map.view"] },
  { to: "/map", label: "Mapa", icon: "mapPin", permission: "map.view" },
  { to: "/works", label: "Calendário de obras", icon: "columns", permission: ["project.view_all", "project.view_own"] },
  { to: "/planning", label: "Planeamento", icon: "calendar", permission: "calendar.view" },
  {
    to: "/performance",
    label: "Metas e indicadores",
    icon: "flag",
    permission: ["performance.view_all", "performance.view_own"],
  },
  { to: "/vacations", label: "Férias e aniversários", icon: "calendar" },
];

export const ADMIN_NAV_ITEMS: NavItem[] = [
  { to: "/installers", label: "Instaladores", icon: "wrench", permission: "installer.manage" },
  { to: "/reconciliation", label: "Reconciliação de PM", icon: "link", permission: "migration.view" },
  { to: "/status", label: "Estado do sistema", icon: "activity" },
];

// Barra inferior no telemóvel (D-079): os destinos de uso diário. O resto
// continua acessível em "Mais", que abre a gaveta com o menu completo.
export const MOBILE_TAB_PATHS = ["/", "/projects", "/tasks", "/planning"];

const MOBILE_TAB_LABELS: Record<string, string> = { "/planning": "Agenda" };

const PAGE_TITLES: [string, string][] = [
  ["/projects/", "Detalhe do projeto"],
  ["/projects", "Projetos"],
  ["/tasks", "Tarefas"],
  ["/inventory", "Inventário"],
  ["/suppliers", "Fornecedores"],
  ["/works", "Calendário de obras"],
  ["/installers", "Instaladores"],
  ["/map", "Mapa"],
  ["/planning", "Planeamento"],
  ["/performance", "Metas e indicadores"],
  ["/vacations", "Férias e aniversários"],
  ["/reconciliation", "Reconciliação de PM"],
  ["/status", "Estado do sistema"],
];

function pageTitle(pathname: string): string {
  if (pathname === "/") return "Painel de operações";
  return PAGE_TITLES.find(([prefix]) => pathname.startsWith(prefix))?.[1] ?? "Solcor Operações";
}

export default function Layout({ children }: { children: ReactNode }) {
  const { me, health, can } = useSession();
  const navigate = useNavigate();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);

  const mainRef = useRef<HTMLElement>(null);

  useEffect(() => setMenuOpen(false), [location.pathname]);

  useEffect(() => {
    if (!mainRef.current) return undefined;
    return observeTableCardLabels(mainRef.current);
  }, []);

  useEffect(() => {
    document.title = `${pageTitle(location.pathname)} · Solcor Operações`;
  }, [location.pathname]);

  const displayName = me?.display_name ?? getSessionDisplayName() ?? "Utilizador";
  const roleLabel = me?.role_labels?.join(", ") || me?.roles.join(", ") || "";
  const usingDevLogin = getDevUser() !== null;
  const usesRealOperationalData = import.meta.env.VITE_REAL_DATA_INSTANCE === "true";
  const showDemoBanner = Boolean(health?.demo_mode) || usingDevLogin;

  async function handleLogout() {
    setLoggingOut(true);
    try {
      await logoutCurrentSession();
      navigate("/login");
    } finally {
      setLoggingOut(false);
    }
  }

  const renderLink = (item: NavItem) => (
    <NavLink key={item.to} to={item.to} end={item.end} className="nav-link" title={item.label}>
      <Icon name={item.icon} size={20} />
      <span className="nav-link__label">{item.label}</span>
    </NavLink>
  );

  const hasNavPermission = (item: NavItem) => {
    if (!item.permission) return true;
    const codes = Array.isArray(item.permission) ? item.permission : [item.permission];
    return codes.some(can);
  };
  const mainItems = NAV_ITEMS.filter(hasNavPermission);
  const adminItems = ADMIN_NAV_ITEMS.filter(hasNavPermission);
  const mobileTabs = MOBILE_TAB_PATHS.map((path) => mainItems.find((item) => item.to === path)).filter(
    (item): item is NavItem => Boolean(item),
  );

  return (
    <div className="app-shell">
      <a href="#conteudo" className="skip-link">
        Saltar para o conteúdo
      </a>

      <aside className={`sidebar ${menuOpen ? "open" : ""}`} id="menu-principal">
        <NavLink to="/" className="sidebar__brand" aria-label="Op_PM — página inicial">
          <SolcorLogo height={24} />
          <span className="brand-text">
            <span className="brand-name">Operações</span>
            <span className="brand-sub">Gestão de obra</span>
          </span>
        </NavLink>
        <nav className="sidebar__nav" aria-label="Navegação principal">
          {mainItems.map(renderLink)}
          {adminItems.length > 0 && <div className="sidebar__section">Administração</div>}
          {adminItems.map(renderLink)}
        </nav>
        <div className="sidebar__footer">
          {health ? `Ambiente: ${health.app_env}` : "Op_PM"}
          {usesRealOperationalData ? " · dados reais" : health?.demo_mode && " · demonstração"}
        </div>
      </aside>
      <div className={`backdrop ${menuOpen ? "open" : ""}`} onClick={() => setMenuOpen(false)} aria-hidden="true" />

      <div className="main-area">
        {showDemoBanner && (
          <div className="demo-banner" role="note">
            <Icon name="info" size={16} />
            {usesRealOperationalData
              ? "Instância interna — contém dados operacionais reais. As integrações externas continuam inativas."
              : "Modo demonstração — todos os dados apresentados são sintéticos. Nenhuma integração externa está ativa."}
          </div>
        )}
        <header className="topbar">
          <button
            type="button"
            className="btn btn--ghost btn--icon menu-toggle"
            aria-label={menuOpen ? "Fechar menu" : "Abrir menu"}
            aria-expanded={menuOpen}
            aria-controls="menu-principal"
            onClick={() => setMenuOpen((v) => !v)}
          >
            <Icon name={menuOpen ? "x" : "menu"} />
          </button>
          <span className="topbar__title">{pageTitle(location.pathname)}</span>
          <span className="topbar__spacer" />
          <div className="user-chip">
            <span className="user-chip__text">
              <span className="user-chip__name">{displayName}</span>
              {roleLabel && <span className="user-chip__role">{roleLabel}</span>}
            </span>
            <Avatar name={displayName} />
          </div>
          <button
            type="button"
            className="btn btn--ghost btn--icon"
            onClick={handleLogout}
            disabled={loggingOut}
            aria-label="Terminar sessão"
            title="Terminar sessão"
          >
            <Icon name="logout" />
          </button>
        </header>
        <main id="conteudo" className="content" tabIndex={-1} ref={mainRef}>
          {children}
        </main>
      </div>

      <nav className="bottom-nav" aria-label="Navegação rápida">
        {mobileTabs.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.end} className="bottom-nav__link">
            <Icon name={item.icon} size={22} />
            <span>{MOBILE_TAB_LABELS[item.to] ?? item.label}</span>
          </NavLink>
        ))}
        <button
          type="button"
          className={`bottom-nav__link ${menuOpen ? "active" : ""}`}
          aria-expanded={menuOpen}
          aria-controls="menu-principal"
          onClick={() => setMenuOpen((v) => !v)}
        >
          <Icon name="menu" size={22} />
          <span>Mais</span>
        </button>
      </nav>
    </div>
  );
}
