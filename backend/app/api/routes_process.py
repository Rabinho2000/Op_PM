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
from app.security.permissions import AuthContext, is_installer_readonly_scope
from app.services.process import ProcessError, build_project_process, set_contact_done, set_stage_subtasks_done, set_subtask_done
from app.utils.timezones import today_lisbon
from app.security.guards import permission_denied_message
from app.api.deps import visible_project_or_404

router = APIRouter(prefix="/api/projects", tags=["process"])

_deny_mark_progress = permission_denied_message("Sem permissão para marcar o progresso deste projeto.")


def _redact_process(process: ProcessRead, ctx: AuthContext) -> ProcessRead:
    if not is_installer_readonly_scope(ctx):
        return process
    redacted = process.model_copy(deep=True)
    redacted.can_update = False
    for phase in redacted.phases:
        for stage in phase.stages:
            stage.note = ""
            stage.responsible.names = []
            if stage.contact is not None:
                stage.contact.note = ""
            for subtask in stage.subtasks:
                subtask.done_by_display_name = None
    return redacted


@router.get("/{project_id}/process", response_model=ProcessRead)
def get_process_endpoint(
    project_id: uuid.UUID, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> ProcessRead:
    project = visible_project_or_404(db, ctx, project_id)
    return _redact_process(build_project_process(db, project, ctx, today_lisbon()), ctx)


@router.patch(
    "/{project_id}/process/subtasks/{subtask_id}",
    response_model=ProcessRead,
    dependencies=[Depends(_deny_mark_progress)],
)
def update_subtask_endpoint(
    project_id: uuid.UUID,
    subtask_id: uuid.UUID,
    body: SubtaskProgressUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ProcessRead:
    if is_installer_readonly_scope(ctx):
        raise HTTPException(status_code=403, detail="O papel externo tem acesso somente de leitura.")
    project = visible_project_or_404(db, ctx, project_id)
    try:
        set_subtask_done(db, project=project, subtask_id=subtask_id, done=body.done, ctx=ctx)
    except ProcessError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _redact_process(build_project_process(db, project, ctx, today_lisbon()), ctx)


@router.patch(
    "/{project_id}/process/stages/{stage_id}/subtasks",
    response_model=ProcessRead,
    dependencies=[Depends(_deny_mark_progress)],
)
def update_stage_subtasks_endpoint(
    project_id: uuid.UUID,
    stage_id: uuid.UUID,
    body: SubtaskProgressUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ProcessRead:
    if is_installer_readonly_scope(ctx):
        raise HTTPException(status_code=403, detail="O papel externo tem acesso somente de leitura.")
    project = visible_project_or_404(db, ctx, project_id)
    try:
        set_stage_subtasks_done(db, project=project, stage_id=stage_id, done=body.done, ctx=ctx)
    except ProcessError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _redact_process(build_project_process(db, project, ctx, today_lisbon()), ctx)


@router.patch(
    "/{project_id}/process/stages/{stage_id}/contact",
    response_model=ProcessRead,
    dependencies=[Depends(_deny_mark_progress)],
)
def update_contact_endpoint(
    project_id: uuid.UUID,
    stage_id: uuid.UUID,
    body: ContactProgressUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ProcessRead:
    if is_installer_readonly_scope(ctx):
        raise HTTPException(status_code=403, detail="O papel externo tem acesso somente de leitura.")
    project = visible_project_or_404(db, ctx, project_id)
    try:
        set_contact_done(db, project=project, stage_id=stage_id, done=body.done, ctx=ctx)
    except ProcessError as exc:
        raise HTTPException(status_code=404 if "não encontrada" in str(exc) else 422, detail=str(exc))
    return _redact_process(build_project_process(db, project, ctx, today_lisbon()), ctx)
