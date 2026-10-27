import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { DashboardWorkProject, DashboardWorks, MapData } from "../api/client";
import ProjectMapView, { MapItem } from "./ProjectMapView";
import { Alert, Badge, Card, EmptyState, LoadingState } from "./ui";
import { formatDatePt } from "../utils/dates";

const LIST_LIMIT = 6;

function WorkList({
  projects,
  emptyTitle,
  loading,
}: {
  projects: DashboardWorkProject[] | null;
  emptyTitle: string;
  loading: boolean;
}) {
  if (loading || projects === null) return <LoadingState rows={3} />;
  if (projects.length === 0) return <EmptyState compact title={emptyTitle} />;

  return (
    <>
      <ul className="list">
        {projects.slice(0, LIST_LIMIT).map((project) => (
          <li key={project.id} className="list__item dashboard-work-item">
            <div className="list__main">
              <Link className="list__title" to={`/projects/${project.id}`}>
                {project.name}
              </Link>
              <div className="list__meta">
                {project.expected_start_date && `Início previsto: ${formatDatePt(project.expected_start_date)}`}
                {project.pm_display_name ? ` · PM: ${project.pm_display_name}` : " · Sem PM atribuído"}
                {project.team_display_name && ` · Equipa: ${project.team_display_name}`}
                {project.installer_display_name && ` · Instalador: ${project.installer_display_name}`}
              </div>
              <div className="list__meta dashboard-work-item__task">
                Próxima tarefa: {project.next_task_title ?? "Sem tarefas pendentes"}
                {project.next_task_due_date && ` · prazo ${formatDatePt(project.next_task_due_date)}`}
              </div>
            </div>
          </li>
        ))}
      </ul>
      {projects.length > LIST_LIMIT && (
        <div className="list-more">
          <Link to="/projects?estado=todos">Ver projetos ({projects.length})</Link>
        </div>
      )}
    </>
  );
}

export default function DashboardWorksPanel({
  works,
  mapAllowed,
  mapData,
  mapError,
  worksError,
}: {
  works: DashboardWorks | null;
  mapAllowed: boolean;
  mapData: MapData | null;
  mapError: string | null;
  worksError: string | null;
}) {
  const navigate = useNavigate();
  const mapItems = useMemo<MapItem[]>(() => {
    if (!mapData) return [];
    return mapData.projects
      .filter(
        (project) =>
          (project.lifecycle_status === "construcao" || project.lifecycle_status === "preparacao") &&
          project.lat !== null &&
          project.lon !== null
      )
      .map((project) => ({
        key: `project-${project.id}`,
        layer: "projects",
        lat: project.lat as number,
        lon: project.lon as number,
        title: project.name,
        lifecycleStatus: project.lifecycle_status,
        projectId: project.id,
        projectName: project.name,
        projectStatus: project.lifecycle_status === "construcao" ? "Construção" : "Preparação",
        onClick: () => navigate(`/projects/${project.id}`),
      }));
  }, [mapData, navigate]);

  const mapCard = mapAllowed ? (
    <Card title="Mapa das obras" icon="mapPin" flush>
      {mapError ? (
        <Alert tone="danger">{mapError}</Alert>
      ) : !mapData ? (
        <LoadingState rows={3} />
      ) : !mapData.config.provider_enabled ? (
        <Alert tone="info">
          Sem provider de mapa configurado (<code>MAP_TILE_URL</code>) — a mostrar a lista funcional dos locais em vez
          de um mapa visual. O resto da aplicação funciona normalmente sem esta configuração.
        </Alert>
      ) : (
        <>
          {mapItems.length > 0 ? (
            <ProjectMapView items={mapItems} config={mapData.config} height={260} />
          ) : (
            <EmptyState compact icon="mapPin" title="Sem obras com coordenadas em construção ou preparação." />
          )}
          <div className="legend dashboard-works-legend" aria-label="Legenda dos estados das obras">
            <span>
              <span className="legend__swatch dashboard-work-swatch dashboard-work-swatch--construction" />
              Construção
            </span>
            <span>
              <span className="legend__swatch dashboard-work-swatch dashboard-work-swatch--preparation" />
              Preparação
            </span>
          </div>
        </>
      )}
    </Card>
  ) : null;

  return (
    <section
      className={`dashboard-works-panel section-gap ${mapAllowed ? "" : "dashboard-works-panel--without-map"}`}
      aria-label="Obras em curso e próximas obras"
    >
      {mapCard}
      <div className="dashboard-works-panel__lists">
        {worksError ? (
          <Card title="Obras" icon="folder" flush>
            <Alert tone="danger">{worksError}</Alert>
          </Card>
        ) : (
          <>
            <Card title="Obras a decorrer" icon="activity" flush>
              <WorkList projects={works?.construction ?? null} emptyTitle="Nenhuma obra a decorrer." loading={!works} />
            </Card>
            <Card title="Próximas obras" icon="flag" flush>
              <WorkList projects={works?.preparation ?? null} emptyTitle="Nenhuma obra em preparação." loading={!works} />
            </Card>
          </>
        )}
      </div>
    </section>
  );
}
