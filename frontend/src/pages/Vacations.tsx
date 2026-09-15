import { useEffect, useState } from "react";
import {
  ABSENCE_TYPE_LABELS,
  Absence,
  AbsenceType,
  ApiError,
  MeResponse,
  Person,
  cancelAbsence,
  createAbsence,
  getMe,
  listAbsences,
  listPeople,
} from "../api/client";
import { formatDatePt } from "../utils/dates";

export default function Vacations() {
  const [absences, setAbsences] = useState<Absence[] | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [me, setMe] = useState<MeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [form, setForm] = useState({
    person_id: "",
    start_date: "",
    end_date: "",
    type: "ferias" as AbsenceType,
    note: "",
  });

  // Um perfil sem `absence.manage_all` (ex. PM, Comercial) só pode
  // registar ausências para si próprio — ver can_create_absence_for em
  // app/security/permissions.py. A UI reflete isso escondendo a escolha
  // de pessoa em vez de deixar submeter e falhar com 403.
  const canManageAnyone = me?.permissions.includes("absence.manage_all") ?? false;

  function load() {
    setError(null);
    listAbsences()
      .then(setAbsences)
      .catch((e) => setError(e instanceof ApiError ? e.detail : String(e)));
  }

  useEffect(() => {
    listPeople().then(setPeople).catch(() => setPeople([]));
    getMe()
      .then((m) => {
        setMe(m);
        setForm((f) => ({ ...f, person_id: f.person_id || m.person_id }));
      })
      .catch(() => setMe(null));
    load();
  }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    if (!form.person_id || !form.start_date || !form.end_date) {
      setFormError("Escolha a pessoa e as datas inicial/final.");
      return;
    }
    try {
      await createAbsence(form);
      setForm({ person_id: "", start_date: "", end_date: "", type: "ferias", note: "" });
      load();
    } catch (e) {
      setFormError(e instanceof ApiError ? `${e.status}: ${e.detail}` : String(e));
    }
  }

  async function handleCancel(absence: Absence) {
    try {
      await cancelAbsence(absence.id);
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    }
  }

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", padding: "1.5rem" }}>
      <h1>Férias e ausências</h1>

      <form
        onSubmit={handleCreate}
        style={{ border: "1px solid #ddd", borderRadius: 8, padding: "1rem", marginBottom: "1.5rem", maxWidth: 480 }}
      >
        <h2 style={{ fontSize: "1rem", marginTop: 0 }}>Registar ausência</h2>
        <div style={{ marginBottom: "0.5rem" }}>
          <label style={{ display: "block", fontSize: "0.85rem" }}>Pessoa</label>
          {canManageAnyone ? (
            <select
              value={form.person_id}
              onChange={(e) => setForm({ ...form, person_id: e.target.value })}
              style={{ width: "100%", padding: "0.4rem" }}
            >
              <option value="">— escolher —</option>
              {people.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.display_name}
                </option>
              ))}
            </select>
          ) : (
            <input value={me?.email ?? ""} disabled style={{ width: "100%", padding: "0.4rem", boxSizing: "border-box" }} />
          )}
        </div>
        <div style={{ display: "flex", gap: "0.5rem", marginBottom: "0.5rem" }}>
          <div style={{ flex: 1 }}>
            <label style={{ display: "block", fontSize: "0.85rem" }}>Data inicial</label>
            <input
              type="date"
              value={form.start_date}
              onChange={(e) => setForm({ ...form, start_date: e.target.value })}
              style={{ width: "100%", padding: "0.4rem", boxSizing: "border-box" }}
            />
          </div>
          <div style={{ flex: 1 }}>
            <label style={{ display: "block", fontSize: "0.85rem" }}>Data final</label>
            <input
              type="date"
              value={form.end_date}
              onChange={(e) => setForm({ ...form, end_date: e.target.value })}
              style={{ width: "100%", padding: "0.4rem", boxSizing: "border-box" }}
            />
          </div>
        </div>
        <div style={{ marginBottom: "0.5rem" }}>
          <label style={{ display: "block", fontSize: "0.85rem" }}>Tipo</label>
          <select
            value={form.type}
            onChange={(e) => setForm({ ...form, type: e.target.value as AbsenceType })}
            style={{ width: "100%", padding: "0.4rem" }}
          >
            {Object.entries(ABSENCE_TYPE_LABELS).map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div style={{ marginBottom: "0.5rem" }}>
          <label style={{ display: "block", fontSize: "0.85rem" }}>Nota</label>
          <textarea
            value={form.note}
            onChange={(e) => setForm({ ...form, note: e.target.value })}
            style={{ width: "100%", padding: "0.4rem", boxSizing: "border-box" }}
            rows={2}
          />
        </div>
        {formError && <p style={{ color: "crimson" }}>{formError}</p>}
        <button type="submit" style={{ padding: "0.5rem 1rem" }}>
          Registar
        </button>
      </form>

      {error && <p style={{ color: "crimson" }}>Erro: {error}</p>}
      {absences === null && !error && <p>A carregar…</p>}
      {absences && absences.length === 0 && <p>Nenhuma ausência encontrada (ou sem permissão para ver nenhuma).</p>}

      {absences && absences.length > 0 && (
        <table style={{ borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "2px solid #ccc" }}>
              <th style={{ padding: "0.4rem" }}>Pessoa</th>
              <th style={{ padding: "0.4rem" }}>Tipo</th>
              <th style={{ padding: "0.4rem" }}>Início</th>
              <th style={{ padding: "0.4rem" }}>Fim</th>
              <th style={{ padding: "0.4rem" }}>Nota</th>
              <th style={{ padding: "0.4rem" }}>Estado</th>
              <th style={{ padding: "0.4rem" }} />
            </tr>
          </thead>
          <tbody>
            {absences.map((a) => (
              <tr key={a.id} style={{ borderBottom: "1px solid #eee" }}>
                <td style={{ padding: "0.4rem" }}>{a.person_display_name ?? "—"}</td>
                <td style={{ padding: "0.4rem" }}>{ABSENCE_TYPE_LABELS[a.type]}</td>
                <td style={{ padding: "0.4rem" }}>{formatDatePt(a.start_date)}</td>
                <td style={{ padding: "0.4rem" }}>{formatDatePt(a.end_date)}</td>
                <td style={{ padding: "0.4rem" }}>{a.note || "—"}</td>
                <td style={{ padding: "0.4rem" }}>{a.status === "aprovada" ? "Aprovada" : "Cancelada"}</td>
                <td style={{ padding: "0.4rem" }}>
                  {a.status === "aprovada" && (
                    <button type="button" onClick={() => handleCancel(a)} style={{ padding: "0.2rem 0.5rem" }}>
                      Cancelar
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
