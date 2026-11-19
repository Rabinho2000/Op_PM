// Sino de alarmes de etapas do processo (D-104): contagem de não lidas,
// painel com as últimas notificações e marcação como lida. Só aparece a quem
// tem `process_alert.use`; se a API responder 403 (instalador externo), o
// sino deixa de existir nesta sessão.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, errorMessage } from "../api/client";
import {
  listProcessNotifications,
  getUnreadProcessNotificationCount,
  markAllProcessNotificationsRead,
  markProcessNotificationRead,
} from "../api/processAlerts";
import type { ProcessNotification } from "../api/processAlerts";
import { useSession } from "../session/SessionContext";
import { formatDateTimePt } from "../utils/dates";
import Icon from "./Icon";
import { Alert, EmptyState, ErrorState, LoadingState } from "./ui";
import "./ProcessAlertBell.css";

const POLL_INTERVAL_MS = 60_000;
const PANEL_PAGE_SIZE = 20;

export default function ProcessAlertBell() {
  const { can } = useSession();
  const allowed = can("process_alert.use");
  const [unavailable, setUnavailable] = useState(false);
  const [unread, setUnread] = useState<number | null>(null);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<ProcessNotification[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  const handleError = useCallback((error: unknown) => {
    if (error instanceof ApiError && error.status === 403) {
      setUnavailable(true);
      return true;
    }
    return false;
  }, []);

  const loadCount = useCallback(async () => {
    try {
      const result = await getUnreadProcessNotificationCount();
      setUnread(result.unread);
    } catch (error) {
      handleError(error);
    }
  }, [handleError]);

  const loadItems = useCallback(async () => {
    setListError(null);
    try {
      const page = await listProcessNotifications({ limit: PANEL_PAGE_SIZE, offset: 0 });
      setItems(page.items);
    } catch (error) {
      if (!handleError(error)) setListError(errorMessage(error));
    }
  }, [handleError]);

  // Contagem: carrega ao montar e de 60 em 60 s, sem pedidos com a aba oculta.
  useEffect(() => {
    if (!allowed || unavailable) return undefined;
    void loadCount();
    const refresh = window.setInterval(() => {
      if (document.visibilityState === "visible") void loadCount();
    }, POLL_INTERVAL_MS);
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") void loadCount();
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      window.clearInterval(refresh);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [allowed, unavailable, loadCount]);

  // Painel aberto: lista atualizada ao abrir e fecha com Escape ou clique fora.
  useEffect(() => {
    if (!open) return undefined;
    void loadItems();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    const onPointerDown = (event: MouseEvent) => {
      if (rootRef.current && event.target instanceof Node && !rootRef.current.contains(event.target)) {
        setOpen(false);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("mousedown", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("mousedown", onPointerDown);
    };
  }, [open, loadItems]);

  if (!allowed || unavailable) return null;

  async function markRead(item: ProcessNotification) {
    if (item.is_read || busy) return;
    setBusy(true);
    setActionError(null);
    try {
      const updated = await markProcessNotificationRead(item.id);
      setItems((current) => current?.map((row) => (row.id === updated.id ? updated : row)) ?? null);
      void loadCount();
    } catch (error) {
      if (!handleError(error)) setActionError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function markAll() {
    if (busy) return;
    setBusy(true);
    setActionError(null);
    try {
      await markAllProcessNotificationsRead();
      await Promise.all([loadItems(), loadCount()]);
    } catch (error) {
      if (!handleError(error)) setActionError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  const count = unread ?? 0;
  const label = count > 0 ? `Alarmes do processo, ${count} por ler` : "Alarmes do processo";

  return (
    <div className="process-alert-bell" ref={rootRef}>
      <button
        type="button"
        className="btn btn--ghost btn--icon process-alert-bell__trigger"
        aria-label={label}
        aria-expanded={open}
        aria-controls="process-alert-bell-panel"
        onClick={() => setOpen((current) => !current)}
      >
        <Icon name="bell" size={18} />
        {count > 0 && <span className="process-alert-bell__count">{count > 99 ? "99+" : count}</span>}
      </button>
      {open && (
        <section id="process-alert-bell-panel" className="process-alert-bell__panel" aria-label="Alarmes do processo">
          <header className="process-alert-bell__head">
            <strong>Alarmes do processo</strong>
            <button
              type="button"
              className="btn btn--sm btn--ghost"
              onClick={() => void markAll()}
              disabled={busy || count === 0}
            >
              Marcar todas como lidas
            </button>
          </header>
          {actionError && <Alert tone="danger">{actionError}</Alert>}
          {listError && <ErrorState message={listError} onRetry={() => void loadItems()} />}
          {!listError && items === null && <LoadingState label="A carregar alarmes…" rows={3} />}
          {!listError && items !== null && items.length === 0 && (
            <EmptyState compact icon="bell" title="Sem alarmes." text="Recebe aqui as etapas que subscreveu quando forem concluídas." />
          )}
          {items !== null && items.length > 0 && (
            <ul className="process-alert-bell__list">
              {items.map((item) => (
                <li key={item.id} className={`process-alert-bell__item ${item.is_read ? "" : "process-alert-bell__item--unread"}`}>
                  <div className="process-alert-bell__body">
                    <span>{item.message}</span>
                    <span className="small muted">
                      <time dateTime={item.created_at}>{formatDateTimePt(item.created_at)}</time>
                      {item.is_read ? " · lida" : " · não lida"}
                    </span>
                  </div>
                  <div className="process-alert-bell__actions">
                    {item.project_id && (
                      <Link className="btn btn--sm" to={`/projects/${item.project_id}`} onClick={() => setOpen(false)}>
                        Ver projeto
                      </Link>
                    )}
                    {!item.is_read && (
                      <button type="button" className="btn btn--sm btn--ghost" onClick={() => void markRead(item)} disabled={busy}>
                        Marcar como lida
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
