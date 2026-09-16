import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  ABSENCE_TYPE_LABELS,
  Absence,
  AbsenceMini,
  AbsenceType,
  ApiError,
  BirthdayMini,
  cancelAbsence,
  createAbsence,
  getDashboardSummary,
  listAbsences,
  listPeople,
  Person,
} from "../api/client";
import Icon from "../components/Icon";
import { useToast } from "../components/Toast";
import { Alert, Avatar, Badge, Card, EmptyState, ErrorState, LoadingState, Modal, PageHeader } from "../components/ui";
import { useSession } from "../session/SessionContext";
import {
  addDaysIso,
  daysUntilLabel,
  formatDatePt,
  formatDayMonthPt,
  MONTHS_LONG,
  todayIsoLisbon,
} from "../utils/dates";
import { ABSENCE_TYPE_TONES } from "../utils/labels";

// Visibilidade: a lista vem de GET /api/absences, já filtrada pelo servidor
// (absence.view_all vs. absence.view_own); aniversários só chegam pelo
// dashboard, que aplica a mesma regra (D-044). Nada aqui alarga o que o
// utilizador pode ver.

const DOW = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"];

function monthGrid(year: number, month: number): string[] {
  // Segunda-feira como primeiro dia; 6 semanas fixas.
  const first = new Date(Date.UTC(year, month, 1));
  const offset = (first.getUTCDay() + 6) % 7;
  const start = new Date(Date.UTC(year, month, 1 - offset));
  return Array.from({ length: 42 }, (_, i) => {
    const d = new Date(start);
    d.setUTCDate(start.getUTCDate() + i);
    return d.toISOString().slice(0, 10);
  });
}

function CreateAbsenceModal({
  people,
  canManageAll,
  selfPersonId,
  selfName,
  onClose,
  onCreated,
}: {
  people: Person[];
  canManageAll: boolean;
  selfPersonId: string;
  selfName: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [form, setForm] = useState({
    person_id: selfPersonId,
    start_date: "",
    end_date: "",
    type: "ferias" as AbsenceType,
    note: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!form.person_id || !form.start_date || !form.end_date) {
      setError("Indique a pessoa e as datas de início e fim.");
      return;
    }
    if (form.end_date < form.start_date) {
      setError("A data de fim não pode ser anterior à data de início.");
      return;
    }
    setSaving(true);
    try {
      await createAbsence({ ...form, person_id: canManageAll ? form.person_id : selfPersonId });
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Não foi possível registar a ausência.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title="Registar férias ou ausência"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancelar
          </button>
          <button type="submit" form="absence-form" className="btn btn--primary" disabled={saving}>
            {saving ? "A registar…" : "Registar"}
          </button>
        </>
      }
    >
      <form id="absence-form" className="form-grid" onSubmit={handleSubmit}>
        {error && (
          <div className="span-2">
            <Alert tone="danger">{error}</Alert>
          </div>
        )}
        <div className="field span-2">
          <label htmlFor="a-person">Pessoa</label>
          {canManageAll ? (
            <select
              id="a-person"
              className="select"
              value={form.person_id}
              onChange={(e) => setForm({ ...form, person_id: e.target.value })}
            >
              {people
                .filter((p) => p.is_active)
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.display_name}
                  </option>
                ))}
            </select>
          ) : (
            <>
              <input id="a-person" className="input" value={selfName} disabled />
              <span className="small muted">O seu perfil só permite registar as suas próprias ausências.</span>
            </>
          )}
        </div>
        <div className="field">
          <label htmlFor="a-start">Início *</label>
          <input
            id="a-start"
            className="input"
            type="date"
            required
            value={form.start_date}
            onChange={(e) =>
              setForm({ ...form, start_date: e.target.value, end_date: form.end_date || e.target.value })
            }
          />
        </div>
        <div className="field">
          <label htmlFor="a-end">Fim *</label>
          <input
            id="a-end"
            className="input"
            type="date"
            required
            min={form.start_date || undefined}
            value={form.end_date}
            onChange={(e) => setForm({ ...form, end_date: e.target.value })}
          />
        </div>
        <div className="field span-2">
          <label htmlFor="a-type">Tipo</label>
          <select
            id="a-type"
            className="select"
            value={form.type}
            onChange={(e) => setForm({ ...form, type: e.target.value as AbsenceType })}
          >
            {(Object.keys(ABSENCE_TYPE_LABELS) as AbsenceType[]).map((k) => (
              <option key={k} value={k}>
                {ABSENCE_TYPE_LABELS[k]}
              </option>
            ))}
          </select>
        </div>
        <div className="field span-2">
          <label htmlFor="a-note">Nota</label>
          <textarea
            id="a-note"
            className="textarea"
            rows={2}
            value={form.note}
            onChange={(e) => setForm({ ...form, note: e.target.value })}
          />
        </div>
      </form>
    </Modal>
  );
}

