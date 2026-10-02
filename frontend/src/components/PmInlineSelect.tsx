import { useState } from "react";
import { ApiError, Person, Project, updateProject } from "../api/client";
import { useToast } from "./Toast";
import { Avatar, Badge } from "./ui";

/**
 * Seletor inline de PM: mostrado em qualquer lista/detalhe de projeto a quem
 * o servidor autoriza a editar `pm_person_id` (hoje: `project.edit_all`,
 * verificado via `project.editable_fields`, nunca por papel deduzido no
 * cliente — D-028/D-0xx). Quem não tem a permissão continua a ver só o nome
 * do PM, sem controlo algum.
 */
export default function PmInlineSelect({
  project,
  people,
  onChanged,
}: {
  project: Project;
  people: Person[];
  onChanged: (updated: Project) => void;
}) {
  const { notify } = useToast();
  const [saving, setSaving] = useState(false);
  const canEditPm = project.editable_fields.includes("pm_person_id");

  if (!canEditPm) {
    return project.pm_display_name ? (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
        <Avatar name={project.pm_display_name} small /> {project.pm_display_name}
      </span>
    ) : (
      <Badge tone="warning">Sem PM</Badge>
    );
  }

  async function handleChange(personId: string) {
    setSaving(true);
    try {
      const updated = await updateProject(project.id, { pm_person_id: personId || null } as Partial<Project>);
      onChanged(updated);
      notify("PM atualizado.", "success");
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Não foi possível atualizar o PM.";
      notify(message, "error");
    } finally {
      setSaving(false);
    }
  }

  const activePeople = people.filter((p) => p.is_active || p.id === project.pm_person_id);

  return (
    <select
      aria-label={`PM do projeto ${project.name}`}
      className="select"
      value={project.pm_person_id ?? ""}
      disabled={saving}
      onChange={(e) => handleChange(e.target.value)}
    >
      <option value="">Sem PM</option>
      {activePeople.map((p) => (
        <option key={p.id} value={p.id}>
          {p.display_name}
          {p.is_active ? "" : " (inativo)"}
        </option>
      ))}
    </select>
  );
}
