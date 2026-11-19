import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  getRequest,
  listRequests,
  postRequestMessage,
  setRequestStatus,
} from "../api/requests";
import type {
  RequestListPage,
  RequestListStatus,
  RequestMessage,
  RequestThread,
} from "../api/requests";
import { errorMessage } from "../api/client";
import { Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader } from "../components/ui";
import { formatDateTimePt } from "../utils/dates";
import { useSession } from "../session/SessionContext";
import "./Requests.css";

const REQUEST_PAGE_SIZE = 50;

function statusLabel(status: "open" | "resolved"): string {
  return status === "open" ? "Aberto" : "Resolvido";
}

function statusTone(status: "open" | "resolved"): "success" | "neutral" {
  return status === "open" ? "success" : "neutral";
}

function Message({ message }: { message: RequestMessage }) {
  const author = message.is_staff_reply ? "Equipa" : message.is_mine ? "Tu" : message.author_name;
  return (
    <li className={`requests-page__message ${message.is_staff_reply ? "requests-page__message--staff" : ""}`}>
      <div className="requests-page__message-meta">
        <strong>{author}</strong>
        <time dateTime={message.created_at}>{formatDateTimePt(message.created_at)}</time>
      </div>
      <p>{message.body}</p>
    </li>
  );
}

export default function Requests() {
  const { can } = useSession();
  const canManage = can("requests.manage");
  const [status, setStatus] = useState<RequestListStatus>("open");
  const [list, setList] = useState<RequestListPage | null>(null);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [thread, setThread] = useState<RequestThread | null>(null);
  const [threadLoading, setThreadLoading] = useState(false);
  const [threadError, setThreadError] = useState<string | null>(null);
  const [reply, setReply] = useState("");
  const [replyError, setReplyError] = useState<string | null>(null);
  const [replying, setReplying] = useState(false);
  const [statusSaving, setStatusSaving] = useState(false);

  const loadList = useCallback(async () => {
    setListLoading(true);
    setListError(null);
    try {
      setList(await listRequests({ scope: "all", status, limit: REQUEST_PAGE_SIZE, offset: 0 }));
    } catch (error) {
      setListError(errorMessage(error));
    } finally {
      setListLoading(false);
    }
  }, [status]);

  useEffect(() => {
    setSelectedId(null);
    setThread(null);
    setThreadError(null);
    void loadList();
  }, [loadList]);

  if (!canManage) return <ErrorState message="Não tem permissão para ver a caixa de pedidos." />;

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
      setThreadError(errorMessage(error));
    } finally {
      setThreadLoading(false);
    }
  }

  async function refreshThread(id: string) {
    try {
      setThread(await getRequest(id));
    } catch (error) {
      setThreadError(errorMessage(error));
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
      await refreshThread(selectedId);
      await loadList();
    } catch (error) {
      setReplyError(errorMessage(error));
    } finally {
      setReplying(false);
    }
  }

  async function changeStatus(nextStatus: "open" | "resolved") {
    if (!selectedId || statusSaving) return;
    setStatusSaving(true);
    setReplyError(null);
    try {
      const updated = await setRequestStatus(selectedId, nextStatus);
      if (updated) setThread(updated);
      else await refreshThread(selectedId);
      await loadList();
    } catch (error) {
      setReplyError(errorMessage(error));
    } finally {
      setStatusSaving(false);
    }
  }

  return (
    <div className="requests-page">
      <PageHeader title="Pedidos" subtitle="Caixa de entrada dos pedidos enviados à equipa de operações." />
      <div className="requests-page__layout">
        <Card
          title="Pedidos recebidos"
          icon="mail"
          actions={
            <label className="requests-page__filter">
              <span>Filtrar por estado</span>
              <select
                className="select select--compact"
                aria-label="Filtrar por estado"
                value={status}
                onChange={(event) => setStatus(event.target.value as RequestListStatus)}
              >
                <option value="open">Abertos</option>
                <option value="resolved">Resolvidos</option>
                <option value="all">Todos</option>
              </select>
            </label>
          }
        >
          {listLoading && !list && <LoadingState label="A carregar pedidos…" rows={5} />}
          {listError && <ErrorState message={listError} onRetry={() => void loadList()} />}
          {!listLoading && !listError && list && list.items.length === 0 && (
            <EmptyState compact icon="mail" title="Não há pedidos neste filtro." />
          )}
          {list && list.items.length > 0 && (
            <ul className="requests-page__list">
              {list.items.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    className={`requests-page__item ${selectedId === item.id ? "requests-page__item--selected" : ""}`}
                    aria-pressed={selectedId === item.id}
                    onClick={() => void openThread(item.id)}
                  >
                    <span className="requests-page__item-main">
                      <strong>{item.last_message_preview}</strong>
                      <span className="small muted">
                        {item.author_name} · {formatDateTimePt(item.updated_at)}
                      </span>
                      <span className="small muted">{item.page_path ?? "Página não indicada"}</span>
                    </span>
                    <span className="requests-page__item-aside">
                      <Badge tone={statusTone(item.status)}>{statusLabel(item.status)}</Badge>
                      <span className="small muted">{item.message_count} {item.message_count === 1 ? "mensagem" : "mensagens"}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Conversa" icon="mail" className="requests-page__conversation-card">
          {!selectedId && <EmptyState compact icon="mail" title="Seleciona um pedido." text="A conversa aparecerá aqui." />}
          {selectedId && threadLoading && <LoadingState label="A carregar conversa…" rows={4} />}
          {selectedId && threadError && <ErrorState message={threadError} onRetry={() => void openThread(selectedId)} />}
          {thread && (
            <div className="requests-page__conversation">
              <div className="requests-page__conversation-head">
                <div>
                  <strong>{thread.author_name}</strong>
                  <span className="small muted">
                    {thread.page_path ?? "Página não indicada"} · criado {formatDateTimePt(thread.created_at)}
                  </span>
                </div>
                <Badge tone={statusTone(thread.status)}>{statusLabel(thread.status)}</Badge>
              </div>
              <ol className="requests-page__messages">
                {thread.messages.map((message) => <Message key={message.id} message={message} />)}
              </ol>
              {replyError && <p className="requests-page__action-error" role="alert">{replyError}</p>}
              <form className="requests-page__reply" onSubmit={submitReply}>
                <label className="field" htmlFor="requests-page-reply">
                  <span className="field__label">Responder ao pedido</span>
                  <textarea
                    id="requests-page-reply"
                    className="textarea"
                    maxLength={2000}
                    value={reply}
                    onChange={(event) => setReply(event.target.value)}
                    placeholder="Escreve uma resposta…"
                  />
                </label>
                <div className="button-row">
                  <button type="submit" className="btn btn--primary" disabled={replying || !reply.trim()}>
                    {replying ? "A enviar…" : "Enviar resposta"}
                  </button>
                  {thread.status === "open" ? (
                    <button type="button" className="btn" disabled={statusSaving} onClick={() => void changeStatus("resolved")}>
                      {statusSaving ? "A guardar…" : "Marcar como resolvido"}
                    </button>
                  ) : (
                    <button type="button" className="btn" disabled={statusSaving} onClick={() => void changeStatus("open")}>
                      {statusSaving ? "A guardar…" : "Reabrir"}
                    </button>
                  )}
                </div>
              </form>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
