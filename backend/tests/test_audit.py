"""Histórico de alterações — append-only, com autor e timestamp."""
from __future__ import annotations

import pytest

from app.audit.log import approve_ai_action, record_ai_action, record_project_change
from app.models.ai import AiAuditLog
from app.models.project import Project, ProjectHistory


def test_record_project_change_creates_history_row_with_author(db_session):
    db = db_session
    project = Project(name="Projeto Sintético para Histórico")
    db.add(project)
    db.flush()

    entry = record_project_change(
        db,
        project_id=project.id,
        field_name="client_email",
        old_value=None,
        new_value="novo.email.sintetico@example.invalid",
        source="ui",
        note="Teste sintético",
    )
    db.flush()

    assert entry.id is not None
    assert entry.old_value is None
    assert entry.new_value == "novo.email.sintetico@example.invalid"
    assert entry.source == "ui"
    assert entry.changed_at is not None
    db.rollback()


def test_record_project_change_rejects_no_op_change(db_session):
    """Corrige, por desenho, o bug do script legado que marcava campos como
    alterados mesmo sem diferença real (C-08)."""
    db = db_session
    project = Project(name="Projeto Sintético Sem Alteração")
    db.add(project)
    db.flush()

    with pytest.raises(ValueError):
        record_project_change(
            db,
            project_id=project.id,
            field_name="client_email",
            old_value="mesmo@example.invalid",
            new_value="mesmo@example.invalid",
            source="clickup",
        )
    db.rollback()


def test_project_history_has_no_updated_at_field():
    """Confirma que o modelo de histórico não tem `updated_at` — reforça,
    ao nível do schema, que uma linha de histórico nunca é atualizada."""
    assert "updated_at" not in ProjectHistory.__table__.columns.keys()
    assert "created_at" not in ProjectHistory.__table__.columns.keys()
    assert "changed_at" in ProjectHistory.__table__.columns.keys()


def test_ai_action_requires_explicit_human_approval(db_session):
    db = db_session
    entry = record_ai_action(
        db,
        tool_name="draft_client_email",
        input_summary="Pedido sintético de rascunho de email",
        output_summary="Rascunho de exemplo gerado pelo mock",
    )
    db.flush()
    assert entry.status == "proposed"
    assert entry.approved_by_person_id is None

    from uuid import uuid4

    approve_ai_action(db, entry, approved_by_person_id=uuid4())
    assert entry.status == "approved"
    assert entry.approved_at is not None
    db.rollback()


def test_ai_audit_log_table_exists_and_is_queryable(db_session):
    db = db_session
    assert db.query(AiAuditLog).count() >= 0
