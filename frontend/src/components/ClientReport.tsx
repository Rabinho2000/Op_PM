import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  approveClientReportSend,
  ClientReportConfig,
  ClientReportPreview,
  ClientReportResponse,
  ClientReportSend,
  discardClientReportSend,
  formatApiDetail,
  getClientReport,
  previewClientReport,
  sendClientReportNow,
  updateClientReport,
} from "../api/client";
import { useToast } from "./Toast";
import { Alert, Badge, Card, EmptyState, ErrorState, LoadingState } from "./ui";

const WEEKDAYS = [
  "Segunda-feira",
  "Terça-feira",
  "Quarta-feira",
  "Quinta-feira",
  "Sexta-feira",
  "Sábado",
  "Domingo",
];

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const NOTE_MAX_LENGTH = 2000;

interface ClientReportForm {
  enabled: boolean;
  review_before_send: boolean;
  weekday: number;
  send_time: string;
  to_emails: string[];
  cc_emails: string[];
  weekly_note: string;
}

interface ClientReportProps {
  projectId: string;
}

function reportConfig(report: ClientReportResponse): ClientReportConfig {
  return report.config ?? report;
}

function formFromReport(report: ClientReportResponse): ClientReportForm {
  const config = reportConfig(report);
  return {
    enabled: Boolean(config.enabled),
    review_before_send: Boolean(config.review_before_send),
    weekday: typeof config.weekday === "number" && config.weekday >= 0 && config.weekday <= 6 ? config.weekday : 0,
    send_time: config.send_time ?? "09:00",
    to_emails: config.to_emails?.length ? [...config.to_emails] : [""],
    cc_emails: config.cc_emails?.length ? [...config.cc_emails] : [],
    weekly_note: config.weekly_note ?? "",
  };
}

function formatLisbonDate(value: string | null | undefined): string {
  if (!value) return "Sem próximo envio agendado";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("pt-PT", {
    timeZone: "Europe/Lisbon",
    weekday: "long",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    sent: "Enviado",
    failed: "Falhou",
    skipped: "Ignorado",
    pending_review: "A aguardar aprovação",
    discarded: "Descartado",
    expired: "Expirado",
    pending: "Pendente",
  };
  return labels[status] ?? status;
}

function sendDate(send: ClientReportSend): string {
  return formatLisbonDate(send.sent_at ?? send.created_at);
}

function apiErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return formatApiDetail(error.detail) ?? fallback;
  return fallback;
}

function validateEmailList(values: string[], label: string, required: boolean): string[] {
  const errors: string[] = [];
  const nonEmpty = values.map((email) => email.trim()).filter(Boolean);
  if (required && nonEmpty.length === 0) errors.push(`${label}: indique pelo menos um endereço de email.`);
  if (nonEmpty.length > 10) errors.push(`${label}: pode indicar no máximo 10 endereços de email.`);
  values.forEach((email, index) => {
    const value = email.trim();
    if (value && !EMAIL_PATTERN.test(value)) errors.push(`${label} ${index + 1}: endereço de email inválido.`);
  });
  return errors;
}

