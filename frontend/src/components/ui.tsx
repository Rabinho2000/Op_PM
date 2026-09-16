// Componentes base da interface (D-051) — só apresentação: nenhum destes
// calcula métricas nem decide permissões; recebem tudo já pronto da API.
import { ReactNode, useEffect, useId, useRef } from "react";
import { Link } from "react-router-dom";
import Icon, { IconName } from "./Icon";

export type Tone = "brand" | "success" | "warning" | "danger" | "info" | "violet" | "neutral";

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions && <div className="page-header__actions">{actions}</div>}
    </header>
  );
}

export function Card({
  title,
  icon,
  tone = "brand",
  actions,
  children,
  flush,
  className,
  titleId,
}: {
  title?: ReactNode;
  icon?: IconName;
  tone?: Tone;
  actions?: ReactNode;
  children: ReactNode;
  flush?: boolean;
  className?: string;
  titleId?: string;
}) {
  const generatedId = useId();
  const headingId = titleId ?? generatedId;
  return (
    <section className={`card ${className ?? ""}`} aria-labelledby={title ? headingId : undefined}>
      {title && (
        <div className="card__header">
          <h2 className="card__title" id={headingId}>
            {icon && (
              <span className={`card__title-icon tone-${tone}`}>
                <Icon name={icon} size={16} />
              </span>
            )}
            {title}
          </h2>
          {actions}
        </div>
      )}
      <div className={flush ? "card__body card__body--flush" : "card__body"}>{children}</div>
    </section>
  );
}

export function StatCard({
  label,
  value,
  icon,
  tone = "brand",
  to,
  alert,
}: {
  label: string;
  value: number;
  icon: IconName;
  tone?: Tone;
  to?: string;
  alert?: boolean;
}) {
  const content = (
    <>
      <span className={`stat__icon tone-${tone}`}>
        <Icon name={icon} size={20} />
      </span>
      <span>
        <span className="stat__value" data-testid={`stat-${label}`}>
          {value}
        </span>
        <span className="stat__label" style={{ display: "block" }}>
          {label}
        </span>
      </span>
    </>
  );
  const className = `card stat ${alert && value > 0 ? "stat--alert" : ""}`;
  if (to) {
    return (
      <Link to={to} className={className} aria-label={`${label}: ${value}`}>
        {content}
      </Link>
    );
  }
  return <div className={className}>{content}</div>;
}

export function Badge({ tone = "neutral", children, dot }: { tone?: Tone; children: ReactNode; dot?: boolean }) {
  return (
    <span className={`badge tone-${tone}`}>
      {dot && <span className="dot" aria-hidden="true" />}
      {children}
    </span>
  );
}

export function ProgressBar({ value, label, large }: { value: number; label?: string; large?: boolean }) {
  const clamped = Math.max(0, Math.min(100, Math.round(value)));
  return (
    <div className={`progress ${large ? "progress--lg" : ""}`}>
      <div
        className="progress__track"
        role="progressbar"
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label ?? "Progresso"}
      >
        <div
          className={`progress__bar ${clamped === 100 ? "progress__bar--done" : ""}`}
          style={{ width: `${clamped}%` }}
        />
      </div>
      <span className="progress__value">{clamped}%</span>
    </div>
  );
}

const ALERT_ICONS: Record<"warning" | "danger" | "info" | "success", IconName> = {
  warning: "alert",
  danger: "alert",
  info: "info",
  success: "checkCircle",
};

export function Alert({
  tone = "info",
  title,
  children,
  action,
}: {
  tone?: "warning" | "danger" | "info" | "success";
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className={`alert alert--${tone}`} role={tone === "danger" ? "alert" : "status"}>
      <Icon name={ALERT_ICONS[tone]} size={20} />
      <div className="alert__body">
        {title && <div className="alert__title">{title}</div>}
        {children && <div>{children}</div>}
      </div>
      {action}
    </div>
  );
}

export function EmptyState({
  title,
  text,
  icon = "checkCircle",
  compact,
  action,
}: {
  title: string;
  text?: ReactNode;
  icon?: IconName;
  compact?: boolean;
  action?: ReactNode;
}) {
  return (
    <div className={`state ${compact ? "state--compact" : ""}`} data-testid="empty-state">
      <span className="state__icon tone-neutral">
        <Icon name={icon} size={22} />
      </span>
      <div className="state__title">{title}</div>
      {text && <div className="state__text">{text}</div>}
      {action}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="state" role="alert" data-testid="error-state">
      <span className="state__icon tone-danger">
        <Icon name="alert" size={22} />
      </span>
      <div className="state__title">Não foi possível carregar os dados</div>
      <div className="state__text">{message}</div>
      {onRetry && (
        <button type="button" className="btn btn--sm" onClick={onRetry}>
          <Icon name="refresh" size={14} /> Tentar novamente
        </button>
      )}
    </div>
  );
}

export function LoadingState({ label = "A carregar…", rows = 3 }: { label?: string; rows?: number }) {
  return (
    <div role="status" aria-live="polite" data-testid="loading-state" style={{ padding: 20 }}>
      <span className="sr-only">{label}</span>
      <div className="stack" aria-hidden="true">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="skeleton" style={{ height: 18, width: `${90 - i * 12}%` }} />
        ))}
      </div>
    </div>
  );
}

export function StatsSkeleton({ count = 10 }: { count?: number }) {
  return (
    <div className="grid grid--stats" aria-hidden="true">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="card skeleton" style={{ height: 82 }} />
      ))}
    </div>
  );
}

export function initials(name: string | null | undefined): string {
  if (!name) return "?";
  const parts = name
    .replace(/[^\p{L}\s]/gu, " ")
    .split(/\s+/)
    .filter(Boolean);
  if (parts.length === 0) return "?";
  const first = parts[0][0] ?? "";
  const last = parts.length > 1 ? parts[parts.length - 1][0] : "";
  return (first + last).toUpperCase();
}

export function Avatar({ name, small }: { name: string | null | undefined; small?: boolean }) {
  return (
    <span className={`avatar ${small ? "avatar--sm" : ""}`} title={name ?? undefined} aria-hidden="true">
      {initials(name)}
    </span>
  );
}

export function Modal({
  title,
  onClose,
  children,
  footer,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const first = dialogRef.current?.querySelector<HTMLElement>("input, select, textarea, button");
    first?.focus();

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onCloseRef.current();
      if (e.key === "Tab" && dialogRef.current) {
        const focusables = dialogRef.current.querySelectorAll<HTMLElement>(
          "a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])"
        );
        if (focusables.length === 0) return;
        const firstEl = focusables[0];
        const lastEl = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === firstEl) {
          e.preventDefault();
          lastEl.focus();
        } else if (!e.shiftKey && document.activeElement === lastEl) {
          e.preventDefault();
          firstEl.focus();
        }
      }
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previouslyFocused?.focus?.();
    };
  }, []);

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby={titleId} ref={dialogRef}>
        <div className="modal__head">
          <h2 id={titleId}>{title}</h2>
          <button type="button" className="btn btn--ghost btn--icon" onClick={onClose} aria-label="Fechar">
            <Icon name="x" />
          </button>
        </div>
        <div className="modal__body">{children}</div>
        {footer && <div className="modal__foot">{footer}</div>}
      </div>
    </div>
  );
}
