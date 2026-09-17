"""Percurso de obra de um projeto (D-052): leitura e marcação de progresso.
Toda a lógica (datas, estados, permissões, histórico) vive em
`app/services/workflow.py`."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.project import Project
from app.schemas.workflow import ProjectWorkflowRead, WorkflowDoneUpdate
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext, PermissionDenied
from app.services.projects import get_visible_project
from app.services.workflow import (
    WorkflowItemNotFound,
    build_project_workflow,
    set_stage_contact_done,
    set_subtask_done,
)

router = APIRouter(prefix="/api/projects/{project_id}/workflow", tags=["workflow"])


def _visible_project(db: Session, ctx: AuthContext, project_id: uuid.UUID) -> Project:
    project = get_visible_project(db, ctx, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado ou sem permissão para o ver.")
    return project


@router.get("", response_model=ProjectWorkflowRead)
def get_project_workflow(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ProjectWorkflowRead:
    project = _visible_project(db, ctx, project_id)
    return ProjectWorkflowRead.model_validate(build_project_workflow(db, project, ctx))


@router.put("/subtasks/{subtask_code}", response_model=ProjectWorkflowRead)
def update_subtask(
    project_id: uuid.UUID,
    subtask_code: str,
    body: WorkflowDoneUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ProjectWorkflowRead:
    project = _visible_project(db, ctx, project_id)
    try:
        set_subtask_done(db, ctx, project, subtask_code, body.done)
    except PermissionDenied:
        raise HTTPException(status_code=403, detail="Sem permissão para alterar o percurso deste projeto.")
    except WorkflowItemNotFound:
        raise HTTPException(status_code=404, detail="Subtarefa do percurso não encontrada.")
    return ProjectWorkflowRead.model_validate(build_project_workflow(db, project, ctx))


@router.put("/stages/{stage_code}/contact", response_model=ProjectWorkflowRead)
def update_stage_contact(
    project_id: uuid.UUID,
    stage_code: str,
    body: WorkflowDoneUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ProjectWorkflowRead:
    project = _visible_project(db, ctx, project_id)
    try:
        set_stage_contact_done(db, ctx, project, stage_code, body.done)
    except PermissionDenied:
        raise HTTPException(status_code=403, detail="Sem permissão para alterar o percurso deste projeto.")
    except WorkflowItemNotFound:
        raise HTTPException(status_code=404, detail="Etapa sem ponto de contacto ou inexistente.")
    return ProjectWorkflowRead.model_validate(build_project_workflow(db, project, ctx))
