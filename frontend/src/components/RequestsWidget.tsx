import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  createRequest,
  getRequest,
  listRequests,
  postRequestMessage,
} from "../api/requests";
import type { RequestListPage, RequestMessage, RequestThread } from "../api/requests";
import { ApiError } from "../api/client";
import Icon from "./Icon";
import { Alert, Badge, EmptyState, ErrorState, LoadingState, Modal } from "./ui";
import { useSession } from "../session/SessionContext";
import { formatDateTimePt } from "../utils/dates";
import "./RequestsWidget.css";

const REQUEST_PAGE_SIZE = 50;
type WidgetTab = "new" | "mine";

function apiErrorMessage(error: unknown): string {
  return error instanceof ApiError ? error.detail : "Não foi possível contactar o servidor.";
}

function statusLabel(status: RequestThread["status"]): string {
  return status === "open" ? "Aberto" : "Resolvido";
}

function statusTone(status: RequestThread["status"]): "success" | "neutral" {
  return status === "open" ? "success" : "neutral";
}

function RequestStatusBadge({ status }: { status: RequestThread["status"] }) {
  return <Badge tone={statusTone(status)}>{statusLabel(status)}</Badge>;
}

function Message({ message }: { message: RequestMessage }) {
  const author = message.is_staff_reply ? "Equipa" : message.is_mine ? "Tu" : message.author_name;
  return (
    <li className={`requests-widget__message ${message.is_staff_reply ? "requests-widget__message--staff" : ""}`}>
      <div className="requests-widget__message-meta">
        <strong>{author}</strong>
        <time dateTime={message.created_at}>{formatDateTimePt(message.created_at)}</time>
      </div>
      <p>{message.body}</p>
    </li>
  );
}

