// Estrutura das páginas autenticadas: sidebar de navegação, cabeçalho com
// o utilizador atual, banner do modo demonstração e área de conteúdo.
import { ReactNode, useEffect, useRef, useState, MouseEvent as ReactMouseEvent } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { SolcorLogo } from "./SolcorLogo";
import { getDevUser, getSessionDisplayName, logoutCurrentSession } from "../api/client";
import { getRequestsSummary } from "../api/requests";
import { useSession } from "../session/SessionContext";
import { isInstallerCollaborator } from "../session/installerAccess";
import Icon, { IconName } from "./Icon";
import { Avatar } from "./ui";
import { observeTableCardLabels } from "./tableCardLabels";
import ThemeToggle from "./ThemeToggle";
import RequestsWidget from "./RequestsWidget";
import ProcessAlertBell from "./ProcessAlertBell";

interface NavItem {
  to: string;
  label: string;
  icon: IconName;
  // Só aparece a quem tem pelo menos uma destas permissões (o servidor
  // volta sempre a validar em cada pedido — isto é só para não mostrar um
  // link que levaria a um 403).
  permission?: string | string[];
  roles?: string[];
  end?: boolean;
}

interface RailTooltip {
  target: string;
  text: string;
  left: number;
  top: number;
}

export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Painel", icon: "dashboard", end: true },
  { to: "/projects", label: "Projetos", icon: "folder", permission: ["project.view_all", "project.view_own", "project.view_assigned_installer"] },
  { to: "/client-reports", label: "Relatórios a clientes", icon: "fileText", permission: ["client_report.view", "client_report.manage"] },
  { to: "/tasks", label: "Tarefas", icon: "tasks", permission: ["task.view_all", "task.view_own", "task.view_assigned_installer"] },
  { to: "/inventory", label: "Inventário", icon: "database", permission: ["inventory.view", "inventory.view_assigned_installer"] },
  { to: "/suppliers", label: "Fornecedores", icon: "truck", permission: ["supplier.view", "map.view"] },
  { to: "/map", label: "Mapa", icon: "mapPin", permission: "map.view" },
  { to: "/works", label: "Calendário de obras", icon: "columns", permission: ["project.view_all", "project.view_own", "works_calendar.view_assigned_installer"] },
  { to: "/works/teams", label: "Equipas", icon: "users", permission: ["project.view_all", "project.view_own", "installer_team.view_assigned_installer"] },
  { to: "/planning", label: "Planeamento", icon: "calendar", permission: "calendar.view" },
  {
    to: "/performance",
    label: "Metas e indicadores",
    icon: "flag",
    permission: ["performance.view_all", "performance.view_own"],
  },
  { to: "/vacations", label: "Férias e aniversários", icon: "plane" },
  { to: "/time-bank", label: "Banco de Horas", icon: "clock", permission: ["time_bank.view_own", "time_bank.view_all"] },
  { to: "/requests", label: "Pedidos", icon: "inbox", permission: "requests.manage" },
  { to: "/alerts", label: "Alertas", icon: "bell", permission: "process_alert.use" },
  { to: "/my-process", label: "As minhas etapas", icon: "listCheck", permission: ["process.view_own", "process.update_own"], roles: ["suporte_operacoes"] },
  // O backend autoriza Administrador e Chefe de Operações por papel, mesmo
  // quando o segundo não tem a permissão administrativa genérica.
  { to: "/support", label: "Suporte de operações", icon: "user", permission: "admin.manage_users", roles: ["admin", "administrador", "chefe_operacoes"] },
];

export const ADMIN_NAV_ITEMS: NavItem[] = [
  { to: "/installers", label: "Instaladores", icon: "hardHat", permission: "installer.manage" },
  { to: "/reconciliation", label: "Reconciliação de PM", icon: "link", permission: "migration.view" },
  { to: "/status", label: "Estado do sistema", icon: "activity" },
];

// Barra inferior no telemóvel (D-079): os destinos de uso diário. O resto
// continua acessível em "Mais", que abre a gaveta com o menu completo.
export const MOBILE_TAB_PATHS = ["/", "/projects", "/tasks", "/planning"];

const MOBILE_TAB_LABELS: Record<string, string> = { "/planning": "Agenda" };
export const NAV_RAIL_STORAGE_PREFIX = "op_pm_nav_rail_expanded_v1:";

function readNavRailExpanded(accountKey: string): boolean {
  try {
    return typeof window !== "undefined" && window.localStorage.getItem(`${NAV_RAIL_STORAGE_PREFIX}${accountKey}`) === "true";
  } catch {
    return false;
  }
}

