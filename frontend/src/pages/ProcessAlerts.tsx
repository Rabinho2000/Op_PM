// Página «Alertas» (D-104): escolha das etapas do catálogo de que o utilizador
// quer ser avisado (gravado com PUT, substitui o conjunto completo) e histórico
// das notificações in-app com filtro «não lidas».
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  getAlertSubscriptions,
  listProcessNotifications,
  markAllProcessNotificationsRead,
  markProcessNotificationRead,
  saveAlertSubscriptions,
} from "../api/processAlerts";
import type { AlertPhase, ProcessNotification } from "../api/processAlerts";
import { Alert, Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader } from "../components/ui";
import { formatDateTimePt } from "../utils/dates";
import "./ProcessAlerts.css";

const HISTORY_PAGE_SIZE = 50;

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.detail : fallback;
}

export default function ProcessAlerts() {
  const [phases, setPhases] = useState<AlertPhase[] | null>(null);
  const [savedIds, setSavedIds] = useState<Set<string>>(new Set());
  const [draftIds, setDraftIds] = useState<Set<string>>(new Set());
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveNotice, setSaveNotice] = useState<string | null>(null);

  const [unreadOnly, setUnreadOnly] = useState(false);
  const [history, setHistory] = useState<ProcessNotification[] | null>(null);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyBusy, setHistoryBusy] = useState(false);

  const loadCatalog = useCallback(async () => {
    setCatalogError(null);
    try {
      const data = await getAlertSubscriptions();
      const subscribed = new Set(
        data.phases.flatMap((phase) => phase.stages.filter((s) => s.subscribed).map((s) => s.id)),
      );
      setPhases(data.phases);
      setSavedIds(subscribed);
      setDraftIds(new Set(subscribed));
    } catch (error) {
      setCatalogError(errorMessage(error, "Não foi possível carregar as etapas."));
    }
  }, []);

  const loadHistory = useCallback(async (onlyUnread: boolean) => {
    setHistoryBusy(true);
    setHistoryError(null);
    try {
      const page = await listProcessNotifications({
        unread_only: onlyUnread,
        limit: HISTORY_PAGE_SIZE,
        offset: 0,
      });
      setHistory(page.items);
      setHistoryTotal(page.total);
    } catch (error) {
      setHistoryError(errorMessage(error, "Não foi possível carregar o histórico."));
    } finally {
      setHistoryBusy(false);
    }
  }, []);

  useEffect(() => {
    void loadCatalog();
  }, [loadCatalog]);

  useEffect(() => {
    void loadHistory(unreadOnly);
  }, [loadHistory, unreadOnly]);

  const dirty = useMemo(() => {
    if (draftIds.size !== savedIds.size) return true;
    for (const id of draftIds) if (!savedIds.has(id)) return true;
    return false;
  }, [draftIds, savedIds]);

  function toggleStage(stageId: string) {
    setSaveNotice(null);
    setDraftIds((current) => {
      const next = new Set(current);
      if (next.has(stageId)) next.delete(stageId);
      else next.add(stageId);
      return next;
    });
  }

  async function save() {
    if (saving || !dirty) return;
    setSaving(true);
    setSaveError(null);
    setSaveNotice(null);
    try {
      const data = await saveAlertSubscriptions([...draftIds]);
      const subscribed = new Set(
        data.phases.flatMap((phase) => phase.stages.filter((s) => s.subscribed).map((s) => s.id)),
      );
      setPhases(data.phases);
      setSavedIds(subscribed);
      setDraftIds(new Set(subscribed));
      setSaveNotice("Subscrições guardadas.");
    } catch (error) {
      setSaveError(errorMessage(error, "Não foi possível guardar as subscrições."));
    } finally {
      setSaving(false);
    }
  }

  async function markRead(item: ProcessNotification) {
    if (historyBusy) return;
    setHistoryBusy(true);
    setHistoryError(null);
    try {
      await markProcessNotificationRead(item.id);
      await loadHistory(unreadOnly);
    } catch (error) {
      setHistoryError(errorMessage(error, "Não foi possível marcar a notificação."));
      setHistoryBusy(false);
    }
  }

  async function markAll() {
    if (historyBusy) return;
    setHistoryBusy(true);
    setHistoryError(null);
    try {
      await markAllProcessNotificationsRead();
      await loadHistory(unreadOnly);
    } catch (error) {
      setHistoryError(errorMessage(error, "Não foi possível marcar as notificações."));
      setHistoryBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Alertas"
        subtitle="Seja avisado quando uma etapa do processo for concluída. Não recebe alertas das suas próprias ações."
      />

      <Card title="Etapas subscritas" icon="bell">
        {catalogError ? (
          <ErrorState message={catalogError} onRetry={() => void loadCatalog()} />
        ) : !phases ? (
          <LoadingState label="A carregar etapas…" rows={4} />
        ) : phases.length === 0 ? (
          <EmptyState compact icon="tasks" title="Sem etapas no catálogo." />
        ) : (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void save();
            }}
          >
            {saveError && <Alert tone="danger">{saveError}</Alert>}
            {saveNotice && !dirty && <Alert tone="success">{saveNotice}</Alert>}
            <div className="stack">
              {phases.map((phase) => (
                <fieldset key={phase.id} className="process-alerts__phase">
                  <legend>{phase.name}</legend>
                  {phase.stages.map((stage) => (
                    <label key={stage.id} className="process-alerts__stage">
                      <input
                        type="checkbox"
                        checked={draftIds.has(stage.id)}
                        onChange={() => toggleStage(stage.id)}
                        disabled={saving}
                      />
                      <span>{stage.title}</span>
                    </label>
                  ))}
                </fieldset>
              ))}
            </div>
            <div className="process-alerts__save">
              <span className="small muted">
                {draftIds.size} {draftIds.size === 1 ? "etapa selecionada" : "etapas selecionadas"}
              </span>
              <button type="submit" className="btn btn--primary" disabled={saving || !dirty}>
                {saving ? "A guardar…" : "Guardar subscrições"}
              </button>
            </div>
          </form>
        )}
      </Card>

      <Card
        title="Histórico"
        icon="history"
        actions={
          <div className="process-alerts__history-actions">
            <label className="process-alerts__filter">
              <input
                type="checkbox"
                checked={unreadOnly}
                onChange={(event) => setUnreadOnly(event.target.checked)}
              />
              <span>Só não lidas</span>
            </label>
            <button type="button" className="btn btn--sm btn--ghost" onClick={() => void markAll()} disabled={historyBusy}>
              Marcar todas como lidas
            </button>
          </div>
        }
      >
        {historyError && <ErrorState message={historyError} onRetry={() => void loadHistory(unreadOnly)} />}
        {!historyError && history === null && <LoadingState label="A carregar histórico…" rows={3} />}
        {!historyError && history !== null && history.length === 0 && (
          <EmptyState
            compact
            icon="checkCircle"
            title={unreadOnly ? "Sem alertas por ler." : "Ainda não há alertas."}
            text="As etapas que subscreveu aparecerão aqui quando forem concluídas por outra pessoa."
          />
        )}
        {history !== null && history.length > 0 && (
          <>
            <p className="small muted">
              {historyTotal} {historyTotal === 1 ? "alerta" : "alertas"}
              {historyTotal > history.length ? ` (a mostrar os ${history.length} mais recentes)` : ""}
            </p>
            <ul className="process-alerts__history">
              {history.map((item) => (
                <li key={item.id} className="process-alerts__item">
                  <div>
                    <span>{item.message}</span>
                    <span className="small muted">
                      <time dateTime={item.created_at}>{formatDateTimePt(item.created_at)}</time>
                    </span>
                  </div>
                  <div className="process-alerts__item-actions">
                    <Badge tone={item.is_read ? "neutral" : "brand"}>{item.is_read ? "Lida" : "Não lida"}</Badge>
                    {item.project_id && <Link to={`/projects/${item.project_id}`}>Ver projeto</Link>}
                    {!item.is_read && (
                      <button type="button" className="btn btn--sm btn--ghost" onClick={() => void markRead(item)} disabled={historyBusy}>
                        Marcar como lida
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
      </Card>
    </>
  );
}
