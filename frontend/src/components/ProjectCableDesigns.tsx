import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ApiError,
} from "../api/client";
import {
  CableDesignListItem,
  createCableDesign,
  deactivateCableDesign,
  getCableTool,
  listCableDesigns,
} from "../api/cableDesigns";
import { useSession } from "../session/SessionContext";
import { formatDateTimePt } from "../utils/dates";
import { Badge, Card, EmptyState, ErrorState, LoadingState, Modal } from "./ui";
import "./ProjectCableDesigns.css";

type CableStatus = "rascunho" | "em_analise" | "em análise" | "aprovado" | "aprovada" | string;

const STATUS_LABELS: Record<string, string> = {
  rascunho: "Rascunho",
  em_analise: "Em análise",
  "em análise": "Em análise",
  aprovado: "Aprovado",
  aprovada: "Aprovado",
};

function statusLabel(status: CableStatus): string {
  return STATUS_LABELS[status] ?? status;
}

function statusTone(status: CableStatus): "neutral" | "warning" | "success" {
  if (status === "aprovado" || status === "aprovada") return "success";
  if (status === "em_analise" || status === "em análise") return "warning";
  return "neutral";
}

function apiErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return "Não tem permissão para ver os estudos de cabos deste projeto.";
    if (error.status === 404) return "O projeto ou os estudos de cabos não estão no seu âmbito.";
    return error.detail;
  }
  return "Não foi possível carregar os estudos de cabos.";
}

function NewCableDesignModal({
  projectId,
  canViewCosts,
  onClose,
  onCreated,
}: {
  projectId: string;
  canViewCosts: boolean;
  onClose: () => void;
  onCreated: (designId: string) => void;
}) {
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedTitle = title.trim();
    if (!normalizedTitle) {
      setError("Indique um título para o estudo.");
      return;
    }
    setError(null);
    setSaving(true);
    try {
      const engineVersion = canViewCosts ? (await getCableTool()).engine_version : "n/a";
      const design = await createCableDesign(projectId, { title: normalizedTitle, engine_version: engineVersion });
      onCreated(design.id);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.detail : "Não foi possível criar o estudo de cabos.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title="Novo estudo de cabos"
      onClose={saving ? () => undefined : onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} disabled={saving}>
            Cancelar
          </button>
          <button type="submit" form="new-cable-design-form" className="btn btn--primary" disabled={saving}>
            {saving ? "A criar…" : "Criar estudo"}
          </button>
        </>
      }
    >
      <form id="new-cable-design-form" onSubmit={submit}>
        <div className="field">
          <label htmlFor="cable-design-title">Título *</label>
          <input
            id="cable-design-title"
            className="input"
            value={title}
            maxLength={256}
            onChange={(event) => setTitle(event.target.value)}
            required
            autoFocus
          />
        </div>
        {error && <div className="cable-designs__dialog-error">{error}</div>}
      </form>
    </Modal>
  );
}

export default function ProjectCableDesigns({ projectId }: { projectId: string }) {
  const { can } = useSession();
  const navigate = useNavigate();
  const canView = can("cable_design.view");
  const canEdit = can("cable_design.edit");
  const canViewCosts = can("cable_design.view_costs");
  const [designs, setDesigns] = useState<CableDesignListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [deactivatingId, setDeactivatingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setDesigns(await listCableDesigns(projectId));
    } catch (reason) {
      setDesigns(null);
      setError(apiErrorMessage(reason));
    }
  }, [projectId]);

  useEffect(() => {
    if (canView) void load();
  }, [canView, load]);

  if (!canView) return null;

  async function deactivate(design: CableDesignListItem) {
    if (!window.confirm("Tens a certeza?")) return;
    setActionError(null);
    setDeactivatingId(design.id);
    try {
      await deactivateCableDesign(design.id, design.version);
      await load();
    } catch (reason) {
      setActionError(reason instanceof ApiError ? reason.detail : "Não foi possível desativar o estudo de cabos.");
    } finally {
      setDeactivatingId(null);
    }
  }

  return (
    <>
      <Card
        title="Estudos de cabos"
        icon="wrench"
        actions={
          canEdit ? (
            <button type="button" className="btn btn--primary btn--sm" onClick={() => setCreateOpen(true)}>
              Novo estudo
            </button>
          ) : undefined
        }
      >
        {actionError && <div className="cable-designs__action-error" role="alert">{actionError}</div>}
        {error && <ErrorState message={error} onRetry={() => void load()} />}
        {!error && designs === null && <LoadingState label="A carregar estudos de cabos…" rows={4} />}
        {!error && designs?.length === 0 && (
          <EmptyState
            icon="wrench"
            title="Ainda não há estudos de cabos."
            text={canEdit ? "Crie um estudo para começar o dimensionamento." : "Não há estudos de cabos ativos neste projeto."}
          />
        )}
        {!error && designs && designs.length > 0 && (
          <div className="table-wrap cable-designs__table-wrap">
            <table className="table cable-designs__table">
              <caption className="sr-only">Estudos de cabos do projeto</caption>
              <thead>
                <tr>
                  <th scope="col">Título</th>
                  <th scope="col">Estado</th>
                  <th scope="col">Rev.</th>
                  <th scope="col">Circuitos a rever</th>
                  <th scope="col">Atualizado</th>
                  <th scope="col"><span className="sr-only">Ações</span></th>
                </tr>
              </thead>
              <tbody>
                {designs.map((design) => (
                  <tr key={design.id}>
                    <td>
                      <Link className="cell-title" to={`/projects/${encodeURIComponent(projectId)}/cables/${encodeURIComponent(design.id)}`}>
                        {design.title}
                      </Link>
                    </td>
                    <td><Badge tone={statusTone(design.status)}>{statusLabel(design.status)}</Badge></td>
                    <td>{design.current_revision}</td>
                    <td>{design.unresolved_circuits}</td>
                    <td className="nowrap">{formatDateTimePt(design.updated_at)}</td>
                    <td>
                      <div className="cable-designs__row-actions">
                        <Link className="btn btn--sm" to={`/projects/${encodeURIComponent(projectId)}/cables/${encodeURIComponent(design.id)}`}>
                          Abrir
                        </Link>
                        {canEdit && (
                          <button
                            type="button"
                            className="btn btn--sm btn--danger-ghost"
                            aria-label={`Desativar ${design.title}`}
                            disabled={deactivatingId === design.id}
                            onClick={() => void deactivate(design)}
                          >
                            {deactivatingId === design.id ? "A desativar…" : "Desativar"}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {createOpen && (
        <NewCableDesignModal
          projectId={projectId}
          canViewCosts={canViewCosts}
          onClose={() => setCreateOpen(false)}
          onCreated={(designId) => {
            setCreateOpen(false);
            navigate(`/projects/${encodeURIComponent(projectId)}/cables/${encodeURIComponent(designId)}`);
          }}
        />
      )}
    </>
  );
}