export default function ClientReport({ projectId }: ClientReportProps) {
  const { notify } = useToast();
  const [report, setReport] = useState<ClientReportResponse | null>(null);
  const [form, setForm] = useState<ClientReportForm | null>(null);
  const [preview, setPreview] = useState<ClientReportPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [emailErrors, setEmailErrors] = useState<string[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getClientReport(projectId);
      setReport(data);
      setForm(formFromReport(data));
    } catch (loadError) {
      setError(apiErrorMessage(loadError, "Não foi possível carregar o relatório semanal."));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const canManage = Boolean(report?.can_manage);
  const pendingSends = useMemo(
    () => (report?.last_sends ?? []).filter((send) => send.status === "pending_review"),
    [report]
  );

  function updateForm<K extends keyof ClientReportForm>(field: K, value: ClientReportForm[K]) {
    setForm((current) => (current ? { ...current, [field]: value } : current));
  }

  function updateEmail(kind: "to_emails" | "cc_emails", index: number, value: string) {
    setForm((current) => {
      if (!current) return current;
      const values = [...current[kind]];
      values[index] = value;
      return { ...current, [kind]: values };
    });
    setEmailErrors([]);
  }

  function addEmail(kind: "to_emails" | "cc_emails") {
    setForm((current) => (current ? { ...current, [kind]: [...current[kind], ""] } : current));
  }

  function removeEmail(kind: "to_emails" | "cc_emails", index: number) {
    setForm((current) => {
      if (!current) return current;
      const values = current[kind].filter((_, itemIndex) => itemIndex !== index);
      return { ...current, [kind]: values };
    });
    setEmailErrors([]);
  }

  async function handleSave(event: FormEvent) {
    event.preventDefault();
    if (!form) return;
    const validation = [
      ...validateEmailList(form.to_emails, "Para", true),
      ...validateEmailList(form.cc_emails, "CC", false),
    ];
    const normalizedEmails = [...form.to_emails, ...form.cc_emails].map((email) => email.trim().toLowerCase()).filter(Boolean);
    if (new Set(normalizedEmails).size !== normalizedEmails.length) validation.push("Não pode repetir o mesmo endereço em Para ou CC.");
    if (validation.length > 0) {
      setEmailErrors(validation);
      setFormError(null);
      return;
    }
    setEmailErrors([]);
    setFormError(null);
    setBusy("save");
    try {
      const saved = await updateClientReport(projectId, {
        ...form,
        to_emails: form.to_emails.map((email) => email.trim()).filter(Boolean),
        cc_emails: form.cc_emails.map((email) => email.trim()).filter(Boolean),
      });
      setReport(saved);
      setForm(formFromReport(saved));
      setPreview(null);
      notify("Configuração do relatório guardada.", "success");
    } catch (saveError) {
      setFormError(apiErrorMessage(saveError, "Não foi possível guardar a configuração."));
    } finally {
      setBusy(null);
    }
  }

  async function handlePreview() {
    setBusy("preview");
    setFormError(null);
    try {
      setPreview(await previewClientReport(projectId));
    } catch (previewError) {
      setFormError(apiErrorMessage(previewError, "Não foi possível gerar a pré-visualização."));
    } finally {
      setBusy(null);
    }
  }

  async function handleSendNow() {
    if (!window.confirm("Enviar o relatório desta semana agora?")) return;
    setBusy("send-now");
    setFormError(null);
    try {
      await sendClientReportNow(projectId);
      notify("Pedido de envio criado.", "success");
      await load();
    } catch (sendError) {
      setFormError(apiErrorMessage(sendError, "Não foi possível enviar o relatório agora."));
    } finally {
      setBusy(null);
    }
  }

  async function handleReview(send: ClientReportSend, action: "approve" | "discard") {
    setBusy(`${action}-${send.id}`);
    setFormError(null);
    try {
      if (action === "approve") await approveClientReportSend(send.id);
      else await discardClientReportSend(send.id);
      notify(action === "approve" ? "Rascunho aprovado." : "Rascunho descartado.", "success");
      await load();
    } catch (reviewError) {
      setFormError(apiErrorMessage(reviewError, "Não foi possível atualizar o rascunho."));
    } finally {
      setBusy(null);
    }
  }

  if (loading) return <LoadingState label="A carregar o relatório semanal…" rows={5} />;
  if (error || !report || !form) return <ErrorState message={error ?? "Relatório indisponível."} onRetry={load} />;

  return (
    <div className="stack" data-testid="client-report">
      {report.delivery_mode === "local" && (
        <Alert tone="warning" title="Modo de teste">
          <strong>Modo de teste — nenhum email é entregue ao cliente.</strong>
        </Alert>
      )}
      {(report.warnings ?? []).map((warning, index) => (
        <Alert key={`${warning}-${index}`} tone="warning" title="Aviso">
          {warning}
        </Alert>
      ))}
      {report.next_send_at && (
        <p className="muted" data-testid="next-client-report">
          Próximo envio: <strong>{formatLisbonDate(report.next_send_at)}</strong>
        </p>
      )}
      {formError && (
        <Alert tone="danger" title="Não foi possível concluir a operação">
          {formError}
        </Alert>
      )}
      {emailErrors.length > 0 && (
        <Alert tone="danger" title="Verifique os destinatários">
          <ul className="list--plain">
            {emailErrors.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        </Alert>
      )}

      <Card title="Configuração" icon="mail" tone="brand">
        <form onSubmit={handleSave} className="form-grid" noValidate>
          <label className="checkbox-row form-grid__full">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(event) => updateForm("enabled", event.target.checked)}
              disabled={!canManage || busy !== null}
            />
            <span>Ativar relatório semanal</span>
          </label>
          <label>
            <span className="label">Dia da semana</span>
            <select
              value={form.weekday}
              onChange={(event) => updateForm("weekday", Number(event.target.value))}
              disabled={!canManage || busy !== null}
            >
              {WEEKDAYS.map((day, index) => (
                <option key={day} value={index}>
                  {day}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span className="label">Hora</span>
            <input
              type="time"
              value={form.send_time}
              onChange={(event) => updateForm("send_time", event.target.value)}
              disabled={!canManage || busy !== null}
            />
          </label>
          <EmailList
            label="Para"
            values={form.to_emails}
            required
            disabled={!canManage || busy !== null}
            onChange={(index, value) => updateEmail("to_emails", index, value)}
            onAdd={() => addEmail("to_emails")}
            onRemove={(index) => removeEmail("to_emails", index)}
          />
          <EmailList
            label="CC"
            values={form.cc_emails}
            disabled={!canManage || busy !== null}
            onChange={(index, value) => updateEmail("cc_emails", index, value)}
            onAdd={() => addEmail("cc_emails")}
            onRemove={(index) => removeEmail("cc_emails", index)}
          />
          <label className="checkbox-row form-grid__full">
            <input
              type="checkbox"
              checked={form.review_before_send}
              onChange={(event) => updateForm("review_before_send", event.target.checked)}
              disabled={!canManage || busy !== null}
            />
            <span>Rever antes de enviar</span>
          </label>
          <label className="form-grid__full">
            <span className="label" id="weekly-note-label">Nota da semana</span>
            <textarea
              id="weekly-note"
              aria-labelledby="weekly-note-label"
              value={form.weekly_note}
              maxLength={NOTE_MAX_LENGTH}
              rows={4}
              onChange={(event) => updateForm("weekly_note", event.target.value)}
              disabled={!canManage || busy !== null}
            />
            <span className="small muted" data-testid="weekly-note-count">
              {form.weekly_note.length}/{NOTE_MAX_LENGTH}
            </span>
          </label>
          {canManage && (
            <div className="form-actions form-grid__full">
              <button type="submit" className="btn btn--primary" disabled={busy !== null}>
                {busy === "save" ? "A guardar…" : "Guardar configuração"}
              </button>
              <button type="button" className="btn" onClick={handlePreview} disabled={busy !== null}>
                {busy === "preview" ? "A gerar…" : "Pré-visualizar email"}
              </button>
              <button type="button" className="btn btn--danger" onClick={handleSendNow} disabled={busy !== null}>
                Enviar agora
              </button>
            </div>
          )}
        </form>
      </Card>

      {preview && (
        <Card title="Pré-visualização do email" icon="mail" tone="info">
          <dl className="detail-list">
            <div>
              <dt>Assunto</dt>
              <dd>{preview.subject}</dd>
            </div>
            {preview.from_email && (
              <div>
                <dt>De</dt>
                <dd>{preview.from_email}</dd>
              </div>
            )}
            <div>
              <dt>Para</dt>
              <dd>{preview.to.join(", ") || "—"}</dd>
            </div>
            <div>
              <dt>CC</dt>
              <dd>{preview.cc.join(", ") || "—"}</dd>
            </div>
          </dl>
          <iframe
            title="Conteúdo do email"
            sandbox=""
            srcDoc={preview.body_html}
            className="client-report__preview"
          />
        </Card>
      )}

      <Card title="Histórico de envios" icon="history" tone="neutral">
        {(report.last_sends ?? []).length === 0 ? (
          <EmptyState title="Ainda não há envios" text="Os envios deste relatório aparecerão aqui." />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Semana</th>
                  <th>Estado</th>
                  <th>Data</th>
                  <th>Destinatários</th>
                  {canManage && <th>Ações</th>}
                </tr>
              </thead>
              <tbody>
                {report.last_sends?.map((send) => (
                  <tr key={send.id}>
                    <td>{send.iso_week ?? "—"}</td>
                    <td>
                      <Badge tone={send.status === "sent" ? "success" : send.status === "failed" ? "danger" : "neutral"}>
                        {statusLabel(send.status)}
                      </Badge>
                      {send.error && <div className="small danger-text">{send.error}</div>}
                    </td>
                    <td>{sendDate(send)}</td>
                    <td>{[...(send.to_emails ?? []), ...(send.cc_emails ?? [])].join(", ") || "—"}</td>
                    {canManage && (
                      <td>
                        {send.status === "pending_review" && (
                          <div className="button-row">
                            <button
                              type="button"
                              className="btn btn--small btn--primary"
                              onClick={() => handleReview(send, "approve")}
                              disabled={busy !== null}
                            >
                              {busy === `approve-${send.id}` ? "A aprovar…" : "Aprovar"}
                            </button>
                            <button
                              type="button"
                              className="btn btn--small"
                              onClick={() => handleReview(send, "discard")}
                              disabled={busy !== null}
                            >
                              {busy === `discard-${send.id}` ? "A descartar…" : "Descartar"}
                            </button>
                          </div>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {pendingSends.length > 0 && (
        <p className="small muted">{pendingSends.length} rascunho(s) aguardam aprovação.</p>
      )}
    </div>
  );
}

function EmailList({
  label,
  values,
  required = false,
  disabled,
  onChange,
  onAdd,
  onRemove,
}: {
  label: string;
  values: string[];
  required?: boolean;
  disabled: boolean;
  onChange: (index: number, value: string) => void;
  onAdd: () => void;
  onRemove: (index: number) => void;
}) {
  return (
    <fieldset className="form-grid__full email-list">
      <legend className="label">
        {label}
        {required ? " *" : ""}
      </legend>
      {values.map((value, index) => (
        <div className="email-list__row" key={`${label}-${index}`}>
          <input
            type="email"
            value={value}
            aria-label={`${label} ${index + 1}`}
            placeholder="nome@empresa.pt"
            onChange={(event) => onChange(index, event.target.value)}
            disabled={disabled}
          />
          {!disabled && (
            <button
              type="button"
              className="btn btn--small"
              aria-label={`Remover ${label} ${index + 1}`}
              onClick={() => onRemove(index)}
              disabled={required && values.length === 1}
            >
              Remover
            </button>
          )}
        </div>
      ))}
      {!disabled && (
        <button type="button" className="btn btn--small" onClick={onAdd}>
          Adicionar {label.toLowerCase()}
        </button>
      )}
    </fieldset>
  );
}