export default function RequestsWidget() {
  const { can } = useSession();
  const canCreate = can("requests.create");
  const canManage = can("requests.manage");
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<WidgetTab>("new");
  const [body, setBody] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [mine, setMine] = useState<RequestListPage | null>(null);
  const [mineLoading, setMineLoading] = useState(false);
  const [mineError, setMineError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [thread, setThread] = useState<RequestThread | null>(null);
  const [threadLoading, setThreadLoading] = useState(false);
  const [threadError, setThreadError] = useState<string | null>(null);
  const [reply, setReply] = useState("");
  const [replyError, setReplyError] = useState<string | null>(null);
  const [replying, setReplying] = useState(false);

  const loadMine = useCallback(async () => {
    setMineLoading(true);
    setMineError(null);
    try {
      setMine(await listRequests({ scope: "mine", status: "all", limit: REQUEST_PAGE_SIZE, offset: 0 }));
    } catch (error) {
      setMineError(apiErrorMessage(error));
    } finally {
      setMineLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!canCreate || !open || tab !== "mine") return undefined;
    void loadMine();
    const refresh = window.setInterval(() => {
      if (document.visibilityState === "visible") void loadMine();
    }, 60_000);
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") void loadMine();
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      window.clearInterval(refresh);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [canCreate, loadMine, open, tab]);

  if (!canCreate) return null;

  function close() {
    setOpen(false);
    setSelectedId(null);
    setThread(null);
    setReply("");
  }

  function selectTab(nextTab: WidgetTab) {
    setTab(nextTab);
    setNotice(null);
    setFormError(null);
    if (nextTab === "mine") {
      setSelectedId(null);
      setThread(null);
      setThreadError(null);
    }
  }

  async function submitRequest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = body.trim();
    if (!trimmed || saving) return;
    setSaving(true);
    setFormError(null);
    setNotice(null);
    try {
      await createRequest({ body: trimmed, page_path: window.location.pathname });
      setBody("");
      setNotice("Pedido enviado.");
    } catch (error) {
      setFormError(apiErrorMessage(error));
    } finally {
      setSaving(false);
    }
  }

  async function openThread(id: string) {
    setSelectedId(id);
    setThread(null);
    setThreadError(null);
    setReplyError(null);
    setReply("");
    setThreadLoading(true);
    try {
      setThread(await getRequest(id));
    } catch (error) {
      setThreadError(apiErrorMessage(error));
    } finally {
      setThreadLoading(false);
    }
  }

  async function submitReply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedId || !reply.trim() || replying) return;
    setReplying(true);
    setReplyError(null);
    try {
      await postRequestMessage(selectedId, reply.trim());
      setReply("");
      await openThread(selectedId);
      void loadMine();
    } catch (error) {
      setReplyError(apiErrorMessage(error));
    } finally {
      setReplying(false);
    }
  }

  const dialogBody = selectedId ? (
    <div className="requests-widget__thread-view">
      <button
        type="button"
        className="btn btn--sm btn--ghost requests-widget__back"
        onClick={() => {
          setSelectedId(null);
          setThread(null);
        }}
      >
        <Icon name="arrowLeft" size={15} /> Voltar aos meus pedidos
      </button>
      {threadLoading && <LoadingState label="A carregar conversa…" rows={3} />}
      {threadError && <ErrorState message={threadError} onRetry={() => void openThread(selectedId)} />}
      {thread && (
        <>
          <div className="requests-widget__thread-head">
            <div>
              <strong>{thread.messages[0]?.body ?? "Pedido"}</strong>
              <span className="small muted">
                {thread.page_path ?? "Página não indicada"} · {formatDateTimePt(thread.created_at)}
              </span>
            </div>
            <RequestStatusBadge status={thread.status} />
          </div>
          <ol className="requests-widget__messages">
            {thread.messages.map((message) => <Message key={message.id} message={message} />)}
          </ol>
          {replyError && <Alert tone="danger">{replyError}</Alert>}
          <form className="requests-widget__reply" onSubmit={submitReply}>
            <label className="field" htmlFor="requests-widget-reply">
              <span className="field__label">Responder</span>
              <textarea
                id="requests-widget-reply"
                className="textarea"
                maxLength={2000}
                value={reply}
                onChange={(event) => setReply(event.target.value)}
                placeholder="Escreve uma resposta…"
              />
            </label>
            <button type="submit" className="btn btn--primary" disabled={replying || !reply.trim()}>
              {replying ? "A enviar…" : "Enviar resposta"}
            </button>
          </form>
        </>
      )}
    </div>
  ) : tab === "new" ? (
    <div className="requests-widget__new">
      {notice && <Alert tone="success">{notice}</Alert>}
      {formError && <Alert tone="danger">{formError}</Alert>}
      <form onSubmit={submitRequest}>
        <label className="field" htmlFor="requests-widget-body">
          <span className="field__label">Descreve o pedido</span>
          <textarea
            id="requests-widget-body"
            className="textarea"
            maxLength={2000}
            value={body}
            onChange={(event) => setBody(event.target.value)}
            placeholder="O que precisas de esclarecer?"
            aria-describedby="requests-widget-counter"
          />
        </label>
        <div className="requests-widget__form-foot">
          <span id="requests-widget-counter" className="small muted">{body.length}/2000</span>
          <button type="submit" className="btn btn--primary" disabled={saving || !body.trim()}>
            {saving ? "A enviar…" : "Enviar"}
          </button>
        </div>
      </form>
      {canManage && (
        <Link className="requests-widget__inbox-link" to="/requests" onClick={close}>
          Abrir caixa de pedidos
        </Link>
      )}
    </div>
  ) : (
    <div className="requests-widget__mine">
      {mineLoading && !mine && <LoadingState label="A carregar pedidos…" rows={3} />}
      {mineError && <ErrorState message={mineError} onRetry={() => void loadMine()} />}
      {!mineLoading && !mineError && mine && mine.items.length === 0 && (
        <EmptyState compact icon="mail" title="Ainda não tens pedidos." text="Os teus pedidos e respostas aparecerão aqui." />
      )}
      {mine && mine.items.length > 0 && (
        <ul className="requests-widget__request-list">
          {mine.items.map((item) => (
            <li key={item.id}>
              <button type="button" className="requests-widget__request" onClick={() => void openThread(item.id)}>
                <span className="requests-widget__request-main">
                  <strong>{item.last_message_preview}</strong>
                  <span className="small muted">{item.page_path ?? "Página não indicada"} · {formatDateTimePt(item.updated_at)}</span>
                </span>
                <span className="requests-widget__request-aside">
                  <RequestStatusBadge status={item.status} />
                  <span className="small muted">{item.message_count} {item.message_count === 1 ? "mensagem" : "mensagens"}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {canManage && (
        <Link className="requests-widget__inbox-link" to="/requests" onClick={close}>
          Abrir caixa de pedidos
        </Link>
      )}
    </div>
  );

  return (
    <div className="requests-widget">
      <button
        type="button"
        className="requests-widget__trigger"
        aria-label="Pedidos"
        onClick={() => {
          setOpen(true);
          setTab("new");
          setNotice(null);
        }}
      >
        <Icon name="mail" size={20} />
        <span>Pedidos</span>
      </button>
      {open && (
        <Modal title="Pedidos" onClose={close}>
          <div className="requests-widget__panel">
            <div className="tabs requests-widget__tabs" role="tablist" aria-label="Pedidos">
              <button
                type="button"
                role="tab"
                className="tab"
                aria-selected={tab === "new"}
                aria-controls="requests-widget-new"
                onClick={() => selectTab("new")}
              >
                Novo pedido
              </button>
              <button
                type="button"
                role="tab"
                className="tab"
                aria-selected={tab === "mine"}
                aria-controls="requests-widget-mine"
                onClick={() => selectTab("mine")}
              >
                Os meus pedidos
              </button>
            </div>
            <div id={tab === "new" ? "requests-widget-new" : "requests-widget-mine"} role="tabpanel">
              {dialogBody}
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
