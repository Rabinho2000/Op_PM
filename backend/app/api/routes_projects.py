"""Endpoints de projeto: listagem/filtros, detalhe, edição autorizada, e
histórico. Toda a escrita passa por `app/services/projects.py` — nenhuma
rota aqui manipula `Project`/`ProjectHistory` diretamente.
"""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.people import Person
from app.models.project import Project, ProjectHistory
from app.schemas.projects import ProjectHistoryRead, ProjectRead, ProjectUpdate
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext, PermissionDenied, can_create_task, can_edit_project
from app.security.project_fields import PM_EDITABLE_PROJECT_FIELDS
from app.services.projects import compute_project_task_summary, get_visible_project, list_projects
from app.services.projects import update_project as update_project_service

router = APIRouter(prefix="/api/projects", tags=["projects"])

PROJECT_STATUSES = frozenset({"nao_iniciado", "em_curso", "concluido"})


def _editable_fields(ctx: AuthContext, project: Project) -> list[str]:
    """Mesma regra de app/services/projects.py:update_project (D-028)."""
    if not can_edit_project(ctx, project):
        return []
    if ctx.has_permission("project.edit_all"):
        return sorted(ProjectUpdate.model_fields)
    return sorted(PM_EDITABLE_PROJECT_FIELDS)


def _to_read(db: Session, project: Project, ctx: AuthContext) -> ProjectRead:
    data = ProjectRead.model_validate(project)
    data.pm_display_name = project.pm.display_name if project.pm else None
    data.has_pm = project.has_pm
    data.has_email = project.has_email
    data.has_coordinates = project.has_coordinates
    data.has_contact = project.has_contact

    summary = compute_project_task_summary(db, project.id)
    data.status = summary.status
    data.next_task_title = summary.next_task_title
    data.next_task_due_date = summary.next_task_due_date
    data.overdue_tasks_count = summary.overdue_tasks_count
    data.workflow_progress_percent = summary.workflow_progress_percent
    data.photos_pending_warning = summary.photos_pending_warning

    data.editable_fields = _editable_fields(ctx, project)
    data.can_manage_tasks = can_create_task(ctx, project)
    return data


@router.get("", response_model=list[ProjectRead])
def list_projects_endpoint(
    pm_person_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    q: str | None = Query(default=None, description="Pesquisa por nome/cliente/contacto"),
    status: str | None = Query(default=None, description="nao_iniciado | em_curso | concluido"),
    start_from: dt.date | None = Query(default=None, description="Data de início a partir de (inclusive)"),
    start_to: dt.date | None = Query(default=None, description="Data de início até (inclusive)"),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[ProjectRead]:
    if status is not None and status not in PROJECT_STATUSES:
        raise HTTPException(status_code=400, detail=f"Estado de projeto inválido: {status!r}")
    projects = list_projects(
        db, ctx, pm_person_id=pm_person_id, is_active=is_active, search=q, start_from=start_from, start_to=start_to
    )
    result = [_to_read(db, p, ctx) for p in projects]
    # O estado é derivado das tarefas (compute_project_task_summary), por
    # isso o filtro aplica-se depois do cálculo — nunca uma segunda regra.
    if status is not None:
        result = [r for r in result if r.status == status]
    return result


@router.get("/{project_id}", response_model=ProjectRead)
def get_project_endpoint(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ProjectRead:
    project = get_visible_project(db, ctx, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado ou sem permissão para o ver.")
    return _to_read(db, project, ctx)


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project_endpoint(
    project_id: uuid.UUID,
    body: ProjectUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ProjectRead:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado.")
    try:
        updated = update_project_service(db, project=project, changes=body, ctx=ctx)
    except PermissionDenied as exc:
        # str(exc) inclui, quando aplicável, a lista de campos
        # administrativos recusados (D-028) — não é uma fuga de
        # informação sensível, o próprio pedido já continha esses campos.
        raise HTTPException(status_code=403, detail=f"Sem permissão para editar este projeto: {exc}")
    return _to_read(db, updated, ctx)


@router.get("/{project_id}/history", response_model=list[ProjectHistoryRead])
def get_project_history_endpoint(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[ProjectHistoryRead]:
    project = get_visible_project(db, ctx, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado ou sem permissão para o ver.")

    entries = (
        db.query(ProjectHistory)
        .filter(ProjectHistory.project_id == project_id)
        .order_by(ProjectHistory.changed_at.desc())
        .all()
    )
    result: list[ProjectHistoryRead] = []
    for entry in entries:
        data = ProjectHistoryRead.model_validate(entry)
        if entry.changed_by_person_id:
            person = db.get(Person, entry.changed_by_person_id)
            data.changed_by_person_name = person.display_name if person else None
        result.append(data)
    return result
