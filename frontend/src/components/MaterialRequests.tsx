// Pedidos de material a fornecedores (D-067). A máquina de estados vive no
// servidor: as ações mostradas são as de `allowed_actions` (estado ∩ permissões
// ∩ âmbito), nunca reconstruídas aqui. O sistema NUNCA envia email — "marcar como
// enviado" regista que uma pessoa autorizada o fez fora do sistema.
import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  ApiError,
  applyMaterialRequestAction,
  createMaterialRequest,
  getMaterialRequest,
  getMaterialRequestEmailDraft,
  InventoryItem,
  listInventoryItems,
  listMaterialRequests,
  MATERIAL_REQUEST_ACTION_LABELS,
  MATERIAL_REQUEST_STATUS_LABELS,
  MaterialRequest,
  MaterialRequestAction,
  MaterialRequestEmailDraft,
  MaterialRequestStatus,
} from "../api/client";
import { formatDateTimePt } from "../utils/dates";
import { Alert, Badge, EmptyState, LoadingState, Modal, Tone } from "./ui";

const STATUS_TONES: Record<MaterialRequestStatus, Tone> = {
  rascunho: "neutral",
  pedido_enviado: "info",
  orcamento_recebido: "warning",
  aprovado: "brand",
  adjudicado: "success",
  cancelado: "danger",
};

const HISTORY_LABELS: Record<string, string> = {
  create: "Criado",
  send: "Marcado como enviado",
  record_quote: "Orçamento registado",
  approve: "Orçamento aprovado",
  adjudicate: "Adjudicado",
  cancel: "Cancelado",
};

function euros(value: string | null): string {
  return value === null ? "—" : `${value} €`;
}

// Preço unitário: o servidor devolve a escala da coluna (4 casas: "10.1000");
// mostra-se sem zeros a mais mas nunca com menos de 2 casas ("10.10", "4.325").
// Só formata o texto — nunca converte para número (evita erros de vírgula flutuante).
export function formatUnitPrice(value: string | null): string {
  if (value === null) return "—";
  const [whole, frac = ""] = value.split(".");
  const trimmed = frac.replace(/0+$/, "").padEnd(2, "0");
  return `${whole}.${trimmed} €`;
}

export function RequestStatusBadge({ status }: { status: MaterialRequestStatus }) {
  return <Badge tone={STATUS_TONES[status] ?? "neutral"}>{MATERIAL_REQUEST_STATUS_LABELS[status] ?? status}</Badge>;
}

// --- Criar ---

type LineDraft = { item_id: string; description: string; quantity: string };

const EMPTY_LINE: LineDraft = { item_id: "", description: "", quantity: "" };

