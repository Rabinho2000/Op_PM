"""Endpoints dos dados satélite do projeto: instalação, licenciamento,
comunicação/M2M, e o histórico combinado das três. Toda a escrita passa
por `app/services/project_data.py`. Ver docs/PLAN_OPERATIONS_MVP.md
secção 2.1.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.people import Person
from app.schemas.project_data import (
    ProjectCommunicationDataRead,
    ProjectCommunicationDataUpdate,
    ProjectDataHistoryRead,
    ProjectInstallationDataRead,
    ProjectInstallationDataUpdate,
    ProjectLicensingDataRead,
    ProjectLicensingDataUpdate,
)
from app.security.current_user import get_auth_context
from app.security.permissions import (
    AuthContext,
    can_edit_project_communication_data,
    can_edit_project_installation_data,
    can_edit_project_licensing_data,
    can_view_project_communication_data,
    can_view_project_installation_data,
    can_view_project_licensing_data,
)
from app.services.project_data import (
    get_communication_data,
    get_installation_data,
    get_licensing_data,
    list_data_history,
    upsert_communication_data,
    upsert_installation_data,
    upsert_licensing_data,
)
from app.services.projects import get_visible_project

router = APIRouter(prefix="/api/projects", tags=["project-data"])


def _get_project_or_404(db: Session, project_id: uuid.UUID, ctx: AuthContext):
    project = get_visible_project(db, ctx, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado ou sem permissão para o ver.")
    return project


@router.get("/{project_id}/installation-data", response_model=ProjectInstallationDataRead)
def get_installation_data_endpoint(
    project_id: uuid.UUID, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> ProjectInstallationDataRead:
    project = _get_project_or_404(db, project_id, ctx)
    if not can_view_project_installation_data(ctx, project):
        raise HTTPException(status_code=403, detail="Sem permissão para ver dados de instalação.")
    data = get_installation_data(db, project_id)
    if data is None:
        return ProjectInstallationDataRead(project_id=project_id)
    return ProjectInstallationDataRead.model_validate(data)


@router.patch("/{project_id}/installation-data", response_model=ProjectInstallationDataRead)
def update_installation_data_endpoint(
    project_id: uuid.UUID,
    body: ProjectInstallationDataUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ProjectInstallationDataRead:
    project = _get_project_or_404(db, project_id, ctx)
    if not can_edit_project_installation_data(ctx, project):
        raise HTTPException(status_code=403, detail="Sem permissão para editar dados de instalação.")
    changes = body.model_dump(exclude_unset=True)
    data = upsert_installation_data(
        db, project_id=project_id, changes=changes, changed_by_person_id=ctx.person_id
    )
    return ProjectInstallationDataRead.model_validate(data)


@router.get("/{project_id}/licensing-data", response_model=ProjectLicensingDataRead)
def get_licensing_data_endpoint(
    project_id: uuid.UUID, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> ProjectLicensingDataRead:
    project = _get_project_or_404(db, project_id, ctx)
    if not can_view_project_licensing_data(ctx, project):
        raise HTTPException(status_code=403, detail="Sem permissão para ver dados de licenciamento.")
    data = get_licensing_data(db, project_id)
    if data is None:
        return ProjectLicensingDataRead(project_id=project_id)
    return ProjectLicensingDataRead.model_validate(data)


@router.patch("/{project_id}/licensing-data", response_model=ProjectLicensingDataRead)
def update_licensing_data_endpoint(
    project_id: uuid.UUID,
    body: ProjectLicensingDataUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ProjectLicensingDataRead:
    project = _get_project_or_404(db, project_id, ctx)
    if not can_edit_project_licensing_data(ctx, project):
        raise HTTPException(status_code=403, detail="Sem permissão para editar dados de licenciamento.")
    changes = body.model_dump(exclude_unset=True)
    data = upsert_licensing_data(db, project_id=project_id, changes=changes, changed_by_person_id=ctx.person_id)
    return ProjectLicensingDataRead.model_validate(data)


@router.get("/{project_id}/communication-data", response_model=ProjectCommunicationDataRead)
def get_communication_data_endpoint(
    project_id: uuid.UUID, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> ProjectCommunicationDataRead:
    project = _get_project_or_404(db, project_id, ctx)
    if not can_view_project_communication_data(ctx, project):
        raise HTTPException(status_code=403, detail="Sem permissão para ver dados de comunicação.")
    data = get_communication_data(db, project_id)
    if data is None:
        return ProjectCommunicationDataRead(project_id=project_id)
    return ProjectCommunicationDataRead.model_validate(data)


@router.patch("/{project_id}/communication-data", response_model=ProjectCommunicationDataRead)
def update_communication_data_endpoint(
    project_id: uuid.UUID,
    body: ProjectCommunicationDataUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> ProjectCommunicationDataRead:
    project = _get_project_or_404(db, project_id, ctx)
    if not can_edit_project_communication_data(ctx, project):
        raise HTTPException(status_code=403, detail="Sem permissão para editar dados de comunicação.")
    changes = body.model_dump(exclude_unset=True)
    data = upsert_communication_data(
        db, project_id=project_id, changes=changes, changed_by_person_id=ctx.person_id
    )
    return ProjectCommunicationDataRead.model_validate(data)


@router.get("/{project_id}/data-history", response_model=list[ProjectDataHistoryRead])
def get_data_history_endpoint(
    project_id: uuid.UUID,
    entity_type: str | None = Query(default=None, description="installation | licensing | communication"),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[ProjectDataHistoryRead]:
    _get_project_or_404(db, project_id, ctx)
    entries = list_data_history(db, project_id, entity_type=entity_type)
    result: list[ProjectDataHistoryRead] = []
    for entry in entries:
        data = ProjectDataHistoryRead.model_validate(entry)
        if entry.changed_by_person_id:
            person = db.get(Person, entry.changed_by_person_id)
            data.changed_by_person_name = person.display_name if person else None
        result.append(data)
    return result
