import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./IsolatedTimeBank.css";
import Icon from "../components/Icon";
import { useToast } from "../components/Toast";
import { Alert, Badge, Card, EmptyState, ErrorState, LoadingState, Modal, PageHeader } from "../components/ui";
import { useSession } from "../session/SessionContext";
import { formatDatePt, todayIsoLisbon } from "../utils/dates";
import {
  applyTimeBankImport,
  createTimeBankAdjustment,
  createTimeBankEntry,
  formatClockMinute,
  formatSignedTimeBankDuration,
  getTimeBankImport,
  getTimeBankSummary,
  hasBlockingTimeBankImportIssues,
  inferTimeBankMode,
  listTimeBankAdjustments,
  listTimeBankEntries,
  listTimeBankPeople,
  parseClockMinute,
  parseSignedTimeBankDuration,
  previewTimeBankImport,
  resolveTimeBankImport,
  reverseTimeBankAdjustment,
  reverseTimeBankEntry,
  TimeBankAdjustmentKind,
  TimeBankAdjustmentRead,
  TimeBankCalculationMode,
  TimeBankEntryRead,
  TimeBankImportRead,
  TimeBankJsonObject,
  TimeBankPerson,
  TimeBankProvenance,
  TimeBankSummary,
  timeBankDateRange,
} from "../api/timeBank";
import { ApiError } from "../api/client";

const MAX_IMPORT_BYTES = 5 * 1024 * 1024;
const TIME_BANK_PAGE_SIZE = 100;
const MONTHS = [
  ["", "Ano inteiro"],
  ["1", "Janeiro"],
  ["2", "Fevereiro"],
  ["3", "Março"],
  ["4", "Abril"],
  ["5", "Maio"],
  ["6", "Junho"],
  ["7", "Julho"],
  ["8", "Agosto"],
  ["9", "Setembro"],
  ["10", "Outubro"],
  ["11", "Novembro"],
  ["12", "Dezembro"],
] as const;

const MODE_LABELS: Record<TimeBankCalculationMode, string> = {
  standard: "Dia normal",
  saturday: "Sábado ×1,5",
  manual: "Manual",
  imported: "Importado",
};

const KIND_LABELS: Record<TimeBankAdjustmentKind, string> = {
  opening: "Saldo de abertura",
  correction: "Correção",
  consumption: "Consumo",
};

function calculationModeLabel(mode: string): string {
  return MODE_LABELS[mode as TimeBankCalculationMode] ?? mode;
}

function adjustmentKindLabel(kind: string): string {
  return KIND_LABELS[kind as TimeBankAdjustmentKind] ?? kind;
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.detail : fallback;
}

function currentYearMonth(): { year: number; month: string } {
  const today = todayIsoLisbon();
  return { year: Number(today.slice(0, 4)), month: String(Number(today.slice(5, 7))) };
}

function personLabel(person: TimeBankPerson | undefined, personId: string, fallback?: string | null): string {
  return person?.display_name ?? fallback ?? personId;
}

function jsonText(value: unknown): string {
  if (typeof value === "string") return value;
  try {
    const encoded = JSON.stringify(value);
    return encoded === undefined ? String(value) : encoded;
  } catch {
    return String(value);
  }
}

function importCountsLabel(counts: TimeBankImportRead["counts"]): string {
  const parts = [
    counts.source_rows === undefined ? null : `${counts.source_rows} linhas de origem`,
    `${counts.entries} lançamentos`,
    counts.quarantined === undefined ? null : `${counts.quarantined} em quarentena`,
    `${counts.openings} aberturas`,
    `${counts.needs_review} para revisão`,
  ];
  return parts.filter((part): part is string => part !== null).join(" · ");
}

function reviewFlags(flags: TimeBankJsonObject | null | undefined): string {
  const entries = Object.entries(flags ?? {});
  return entries.length > 0
    ? entries.map(([key, value]) => `${key}: ${jsonText(value)}`).join(" · ")
    : "Revisão necessária";
}

function ProvenanceModal({
  title,
  provenance,
  onClose,
}: {
  title: string;
  provenance: TimeBankProvenance;
  onClose: () => void;
}) {
  const fields = Object.entries(provenance);
  return (
    <Modal title={title} onClose={onClose} footer={<button type="button" className="btn" onClick={onClose}>Fechar</button>}>
      {fields.length > 0 ? (
        <dl className="time-bank-provenance">
          {fields.map(([key, value]) => {
            return (
              <div key={key}>
                <dt>{key === "source_hash" || key === "sha256" ? "Hash da fonte" : key}</dt>
                <dd>{jsonText(value)}</dd>
              </div>
            );
          })}
        </dl>
      ) : (
        <p className="muted">Não há detalhes de proveniência disponíveis para este movimento.</p>
      )}
      <p className="small muted">O conteúdo bruto do Excel não é apresentado nem guardado nesta vista.</p>
    </Modal>
  );
}