export function CreateMaterialRequestModal({
  supplierId,
  supplierName,
  projects,
  onClose,
  onDone,
}: {
  supplierId: string;
  supplierName: string;
  projects: { id: string; name: string }[];
  onClose: () => void;
  onDone: (created: MaterialRequest) => void;
}) {
  const [projectId, setProjectId] = useState("");
  const [lines, setLines] = useState<LineDraft[]>([{ ...EMPTY_LINE }]);
  const [notes, setNotes] = useState("");
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    // Sem inventory.view a lista de itens falha: continua a ser possível pedir por descrição livre.
    listInventoryItems().then(setItems).catch(() => setItems([]));
  }, []);

  function setLine(index: number, changes: Partial<LineDraft>) {
    setLines((prev) => prev.map((line, i) => (i === index ? { ...line, ...changes } : line)));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!projectId) {
      setError("Escolha o projeto.");
      return;
    }
    const filled = lines.filter((l) => l.item_id || l.description.trim() || l.quantity);
    if (filled.length === 0 || filled.some((l) => !(l.item_id || l.description.trim()) || !(Number(l.quantity) > 0))) {
      setError("Cada linha precisa de um item ou descrição e de uma quantidade positiva.");
      return;
    }
    setSaving(true);
    try {
      const created = await createMaterialRequest({
        project_id: projectId,
        supplier_id: supplierId,
        notes,
        lines: filled.map((l) => ({
          item_id: l.item_id || null,
          description: l.description.trim(),
          quantity: l.quantity,
        })),
      });
      onDone(created);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Não foi possível criar o pedido.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={`Pedir material — ${supplierName}`}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancelar
          </button>
          <button type="submit" form="material-request-form" className="btn btn--primary" disabled={saving}>
            {saving ? "A criar…" : "Criar rascunho"}
          </button>
        </>
      }
    >
      {error && <Alert tone="danger">{error}</Alert>}
      <form id="material-request-form" onSubmit={handleSubmit}>
        <div className="form-grid">
          <div className="field span-2">
            <label htmlFor="mr-project">Projeto *</label>
            <select id="mr-project" className="select" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
              <option value="">— escolha —</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
        </div>
        <fieldset style={{ border: 0, padding: 0, margin: "12px 0 0" }}>
          <legend className="small muted">Material</legend>
          {lines.map((line, index) => (
            <div key={index} style={{ display: "flex", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
              <select
                aria-label={`Item da linha ${index + 1}`}
                className="select"
                value={line.item_id}
                onChange={(e) => setLine(index, { item_id: e.target.value })}
              >
                <option value="">— item do inventário —</option>
                {items.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.name} ({i.unit})
                  </option>
                ))}
              </select>
              <input
                aria-label={`Descrição da linha ${index + 1}`}
                className="input"
                placeholder="ou descrição livre"
                value={line.description}
                onChange={(e) => setLine(index, { description: e.target.value })}
              />
              <input
                aria-label={`Quantidade da linha ${index + 1}`}
                className="input"
                type="number"
                min="0"
                step="0.001"
                placeholder="Qtd."
                style={{ width: 90 }}
                value={line.quantity}
                onChange={(e) => setLine(index, { quantity: e.target.value })}
              />
              {lines.length > 1 && (
                <button
                  type="button"
                  className="btn btn--sm"
                  aria-label={`Remover linha ${index + 1}`}
                  onClick={() => setLines((prev) => prev.filter((_, i) => i !== index))}
                >
                  Remover
                </button>
              )}
            </div>
          ))}
          <button type="button" className="btn btn--sm" onClick={() => setLines((prev) => [...prev, { ...EMPTY_LINE }])}>
            Adicionar linha
          </button>
        </fieldset>
        <div className="field" style={{ marginTop: 12 }}>
          <label htmlFor="mr-notes">Notas</label>
          <textarea id="mr-notes" className="textarea" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </div>
      </form>
      <p className="small muted">
        Cria um rascunho. O sistema não envia emails: depois de o aprovar, o envio ao fornecedor é feito por uma pessoa.
      </p>
    </Modal>
  );
}

// --- Detalhe e ações ---

