import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import "./MyTimeBank.css";
import { ApiError } from "../api/client";
import {
  createMyTimeBankEntry,
  formatClockMinute,
  formatSignedTimeBankDuration,
  getTimeBankSummary,
  listTimeBankAdjustments,
  listTimeBankEntries,
  parseClockMinute,
  previewMyTimeBankEntry,
  reverseMyTimeBankEntry,
} from "../api/timeBank";
import type {
  TimeBankAdjustmentRead,
  TimeBankEntryRead,
  TimeBankMyEntryPreview,
  TimeBankSummary,
} from "../api/timeBank";
import { Alert, Badge, Card, EmptyState, ErrorState, LoadingState, PageHeader } from "../components/ui";
import { formatDatePt, todayIsoLisbon } from "../utils/dates";

const HISTORY_LIMIT = 100;

type Hours = { start: string; end: string };

type Validation = {
  valid: boolean;
  message: string | null;
  startMinute: number | null;
  endMinute: number | null;
};

function apiErrorMessage(error: unknown): string {
  return error instanceof ApiError ? error.detail : "Não foi possível contactar o servidor.";
}

function weekdayForIsoDate(value: string): number | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return null;
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return Number.isNaN(date.getTime()) ? null : date.getUTCDay();
}

function defaultHoursForDate(value: string): Hours {
  const weekday = weekdayForIsoDate(value);
  if (weekday === 5) return { start: "09:00", end: "14:00" };
  if (weekday === 6) return { start: "09:00", end: "13:00" };
  return { start: "09:00", end: "18:30" };
}

function validateJourney(workDate: string, start: string, end: string, today: string): Validation {
  if (!workDate) return { valid: false, message: "Indique uma data.", startMinute: null, endMinute: null };
  if (workDate > today) return { valid: false, message: "A data não pode ser futura.", startMinute: null, endMinute: null };
  const weekday = weekdayForIsoDate(workDate);
  if (weekday === null) return { valid: false, message: "Indique uma data válida.", startMinute: null, endMinute: null };
  if (weekday === 0) {
    return {
      valid: false,
      message: "Domingos e feriados só podem ser lançados por um Chefe ou Administrador.",
      startMinute: null,
      endMinute: null,
    };
  }
  const startMinute = parseClockMinute(start);
  const endMinute = parseClockMinute(end);
  if (startMinute === null || endMinute === null || endMinute <= startMinute) {
    return {
      valid: false,
      message: "Indique horas válidas; a saída tem de ser posterior à entrada.",
      startMinute,
      endMinute,
    };
  }
  return { valid: true, message: null, startMinute, endMinute };
}

function sourceIsSelfService(entry: TimeBankEntryRead): boolean {
  return entry.provenance.source === "self_service";
}

function entryHasCompensation(entry: TimeBankEntryRead, reversedIds: ReadonlySet<string>): boolean {
  return reversedIds.has(entry.id);
}

