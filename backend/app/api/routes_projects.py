"""Endpoints de projeto: listagem/filtros, detalhe, edição autorizada, e
histórico. Toda a escrita passa por `app/services/projects.py` — nenhuma
rota aqui manipula `Project`/`ProjectHistory` diretamente.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.people import Person
from app.models.project import Project, ProjectHistory
from app.schemas.projects import ProjectHistoryRead, ProjectRead, ProjectUpdate
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext, PermissionDenied
from app.services.projects import get_visible_project, list_projects
from app.services.projects import update_project as update_project_service

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _to_read(project: Project) -> ProjectRead:
    data = ProjectRead.model_validate(project)
    data.pm_display_name = project.pm.display_name if project.pm else None
    data.has_pm = project.has_pm
    data.has_email = project.has_email
    data.has_coordinates = project.has_coordinates
    data.has_contact = project.has_contact
    return data


@router.get("", response_model=list[ProjectRead])
def list_projects_endpoint(
    pm_person_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    q: str | None = Query(default=None, description="Pesquisa por nome/cliente/contacto"),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[ProjectRead]:
    projects = list_projects(db, ctx, pm_person_id=pm_person_id, is_active=is_active, search=q)
    return [_to_read(p) for p in projects]


@router.get("/{project_id}", response_model=ProjectRead)
def get_project_endpoint(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ProjectRead:
    project = get_visible_project(db, ctx, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado ou sem permissão para o ver.")
    return _to_read(project)


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
    except PermissionDenied:
        raise HTTPException(status_code=403, detail="Sem permissão para editar este projeto.")
    return _to_read(updated)


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