function persistNavRailExpanded(accountKey: string, expanded: boolean): void {
  try {
    window.localStorage.setItem(`${NAV_RAIL_STORAGE_PREFIX}${accountKey}`, String(expanded));
  } catch {
    // A indisponibilidade do armazenamento local não deve bloquear a navegação.
  }
}

const INSTALLER_NAV_PATHS = new Set([
  "/projects",
  "/tasks",
  "/inventory",
  "/works",
  "/works/teams",
  "/time-bank",
]);

const EXACT_PAGE_TITLES: Record<string, string> = {
  "/projects/import": "Importar notas iniciais",
  "/projects/deleted": "Projetos apagados",
};

const PAGE_TITLES: [string, string][] = [
  ["/projects/", "Detalhe do projeto"],
  ["/projects", "Projetos"],
  ["/client-reports", "Relatórios a clientes"],
  ["/tasks", "Tarefas"],
  ["/inventory", "Inventário"],
  ["/suppliers", "Fornecedores"],
  ["/works/teams", "Equipas"],
  ["/works", "Calendário de obras"],
  ["/installers", "Instaladores"],
  ["/map", "Mapa"],
  ["/planning", "Planeamento"],
  ["/performance", "Metas e indicadores"],
  ["/vacations", "Férias e aniversários"],
  ["/time-bank", "Banco de Horas"],
  ["/requests", "Pedidos"],
  ["/alerts", "Alertas"],
  ["/my-process", "As minhas etapas"],
  ["/support", "Suporte de operações"],
  ["/reconciliation", "Reconciliação de PM"],
  ["/status", "Estado do sistema"],
];

function pageTitle(pathname: string): string {
  if (pathname === "/") return "Painel de operações";
  const exactTitle = EXACT_PAGE_TITLES[pathname];
  if (exactTitle) return exactTitle;
  return PAGE_TITLES.find(([prefix]) => pathname.startsWith(prefix))?.[1] ?? "Solcor Operações";
}

