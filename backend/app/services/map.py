"""Dados do mapa operacional: um único payload com projetos (com e sem
coordenadas), fornecedores, pontos de recolha e pendências — sempre já
filtrado pela visibilidade do utilizador (nunca a lista completa enviada
para o cliente filtrar). Ver docs/MAP_AND_PLANNING.md.
"""
from __future__ import annotations

import dataclasses
import uuid

from sqlalchemy.orm import Session

from app.models.map_ops import PickupPoint, ProjectIssue
from app.models.project import Project
from app.models.supplier import Supplier
from app.models.task import OPEN_TASK_STATUSES, Task
from app.security.permissions import AuthContext, can_view_project_issue
from app.services.projects import visible_projects_query


@dataclasses.dataclass
class MapProject:
    project: Project
    open_tasks_count: int
    issues_count: int


def get_map_projects(db: Session, ctx: AuthContext) -> tuple[list[MapProject], list[MapProject]]:
    """Devolve (com_coordenadas, sem_coordenadas) — sempre a partir de
    `visible_projects_query`, nunca a lista completa de projetos."""
    projects = visible_projects_query(db, ctx).filter(Project.is_active.is_(True)).all()
    with_coords: list[MapProject] = []
    without_coords: list[MapProject] = []
    for project in projects:
        open_tasks_count = (
            db.query(Task)
            .filter(Task.project_id == project.id, Task.status.in_(OPEN_TASK_STATUSES))
            .count()
        )
        issues_count = (
            db.query(ProjectIssue)
            .filter(ProjectIssue.project_id == project.id, ProjectIssue.status == "aberta")
            .count()
        )
        entry = MapProject(project=project, open_tasks_count=open_tasks_count, issues_count=issues_count)
        if project.has_coordinates:
            with_coords.append(entry)
        else:
            without_coords.append(entry)
    return with_coords, without_coords


def get_visible_suppliers(db: Session) -> list[Supplier]:
    return db.query(Supplier).filter(Supplier.is_active.is_(True)).order_by(Supplier.name).all()


def get_visible_pickup_points(db: Session) -> list[PickupPoint]:
    return db.query(PickupPoint).filter(PickupPoint.is_active.is_(True)).order_by(PickupPoint.name).all()


def get_visible_issues(db: Session, ctx: AuthContext) -> list[ProjectIssue]:
    """Filtra sempre por `can_view_project_issue` — nunca a lista completa
    de pendências, mesmo as marcadas `visible_on_map=True`."""
    issues = (
        db.query(ProjectIssue)
        .filter(ProjectIssue.visible_on_map.is_(True))
        .order_by(ProjectIssue.created_at.desc())
        .all()
    )
    return [issue for issue in issues if can_view_project_issue(ctx, issue.project)]


def list_project_issues(db: Session, project_id: uuid.UUID) -> list[ProjectIssue]:
    return (
        db.query(ProjectIssue)
        .filter(ProjectIssue.project_id == project_id)
        .order_by(ProjectIssue.created_at.desc())
        .all()
    )


def create_project_issue(
    db: Session,
    *,
    project_id: uuid.UUID,
    description: str,
    category: str,
    priority: str,
    lat: float | None,
    lon: float | None,
    notes: str,
    created_by_person_id: uuid.UUID | None,
) -> ProjectIssue:
    issue = ProjectIssue(
        project_id=project_id,
        description=description,
        category=category,
        priority=priority,
        lat=lat,
        lon=lon,
        notes=notes,
        created_by_person_id=created_by_person_id,
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)
    return issue


def update_project_issue(db: Session, *, issue: ProjectIssue, changes: dict) -> ProjectIssue:
    for field_name, value in changes.items():
        setattr(issue, field_name, value)
    db.commit()
    db.refresh(issue)
    return issue


def convert_issue_to_task(
    db: Session, *, issue: ProjectIssue, title: str, created_by_person_id: uuid.UUID | None
) -> Task:
    """Cria uma `Task` a partir da pendência e liga `related_task_id` —
    nunca duplica a entidade: a pendência continua a existir para controlo
    do mapa, a tarefa passa a ser o item de trabalho a executar."""
    task = Task(
        project_id=issue.project_id,
        title=title,
        task_type="custom",
        description=issue.description,
        priority=issue.priority,
        assigned_to_person_id=issue.assigned_to_person_id,
        due_date=issue.due_date,
        created_by_person_id=created_by_person_id,
    )
    db.add(task)
    db.flush()
    issue.related_task_id = task.id
    db.commit()
    db.refresh(task)
    return task
