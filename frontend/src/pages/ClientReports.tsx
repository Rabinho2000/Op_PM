import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, ClientReportListItem, formatApiDetail, listClientReports } from "../api/client";
import { Alert, Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader } from "../components/ui";

function formatLisbonDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("pt-PT", {
    timeZone: "Europe/Lisbon",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function sendStatusLabel(status: string | undefined): string {
  const labels: Record<string, string> = {
    sent: "Enviado",
    failed: "Falhou",
    skipped: "Ignorado",
    pending_review: "A aguardar aprovação",
    discarded: "Descartado",
    expired: "Expirado",
    pending: "Pendente",
  };
  return status ? labels[status] ?? status : "Sem envios";
}

function reportStatus(item: ClientReportListItem): string {
  if (item.pending_review_count && item.pending_review_count > 0) return "A aguardar revisão";
  if (item.last_send?.status === "failed") return "Falhou";
  if (item.enabled) return "Ativo";
  if (item.last_send || item.next_send_at) return "Pausado";
  return "Sem configuração";
}

function statusFilterMatches(item: ClientReportListItem, filter: string): boolean {
  if (!filter) return true;
  if (filter === "enabled" || filter === "active") return item.enabled;
  if (filter === "disabled" || filter === "paused") return !item.enabled && reportStatus(item) === "Pausado";
  if (filter === "unconfigured") return reportStatus(item) === "Sem configuração";
  if (filter === "pending_review") return reportStatus(item) === "A aguardar revisão";
  if (filter === "failed") return reportStatus(item) === "Falhou";
  return item.lifecycle_status === filter || item.status_label === filter;
}

function itemRecipients(item: ClientReportListItem): string {
  const to = item.to_emails ?? item.last_send?.to_emails ?? [];
  const cc = item.cc_emails ?? item.last_send?.cc_emails ?? [];
  return [...to, ...cc].join(", ") || "—";
}

export default function ClientReports() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [items, setItems] = useState<ClientReportListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const status = searchParams.get("status") ?? "";
  const pm = searchParams.get("pm") ?? "";

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setItems(await listClientReports());
    } catch (loadError) {
      setError(loadError instanceof ApiError ? formatApiDetail(loadError.detail) ?? "Não foi possível carregar os relatórios." : "Não foi possível carregar os relatórios.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const pmOptions = useMemo(
    () => Array.from(new Set(items.map((item) => item.pm).filter((value): value is string => Boolean(value)))).sort((a, b) => a.localeCompare(b, "pt-PT")),
    [items]
  );
  const statusOptions = useMemo(() => {
    const values = new Map<string, string>([
      ["enabled", "Ativo"],
      ["paused", "Pausado"],
      ["unconfigured", "Sem configuração"],
      ["pending_review", "A aguardar revisão"],
      ["failed", "Falhou"],
    ]);
    items.forEach((item) => {
      if (item.lifecycle_status) values.set(item.lifecycle_status, item.status_label ?? item.lifecycle_status);
    });
    return Array.from(values.entries()).sort((a, b) => a[1].localeCompare(b[1], "pt-PT"));
  }, [items]);
  const filteredItems = useMemo(
    () => items.filter((item) => statusFilterMatches(item, status) && (!pm || item.pm === pm)),
    [items, pm, status]
  );
  const pendingReviewCount = useMemo(
    () => items.reduce((total, item) => total + (item.pending_review_count ?? 0), 0),
    [items]
  );

  function updateFilter(key: "status" | "pm", value: string) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    setSearchParams(next, { replace: true });
  }

  return (
    <>
      <PageHeader
        title="Relatórios a clientes"
        subtitle="Configuração, próximos envios e histórico dos relatórios semanais."
      />
      {pendingReviewCount > 0 && (
        <Alert tone="warning" title="Rascunhos por aprovar">
          Existem <strong>{pendingReviewCount}</strong> rascunho(s) de relatório a aguardar aprovação.
        </Alert>
      )}
      <Card title="Filtros" icon="search" tone="neutral">
        <div className="filters filters--inline">
          <label>
            <span className="label">Estado</span>
            <select aria-label="Filtrar por estado" value={status} onChange={(event) => updateFilter("status", event.target.value)}>
              <option value="">Todos os estados</option>
              {statusOptions.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span className="label">PM</span>
            <select aria-label="Filtrar por PM" value={pm} onChange={(event) => updateFilter("pm", event.target.value)}>
              <option value="">Todos os PMs</option>
              {pmOptions.map((person) => (
                <option key={person} value={person}>
                  {person}
                </option>
              ))}
            </select>
          </label>
        </div>
      </Card>

      <div className="card" data-testid="client-reports-list">
        {loading ? (
          <LoadingState label="A carregar relatórios…" rows={6} />
        ) : error ? (
          <ErrorState message={error} onRetry={load} />
        ) : filteredItems.length === 0 ? (
          <EmptyState
            title={items.length === 0 ? "Ainda não há relatórios a clientes" : "Nenhum relatório corresponde aos filtros"}
            text={items.length === 0 ? "Quando existirem projetos configurados, aparecerão aqui." : "Altere ou limpe os filtros para ver outros projetos."}
          />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Projeto</th>
                  <th>Cliente</th>
                  <th>PM</th>
                  <th>Estado</th>
                  <th>Próximo envio</th>
                  <th>Último envio</th>
                  <th>Destinatários</th>
                </tr>
              </thead>
              <tbody>
                {filteredItems.map((item) => {
                  const lastSend = item.last_send;
                  const configStatus = reportStatus(item);
                  const statusTone = configStatus === "Ativo" ? "success" : configStatus === "Falhou" ? "danger" : configStatus === "A aguardar revisão" ? "warning" : "neutral";
                  return (
                    <tr key={item.project_id}>
                      <td>
                        <Link to={`/projects/${item.project_id}?tab=relatorio`} className="link-strong">
                          {item.project_name}
                        </Link>
                        {item.pending_review_count ? (
                          <span className="cell-sub text-warning">{item.pending_review_count} por aprovar</span>
                        ) : null}
                      </td>
                      <td>{item.client_name ?? "—"}</td>
                      <td>{item.pm ?? "—"}</td>
                      <td>
                        <div className="button-row">
                          <Badge tone={statusTone}>{configStatus}</Badge>
                          {item.status_label && <span className="small muted">{item.status_label}</span>}
                        </div>
                      </td>
                      <td>{item.enabled ? formatLisbonDate(item.next_send_at) : "—"}</td>
                      <td>
                        {lastSend ? (
                          <>
                            <span>{sendStatusLabel(lastSend.status)}</span>
                            <span className="cell-sub">{formatLisbonDate(lastSend.sent_at ?? lastSend.created_at)}</span>
                          </>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td>{itemRecipients(item)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
