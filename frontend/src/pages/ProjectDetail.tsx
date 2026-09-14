import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ApiError,
  getProject,
  getProjectHistory,
  Project,
  ProjectHistoryEntry,
  updateProject,
} from "../api/client";

// Campos editáveis via API (ver app/schemas/projects.py:ProjectUpdate) —
// clickup_status_mirror fica sempre de fora, fonte de verdade ClickUp.
const EDITABLE_FIELDS: { key: keyof Project; label: string; multiline?: boolean }[] = [
  { key: "name", label: "Nome" },
  { key: "client_name", label: "Cliente" },
  { key: "client_contact", label: "Contacto" },
  { key: "client_email", label: "Email" },
  { key: "address", label: "Morada" },
  { key: "role", label: "Papel (legado)" },
  { key: "equipment_notes", label: "Equipamento", multiline: true },
  { key: "notes", label: "Notas", multiline: true },
];

export default function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [history, setHistory] = useState<ProjectHistoryEntry[]>([]);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function load() {
    if (!projectId) return;
    setError(null);
    getProject(projectId)
      .then((p) => {
        setProject(p);
        const d: Record<string, string> = {};
        for (const f of EDITABLE_FIELDS) d[f.key] = (p[f.key] as string) ?? "";
        setDraft(d);
      })
      .catch((e) => setError(e instanceof ApiError ? e.detail : String(e)));
    getProjectHistory(projectId)
      .then(setHistory)
      .catch(() => setHistory([]));
  }

  useEffect(load, [projectId]);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!projectId || !project) return;
    setSaving(true);
    setSaveError(null);
    const changes: Record<string, string> = {};
    for (const f of EDITABLE_FIELDS) {
      const current = (project[f.key] as string) ?? "";
      if (draft[f.key] !== current) changes[f.key] = draft[f.key];
    }
    if (Object.keys(changes).length === 0) {
      setSaving(false);
      return;
    }
    try {
      await updateProject(projectId, changes);
      load();
    } catch (e) {
      setSaveError(e instanceof ApiError ? `${e.status}: ${e.detail}` : String(e));
    } finally {
      setSaving(false);
    }
  }

  if (error) {
    return (
      <div style={{ fontFamily: "system-ui, sans-serif", padding: "1.5rem" }}>
        <Link to="/projects">&larr; Projetos</Link>
        <p style={{ color: "crimson" }}>Erro: {error}</p>
      </div>
    );
  }

  if (!project) {
    return (
      <div style={{ fontFamily: "system-ui, sans-serif", padding: "1.5rem" }}>
        <p>A carregar…</p>
      </div>
    );
  }

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", padding: "1.5rem", maxWidth: 900 }}>
      <Link to="/projects">&larr; Projetos</Link>
      <h1>{project.name}</h1>
      <p style={{ color: "#666" }}>
        PM: {project.pm_display_name ?? "— (não atribuído)"} · Estado ClickUp:{" "}
        {project.clickup_status_mirror ?? "—"} · {project.is_active ? "Ativo" : "Inativo"}
      </p>

      <div style={{ display: "flex", gap: "2rem", flexWrap: "wrap" }}>
        <form onSubmit={handleSave} style={{ flex: "1 1 380px", minWidth: 320 }}>
          <h2>Editar</h2>
          {EDITABLE_FIELDS.map((f) => (
            <div key={f.key} style={{ marginBottom: "0.6rem" }}>
              <label style={{ display: "block", fontSize: "0.85rem", color: "#555" }}>{f.label}</label>
              {f.multiline ? (
                <textarea
                  value={draft[f.key] ?? ""}
                  onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
                  style={{ width: "100%", boxSizing: "border-box", padding: "0.4rem" }}
                  rows={3}
                />
              ) : (
                <input
                  value={draft[f.key] ?? ""}
                  onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
                  style={{ width: "100%", boxSizing: "border-box", padding: "0.4rem" }}
                />
              )}
            </div>
          ))}
          {saveError && <p style={{ color: "crimson" }}>{saveError}</p>}
          <button type="submit" disabled={saving} style={{ padding: "0.5rem 1rem" }}>
            {saving ? "A guardar…" : "Guardar alterações"}
          </button>
        </form>

        <div style={{ flex: "1 1 380px", minWidth: 320 }}>
          <h2>Histórico</h2>
          {history.length === 0 && <p style={{ color: "#666" }}>Sem alterações registadas.</p>}
          <ul style={{ listStyle: "none", padding: 0, maxHeight: 500, overflowY: "auto" }}>
            {history.map((h) => (
              <li key={h.id} style={{ borderBottom: "1px solid #eee", padding: "0.5rem 0", fontSize: "0.85rem" }}>
                <strong>{h.field_name}</strong>: {h.old_value ?? "(vazio)"} → {h.new_value ?? "(vazio)"}
                <br />
                <span style={{ color: "#888" }}>
                  {h.changed_by_person_name ?? "sistema"} · {h.source} ·{" "}
                  {new Date(h.changed_at).toLocaleString("pt-PT")}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
