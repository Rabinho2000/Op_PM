import { FormEvent, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { createTimeBankNote, listTimeBankNotes, TimeBankNoteRead } from "../api/timeBank";
import { Alert, Card } from "./ui";
import "./TimeBankNotes.css";

const PAGE_SIZE = 20;
const dateTime = (value: string) => new Intl.DateTimeFormat("pt-PT", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));

export default function TimeBankNotes({ personId, accountId, canManage }: { personId?: string; accountId?: string; canManage: boolean }) {
  const [items, setItems] = useState<TimeBankNoteRead[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [reload, setReload] = useState(0);
  const [body, setBody] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [readError, setReadError] = useState<string | null>(null);
  const requestScope = useRef(0);
  const previousTarget = useRef({ personId, accountId });

  useEffect(() => {
    const personOrAccountChanged = previousTarget.current.personId !== personId || previousTarget.current.accountId !== accountId;
    previousTarget.current = { personId, accountId };
    requestScope.current += 1;
    setSaving(false);
    setError(null);
    setReadError(null);
    setPage(0);
    setItems([]);
    setTotal(0);
    if (personOrAccountChanged) setBody("");
  }, [personId, accountId]);

  const previousCanManage = useRef(canManage);
  useEffect(() => {
    if (previousCanManage.current === canManage) return;
    previousCanManage.current = canManage;
    requestScope.current += 1;
    setSaving(false);
    setError(null);
  }, [canManage]);

  useEffect(() => {
    let active = true;
    if (!personId) { setItems([]); setTotal(0); setLoading(false); return () => { active = false; }; }
    setLoading(true);
    setReadError(null);
    listTimeBankNotes(personId, PAGE_SIZE, page * PAGE_SIZE)
      .then((result) => { if (active) { setItems(result.items); setTotal(result.total); } })
      .catch((reason) => { if (active) setReadError(reason instanceof ApiError ? reason.detail : "Não foi possível carregar as notas."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [personId, accountId, page, reload]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const clean = body.trim();
    if (!canManage || !personId || !clean || clean.length > 2000 || saving) return;
    setSaving(true);
    setError(null);
    const scope = requestScope.current;
    try {
      await createTimeBankNote(personId, clean);
      if (scope === requestScope.current) {
        setBody("");
        setPage(0);
        setReload((value) => value + 1);
      }
    } catch (reason) {
      if (scope === requestScope.current) setError(reason instanceof ApiError ? reason.detail : "Não foi possível guardar a nota.");
    } finally { if (scope === requestScope.current) setSaving(false); }
  }

  return <Card title="Notas da pessoa" icon="fileText" className="time-bank-notes">
    {!personId ? <p className="small muted">Selecione uma pessoa para consultar as notas históricas independentes dos lançamentos.</p> : <>
      {readError && <Alert tone="danger">{readError}</Alert>}
      {canManage && <form onSubmit={submit} className="time-bank-notes__form">
        <div className="field"><label htmlFor="time-bank-note-body">Nova nota (até 2000 caracteres)</label><textarea id="time-bank-note-body" className="textarea" rows={3} maxLength={2000} value={body} onChange={(event) => setBody(event.target.value)} /></div>
        {error && <Alert tone="danger">{error}</Alert>}
        <button type="submit" className="btn btn--primary" disabled={saving || !body.trim() || body.trim().length > 2000}>{saving ? "A guardar…" : "Adicionar nota"}</button>
      </form>}
      {loading ? <p className="small muted" role="status">A carregar notas…</p> : items.length === 0 ? <p className="small muted">Ainda não existem notas para esta pessoa.</p> : <ol className="time-bank-notes__list">{items.map((note) => <li key={note.id}><p>{note.body}</p><small>{note.author_display_name} · {dateTime(note.created_at)}</small></li>)}</ol>}
      {total > PAGE_SIZE && <nav className="time-bank-notes__pagination" aria-label="Paginação das notas">
        <button type="button" className="btn" disabled={page === 0} onClick={() => setPage((value) => value - 1)}>Anterior</button>
        <span className="small muted">{page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} de {total}</span>
        <button type="button" className="btn" disabled={(page + 1) * PAGE_SIZE >= total} onClick={() => setPage((value) => value + 1)}>Seguinte</button>
      </nav>}
    </>}
  </Card>;
}
