import { useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { listDeletedProjects, Project, restoreProject } from "../api/client";
import { useToast } from "../components/Toast";
import { EmptyState, ErrorState, LoadingState, PageHeader } from "../components/ui";
import { useSession } from "../session/SessionContext";
import { formatDateTimePt } from "../utils/dates";
import { errorDetail } from "../utils/errors";

export default function DeletedProjects() {
  const { can } = useSession();
  const allowed = can("project.restore");
  const { notify } = useToast();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [restoringId, setRestoringId] = useState<string | null>(null);
  const [restoreErrors, setRestoreErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!allowed) return undefined;
    let cancelled = false;
    setProjects(null);
    setError(null);
    listDeletedProjects()
      .then((result) => { if (!cancelled) setProjects(result); })
      .catch((reason) => { if (!cancelled) setError(errorDetail(reason, "Não foi possível carregar projetos apagados.")); });
    return () => { cancelled = true; };
  }, [allowed, reloadKey]);

  if (!allowed) return <Navigate to="/projects" replace />;

  async function handleRestore(project: Project) {
    setRestoringId(project.id);
    setRestoreErrors((current) => ({ ...current, [project.id]: "" }));
    try {
      await restoreProject(project.id);
      setProjects((current) => current?.filter((candidate) => candidate.id !== project.id) ?? current);
      notify("Projeto restaurado.", "success");
    } catch (reason) {
      setRestoreErrors((current) => ({ ...current, [project.id]: errorDetail(reason, "Não foi possível restaurar o projeto.") }));
    } finally {
      setRestoringId(null);
    }
  }

  return (
    <>
      <PageHeader
        title="Projetos apagados"
        subtitle="Projetos removidos logicamente; a situação Ativo/Inativo não altera esta lista."
        actions={<Link to="/projects" className="btn">Voltar aos projetos</Link>}
      />
      <div className="card">
        {error && <ErrorState message={error} onRetry={() => setReloadKey((key) => key + 1)} />}
        {!error && projects === null && <LoadingState label="A carregar projetos apagados…" rows={3} />}
        {!error && projects?.length === 0 && <EmptyState icon="folder" title="Não há projetos apagados." />}
        {!error && projects && projects.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <caption className="sr-only">Projetos apagados</caption>
              <thead>
                <tr><th scope="col">Projeto</th><th scope="col">Cliente</th><th scope="col">Apagado em</th><th scope="col">Ações</th></tr>
              </thead>
              <tbody>
                {projects.map((project) => (
                  <tr key={project.id}>
                    <td>{project.name}</td>
                    <td>{project.client_name ?? "—"}</td>
                    <td>{project.deleted_at ? formatDateTimePt(project.deleted_at) : "—"}</td>
                    <td>
                      {project.can_restore === true && (
                        <button type="button" className="btn btn--sm" onClick={() => void handleRestore(project)} disabled={restoringId !== null}>
                          {restoringId === project.id ? "A restaurar…" : "Restaurar"}
                        </button>
                      )}
                      {restoreErrors[project.id] && <div className="small text-danger" role="alert">{restoreErrors[project.id]}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
