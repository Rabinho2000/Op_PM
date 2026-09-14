"""IDs externos estáveis: nunca o nome do projeto como chave de
correspondência (corrige C-07 do sistema legado)."""
from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.project import Project, ProjectExternalId


def test_external_id_unique_per_source_system(db_session):
    db = db_session
    project = Project(name="Projeto Sintético para IDs Externos")
    db.add(project)
    db.flush()

    db.add(ProjectExternalId(project_id=project.id, source_system="clickup", external_id="cu_dup_test"))
    db.flush()

    db.add(ProjectExternalId(project_id=project.id, source_system="clickup", external_id="cu_dup_test"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_same_external_id_allowed_across_different_source_systems(db_session):
    db = db_session
    project = Project(name="Projeto Sintético Multi-Fonte")
    db.add(project)
    db.flush()

    db.add(ProjectExternalId(project_id=project.id, source_system="clickup", external_id="shared_ref_001"))
    db.add(ProjectExternalId(project_id=project.id, source_system="financial", external_id="shared_ref_001"))
    db.flush()  # não deve levantar — a unicidade é por (source_system, external_id)
    db.rollback()


def test_project_name_change_does_not_affect_external_id_mapping(db_session):
    """A correspondência com o ClickUp sobrevive a uma renomeação do
    projeto — ao contrário do `clickup_sync.py` legado, que dependia do
    nome exato."""
    db = db_session
    project = Project(name="Nome Original Sintético")
    db.add(project)
    db.flush()
    db.add(ProjectExternalId(project_id=project.id, source_system="clickup", external_id="cu_stable_001"))
    db.flush()

    project.name = "Nome Renomeado Sintético"
    db.flush()

    link = (
        db.query(ProjectExternalId)
        .filter(ProjectExternalId.source_system == "clickup", ProjectExternalId.external_id == "cu_stable_001")
        .one()
    )
    assert link.project_id == project.id
    db.rollback()