export default function Vacations() {
  const { me, can } = useSession();
  const { notify } = useToast();
  const [absences, setAbsences] = useState<Absence[] | null>(null);
  const [birthdays, setBirthdays] = useState<BirthdayMini[] | null>(null);
  const [current, setCurrent] = useState<AbsenceMini[] | null>(null);
  const [upcoming, setUpcoming] = useState<AbsenceMini[] | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState<Absence | null>(null);
  const [showCancelled, setShowCancelled] = useState(false);
  const today = todayIsoLisbon();
  const [cursor, setCursor] = useState(() => ({ year: Number(today.slice(0, 4)), month: Number(today.slice(5, 7)) - 1 }));

  const canManageAll = can("absence.manage_all");
  const canManageOwn = can("absence.manage_own");
  const seesEveryone = can("absence.view_all");

  const load = useCallback(() => {
    setError(null);
    listAbsences()
      .then(setAbsences)
      .catch((e) => setError(e instanceof ApiError ? e.detail : "Não foi possível contactar o servidor."));
    getDashboardSummary()
      .then((s) => {
        setBirthdays(s.upcoming_birthdays);
        setCurrent(s.current_absences);
        setUpcoming(s.upcoming_absences);
      })
      .catch(() => {
        setBirthdays([]);
        setCurrent([]);
        setUpcoming([]);
      });
  }, []);

  useEffect(load, [load]);
  useEffect(() => {
    if (!canManageAll) return;
    listPeople()
      .then(setPeople)
      .catch(() => setPeople([]));
  }, [canManageAll]);

  const approved = useMemo(() => (absences ?? []).filter((a) => a.status === "aprovada"), [absences]);
  const tableRows = (absences ?? [])
    .filter((a) => showCancelled || a.status === "aprovada")
    .slice()
    .sort((a, b) => b.start_date.localeCompare(a.start_date));

  const days = monthGrid(cursor.year, cursor.month);
  const birthdayByDate = new Map((birthdays ?? []).map((b) => [addDaysIso(today, b.days_until), b]));

  function shiftMonth(delta: number) {
    setCursor(({ year, month }) => {
      const m = month + delta;
      return { year: year + Math.floor(m / 12), month: ((m % 12) + 12) % 12 };
    });
  }

  async function handleCancel(absence: Absence) {
    try {
      await cancelAbsence(absence.id);
      notify("Ausência cancelada.", "success");
      load();
    } catch (e) {
      notify(e instanceof ApiError ? e.detail : "Não foi possível cancelar a ausência.", "error");
    } finally {
      setConfirmCancel(null);
    }
  }

  return (
    <>
      <PageHeader
        title="Férias e aniversários"
        subtitle={
          seesEveryone
            ? "Calendário de ausências de toda a equipa e aniversários dos próximos 30 dias."
            : "As suas férias e ausências. O seu perfil não tem acesso às ausências de outras pessoas."
        }
        actions={
          (canManageAll || canManageOwn) && (
            <button type="button" className="btn btn--primary" onClick={() => setCreating(true)}>
              <Icon name="plus" size={16} /> Registar ausência
            </button>
          )
        }
      />

      {error && (
        <div className="card">
          <ErrorState message={error} onRetry={load} />
        </div>
      )}

      {!error && (
        <div className="grid grid--main-side">
          <Card
            title={<span className="calendar__month">{`${MONTHS_LONG[cursor.month]} ${cursor.year}`}</span>}
            icon="calendar"
            tone="violet"
            actions={
              <div className="calendar__nav">
                <button type="button" className="btn btn--ghost btn--icon" aria-label="Mês anterior" onClick={() => shiftMonth(-1)}>
                  <Icon name="chevronLeft" />
                </button>
                <button
                  type="button"
                  className="btn btn--sm"
                  onClick={() => setCursor({ year: Number(today.slice(0, 4)), month: Number(today.slice(5, 7)) - 1 })}
                >
                  Hoje
                </button>
                <button type="button" className="btn btn--ghost btn--icon" aria-label="Mês seguinte" onClick={() => shiftMonth(1)}>
                  <Icon name="chevronRight" />
                </button>
              </div>
            }
          >
            {absences === null ? (
              <LoadingState rows={6} />
            ) : (
              <div className="calendar" role="grid" aria-label="Calendário de ausências">
                {DOW.map((d) => (
                  <div key={d} className="calendar__dow" role="columnheader">
                    {d}
                  </div>
                ))}
                {days.map((iso, i) => {
                  const inMonth = Number(iso.slice(5, 7)) - 1 === cursor.month;
                  const events = approved.filter((a) => a.start_date <= iso && iso <= a.end_date);
                  const birthday = birthdayByDate.get(iso);
                  const weekend = i % 7 >= 5;
                  const label = [
                    formatDatePt(iso),
                    ...events.map((a) => `${a.person_display_name}: ${ABSENCE_TYPE_LABELS[a.type]}`),
                    birthday ? `Aniversário de ${birthday.person_display_name}` : "",
                  ]
                    .filter(Boolean)
                    .join(" · ");
                  return (
                    <div
                      key={iso}
                      role="gridcell"
                      aria-label={label}
                      className={[
                        "calendar__cell",
                        inMonth ? "" : "calendar__cell--other",
                        weekend ? "calendar__cell--weekend" : "",
                        iso === today ? "calendar__cell--today" : "",
                      ].join(" ")}
                    >
                      <span className="calendar__num" aria-hidden="true">
                        {Number(iso.slice(8, 10))}
                      </span>
                      {birthday && (
                        <span className="calendar__event tone-warning" aria-hidden="true" title={`Aniversário: ${birthday.person_display_name}`}>
                          🎂 {birthday.person_display_name}
                        </span>
                      )}
                      {events.slice(0, 3).map((a) => (
                        <span
                          key={a.id}
                          className={`calendar__event tone-${ABSENCE_TYPE_TONES[a.type]}`}
                          aria-hidden="true"
                          title={`${a.person_display_name} — ${ABSENCE_TYPE_LABELS[a.type]}`}
                        >
                          {a.person_display_name}
                        </span>
                      ))}
                      {events.length > 3 && (
                        <span className="small muted" aria-hidden="true">
                          +{events.length - 3}
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
            <div className="legend" style={{ marginTop: 12 }}>
              {(Object.keys(ABSENCE_TYPE_LABELS) as AbsenceType[]).map((t) => (
                <span key={t}>
                  <span className={`legend__swatch tone-${ABSENCE_TYPE_TONES[t]}`} />
                  {ABSENCE_TYPE_LABELS[t]}
                </span>
              ))}
              <span>🎂 Aniversário</span>
            </div>
          </Card>

          <div className="grid">
            <Card title="Ausentes hoje" icon="plane" tone="violet" flush>
              {current === null ? (
                <LoadingState rows={2} />
              ) : current.length === 0 ? (
                <EmptyState compact icon="calendar" title="Ninguém ausente hoje." />
              ) : (
                <ul className="list">
                  {current.map((a) => (
                    <li key={a.id} className="list__item">
                      <Avatar name={a.person_display_name} small />
                      <div className="list__main">
                        <span className="list__title">{a.person_display_name}</span>
                        <div className="list__meta">regressa depois de {formatDayMonthPt(a.end_date)}</div>
                      </div>
                      <Badge tone={ABSENCE_TYPE_TONES[a.type]}>{ABSENCE_TYPE_LABELS[a.type]}</Badge>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card title="Próximas ausências (30 dias)" icon="calendar" tone="violet" flush>
              {upcoming === null ? (
                <LoadingState rows={2} />
              ) : upcoming.length === 0 ? (
                <EmptyState compact icon="calendar" title="Sem ausências marcadas." />
              ) : (
                <ul className="list">
                  {upcoming.map((a) => (
                    <li key={a.id} className="list__item">
                      <Avatar name={a.person_display_name} small />
                      <div className="list__main">
                        <span className="list__title">{a.person_display_name}</span>
                        <div className="list__meta">
                          {formatDayMonthPt(a.start_date)} – {formatDayMonthPt(a.end_date)}
                        </div>
                      </div>
                      <Badge tone={ABSENCE_TYPE_TONES[a.type]}>{ABSENCE_TYPE_LABELS[a.type]}</Badge>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card title="Aniversários próximos" icon="gift" tone="warning" flush>
              {birthdays === null ? (
                <LoadingState rows={2} />
              ) : birthdays.length === 0 ? (
                <EmptyState compact icon="gift" title="Sem aniversários nos próximos 30 dias." />
              ) : (
                <ul className="list">
                  {birthdays.map((b) => (
                    <li key={b.person_id} className="list__item">
                      <Avatar name={b.person_display_name} small />
                      <div className="list__main">
                        <span className="list__title">{b.person_display_name}</span>
                        <div className="list__meta">{formatDayMonthPt(addDaysIso(today, b.days_until))}</div>
                      </div>
                      <Badge tone={b.days_until === 0 ? "warning" : "neutral"}>
                        {b.days_until === 0 ? "🎉 hoje" : daysUntilLabel(b.days_until)}
                      </Badge>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </div>
      )}

      {!error && (
        <div className="section-gap">
          <Card
            title="Registo de ausências"
            icon="list"
            flush
            actions={
              <label className="checkbox small">
                <input type="checkbox" checked={showCancelled} onChange={(e) => setShowCancelled(e.target.checked)} />
                Mostrar canceladas
              </label>
            }
          >
            {absences === null && <LoadingState />}
            {absences && tableRows.length === 0 && (
              <EmptyState icon="calendar" title="Sem ausências registadas." />
            )}
            {tableRows.length > 0 && (
              <div className="table-wrap">
                <table className="table">
                  <caption className="sr-only">Registo de ausências</caption>
                  <thead>
                    <tr>
                      <th scope="col">Pessoa</th>
                      <th scope="col">Tipo</th>
                      <th scope="col">Período</th>
                      <th scope="col">Nota</th>
                      <th scope="col">Estado</th>
                      <th scope="col">
                        <span className="sr-only">Ações</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {tableRows.map((a) => (
                      <tr key={a.id}>
                        <td className="nowrap">
                          <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                            <Avatar name={a.person_display_name} small />
                            {a.person_display_name ?? "—"}
                          </span>
                        </td>
                        <td>
                          <Badge tone={ABSENCE_TYPE_TONES[a.type]}>{ABSENCE_TYPE_LABELS[a.type]}</Badge>
                        </td>
                        <td className="nowrap">
                          {formatDatePt(a.start_date)} – {formatDatePt(a.end_date)}
                        </td>
                        <td>{a.note || <span className="muted">—</span>}</td>
                        <td>
                          {a.status === "aprovada" ? (
                            a.end_date < today ? (
                              <Badge>Terminada</Badge>
                            ) : a.start_date <= today ? (
                              <Badge tone="violet" dot>
                                Em curso
                              </Badge>
                            ) : (
                              <Badge tone="success" dot>
                                Aprovada
                              </Badge>
                            )
                          ) : (
                            <Badge tone="neutral">Cancelada</Badge>
                          )}
                        </td>
                        <td>
                          {a.can_cancel && a.end_date >= today && (
                            <button type="button" className="btn btn--sm btn--danger" onClick={() => setConfirmCancel(a)}>
                              Cancelar
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>
      )}

      {creating && me && (
        <CreateAbsenceModal
          people={people}
          canManageAll={canManageAll}
          selfPersonId={me.person_id}
          selfName={me.display_name ?? me.email}
          onClose={() => setCreating(false)}
          onCreated={() => {
            setCreating(false);
            notify("Ausência registada.", "success");
            load();
          }}
        />
      )}

      {confirmCancel && (
        <Modal
          title="Cancelar ausência?"
          onClose={() => setConfirmCancel(null)}
          footer={
            <>
              <button type="button" className="btn" onClick={() => setConfirmCancel(null)}>
                Manter
              </button>
              <button type="button" className="btn btn--primary" onClick={() => handleCancel(confirmCancel)}>
                Sim, cancelar
              </button>
            </>
          }
        >
          <p style={{ margin: 0 }}>
            {ABSENCE_TYPE_LABELS[confirmCancel.type]} de <strong>{confirmCancel.person_display_name}</strong> entre{" "}
            {formatDatePt(confirmCancel.start_date)} e {formatDatePt(confirmCancel.end_date)}. A ausência fica registada
            como cancelada.
          </p>
        </Modal>
      )}
    </>
  );
}
