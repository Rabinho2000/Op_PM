"""Processo de um projeto (D-073). Ver `app/services/process.py`.

Ver: quem consegue ver o projeto (404 fora do âmbito). Marcar progresso:
`workflow.update_progress` no âmbito do projeto.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.process import ContactProgressUpdate, ProcessRead, SubtaskProgressUpdate
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext, PermissionDenied
from app.services.process import ProcessError, build_project_process, set_contact_done, set_subtask_done
from app.services.projects import get_visible_project
from app.utils.timezones import today_lisbon

router = APIRouter(prefix="/api/projects", tags=["process"])


def _visible(db: Session, ctx: AuthContext, project_id: uuid.UUID):
    project = get_visible_project(db, ctx, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado ou sem permissão para o ver.")
    return project


@router.get("/{project_id}/process", response_model=ProcessRead)
def get_process_endpoint(
    project_id: uuid.UUID, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> ProcessRead:
    project = _visible(db, ctx, project_id)
    return build_project_process(db, project, ctx, today_lisbon())


@router.patch("/{project_id}/process/subtasks/{subtask_id}", response_model=ProcessRead)
def update_subtask_endpoint(
    project_id: uuid.UUID,
    subtask_id: uuid.UUID,
    body: SubtaskProgressUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ProcessRead:
    project = _visible(db, ctx, project_id)
    try:
        set_subtask_done(db, project=project, subtask_id=subtask_id, done=body.done, ctx=ctx)
    except PermissionDenied:
        raise HTTPException(status_code=403, detail="Sem permissão para marcar o progresso deste projeto.")
    except ProcessError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return build_project_process(db, project, ctx, today_lisbon())


@router.patch("/{project_id}/process/stages/{stage_id}/contact", response_model=ProcessRead)
def update_contact_endpoint(
    project_id: uuid.UUID,
    stage_id: uuid.UUID,
    body: ContactProgressUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ProcessRead:
    project = _visible(db, ctx, project_id)
    try:
        set_contact_done(db, project=project, stage_id=stage_id, done=body.done, ctx=ctx)
    except PermissionDenied:
        raise HTTPException(status_code=403, detail="Sem permissão para marcar o progresso deste projeto.")
    except ProcessError as exc:
        raise HTTPException(status_code=404 if "não encontrada" in str(exc) else 422, detail=str(exc))
    return build_project_process(db, project, ctx, today_lisbon())
