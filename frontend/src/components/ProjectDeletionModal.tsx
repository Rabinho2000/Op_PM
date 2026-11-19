import { FormEvent, useState } from "react";
import { deleteProject, Project } from "../api/client";
import { Alert, Modal } from "./ui";
import { errorDetail } from "../utils/errors";

export default function ProjectDeletionModal({
  project,
  onClose,
  onDeleted,
}: {
  project: Project;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedReason = reason.trim();
    if (!normalizedReason) {
      setError("Indique o motivo da remoção.");
      return;
    }

    setSaving(true);
    setError(null);
    try {
      await deleteProject(project.id, normalizedReason);
      onDeleted();
    } catch (err) {
      setError(errorDetail(err, "Não foi possível apagar o projeto."));
    } finally {
      setSaving(false);
    }
  }

  const closeIfIdle = () => {
    if (!saving) onClose();
  };

  return (
    <Modal
      title="Apagar projeto"
      onClose={closeIfIdle}
      footer={
        <>
          <button type="button" className="btn" onClick={closeIfIdle} disabled={saving}>
            Cancelar
          </button>
          <button type="submit" form="project-deletion-form" className="btn btn--danger" disabled={saving}>
            {saving ? "A apagar…" : "Confirmar remoção"}
          </button>
        </>
      }
    >
      <p>
        O projeto «{project.name}» será removido da lista ativa. A remoção pode ser revertida por alguém com permissão
        para restaurar projetos.
      </p>
      <form id="project-deletion-form" onSubmit={handleSubmit}>
        {error && <Alert tone="danger">{error}</Alert>}
        <div className="field" style={{ marginTop: 12 }}>
          <label htmlFor="project-deletion-reason">Motivo da remoção</label>
          <textarea
            id="project-deletion-reason"
            className="textarea"
            rows={3}
            required
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            disabled={saving}
          />
        </div>
      </form>
    </Modal>
  );
}
