import { FormEvent, useEffect, useState } from "react";
import { ApiError, listPeople, listSupportDelegations, Person, saveSupportDelegation, deleteSupportDelegation, SupportDelegation } from "../api/client";
import { Alert, Card, EmptyState, ErrorState, LoadingState, PageHeader } from "../components/ui";
import { useSession } from "../session/SessionContext";

export default function SupportOperations() {
  const { me } = useSession();
  const canManageSupport = Boolean(
    me?.roles.some((role) => ["admin", "administrador", "chefe_operacoes"].includes(role))
  );
  const [rows, setRows] = useState<SupportDelegation[] | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [pm, setPm] = useState("");
  const [support, setSupport] = useState("");
  const [editingPm, setEditingPm] = useState<string | null>(null);

  async function load() {
    setError(null);
    try { setRows(await listSupportDelegations()); setPeople(await listPeople()); }
    catch (e) { setError(e instanceof ApiError ? e.detail : "Não foi possível carregar as delegações."); }
  }
  useEffect(() => { if (canManageSupport) void load(); }, [canManageSupport]);

  if (!canManageSupport) return <ErrorState message="Não tem permissão para gerir delegações de suporte." />;
  if (error && rows === null) return <ErrorState message={error} onRetry={() => void load()} />;
  if (!rows) return <LoadingState label="A carregar delegações…" rows={3} />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!pm || !support) return;
    setSaving(true); setError(null);
    try { await saveSupportDelegation({ pm_person_id: pm, support_person_id: support }); setPm(""); setSupport(""); setEditingPm(null); await load(); }
    catch (e) { setError(e instanceof ApiError ? e.detail : "Não foi possível guardar a delegação."); }
    finally { setSaving(false); }
  }
  function edit(row: SupportDelegation) {
    setPm(row.pm_person_id);
    setSupport(row.support_person_id);
    setEditingPm(row.pm_person_id);
  }
  function cancelEdit() {
    setPm("");
    setSupport("");
    setEditingPm(null);
  }
  async function remove(id: string) {
    setError(null);
    try { await deleteSupportDelegation(id); await load(); }
    catch (e) { setError(e instanceof ApiError ? e.detail : "Não foi possível remover a delegação."); }
  }

  return <>
    <PageHeader title="Suporte de operações" subtitle="Defina quem apoia cada PM nas etapas delegadas." />
    {error && <Alert tone="danger">{error}</Alert>}
    <Card title={editingPm ? "Editar delegação" : "Nova delegação"} icon="user">
      <form className="form-grid" onSubmit={submit}>
        <div className="field"><label htmlFor="delegation-pm">PM</label><select id="delegation-pm" className="select" value={pm} disabled={Boolean(editingPm)} onChange={(e) => setPm(e.target.value)}><option value="">Selecionar…</option>{people.filter((p) => p.is_active).map((p) => <option key={p.id} value={p.id}>{p.display_name}</option>)}</select></div>
        <div className="field"><label htmlFor="delegation-support">Pessoa de suporte</label><select id="delegation-support" className="select" value={support} onChange={(e) => setSupport(e.target.value)}><option value="">Selecionar…</option>{people.filter((p) => p.is_active).map((p) => <option key={p.id} value={p.id}>{p.display_name}</option>)}</select></div>
        <div className="field" style={{ alignSelf: "end" }}><button className="btn btn--primary" type="submit" disabled={saving || !pm || !support}>{saving ? "A guardar…" : editingPm ? "Atualizar delegação" : "Guardar delegação"}</button>{editingPm && <button className="btn btn--ghost" type="button" onClick={cancelEdit} disabled={saving}>Cancelar</button>}</div>
      </form>
    </Card>
    <Card title="Delegações atuais" icon="user">
      {rows.length === 0 ? <EmptyState compact title="Não existem delegações configuradas." /> : <div className="table-wrap"><table className="table"><thead><tr><th>PM</th><th>Suporte</th><th /></tr></thead><tbody>{rows.map((row) => <tr key={row.pm_person_id}><td>{row.pm_display_name}</td><td>{row.support_display_name}</td><td><button className="btn btn--ghost" type="button" onClick={() => edit(row)}>Editar</button><button className="btn btn--ghost" type="button" onClick={() => void remove(row.pm_person_id)}>Remover</button></td></tr>)}</tbody></table></div>}
    </Card>
  </>;
}