export function MaterialRequestDetailModal({
  requestId,
  onClose,
  onChanged,
  onCopied,
}: {
  requestId: string;
  onClose: () => void;
  onChanged: () => void;
  onCopied: (ok: boolean) => void;
}) {
  const [request, setRequest] = useState<MaterialRequest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<MaterialRequestAction | null>(null);
  const [note, setNote] = useState("");
  const [prices, setPrices] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<MaterialRequestEmailDraft | null>(null);

  const load = useCallback(() => {
    getMaterialRequest(requestId)
      .then(setRequest)
      .catch((e) => setError(e instanceof ApiError ? e.detail : "Não foi possível carregar o pedido."));
  }, [requestId]);

  useEffect(load, [load]);

  function start(action: MaterialRequestAction) {
    setError(null);
    setNote("");
    setPending(action);
    if (action === "record_quote" && request) {
      setPrices(Object.fromEntries(request.lines.map((l) => [l.id, l.unit_price ?? ""])));
    }
  }

  async function confirm() {
    if (!request || !pending) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await applyMaterialRequestAction(request.id, {
        action: pending,
        note,
        prices:
          pending === "record_quote"
            ? request.lines.map((l) => ({ line_id: l.id, unit_price: prices[l.id] ?? "" }))
            : undefined,
      });
      setRequest(updated);
      setPending(null);
      setDraft(null);
      onChanged();
    } catch (err) {
      // A mensagem do servidor (transição inválida, sem permissão, orçamento incompleto…) é a verdade.
      setError(err instanceof ApiError ? err.detail : "Não foi possível aplicar a ação.");
    } finally {
      setBusy(false);
    }
  }

  async function showDraft() {
    if (!request) return;
    try {
      setDraft(await getMaterialRequestEmailDraft(request.id));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Não foi possível preparar o email.");
    }
  }

  async function copyDraft() {
    if (!draft) return;
    try {
      await navigator.clipboard.writeText(`Para: ${draft.to ?? ""}\nAssunto: ${draft.subject}\n\n${draft.body}`);
      onCopied(true);
    } catch {
      onCopied(false);
    }
  }

  return (
    <Modal title="Pedido de material" onClose={onClose}>
      {error && <Alert tone="danger">{error}</Alert>}
      {!request ? (
        error ? null : <LoadingState rows={4} />
      ) : (
        <>
          <dl className="kv">
            <dt>Estado</dt>
            <dd>
              <RequestStatusBadge status={request.status} />
            </dd>
            <dt>Projeto</dt>
            <dd>{request.project_name ?? "—"}</dd>
            <dt>Fornecedor</dt>
            <dd>{request.supplier_name ?? "— (escolha antes de enviar)"}</dd>
            <dt>Criado por</dt>
            <dd>{request.created_by_display_name ?? "—"}</dd>
            {request.approved_by_display_name && (
              <>
                <dt>Orçamento aprovado por</dt>
                <dd>{request.approved_by_display_name}</dd>
              </>
            )}
            {request.notes && (
              <>
                <dt>Notas</dt>
                <dd style={{ whiteSpace: "pre-wrap" }}>{request.notes}</dd>
              </>
            )}
          </dl>

          <table className="table" aria-label="Linhas do pedido">
            <thead>
              <tr>
                <th>Material</th>
                <th>Qtd.</th>
                <th>Preço unit.</th>
                <th>Total</th>
              </tr>
            </thead>
            <tbody>
              {request.lines.map((l) => (
                <tr key={l.id}>
                  <td>{l.description}</td>
                  <td>
                    {l.quantity} {l.unit ?? ""}
                  </td>
                  <td>{formatUnitPrice(l.unit_price)}</td>
                  <td>{euros(l.line_total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p style={{ textAlign: "right", margin: "6px 0" }}>
            <strong>Total: {request.total === null ? "— (sem orçamento completo)" : euros(request.total)}</strong>
          </p>

          {request.allowed_actions.length > 0 && !pending && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "12px 0" }}>
              {request.allowed_actions.map((action) => (
                <button key={action} type="button" className={action === "cancel" ? "btn btn--danger" : "btn btn--primary"} onClick={() => start(action)}>
                  {MATERIAL_REQUEST_ACTION_LABELS[action]}
                </button>
              ))}
            </div>
          )}

          {pending && (
            <div className="card" style={{ padding: 12, margin: "12px 0" }} aria-label={`Confirmar: ${MATERIAL_REQUEST_ACTION_LABELS[pending]}`}>
              <strong>{MATERIAL_REQUEST_ACTION_LABELS[pending]}</strong>
              {pending === "send" && (
                <p className="small">
                  <strong>O sistema não envia emails.</strong> Confirme que este pedido foi (ou vai ser) enviado ao
                  fornecedor por uma pessoa, por exemplo copiando o rascunho do email abaixo.
                </p>
              )}
              {pending === "record_quote" && (
                <div style={{ margin: "8px 0" }}>
                  <p className="small">Indique o preço unitário de TODAS as linhas, conforme o orçamento recebido.</p>
                  {request.lines.map((l) => (
                    <div key={l.id} className="field" style={{ marginBottom: 6 }}>
                      <label htmlFor={`price-${l.id}`}>Preço unitário — {l.description}</label>
                      <input
                        id={`price-${l.id}`}
                        className="input"
                        type="number"
                        min="0"
                        step="0.0001"
                        value={prices[l.id] ?? ""}
                        onChange={(e) => setPrices((prev) => ({ ...prev, [l.id]: e.target.value }))}
                      />
                    </div>
                  ))}
                </div>
              )}
              {pending === "approve" && (
                <p className="small">Aprovar o orçamento de {euros(request.total)}. É uma decisão humana e fica registada.</p>
              )}
              {pending === "adjudicate" && (
                <p className="small">
                  A adjudicação é uma decisão humana, fica registada e <strong>não pode ser desfeita</strong> neste
                  momento.
                </p>
              )}
              {(pending === "cancel" || pending === "send") && (
                <div className="field">
                  <label htmlFor="mr-action-note">{pending === "cancel" ? "Motivo do cancelamento" : "Nota (opcional)"}</label>
                  <textarea id="mr-action-note" className="textarea" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
                </div>
              )}
              <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                <button type="button" className="btn" onClick={() => setPending(null)} disabled={busy}>
                  Voltar
                </button>
                <button type="button" className="btn btn--primary" onClick={confirm} disabled={busy}>
                  {busy ? "A guardar…" : "Confirmar"}
                </button>
              </div>
            </div>
          )}

          {request.supplier_id && (
            <div style={{ margin: "12px 0" }}>
              <button type="button" className="btn btn--sm" onClick={showDraft}>
                Ver rascunho do email
              </button>
              {draft && (
                <div className="card" style={{ padding: 12, marginTop: 8 }} aria-label="Rascunho do email">
                  <div className="small muted">Para: {draft.to ?? "— (o fornecedor não tem email registado)"}</div>
                  <div className="small">
                    <strong>Assunto:</strong> {draft.subject}
                  </div>
                  <pre style={{ whiteSpace: "pre-wrap", margin: "8px 0", fontFamily: "inherit" }}>{draft.body}</pre>
                  <button type="button" className="btn btn--sm" onClick={copyDraft}>
                    Copiar email
                  </button>
                  <span className="small muted"> O sistema não envia este email.</span>
                </div>
              )}
            </div>
          )}

          <h4 style={{ margin: "12px 0 4px" }}>Histórico</h4>
          <ul className="list" aria-label="Histórico do pedido">
            {request.history.map((h, i) => (
              <li key={i} className="list__item">
                <div className="list__main">
                  <span className="list__title">{HISTORY_LABELS[h.action] ?? h.action}</span>
                  <div className="list__meta">
                    {h.changed_by_display_name ?? "—"} · {formatDateTimePt(h.changed_at)}
                    {h.note ? ` · ${h.note}` : ""}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </Modal>
  );
}

// --- Secção no detalhe do fornecedor ---

export function SupplierRequestsSection({
  supplierId,
  canCreate,
  refreshKey,
  onCreate,
  onOpen,
}: {
  supplierId: string;
  canCreate: boolean;
  refreshKey: number;
  onCreate: () => void;
  onOpen: (requestId: string) => void;
}) {
  const [requests, setRequests] = useState<MaterialRequest[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setRequests(null);
    setError(null);
    listMaterialRequests({ supplier_id: supplierId })
      .then(setRequests)
      .catch((e) => setError(e instanceof ApiError ? e.detail : "Não foi possível carregar os pedidos."));
  }, [supplierId, refreshKey]);

  return (
    <div style={{ marginTop: 12 }} aria-label="Pedidos de material">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h4 style={{ margin: 0 }}>Pedidos de material</h4>
        {canCreate && (
          <button type="button" className="btn btn--sm btn--primary" onClick={onCreate}>
            Pedir material
          </button>
        )}
      </div>
      {error ? (
        <div className="small muted">{error}</div>
      ) : requests === null ? (
        <LoadingState rows={2} />
      ) : requests.length === 0 ? (
        <EmptyState compact icon="folder" title="Sem pedidos a este fornecedor." />
      ) : (
        <ul className="list">
          {requests.map((r) => (
            <li key={r.id} className="list__item">
              <button
                type="button"
                className="list__main"
                style={{ background: "none", border: 0, padding: 0, textAlign: "left", cursor: "pointer" }}
                onClick={() => onOpen(r.id)}
              >
                <span className="list__title">{r.project_name ?? "—"}</span>
                <div className="list__meta">
                  {r.lines.length} linha(s) · {euros(r.total)} · {formatDateTimePt(r.created_at)}
                </div>
              </button>
              <RequestStatusBadge status={r.status} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