function PreviewPanel({
  validation,
  preview,
  loading,
  error,
  workDate,
}: {
  validation: Validation;
  preview: TimeBankMyEntryPreview | null;
  loading: boolean;
  error: string | null;
  workDate: string;
}) {
  const weekday = weekdayForIsoDate(workDate);
  return (
    <div className="my-time-bank-preview" aria-live="polite">
      {validation.message && <Alert tone="warning">{validation.message}</Alert>}
      {weekday === 6 && <p className="small muted">Sábado conta ×1,5.</p>}
      {loading && <p className="small muted">A calcular o saldo deste dia…</p>}
      {error && <Alert tone="danger">{error}</Alert>}
      {preview && !loading && (
        <>
          <p className={`my-time-bank-day-balance ${preview.balance_seconds > 0 ? "my-time-bank-day-balance--positive" : preview.balance_seconds < 0 ? "my-time-bank-day-balance--negative" : ""}`}>
            <strong>Saldo deste dia: {formatSignedTimeBankDuration(preview.balance_seconds)}</strong>
          </p>
          {preview.duplicate && <Alert tone="warning">Já existe um lançamento ativo para este dia. Anule-o primeiro se quiser corrigir.</Alert>}
          {preview.warnings.length > 0 && (
            <div className="my-time-bank-preview-warnings">
              {preview.warnings.map((warning) => <Alert key={`${warning.code}-${warning.message}`} tone="warning">{warning.message}</Alert>)}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function JourneyForm({ onSaved }: { onSaved: () => void }) {
  const today = todayIsoLisbon();
  const [workDate, setWorkDate] = useState(today);
  const [hours] = useState(() => defaultHoursForDate(today));
  const [start, setStart] = useState(hours.start);
  const [end, setEnd] = useState(hours.end);
  const [hoursTouched, setHoursTouched] = useState(false);
  const [lunchTaken, setLunchTaken] = useState(true);
  const [preview, setPreview] = useState<TimeBankMyEntryPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [previewKey, setPreviewKey] = useState(0);
  const validation = useMemo(() => validateJourney(workDate, start, end, today), [workDate, start, end, today]);

  useEffect(() => {
    let active = true;
    setPreview(null);
    setPreviewError(null);
    const timer = window.setTimeout(() => {
      if (!validation.valid || validation.startMinute === null || validation.endMinute === null) {
        if (active) setPreviewLoading(false);
        return;
      }
      setPreviewLoading(true);
      setPreviewError(null);
      previewMyTimeBankEntry({
        work_date: workDate,
        start_minute: validation.startMinute,
        end_minute: validation.endMinute,
        lunch_taken: lunchTaken,
      })
        .then((result) => {
          if (!active) return;
          setPreview(result);
        })
        .catch((reason) => {
          if (!active) return;
          setPreview(null);
          setPreviewError(apiErrorMessage(reason));
        })
        .finally(() => {
          if (active) setPreviewLoading(false);
        });
    }, 300);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [end, lunchTaken, previewKey, start, validation, workDate]);

  function changeDate(value: string) {
    setWorkDate(value);
    if (!hoursTouched) {
      const defaults = defaultHoursForDate(value);
      setStart(defaults.start);
      setEnd(defaults.end);
    }
  }

  function changeStart(value: string) {
    setHoursTouched(true);
    setStart(value);
  }

  function changeEnd(value: string) {
    setHoursTouched(true);
    setEnd(value);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!validation.valid || validation.startMinute === null || validation.endMinute === null || !preview || preview.duplicate || saving) return;
    setSaveError(null);
    setSaving(true);
    try {
      await createMyTimeBankEntry({
        work_date: workDate,
        start_minute: validation.startMinute,
        end_minute: validation.endMinute,
        lunch_taken: lunchTaken,
      });
      setPreview(null);
      setPreviewKey((key) => key + 1);
      onSaved();
    } catch (reason) {
      setSaveError(apiErrorMessage(reason));
    } finally {
      setSaving(false);
    }
  }

  const saveDisabled = !validation.valid || !preview || previewLoading || Boolean(previewError) || preview.duplicate || saving;
  return (
    <Card title="Registar jornada" icon="clock" className="my-time-bank-entry-card">
      <form onSubmit={submit}>
        <div className="my-time-bank-form-grid">
          {saveError && <div className="my-time-bank-field--full"><Alert tone="danger">{saveError}</Alert></div>}
          <div className="field">
            <label htmlFor="my-time-bank-date">Data</label>
            <input id="my-time-bank-date" className="input" type="date" value={workDate} max={today} onChange={(event) => changeDate(event.target.value)} required />
          </div>
          <div className="field">
            <span className="field__label">Regra</span>
            <span className="my-time-bank-rule small muted">{weekdayForIsoDate(workDate) === 6 ? "Sábado ×1,5" : "Dia normal"}</span>
          </div>
          <div className="field">
            <label htmlFor="my-time-bank-start">Entrada</label>
            <input id="my-time-bank-start" className="input" type="time" value={start} onChange={(event) => changeStart(event.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="my-time-bank-end">Saída</label>
            <input id="my-time-bank-end" className="input" type="time" value={end} onChange={(event) => changeEnd(event.target.value)} required />
          </div>
          <fieldset className="my-time-bank-lunch my-time-bank-field--full">
            <legend>Almoço</legend>
            <div className="my-time-bank-segmented">
              <label className={lunchTaken ? "is-selected" : undefined}>
                <input type="radio" name="my-time-bank-lunch" value="yes" checked={lunchTaken} onChange={() => setLunchTaken(true)} aria-label="Almoço: Sim" />
                <span>Sim</span>
              </label>
              <label className={!lunchTaken ? "is-selected" : undefined}>
                <input type="radio" name="my-time-bank-lunch" value="no" checked={!lunchTaken} onChange={() => setLunchTaken(false)} aria-label="Almoço: Não" />
                <span>Não</span>
              </label>
            </div>
          </fieldset>
          <div className="my-time-bank-field--full">
            <PreviewPanel validation={validation} preview={preview} loading={previewLoading} error={previewError} workDate={workDate} />
          </div>
          <div className="my-time-bank-form-actions my-time-bank-field--full">
            <button type="submit" className="btn btn--primary" disabled={saveDisabled}>{saving ? "A guardar…" : "Guardar jornada"}</button>
          </div>
        </div>
      </form>
    </Card>
  );
}

type HistoryRow =
  | { kind: "entry"; date: string; entry: TimeBankEntryRead }
  | { kind: "adjustment"; date: string; adjustment: TimeBankAdjustmentRead };

function HistoryTable({
  entries,
  adjustments,
  reversedIds,
  onReverse,
}: {
  entries: TimeBankEntryRead[] | null;
  adjustments: TimeBankAdjustmentRead[] | null;
  reversedIds: ReadonlySet<string>;
  onReverse: (entry: TimeBankEntryRead) => void;
}) {
  if (entries === null || adjustments === null) return <LoadingState label="A carregar histórico…" rows={4} />;
  const rows: HistoryRow[] = [
    ...entries.map((entry): HistoryRow => ({ kind: "entry", date: entry.work_date, entry })),
    ...adjustments.map((adjustment): HistoryRow => ({ kind: "adjustment", date: adjustment.effective_date, adjustment })),
  ].sort((left, right) => right.date.localeCompare(left.date));
  if (rows.length === 0) return <EmptyState title="Sem histórico" text="Ainda não há jornadas ou ajustes registados." icon="clock" compact />;

  return (
    <div className="table-wrap my-time-bank-table-wrap">
      <table className="table my-time-bank-table">
        <thead>
          <tr><th>Data</th><th>Entrada–Saída</th><th>Almoço</th><th>Saldo</th><th>Estado</th><th>Ações</th></tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            if (row.kind === "adjustment") {
              const adjustment = row.adjustment;
              return (
                <tr key={`adjustment-${adjustment.id}`}>
                  <td>{formatDatePt(adjustment.effective_date)}</td>
                  <td>—</td>
                  <td>—</td>
                  <td><strong>{formatSignedTimeBankDuration(adjustment.delta_seconds)}</strong></td>
                  <td>
                    {adjustment.reversal_of_id && <Badge tone="info">anulação</Badge>}
                    {!adjustment.reversal_of_id && <Badge tone="neutral">ajuste</Badge>}
                  </td>
                  <td>—</td>
                </tr>
              );
            }
            const entry = row.entry;
            const reversed = entryHasCompensation(entry, reversedIds);
            const isCompensation = Boolean(entry.reversal_of_id);
            const canReverse = sourceIsSelfService(entry) && !isCompensation && !reversed;
            return (
              <tr key={`entry-${entry.id}`}>
                <td>{formatDatePt(entry.work_date)}</td>
                <td>{entry.start_minute === null || entry.end_minute === null ? "—" : `${formatClockMinute(entry.start_minute)}–${formatClockMinute(entry.end_minute)}`}</td>
                <td>{entry.lunch_taken === null ? "—" : entry.lunch_taken ? "Sim" : "Não"}</td>
                <td><strong>{formatSignedTimeBankDuration(entry.balance_seconds)}</strong></td>
                <td>
                  {reversed && <Badge tone="neutral">anulado</Badge>}
                  {isCompensation && <Badge tone="info">anulação</Badge>}
                  {entry.needs_review && <Badge tone="warning">a rever</Badge>}
                  {!reversed && !isCompensation && !entry.needs_review && <Badge tone="success">registado</Badge>}
                </td>
                <td>{canReverse ? <button type="button" className="btn btn--sm btn--danger-ghost" onClick={() => onReverse(entry)}>Anular</button> : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Summary({ summary }: { summary: TimeBankSummary | null }) {
  const person = summary?.people[0];
  return (
    <>
      <div className="grid grid--stats my-time-bank-summary-grid">
        <Card title="Saldo" icon="clock"><strong>{formatSignedTimeBankDuration(person?.balance_seconds)}</strong></Card>
        <Card title="Período" icon="calendar"><strong>{formatSignedTimeBankDuration(person?.period_seconds)}</strong></Card>
        <Card title="A rever" icon="alert"><strong>{person?.needs_review_count ?? 0}</strong></Card>
      </div>
      {person?.warnings.map((warning) => <Alert key={`${warning.code}-${warning.message}`} tone="warning" title="Aviso não bloqueante">{warning.message}</Alert>)}
    </>
  );
}

export default function MyTimeBank() {
  const today = todayIsoLisbon();
  const [summary, setSummary] = useState<TimeBankSummary | null>(null);
  const [entries, setEntries] = useState<TimeBankEntryRead[] | null>(null);
  const [adjustments, setAdjustments] = useState<TimeBankAdjustmentRead[] | null>(null);
  const [dataError, setDataError] = useState<string | null>(null);
  const [dataLoading, setDataLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  const [reversedIds, setReversedIds] = useState<Set<string>>(new Set());
  const [reverseTarget, setReverseTarget] = useState<TimeBankEntryRead | null>(null);
  const [reverseReason, setReverseReason] = useState("");
  const [reverseError, setReverseError] = useState<string | null>(null);
  const [reverseSaving, setReverseSaving] = useState(false);
  const [actionNotice, setActionNotice] = useState<string | null>(null);
  const reload = useCallback(() => setReloadKey((key) => key + 1), []);

  useEffect(() => {
    let active = true;
    setDataLoading(true);
    setDataError(null);
    Promise.all([
      getTimeBankSummary({ year: Number(today.slice(0, 4)) }),
      listTimeBankEntries({ limit: HISTORY_LIMIT }),
      listTimeBankAdjustments({ limit: HISTORY_LIMIT }),
    ])
      .then(([summaryResult, entriesResult, adjustmentsResult]) => {
        if (!active) return;
        setSummary(summaryResult);
        setEntries(entriesResult.items);
        setAdjustments(adjustmentsResult.items);
        setReversedIds((current) => {
          const next = new Set(current);
          entriesResult.items.forEach((entry) => {
            if (entry.reversal_of_id) next.add(entry.reversal_of_id);
          });
          return next;
        });
      })
      .catch((reason) => {
        if (!active) return;
        setDataError(apiErrorMessage(reason));
        setEntries((current) => current ?? []);
        setAdjustments((current) => current ?? []);
      })
      .finally(() => {
        if (active) setDataLoading(false);
      });
    return () => {
      active = false;
    };
  }, [reloadKey, today]);

  function startReverse(entry: TimeBankEntryRead) {
    setReverseTarget(entry);
    setReverseReason("");
    setReverseError(null);
  }

  async function confirmReverse(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!reverseTarget) return;
    const reason = reverseReason.trim();
    if (!reason) {
      setReverseError("Indique o motivo da anulação.");
      return;
    }
    setReverseSaving(true);
    setReverseError(null);
    try {
      const compensation = await reverseMyTimeBankEntry(reverseTarget.id, reason);
      setReversedIds((current) => {
        const next = new Set(current);
        next.add(compensation.reversal_of_id ?? reverseTarget.id);
        return next;
      });
      setReverseTarget(null);
      setActionNotice("Anulação registada. O lançamento original permanece visível.");
      reload();
    } catch (reasonValue) {
      setReverseError(apiErrorMessage(reasonValue));
    } finally {
      setReverseSaving(false);
    }
  }

  return (
    <>
      <PageHeader title="Banco de Horas" subtitle="Registe a sua jornada, consulte o saldo e anule os seus lançamentos self-service." />
      <JourneyForm onSaved={() => { setActionNotice("Jornada guardada."); reload(); }} />
      {actionNotice && <Alert tone="success" action={<button type="button" className="btn btn--sm" onClick={() => setActionNotice(null)}>Fechar</button>}>{actionNotice}</Alert>}
      {dataError && <div className="my-time-bank-data-error"><ErrorState message={dataError} onRetry={reload} /></div>}
      {dataLoading && !summary && !entries && !adjustments ? <div className="card"><LoadingState label="A carregar o seu Banco de Horas…" rows={4} /></div> : (
        <>
          <Summary summary={summary} />
          <Card title="Histórico" icon="clock" className="my-time-bank-history-card">
            <HistoryTable entries={entries} adjustments={adjustments} reversedIds={reversedIds} onReverse={startReverse} />
            {reverseTarget && (
              <div className="my-time-bank-reverse-dialog" role="dialog" aria-labelledby="my-time-bank-reverse-title">
                <h3 id="my-time-bank-reverse-title">Tens a certeza?</h3>
                <p>Será criada uma anulação compensatória. O lançamento original permanece visível.</p>
                <form onSubmit={confirmReverse}>
                  <div className="field">
                    <label htmlFor="my-time-bank-reverse-reason">Motivo da anulação *</label>
                    <textarea id="my-time-bank-reverse-reason" className="textarea" rows={3} value={reverseReason} onChange={(event) => setReverseReason(event.target.value)} required />
                  </div>
                  {reverseError && <Alert tone="danger">{reverseError}</Alert>}
                  <div className="my-time-bank-reverse-actions">
                    <button type="button" className="btn" onClick={() => setReverseTarget(null)}>Cancelar</button>
                    <button type="submit" className="btn btn--danger" disabled={reverseSaving || !reverseReason.trim()}>{reverseSaving ? "A anular…" : "Confirmar anulação"}</button>
                  </div>
                </form>
              </div>
            )}
          </Card>
        </>
      )}
    </>
  );
}
