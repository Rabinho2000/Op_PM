"""Dados satélite do projeto (instalação/licenciamento/comunicação) — ver
app/models/project_data.py. Um registo 1:1 por projeto em cada tabela;
`PATCH` cria o registo na primeira edição (nunca exige um passo de
"criar" separado) e gera uma entrada de `ProjectDataHistory` por campo
efetivamente alterado, tal como `app/services/projects.py:update_project`
já faz para `Project`.
"""
from __future__ import annotations

import uuid
from typing import TypeVar

from sqlalchemy.orm import Session

from app.models.project_data import (
    ProjectCommunicationData,
    ProjectDataHistory,
    ProjectInstallationData,
    ProjectLicensingData,
)

_ModelT = TypeVar(
    "_ModelT", ProjectInstallationData, ProjectLicensingData, ProjectCommunicationData
)

ENTITY_TYPE_INSTALLATION = "installation"
ENTITY_TYPE_LICENSING = "licensing"
ENTITY_TYPE_COMMUNICATION = "communication"

_ENTITY_TYPE_BY_MODEL: dict[type, str] = {
    ProjectInstallationData: ENTITY_TYPE_INSTALLATION,
    ProjectLicensingData: ENTITY_TYPE_LICENSING,
    ProjectCommunicationData: ENTITY_TYPE_COMMUNICATION,
}


def get_installation_data(db: Session, project_id: uuid.UUID) -> ProjectInstallationData | None:
    return db.query(ProjectInstallationData).filter(ProjectInstallationData.project_id == project_id).one_or_none()


def get_licensing_data(db: Session, project_id: uuid.UUID) -> ProjectLicensingData | None:
    return db.query(ProjectLicensingData).filter(ProjectLicensingData.project_id == project_id).one_or_none()


def get_communication_data(db: Session, project_id: uuid.UUID) -> ProjectCommunicationData | None:
    return (
        db.query(ProjectCommunicationData)
        .filter(ProjectCommunicationData.project_id == project_id)
        .one_or_none()
    )


def _upsert(
    db: Session,
    *,
    model_cls: type[_ModelT],
    project_id: uuid.UUID,
    changes: dict,
    changed_by_person_id: uuid.UUID | None,
    source: str = "ui",
) -> _ModelT:
    entity_type = _ENTITY_TYPE_BY_MODEL[model_cls]
    instance = db.query(model_cls).filter(model_cls.project_id == project_id).one_or_none()
    if instance is None:
        instance = model_cls(project_id=project_id)
        db.add(instance)

    for field_name, new_value in changes.items():
        old_value = getattr(instance, field_name, None)
        if old_value == new_value:
            continue
        db.add(
            ProjectDataHistory(
                project_id=project_id,
                entity_type=entity_type,
                field_name=field_name,
                old_value=str(old_value) if old_value is not None else None,
                new_value=str(new_value) if new_value is not None else None,
                changed_by_person_id=changed_by_person_id,
                source=source,
            )
        )
        setattr(instance, field_name, new_value)

    db.commit()
    db.refresh(instance)
    return instance


def upsert_installation_data(
    db: Session, *, project_id: uuid.UUID, changes: dict, changed_by_person_id: uuid.UUID | None, source: str = "ui"
) -> ProjectInstallationData:
    return _upsert(
        db,
        model_cls=ProjectInstallationData,
        project_id=project_id,
        changes=changes,
        changed_by_person_id=changed_by_person_id,
        source=source,
    )


def upsert_licensing_data(
    db: Session, *, project_id: uuid.UUID, changes: dict, changed_by_person_id: uuid.UUID | None, source: str = "ui"
) -> ProjectLicensingData:
    return _upsert(
        db,
        model_cls=ProjectLicensingData,
        project_id=project_id,
        changes=changes,
        changed_by_person_id=changed_by_person_id,
        source=source,
    )


def upsert_communication_data(
    db: Session, *, project_id: uuid.UUID, changes: dict, changed_by_person_id: uuid.UUID | None, source: str = "ui"
) -> ProjectCommunicationData:
    return _upsert(
        db,
        model_cls=ProjectCommunicationData,
        project_id=project_id,
        changes=changes,
        changed_by_person_id=changed_by_person_id,
        source=source,
    )


def list_data_history(
    db: Session, project_id: uuid.UUID, *, entity_type: str | None = None
) -> list[ProjectDataHistory]:
    query = db.query(ProjectDataHistory).filter(ProjectDataHistory.project_id == project_id)
    if entity_type is not None:
        query = query.filter(ProjectDataHistory.entity_type == entity_type)
    return query.order_by(ProjectDataHistory.changed_at.desc()).all()