function ReverseModal({
  title,
  onClose,
  onConfirm,
  saving,
}: {
  title: string;
  onClose: () => void;
  onConfirm: (reason: string) => Promise<void>;
  saving: boolean;
}) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const clean = reason.trim();
    if (!clean) {
      setError("Indique o motivo da anulação.");
      return;
    }
    setError(null);
    try {
      await onConfirm(clean);
    } catch (err) {
      setError(errorMessage(err, "Não foi possível anular o movimento."));
    }
  }

  return (
    <Modal
      title={title}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>Cancelar</button>
          <button type="submit" form="time-bank-reverse-form" className="btn btn--danger" disabled={saving || !reason.trim()}>
            {saving ? "A anular…" : "Confirmar anulação"}
          </button>
        </>
      }
    >
      <form id="time-bank-reverse-form" onSubmit={submit}>
        <p>O lançamento original permanece visível. Será criada uma compensação de sinal oposto.</p>
        <div className="field">
          <label htmlFor="time-bank-reverse-reason">Motivo da anulação *</label>
          <textarea
            id="time-bank-reverse-reason"
            className="textarea"
            rows={3}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            autoFocus
          />
        </div>
        {error && <Alert tone="danger">{error}</Alert>}
      </form>
    </Modal>
  );
}

function EntryModal({
  people,
  defaultPersonId,
  onClose,
  onSaved,
}: {
  people: TimeBankPerson[];
  defaultPersonId?: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [personId, setPersonId] = useState(defaultPersonId ?? people[0]?.id ?? "");
  const [workDate, setWorkDate] = useState(todayIsoLisbon());
  const [start, setStart] = useState("09:00");
  const [end, setEnd] = useState("18:30");
  const [lunchTaken, setLunchTaken] = useState(true);
  const [mode, setMode] = useState<Exclude<TimeBankCalculationMode, "imported">>(inferTimeBankMode(todayIsoLisbon()));
  const [modeTouched, setModeTouched] = useState(false);
  const [manualBalance, setManualBalance] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function handleDateChange(value: string) {
    setWorkDate(value);
    if (!modeTouched) setMode(inferTimeBankMode(value));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!personId || !workDate) {
      setError("Indique a pessoa e a data de trabalho.");
      return;
    }
    const startMinute = parseClockMinute(start);
    const endMinute = parseClockMinute(end);
    if (mode !== "manual" && (startMinute === null || endMinute === null || endMinute <= startMinute)) {
      setError("Indique horas válidas; a saída tem de ser posterior à entrada.");
      return;
    }
    const payload = {
      person_id: personId,
      work_date: workDate,
      start_minute: mode === "manual" ? null : startMinute,
      end_minute: mode === "manual" ? null : endMinute,
      lunch_taken: mode === "manual" ? null : lunchTaken,
      calculation_mode: mode,
      ...(mode === "manual" ? { manual_balance_seconds: parseSignedTimeBankDuration(manualBalance), reason: reason.trim() } : {}),
    } as Parameters<typeof createTimeBankEntry>[0];
    if (mode === "manual" && (payload.manual_balance_seconds === null || !reason.trim())) {
      setError("O modo manual exige um saldo HH:MM assinado e um motivo.");
      return;
    }
    setSaving(true);
    try {
      await createTimeBankEntry(payload);
      onSaved();
    } catch (err) {
      setError(errorMessage(err, "Não foi possível registar a jornada."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title="Registar jornada"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>Cancelar</button>
          <button type="submit" form="time-bank-entry-form" className="btn btn--primary" disabled={saving}>
            {saving ? "A guardar…" : "Guardar jornada"}
          </button>
        </>
      }
    >
      <form id="time-bank-entry-form" className="form-grid" onSubmit={submit}>
        {error && <div className="span-2"><Alert tone="danger">{error}</Alert></div>}
        <div className="field span-2">
          <label htmlFor="time-bank-entry-person">Pessoa</label>
          <select id="time-bank-entry-person" className="select" value={personId} onChange={(event) => setPersonId(event.target.value)}>
            {people.filter((person) => person.is_active).map((person) => <option key={person.id} value={person.id}>{person.display_name}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="time-bank-entry-date">Data de trabalho *</label>
          <input id="time-bank-entry-date" className="input" type="date" value={workDate} onChange={(event) => handleDateChange(event.target.value)} required />
        </div>
        <div className="field">
          <label htmlFor="time-bank-entry-mode">Modo de cálculo</label>
          <select
            id="time-bank-entry-mode"
            className="select"
            value={mode}
            onChange={(event) => {
              setMode(event.target.value as Exclude<TimeBankCalculationMode, "imported">);
              setModeTouched(true);
            }}
          >
            <option value="standard">Dia normal</option>
            <option value="saturday">Sábado ×1,5</option>
            <option value="manual">Manual</option>
          </select>
          <span className="small muted">O modo é sugerido pela data, mas pode ser alterado explicitamente.</span>
        </div>
        <div className="field">
          <label htmlFor="time-bank-entry-start">Entrada *</label>
          <input id="time-bank-entry-start" className="input" type="time" value={start} onChange={(event) => setStart(event.target.value)} disabled={mode === "manual"} />
        </div>
        <div className="field">
          <label htmlFor="time-bank-entry-end">Saída *</label>
          <input id="time-bank-entry-end" className="input" type="time" value={end} onChange={(event) => setEnd(event.target.value)} disabled={mode === "manual"} />
        </div>
        <label className="checkbox span-2" htmlFor="time-bank-entry-lunch">
          <input id="time-bank-entry-lunch" type="checkbox" checked={lunchTaken} onChange={(event) => setLunchTaken(event.target.checked)} disabled={mode === "manual"} />
          <span>Almoço descontado (1 hora)</span>
        </label>
        {mode === "manual" && (
          <>
            <div className="field">
              <label htmlFor="time-bank-entry-manual-balance">Saldo manual (HH:MM) *</label>
              <input id="time-bank-entry-manual-balance" className="input" value={manualBalance} onChange={(event) => setManualBalance(event.target.value)} placeholder="-01:30" inputMode="text" />
              <span className="small muted">Use um valor assinado; não use horas decimais.</span>
            </div>
            <div className="field">
              <label htmlFor="time-bank-entry-reason">Motivo *</label>
              <textarea id="time-bank-entry-reason" className="textarea" rows={2} value={reason} onChange={(event) => setReason(event.target.value)} />
            </div>
          </>
        )}
      </form>
    </Modal>
  );
}

function AdjustmentModal({
  people,
  defaultPersonId,
  onClose,
  onSaved,
}: {
  people: TimeBankPerson[];
  defaultPersonId?: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [personId, setPersonId] = useState(defaultPersonId ?? people[0]?.id ?? "");
  const [date, setDate] = useState(todayIsoLisbon());
  const [delta, setDelta] = useState("");
  const [kind, setKind] = useState<Exclude<TimeBankAdjustmentKind, "opening">>("correction");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const seconds = parseSignedTimeBankDuration(delta);
    if (!personId || !date || seconds === null || !reason.trim()) {
      setError("Indique pessoa, data, delta HH:MM assinado e motivo.");
      return;
    }
    if (kind === "consumption" && seconds >= 0) {
      setError("Um consumo tem de ser negativo.");
      return;
    }
    setSaving(true);
    try {
      await createTimeBankAdjustment({ person_id: personId, effective_date: date, delta_seconds: seconds, kind, reason: reason.trim() });
      onSaved();
    } catch (err) {
      setError(errorMessage(err, "Não foi possível registar o ajuste."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title="Registar ajuste"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>Cancelar</button>
          <button type="submit" form="time-bank-adjustment-form" className="btn btn--primary" disabled={saving}>
            {saving ? "A guardar…" : "Guardar ajuste"}
          </button>
        </>
      }
    >
      <form id="time-bank-adjustment-form" className="form-grid" onSubmit={submit}>
        {error && <div className="span-2"><Alert tone="danger">{error}</Alert></div>}
        <div className="field span-2">
          <label htmlFor="time-bank-adjustment-person">Pessoa</label>
          <select id="time-bank-adjustment-person" className="select" value={personId} onChange={(event) => setPersonId(event.target.value)}>
            {people.filter((person) => person.is_active).map((person) => <option key={person.id} value={person.id}>{person.display_name}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="time-bank-adjustment-date">Data efetiva *</label>
          <input id="time-bank-adjustment-date" className="input" type="date" value={date} onChange={(event) => setDate(event.target.value)} required />
        </div>
        <div className="field">
          <label htmlFor="time-bank-adjustment-kind">Tipo</label>
          <select id="time-bank-adjustment-kind" className="select" value={kind} onChange={(event) => setKind(event.target.value as Exclude<TimeBankAdjustmentKind, "opening">)}>
            <option value="correction">Correção</option>
            <option value="consumption">Consumo</option>
          </select>
        </div>
        <div className="field span-2">
          <label htmlFor="time-bank-adjustment-delta">Delta (HH:MM assinado) *</label>
          <input id="time-bank-adjustment-delta" className="input" value={delta} onChange={(event) => setDelta(event.target.value)} placeholder="+02:00 ou -00:30" inputMode="text" />
        </div>
        <div className="field span-2">
          <label htmlFor="time-bank-adjustment-reason">Motivo *</label>
          <textarea id="time-bank-adjustment-reason" className="textarea" rows={3} value={reason} onChange={(event) => setReason(event.target.value)} />
        </div>
      </form>
    </Modal>
  );
}

function ImportPanel({
  people,
  onApplied,
}: {
  people: TimeBankPerson[];
  onApplied: () => Promise<void>;
}) {
  const { notify } = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [batch, setBatch] = useState<TimeBankImportRead | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [uploading, setUploading] = useState(false);
  const [savingMapping, setSavingMapping] = useState(false);
  const [applying, setApplying] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [inputKey, setInputKey] = useState(0);

  async function handleFile(file: File | undefined) {
    if (!file) return;
    setError(null);
    if (file.size > MAX_IMPORT_BYTES) {
      setError("O ficheiro excede o limite de 5 MiB.");
      return;
    }
    setUploading(true);
    try {
      const preview = await previewTimeBankImport(file);
      setBatch(preview);
      setMapping(Object.fromEntries(preview.people.filter((person) => person.person_id).map((person) => [person.source_label, person.person_id as string])));
    } catch (err) {
      setError(errorMessage(err, "Não foi possível pré-visualizar o Excel."));
    } finally {
      setUploading(false);
      setInputKey((key) => key + 1);
    }
  }

  async function saveMapping() {
    if (!batch) return;
    setError(null);
    setSavingMapping(true);
    try {
      const resolved = await resolveTimeBankImport(batch.id, { person_mapping: mapping });
      setBatch(resolved);
      setMapping((current) => ({
        ...current,
        ...Object.fromEntries(resolved.people.filter((person) => person.person_id).map((person) => [person.source_label, person.person_id as string])),
      }));
      notify("Mapeamento guardado.", "success");
    } catch (err) {
      setError(errorMessage(err, "Não foi possível guardar o mapeamento."));
    } finally {
      setSavingMapping(false);
    }
  }

  async function applyImport() {
    if (!batch) return;
    setError(null);
    setApplying(true);
    try {
      await applyTimeBankImport(batch.id);
      // A resposta da mutação não substitui o readback: confirma o estado
      // persistido antes de mostrar sucesso ou recarregar o livro.
      const readback = await getTimeBankImport(batch.id);
      setBatch(readback);
      await onApplied();
      notify(`Importação aplicada: ${readback.applied_counts?.entries ?? readback.counts.entries} lançamentos.`, "success");
      setConfirmOpen(false);
    } catch (err) {
      setError(errorMessage(err, "A aplicação falhou; o livro não foi marcado como atualizado."));
    } finally {
      setApplying(false);
    }
  }

  const blocked = batch ? hasBlockingTimeBankImportIssues(batch, mapping) : true;
  const applied = batch?.status === "applied";

  return (
    <Card
      title="Importar Excel"
      icon="database"
      className="time-bank-import"
      actions={
        <>
          <button type="button" className="btn btn--sm btn--primary" onClick={() => fileInputRef.current?.click()} disabled={uploading}>
            <Icon name="database" size={14} /> {uploading ? "A processar…" : "Importar Excel"}
          </button>
          <input
            ref={fileInputRef}
            key={inputKey}
            className="time-bank-file-input"
            type="file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            aria-label="Ficheiro Excel"
            onChange={(event) => void handleFile(event.target.files?.[0])}
            disabled={uploading}
          />
        </>
      }
    >
      {error && <Alert tone="danger">{error}</Alert>}
      {!batch && <p className="muted">O upload abre sempre uma pré-visualização. Nenhuma linha é aplicada automaticamente.</p>}
      {batch && (
        <div className="time-bank-import__body">
          <div className="time-bank-import__meta">
            <span>Hash: <code>{batch.sha256.slice(0, 16)}…</code></span>
            <span>Ano da fonte: {batch.source_year ?? "não identificado"}</span>
            <span>{importCountsLabel(batch.counts)}</span>
          </div>
          {batch.people.length > 0 && (
            <div>
              <h3>Mapeamento explícito de pessoas</h3>
              <p className="small muted">Não são criadas pessoas automaticamente. Pessoas ambíguas ou sem correspondência bloqueiam a aplicação até serem mapeadas.</p>
              <div className="time-bank-mapping-list">
                {batch.people.map((source) => {
                  const selected = mapping[source.source_label] ?? source.person_id ?? "";
                  return (
                    <div className="time-bank-mapping-row" key={source.source_label}>
                      <label htmlFor={`time-bank-map-${source.source_label}`}>{source.source_label}</label>
                      <select
                        id={`time-bank-map-${source.source_label}`}
                        aria-label={`Pessoa do Excel: ${source.source_label}`}
                        className="select"
                        value={selected}
                        onChange={(event) => setMapping((current) => ({ ...current, [source.source_label]: event.target.value }))}
                      >
                        <option value="">Escolher pessoa…</option>
                        {people.filter((person) => person.is_active).map((person) => <option key={person.id} value={person.id}>{person.display_name}</option>)}
                      </select>
                      {source.candidates.length > 0 && <span className="small muted">Candidatos sugeridos: {source.candidates.map((candidate) => candidate.display_name).join(", ")}</span>}
                    </div>
                  );
                })}
              </div>
              <button type="button" className="btn btn--sm" onClick={() => void saveMapping()} disabled={savingMapping}>
                {savingMapping ? "A guardar…" : "Guardar mapeamento"}
              </button>
            </div>
          )}
          <div>
            <h3>Anomalias e validações</h3>
            {batch.issues.length === 0 ? (
              <p className="muted">Não foram detetadas anomalias no preview.</p>
            ) : (
              <ul className="time-bank-issues">
                {batch.issues.map((issue, index) => (
                  <li key={`${issue.code}-${index}`}>
                    <Badge tone={issue.blocking ? "danger" : "warning"}>{issue.blocking ? "Bloqueante" : "needs_review"}</Badge>
                    <span>{issue.message}</span>
                    {(issue.sheet || issue.row) && <span className="small muted">{issue.sheet ? `Folha ${issue.sheet}` : ""}{issue.row ? ` · linha ${issue.row}` : ""}</span>}
                  </li>
                ))}
              </ul>
            )}
            <p className="small muted">Anomalias preserváveis ficam marcadas para revisão e não são apresentadas como validação jurídica.</p>
          </div>
          {applied ? (
            <Alert tone="success" title="Importação aplicada">{batch.applied_counts?.entries ?? batch.counts.entries} lançamentos foram lidos de volta após a aplicação.</Alert>
          ) : (
            <div className="time-bank-import__actions">
              {blocked && <span className="small muted">A aplicação fica bloqueada enquanto houver uma pessoa por mapear ou uma issue bloqueante.</span>}
              <button type="button" className="btn btn--primary" onClick={() => setConfirmOpen(true)} disabled={blocked || applying}>
                {applying ? "A aplicar…" : "Aplicar importação"}
              </button>
            </div>
          )}
        </div>
      )}
      {confirmOpen && (
        <Modal
          title="Confirmar aplicação do Excel"
          onClose={() => setConfirmOpen(false)}
          footer={
            <>
              <button type="button" className="btn" onClick={() => setConfirmOpen(false)}>Cancelar</button>
              <button type="button" className="btn btn--primary" onClick={() => void applyImport()} disabled={applying}>Confirmar aplicação</button>
            </>
          }
        >
          <p>As linhas serão preservadas como lançamentos append-only. Confirme apenas depois de rever o mapeamento e as anomalias.</p>
        </Modal>
      )}
    </Card>
  );
}

function SummaryCards({ summary }: { summary: TimeBankSummary | null }) {
  if (!summary || summary.people.length === 0) return <EmptyState title="Sem saldo para os filtros selecionados" text="Não há pessoas ou movimentos no período escolhido." icon="clock" compact />;
  return (
    <div className="time-bank-summary-grid">
      {summary.people.map((person) => (
        <Card key={person.person_id} title={person.display_name} icon="clock" className="time-bank-summary-card">
          <div className="time-bank-balance-main">
            <span className="small muted">Saldo acumulado</span>
            <strong>{formatSignedTimeBankDuration(person.balance_seconds)}</strong>
          </div>
          <dl className="time-bank-summary-values">
            <div><dt>Abertura / transitado</dt><dd>{formatSignedTimeBankDuration(person.opening_seconds)}</dd></div>
            <div><dt>Créditos no período</dt><dd>{formatSignedTimeBankDuration(person.credited_seconds)}</dd></div>
            <div><dt>Débitos no período</dt><dd>{formatSignedTimeBankDuration(-Math.abs(person.debited_seconds))}</dd></div>
            <div><dt>Movimento do período</dt><dd>{formatSignedTimeBankDuration(person.period_seconds)}</dd></div>
          </dl>
          {person.needs_review_count > 0 && <Badge tone="warning">{person.needs_review_count} para revisão</Badge>}
          {person.warnings.length > 0 && (
            <div className="time-bank-warning-list">
              {person.warnings.map((warning) => <Alert key={`${person.person_id}-${warning.code}`} tone="warning" title="Aviso não bloqueante">{warning.message}</Alert>)}
            </div>
          )}
        </Card>
      ))}
    </div>
  );
}

function EntryTable({
  entries,
  people,
  canManage,
  reversedIds,
  onReverse,
  onProvenance,
}: {
  entries: TimeBankEntryRead[] | null;
  people: TimeBankPerson[];
  canManage: boolean;
  reversedIds: ReadonlySet<string>;
  onReverse: (entry: TimeBankEntryRead) => void;
  onProvenance: (title: string, provenance: TimeBankProvenance) => void;
}) {
  if (!entries) return <LoadingState label="A carregar lançamentos…" rows={5} />;
  if (entries.length === 0) return <EmptyState title="Sem lançamentos" text="Não há lançamentos de jornada para os filtros selecionados." icon="clock" compact />;
  return (
    <div className="table-wrap time-bank-table-wrap">
      <table className="table time-bank-table">
        <thead><tr><th>Data</th><th>Pessoa</th><th>Horário</th><th>Modo</th><th>Saldo</th><th>Calculado</th><th>Estado</th><th>Ações</th></tr></thead>
        <tbody>
          {entries.map((entry) => {
            const reversed = reversedIds.has(entry.id);
            const person = people.find((candidate) => candidate.id === entry.person_id);
            const difference = entry.calculated_seconds !== null && entry.calculated_seconds !== entry.balance_seconds;
            return (
              <tr key={entry.id} className={entry.needs_review ? "time-bank-row--review" : undefined}>
                <td data-label="Data">{formatDatePt(entry.work_date)}</td>
                <td data-label="Pessoa">{personLabel(person, entry.person_id)}</td>
                <td data-label="Horário">{entry.start_minute === null || entry.end_minute === null ? "Sem horário" : `${formatClockMinute(entry.start_minute)}–${formatClockMinute(entry.end_minute)}${entry.lunch_taken ? " · almoço" : ""}`}</td>
                <td data-label="Modo">{calculationModeLabel(entry.calculation_mode)}</td>
                <td data-label="Saldo"><strong>{formatSignedTimeBankDuration(entry.balance_seconds)}</strong></td>
                <td data-label="Calculado">{entry.calculated_seconds === null ? "—" : <span className={difference ? "time-bank-diff" : undefined}>{formatSignedTimeBankDuration(entry.calculated_seconds)}{difference && " · diferente"}</span>}</td>
                <td data-label="Estado">
                  {reversed && <Badge tone="neutral">Original anulada</Badge>}
                  {entry.reversal_of_id && <Badge tone="info">Compensação</Badge>}
                  {entry.needs_review && <Badge tone="warning">needs_review: {reviewFlags(entry.review_flags)}</Badge>}
                  {!reversed && !entry.reversal_of_id && !entry.needs_review && <Badge tone="success">Registado</Badge>}
                </td>
                <td data-label="Ações" className="time-bank-actions-cell">
                  <button type="button" className="btn btn--sm btn--ghost" onClick={() => onProvenance("Proveniência do lançamento", entry.provenance)} disabled={Object.keys(entry.provenance).length === 0}>
                    Proveniência
                  </button>
                  {canManage && !reversed && !entry.reversal_of_id && <button type="button" className="btn btn--sm btn--danger-ghost" onClick={() => onReverse(entry)}>Anular lançamento</button>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function AdjustmentTable({
  adjustments,
  people,
  canManage,
  reversedIds,
  onReverse,
  onProvenance,
}: {
  adjustments: TimeBankAdjustmentRead[] | null;
  people: TimeBankPerson[];
  canManage: boolean;
  reversedIds: ReadonlySet<string>;
  onReverse: (adjustment: TimeBankAdjustmentRead) => void;
  onProvenance: (title: string, provenance: TimeBankProvenance) => void;
}) {
  if (!adjustments) return <LoadingState label="A carregar ajustes…" rows={4} />;
  if (adjustments.length === 0) return <EmptyState title="Sem ajustes" text="Não há ajustes no período selecionado." icon="history" compact />;
  return (
    <div className="table-wrap time-bank-table-wrap">
      <table className="table time-bank-table">
        <thead><tr><th>Data</th><th>Pessoa</th><th>Tipo</th><th>Delta</th><th>Motivo</th><th>Estado</th><th>Ações</th></tr></thead>
        <tbody>
          {adjustments.map((adjustment) => {
            const reversed = reversedIds.has(adjustment.id);
            const person = people.find((candidate) => candidate.id === adjustment.person_id);
            return (
              <tr key={adjustment.id}>
                <td data-label="Data">{formatDatePt(adjustment.effective_date)}</td>
                <td data-label="Pessoa">{personLabel(person, adjustment.person_id)}</td>
                <td data-label="Tipo">{adjustmentKindLabel(adjustment.kind)}</td>
                <td data-label="Delta"><strong>{formatSignedTimeBankDuration(adjustment.delta_seconds)}</strong></td>
                <td data-label="Motivo">{adjustment.reason}</td>
                <td data-label="Estado">
                  {reversed && <Badge tone="neutral">Original anulado</Badge>}
                  {adjustment.reversal_of_id && <Badge tone="info">Compensação</Badge>}
                  {!reversed && !adjustment.reversal_of_id && <Badge tone="success">Registado</Badge>}
                </td>
                <td data-label="Ações" className="time-bank-actions-cell">
                  <button type="button" className="btn btn--sm btn--ghost" onClick={() => onProvenance("Proveniência do ajuste", adjustment.provenance)} disabled={Object.keys(adjustment.provenance).length === 0}>Proveniência</button>
                  {canManage && !reversed && !adjustment.reversal_of_id && <button type="button" className="btn btn--sm btn--danger-ghost" onClick={() => onReverse(adjustment)}>Anular ajuste</button>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function LedgerPagination({
  label,
  page,
  total,
  itemCount,
  onPageChange,
}: {
  label: string;
  page: number;
  total: number;
  itemCount: number;
  onPageChange: (page: number) => void;
}) {
  if (total === 0) return null;
  const first = page * TIME_BANK_PAGE_SIZE + 1;
  const last = Math.min(page * TIME_BANK_PAGE_SIZE + itemCount, total);
  const hasPrevious = page > 0;
  const hasNext = (page + 1) * TIME_BANK_PAGE_SIZE < total;
  return (
    <nav className="time-bank-pagination" aria-label={`Paginação de ${label}`}>
      <span className="small muted">{first}–{last} de {total}</span>
      <div className="time-bank-pagination__actions">
        <button
          type="button"
          className="btn btn--sm"
          onClick={() => onPageChange(page - 1)}
          disabled={!hasPrevious}
          aria-label={`Página anterior de ${label}`}
        >
          Anterior
        </button>
        <button
          type="button"
          className="btn btn--sm"
          onClick={() => onPageChange(page + 1)}
          disabled={!hasNext}
          aria-label={`Próxima página de ${label}`}
        >
          Seguinte
        </button>
      </div>
    </nav>
  );
}

export default function IsolatedTimeBank() {
  const { me, can } = useSession();
  const { notify } = useToast();
  const canViewOwn = can("time_bank.view_own");
  const canViewAll = can("time_bank.view_all");
  const canManage = can("time_bank.manage_all");
  const hasReadAccess = canViewOwn || canViewAll;
  const manager = canViewAll;
  const initial = useMemo(currentYearMonth, []);
  const [year, setYear] = useState(initial.year);
  const [month, setMonth] = useState(initial.month);
  const [personId, setPersonId] = useState("");
  const [people, setPeople] = useState<TimeBankPerson[]>([]);
  const [summary, setSummary] = useState<TimeBankSummary | null>(null);
  const [entries, setEntries] = useState<TimeBankEntryRead[] | null>(null);
  const [adjustments, setAdjustments] = useState<TimeBankAdjustmentRead[] | null>(null);
  const [totalEntries, setTotalEntries] = useState(0);
  const [totalAdjustments, setTotalAdjustments] = useState(0);
  const [entryPage, setEntryPage] = useState(0);
  const [adjustmentPage, setAdjustmentPage] = useState(0);
  const [knownReversedEntryIds, setKnownReversedEntryIds] = useState<Set<string>>(new Set());
  const [knownReversedAdjustmentIds, setKnownReversedAdjustmentIds] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [peopleError, setPeopleError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [entryModalOpen, setEntryModalOpen] = useState(false);
  const [adjustmentModalOpen, setAdjustmentModalOpen] = useState(false);
  const [reverseTarget, setReverseTarget] = useState<{ kind: "entry" | "adjustment"; id: string; label: string } | null>(null);
  const [reverseSaving, setReverseSaving] = useState(false);
  const [provenanceTarget, setProvenanceTarget] = useState<{ title: string; provenance: TimeBankProvenance } | null>(null);
  const [actionNotice, setActionNotice] = useState<string | null>(null);

  const selectedPersonId = manager ? personId || undefined : me?.person_id;
  const range = useMemo(() => timeBankDateRange(year, month ? Number(month) : null), [year, month]);

  const entryReversedIds = useMemo(() => new Set([
    ...knownReversedEntryIds,
    ...(entries ?? []).flatMap((entry) => entry.reversal_of_id ? [entry.reversal_of_id] : []),
  ]), [entries, knownReversedEntryIds]);
  const adjustmentReversedIds = useMemo(() => new Set([
    ...knownReversedAdjustmentIds,
    ...(adjustments ?? []).flatMap((adjustment) => adjustment.reversal_of_id ? [adjustment.reversal_of_id] : []),
  ]), [adjustments, knownReversedAdjustmentIds]);

  const reload = useCallback(() => setReloadKey((key) => key + 1), []);

  useEffect(() => {
    setEntryPage(0);
    setAdjustmentPage(0);
  }, [selectedPersonId, year, month, range.fromDate, range.toDate]);

  useEffect(() => {
    if (!manager) {
      setPeople([]);
      setPeopleError(null);
      return;
    }
    let cancelled = false;
    setPeopleError(null);
    listTimeBankPeople()
      .then((result) => !cancelled && setPeople(result))
      .catch((err) => !cancelled && setPeopleError(errorMessage(err, "Não foi possível carregar as pessoas do Banco de Horas.")));
    return () => {
      cancelled = true;
    };
  }, [manager, reloadKey]);

  useEffect(() => {
    if (!hasReadAccess) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    const hasLastKnown = summary !== null || entries !== null || adjustments !== null;
    setLoading(!hasLastKnown);
    setRefreshing(hasLastKnown);
    setError(null);
    const entryFilters = {
      personId: selectedPersonId,
      fromDate: range.fromDate,
      toDate: range.toDate,
      limit: TIME_BANK_PAGE_SIZE,
      offset: entryPage * TIME_BANK_PAGE_SIZE,
    };
    const adjustmentFilters = {
      personId: selectedPersonId,
      fromDate: range.fromDate,
      toDate: range.toDate,
      limit: TIME_BANK_PAGE_SIZE,
      offset: adjustmentPage * TIME_BANK_PAGE_SIZE,
    };
    Promise.all([
      getTimeBankSummary({ personId: selectedPersonId, year, month: month ? Number(month) : null }),
      listTimeBankEntries(entryFilters),
      listTimeBankAdjustments(adjustmentFilters),
    ])
      .then(([summaryResult, entriesResult, adjustmentsResult]) => {
        if (cancelled) return;
        setSummary(summaryResult);
        setEntries(entriesResult.items);
        setTotalEntries(entriesResult.total);
        setAdjustments(adjustmentsResult.items);
        setTotalAdjustments(adjustmentsResult.total);
      })
      .catch((err) => !cancelled && setError(errorMessage(err, "Não foi possível carregar os dados do Banco de Horas.")))
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
        setRefreshing(false);
      });
    return () => {
      cancelled = true;
    };
    // The reload key intentionally causes a fresh read while preserving last-known rows.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adjustmentPage, canViewAll, canViewOwn, entryPage, hasReadAccess, selectedPersonId, year, month, range.fromDate, range.toDate, reloadKey]);

  const visiblePeople = manager ? people : me?.person_id ? [{ id: me.person_id, display_name: me.display_name ?? "A minha conta", is_active: true }] : [];
  const initialPersonForForm = manager ? personId || people[0]?.id : me?.person_id;

  async function handleReverse(reason: string) {
    if (!reverseTarget) return;
    setReverseSaving(true);
    try {
      if (reverseTarget.kind === "entry") {
        const compensation = await reverseTimeBankEntry(reverseTarget.id, { reason });
        if (compensation.reversal_of_id) {
          setKnownReversedEntryIds((current) => new Set(current).add(compensation.reversal_of_id as string));
        }
      } else {
        const compensation = await reverseTimeBankAdjustment(reverseTarget.id, { reason });
        if (compensation.reversal_of_id) {
          setKnownReversedAdjustmentIds((current) => new Set(current).add(compensation.reversal_of_id as string));
        }
      }
      setReverseTarget(null);
      setActionNotice("Correção por anulação e novo lançamento: o lançamento original continua visível; registe o novo lançamento numa operação separada.");
      notify("Anulação registada.", "success");
      reload();
    } catch (err) {
      throw err;
    } finally {
      setReverseSaving(false);
    }
  }

  async function afterWrite(message: string) {
    setEntryModalOpen(false);
    setAdjustmentModalOpen(false);
    setActionNotice(message);
    notify(message, "success");
    reload();
  }

  if (!hasReadAccess) {
    return (
      <>
        <PageHeader title="Banco de Horas" subtitle="Consulta de saldo e lançamentos." />
        <Alert tone="danger" title="Sem permissão">A sua conta não tem uma capability de consulta do Banco de Horas.</Alert>
      </>
    );
  }

  if (loading && !summary && !entries && !adjustments) {
    return <LoadingState label="A carregar o Banco de Horas…" rows={8} />;
  }

  return (
    <>
      <PageHeader
        title="Banco de Horas"
        subtitle={manager ? "Consulta e gestão append-only de jornadas, saldos, ajustes e importações." : "Consulte os seus lançamentos e saldo acumulado."}
        actions={
          canManage && (
            <div className="page-header__actions">
              <button type="button" className="btn btn--primary" onClick={() => setEntryModalOpen(true)} disabled={visiblePeople.length === 0}><Icon name="plus" size={16} /> Registar jornada</button>
              <button type="button" className="btn" onClick={() => setAdjustmentModalOpen(true)} disabled={visiblePeople.length === 0}><Icon name="plus" size={16} /> Registar ajuste</button>
            </div>
          )
        }
      />

      <Card title="Filtros" icon="search" className="time-bank-filters">
        <div className="time-bank-filter-grid">
          <div className="field">
            <label htmlFor="time-bank-filter-year">Ano</label>
            <input id="time-bank-filter-year" className="input" type="number" min={2000} max={2100} value={year} onChange={(event) => setYear(Number(event.target.value) || initial.year)} />
          </div>
          <div className="field">
            <label htmlFor="time-bank-filter-month">Mês</label>
            <select id="time-bank-filter-month" className="select" value={month} onChange={(event) => setMonth(event.target.value)}>
              {MONTHS.map(([value, label]) => <option key={value || "year"} value={value}>{label}</option>)}
            </select>
          </div>
          {manager ? (
            <div className="field time-bank-filter-person">
              <label htmlFor="time-bank-filter-person">Pessoa a consultar</label>
              <select id="time-bank-filter-person" className="select" value={personId} onChange={(event) => setPersonId(event.target.value)} disabled={Boolean(peopleError)}>
                <option value="">Todas as pessoas</option>
                {people.filter((person) => person.is_active).map((person) => <option key={person.id} value={person.id}>{person.display_name}</option>)}
              </select>
            </div>
          ) : (
            <div className="time-bank-own-scope"><Badge tone="info">Âmbito: os meus registos</Badge><span className="small muted">Não pode consultar outra pessoa.</span></div>
          )}
        </div>
        <div className="small muted time-bank-filter-caption">Período: {formatDatePt(range.fromDate)} a {formatDatePt(range.toDate)} · datas inclusivas · horas locais, sem conversão de fuso horário.</div>
        {peopleError && <Alert tone="danger" action={<button type="button" className="btn btn--sm" onClick={reload}>Tentar novamente</button>}>{peopleError}</Alert>}
      </Card>

      {error && (
        <Alert tone="danger" title={summary || entries || adjustments ? "Dados anteriores mantidos" : "Não foi possível carregar os dados"} action={<button type="button" className="btn btn--sm" onClick={reload}>Tentar novamente</button>}>
          {error}
        </Alert>
      )}
      {refreshing && <div className="time-bank-refresh" role="status"><Icon name="refresh" size={14} /> A atualizar — os últimos dados continuam visíveis.</div>}
      {actionNotice && <Alert tone="info" action={<button type="button" className="btn btn--sm" onClick={() => setActionNotice(null)}>Fechar</button>}>{actionNotice}</Alert>}

      <section aria-labelledby="time-bank-summary-heading">
        <div className="time-bank-section-heading"><h2 id="time-bank-summary-heading">Saldos e avisos</h2><span className="small muted">Abertura, créditos, débitos e movimento do período estão separados.</span></div>
        <SummaryCards summary={summary} />
      </section>

      <Card title={`Lançamentos (${totalEntries})`} icon="clock" className="time-bank-ledger-card">
        <EntryTable entries={entries} people={visiblePeople} canManage={canManage} reversedIds={entryReversedIds} onReverse={(entry) => setReverseTarget({ kind: "entry", id: entry.id, label: "lançamento" })} onProvenance={(title, provenance) => setProvenanceTarget({ title, provenance })} />
        <LedgerPagination label="lançamentos" page={entryPage} total={totalEntries} itemCount={entries?.length ?? 0} onPageChange={setEntryPage} />
      </Card>

      <Card title={`Ajustes (${totalAdjustments})`} icon="history" className="time-bank-ledger-card">
        <AdjustmentTable adjustments={adjustments} people={visiblePeople} canManage={canManage} reversedIds={adjustmentReversedIds} onReverse={(adjustment) => setReverseTarget({ kind: "adjustment", id: adjustment.id, label: "ajuste" })} onProvenance={(title, provenance) => setProvenanceTarget({ title, provenance })} />
        <LedgerPagination label="ajustes" page={adjustmentPage} total={totalAdjustments} itemCount={adjustments?.length ?? 0} onPageChange={setAdjustmentPage} />
      </Card>

      {canManage && canViewAll && <ImportPanel people={people} onApplied={async () => { reload(); }} />}

      {entryModalOpen && <EntryModal people={visiblePeople} defaultPersonId={initialPersonForForm} onClose={() => setEntryModalOpen(false)} onSaved={() => void afterWrite("Jornada registada. O saldo foi recarregado a partir da API.")} />}
      {adjustmentModalOpen && <AdjustmentModal people={visiblePeople} defaultPersonId={initialPersonForForm} onClose={() => setAdjustmentModalOpen(false)} onSaved={() => void afterWrite("Ajuste registado. O saldo foi recarregado a partir da API.")} />}
      {reverseTarget && <ReverseModal title={`Anular ${reverseTarget.label}`} onClose={() => setReverseTarget(null)} onConfirm={handleReverse} saving={reverseSaving} />}
      {provenanceTarget && <ProvenanceModal title={provenanceTarget.title} provenance={provenanceTarget.provenance} onClose={() => setProvenanceTarget(null)} />}
    </>
  );
}