export default function Layout({ children }: { children: ReactNode }) {
  const { me, health, can } = useSession();
  const navigate = useNavigate();
  const location = useLocation();
  const isCableEditor = /^\/projects\/[^/]+\/cables\/[^/]+$/.test(location.pathname);
  const accountKey = me?.user_id ?? me?.email ?? "anonymous";
  const [railExpanded, setRailExpanded] = useState(() => readNavRailExpanded(accountKey));
  const [menuOpen, setMenuOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const [openRequestCount, setOpenRequestCount] = useState<number | null>(null);
  const [railTooltip, setRailTooltip] = useState<RailTooltip | null>(null);
  const menuTriggerRef = useRef<HTMLButtonElement | null>(null);
  const railNavRef = useRef<HTMLElement | null>(null);

  const closeMenu = () => {
    setMenuOpen(false);
    menuTriggerRef.current?.focus();
  };

  const toggleMenu = (event: ReactMouseEvent<HTMLButtonElement>) => {
    menuTriggerRef.current = event.currentTarget;
    setMenuOpen((current) => !current);
  };

  const toggleRail = () => {
    const next = !railExpanded;
    setRailTooltip(null);
    setRailExpanded(next);
    persistNavRailExpanded(accountKey, next);
  };

  const mainRef = useRef<HTMLElement>(null);

  useEffect(() => setRailExpanded(readNavRailExpanded(accountKey)), [accountKey]);
  useEffect(() => setMenuOpen(false), [location.pathname]);
  useEffect(() => setRailTooltip(null), [location]);

  useEffect(() => {
    if (!railTooltip) return undefined;
    const dismissOrRepositionTooltip = () => {
      const focusedElement = document.activeElement;
      if (
        !(focusedElement instanceof HTMLAnchorElement) ||
        !focusedElement.classList.contains("nav-link") ||
        !railNavRef.current?.contains(focusedElement) ||
        focusedElement.getAttribute("href") !== railTooltip.target
      ) {
        setRailTooltip(null);
        return;
      }
      const focusedLink = focusedElement;

      window.requestAnimationFrame(() => {
        const navRect = railNavRef.current?.getBoundingClientRect();
        if (!navRect || document.activeElement !== focusedLink) return;

        const targetRect = focusedLink.getBoundingClientRect();
        const isVisibleInRail =
          targetRect.right > navRect.left &&
          targetRect.left < navRect.right &&
          targetRect.bottom > navRect.top &&
          targetRect.top < navRect.bottom;

        if (!isVisibleInRail) {
          setRailTooltip((current) => (current?.target === railTooltip.target ? null : current));
          return;
        }

        setRailTooltip((current) =>
          current?.target === railTooltip.target
            ? { ...current, left: targetRect.right + 9, top: targetRect.top + targetRect.height / 2 }
            : current
        );
      });
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setRailTooltip(null);
    };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("scroll", dismissOrRepositionTooltip, true);
    window.addEventListener("resize", dismissOrRepositionTooltip);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("scroll", dismissOrRepositionTooltip, true);
      window.removeEventListener("resize", dismissOrRepositionTooltip);
    };
  }, [railTooltip]);

  const canManageRequests = can("requests.manage");

  useEffect(() => {
    if (!canManageRequests) {
      setOpenRequestCount(null);
      return undefined;
    }
    let active = true;
    const loadSummary = () => {
      getRequestsSummary()
        .then((summary) => {
          if (active) setOpenRequestCount(summary.open);
        })
        .catch(() => {
          // A contagem é informativa; a falha não deve perturbar a navegação.
        });
    };
    loadSummary();
    const refresh = window.setInterval(() => {
      if (document.visibilityState === "visible") loadSummary();
    }, 60_000);
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") loadSummary();
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      active = false;
      window.clearInterval(refresh);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [canManageRequests]);

  useEffect(() => {
    if (!menuOpen) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      const target = event.target instanceof Element ? event.target : null;
      const activeElement = document.activeElement instanceof Element ? document.activeElement : null;
      const dialogOpen = document.querySelector('[role="dialog"], [aria-modal="true"], .multiselect[open]');
      if (dialogOpen || target?.closest('select, .multiselect') || activeElement?.closest('select, .multiselect')) return;
      event.preventDefault();
      closeMenu();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [menuOpen]);

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
  const usesRealOperationalData =
    health?.demo_real_data === true || import.meta.env.VITE_REAL_DATA_INSTANCE === "true";
  const showDemoBanner = Boolean(health?.demo_mode) || usingDevLogin || usesRealOperationalData;

  async function handleLogout() {
    setLoggingOut(true);
    try {
      await logoutCurrentSession();
      navigate("/login");
    } finally {
      setLoggingOut(false);
    }
  }

  const showRailTooltip = (target: HTMLElement, targetKey: string, text: string) => {
    if (railExpanded) return;
    const rect = target.getBoundingClientRect();
    setRailTooltip({
      target: targetKey,
      text,
      left: rect.right + 9,
      top: rect.top + rect.height / 2,
    });
  };

  const hideRailTooltip = (targetKey: string) => {
    setRailTooltip((current) => (current?.target === targetKey ? null : current));
  };

  const renderLink = (item: NavItem) => {
    const hasOpenRequestCount = item.to === "/requests" && openRequestCount !== null && openRequestCount > 0;
    const accessibleLabel = hasOpenRequestCount
      ? `${item.label}, ${openRequestCount} pedidos abertos`
      : item.label;

    return (
      <NavLink
        key={item.to}
        to={item.to}
        end={item.end}
        className="nav-link"
        aria-label={accessibleLabel}
        data-icon={item.icon}
        aria-describedby={railTooltip?.target === item.to ? "sidebar-tooltip" : undefined}
        data-tooltip={item.label}
        onFocus={(event) => showRailTooltip(event.currentTarget, item.to, item.label)}
        onBlur={() => hideRailTooltip(item.to)}
        onClick={() => setRailTooltip(null)}
        onMouseEnter={(event) => showRailTooltip(event.currentTarget, item.to, item.label)}
        onMouseLeave={() => hideRailTooltip(item.to)}
      >
        <Icon name={item.icon} size={20} />
        <span className="nav-link__label">{item.label}</span>
        {hasOpenRequestCount && (
          <span className="nav-link__badge" aria-hidden="true">
            {openRequestCount}
          </span>
        )}
      </NavLink>
    );
  };

  const hasNavPermission = (item: NavItem) => {
    if (isInstallerCollaborator(me) && !INSTALLER_NAV_PATHS.has(item.to)) return false;
    if (item.roles?.some((role) => me?.roles.includes(role))) return true;
    if (!item.permission) return true;
    const codes = Array.isArray(item.permission) ? item.permission : [item.permission];
    return codes.some(can);
  };
  const mainItems = NAV_ITEMS.filter((item) => !(isInstallerCollaborator(me) && item.to === "/")).filter(hasNavPermission);
  const adminItems = ADMIN_NAV_ITEMS.filter(hasNavPermission);
  const mobilePaths = isInstallerCollaborator(me) ? ["/", "/projects", "/tasks", "/works"] : MOBILE_TAB_PATHS;
  const mobileTabs = mobilePaths.map((path) => mainItems.find((item) => item.to === path)).filter(
    (item): item is NavItem => Boolean(item),
  );

  const environmentName = health ? `Ambiente: ${health.app_env}` : "Op_PM";
  const environmentDetails = usesRealOperationalData
    ? `${environmentName} · dados reais`
    : health?.demo_mode
      ? `${environmentName} · demonstração`
      : environmentName;

  return (
    <div className={`app-shell ${railExpanded ? "app-shell--sidebar-expanded" : ""}`}>
      <a href="#conteudo" className="skip-link">
        Saltar para o conteúdo
      </a>

      <aside
        className={`sidebar ${railExpanded ? "sidebar--expanded" : "sidebar--compact"} ${menuOpen ? "open" : ""}`}
        id="menu-principal"
      >
        <NavLink to="/" className="sidebar__brand" aria-label="Op_PM — página inicial">
          <SolcorLogo height={24} />
          <span className="brand-text">
            <span className="brand-name">Operações</span>
            <span className="brand-sub">Gestão de obra</span>
          </span>
        </NavLink>
        <nav className="sidebar__nav" aria-label="Navegação principal" ref={railNavRef}>
          {mainItems.map(renderLink)}
          {adminItems.length > 0 && (
            <div className="sidebar__section" role="separator" aria-label="Administração">
              <span className="sidebar__section-label">Administração</span>
            </div>
          )}
          {adminItems.map(renderLink)}
        </nav>
        <div className="sidebar__footer">
          <button
            type="button"
            className="sidebar__collapse"
            aria-label={railExpanded ? "Recolher navegação" : "Expandir navegação"}
            aria-expanded={railExpanded}
            aria-controls="menu-principal"
            aria-describedby={railTooltip?.target === "sidebar-collapse" ? "sidebar-tooltip" : undefined}
            data-tooltip={railExpanded ? "Recolher navegação" : "Expandir navegação"}
            onFocus={(event) => showRailTooltip(event.currentTarget, "sidebar-collapse", railExpanded ? "Recolher navegação" : "Expandir navegação")}
            onBlur={() => hideRailTooltip("sidebar-collapse")}
            onMouseEnter={(event) => showRailTooltip(event.currentTarget, "sidebar-collapse", railExpanded ? "Recolher navegação" : "Expandir navegação")}
            onMouseLeave={() => hideRailTooltip("sidebar-collapse")}
            onClick={toggleRail}
          >
            <Icon name={railExpanded ? "chevronLeft" : "chevronRight"} size={18} />
            <span className="sidebar__collapse-label">{railExpanded ? "Recolher navegação" : "Expandir navegação"}</span>
          </button>
          <div className="sidebar__environment" aria-hidden="true" title={environmentDetails}>
            <Icon name="info" size={16} />
            <span className="sidebar__environment-text">{environmentDetails}</span>
          </div>
        </div>
      </aside>
      {railTooltip && !railExpanded && (
        <div
          id="sidebar-tooltip"
          className="sidebar-tooltip"
          role="tooltip"
          style={{ left: `${railTooltip.left}px`, top: `${railTooltip.top}px` }}
        >
          {railTooltip.text}
        </div>
      )}
      <div className={`backdrop ${menuOpen ? "open" : ""}`} onClick={closeMenu} aria-hidden="true" />

      <div className={`main-area ${isCableEditor ? "main-area--full-screen" : ""}`}>
        {showDemoBanner && (
          <div className="demo-banner" role="note">
            <Icon name="info" size={16} />
            {usesRealOperationalData
              ? "Instância interna — contém dados operacionais reais. As integrações externas continuam inativas."
              : "Modo demonstração — todos os dados apresentados são sintéticos. Nenhuma integração externa está ativa."}
          </div>
        )}
        <header className="topbar">
          <span className="topbar__title">{pageTitle(location.pathname)}</span>
          <span className="topbar__spacer" />
          <ProcessAlertBell />
          <RequestsWidget />
          <ThemeToggle accessibleName="Aparência no cabeçalho" className="theme-toggle--header" />
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
        <main id="conteudo" className={`content ${isCableEditor ? "content--full-screen" : ""}`} tabIndex={-1} ref={mainRef}>
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
          aria-label="Mais"
          aria-expanded={menuOpen}
          aria-controls="menu-principal"
          onClick={toggleMenu}
        >
          <Icon name={menuOpen ? "x" : "menu"} size={22} />
          <span>Mais</span>
        </button>
      </nav>
    </div>
  );
}
