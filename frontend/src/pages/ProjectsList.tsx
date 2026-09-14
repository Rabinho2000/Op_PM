import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, listPeople, listProjects, Person, Project } from "../api/client";

export default function ProjectsList() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [pmFilter, setPmFilter] = useState("");
  const [activeFilter, setActiveFilter] = useState<"all" | "active" | "inactive">("active");
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listPeople()
      .then(setPeople)
      .catch(() => setPeople([]));
  }, []);

  useEffect(() => {
    setError(null);
    listProjects({
      pm_person_id: pmFilter || undefined,
      is_active: activeFilter === "all" ? undefined : activeFilter === "active",
      q: search || undefined,
    })
      .then(setProjects)
      .catch((e) => setError(e instanceof ApiError ? e.detail : String(e)));
  }, [pmFilter, activeFilter, search]);

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", padding: "1.5rem" }}>
      <h1>Projetos</h1>

      <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1rem", flexWrap: "wrap" }}>
        <input
          placeholder="Pesquisar por nome/cliente/contacto…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ padding: "0.4rem", minWidth: 260 }}
        />
        <select value={pmFilter} onChange={(e) => setPmFilter(e.target.value)} style={{ padding: "0.4rem" }}>
          <option value="">Todos os PMs</option>
          {people.map((p) => (
            <option key={p.id} value={p.id}>
              {p.display_name}
            </option>
          ))}
        </select>
        <select
          value={activeFilter}
          onChange={(e) => setActiveFilter(e.target.value as "all" | "active" | "inactive")}
          style={{ padding: "0.4rem" }}
        >
          <option value="active">Ativos</option>
          <option value="inactive">Inativos</option>
          <option value="all">Todos</option>
        </select>
      </div>

      {error && <p style={{ color: "crimson" }}>Erro: {error}</p>}

      {projects === null && !error && <p>A carregar…</p>}

      {projects && projects.length === 0 && <p>Nenhum projeto encontrado (ou sem permissão para ver nenhum).</p>}

      {projects && projects.length > 0 && (
        <table style={{ borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "2px solid #ccc" }}>
              <th style={{ padding: "0.4rem" }}>Nome</th>
              <th style={{ padding: "0.4rem" }}>PM</th>
              <th style={{ padding: "0.4rem" }}>Cliente</th>
              <th style={{ padding: "0.4rem" }}>Estado ClickUp</th>
              <th style={{ padding: "0.4rem" }}>Dados em falta</th>
            </tr>
          </thead>
          <tbody>
            {projects.map((p) => (
              <tr key={p.id} style={{ borderBottom: "1px solid #eee" }}>
                <td style={{ padding: "0.4rem" }}>
                  <Link to={`/projects/${p.id}`}>{p.name}</Link>
                </td>
                <td style={{ padding: "0.4rem" }}>{p.pm_display_name ?? "—"}</td>
                <td style={{ padding: "0.4rem" }}>{p.client_name ?? p.client_contact ?? "—"}</td>
                <td style={{ padding: "0.4rem" }}>{p.clickup_status_mirror ?? "—"}</td>
                <td style={{ padding: "0.4rem", color: "#a66" }}>
                  {[
                    !p.has_pm && "PM",
                    !p.has_email && "email",
                    !p.has_coordinates && "coordenadas",
                    !p.has_contact && "contacto",
                  ]
                    .filter(Boolean)
                    .join(", ") || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
