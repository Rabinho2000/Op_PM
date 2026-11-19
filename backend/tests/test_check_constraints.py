"""CHECKs na BD dos vocabulários fechados e das quantidades (M7) e email único
sem distinção de maiúsculas (M8).

A suite cria o esquema com `Base.metadata.create_all`, por isso estes testes
exercitam os CHECKs declarados nos modelos; `test_check_constraints_migration.py`
garante que a migração produz os mesmos.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db import Base
from app.models.constraints import sql_in_list, vocabulary_check
from app.models.identity import User
from app.models.inventory import (
    MATERIAL_REQUEST_STATUSES,
    MOVEMENT_AJUSTE,
    MOVEMENT_CONSUMO,
    MOVEMENT_ENTRADA,
    MOVEMENT_RESERVA,
    MOVEMENT_TYPES,
    InventoryItem,
    InventoryLocation,
    InventoryMovement,
    MaterialRequest,
    MaterialRequestHistory,
    MaterialRequestItem,
    ProjectMaterialRequirement,
)
from app.models.people import Person
from app.models.project import Project
from app.models.task import Task
from app.models.time_bank import ADJUSTMENT_KINDS, ENTRY_MODES, TimeBankAdjustment, TimeBankEntry
from app.services.project_lifecycle import LIFECYCLE_STATUS_CODES
from app.utils.email import normalize_email


def _must_fail(db_session, *objects) -> None:
    """A escrita tem de ser recusada pela BD (IntegrityError), sem sujar a transação do teste."""
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add_all(objects)
            db_session.flush()


def _must_pass(db_session, *objects) -> None:
    with db_session.begin_nested():
        db_session.add_all(objects)
        db_session.flush()


@pytest.fixture()
def person(db_session) -> Person:
    return db_session.query(Person).filter(Person.user.has()).first()


@pytest.fixture()
def user(db_session) -> User:
    return db_session.query(User).first()


@pytest.fixture()
def project(db_session) -> Project:
    return db_session.query(Project).first()


@pytest.fixture()
def item(db_session) -> InventoryItem:
    item = InventoryItem(sku=f"CHK-{uuid.uuid4().hex[:8]}", name="Artigo de teste")
    db_session.add(item)
    db_session.flush()
    return item


# --- helper -----------------------------------------------------------------


def test_vocabulary_check_is_generated_from_the_constant():
    assert sql_in_list(frozenset({"b", "a"})) == "'a', 'b'"  # conjuntos: ordem determinística
    assert sql_in_list(("z", "a")) == "'z', 'a'"  # sequências: ordem dada
    assert str(vocabulary_check("c", ("x", "y"), name="ck_t_c").sqltext) == "c IN ('x', 'y')"
    assert str(vocabulary_check("c", ("x",), name="ck_t_c", nullable=True).sqltext) == "c IS NULL OR c IN ('x')"
    with pytest.raises(ValueError):
        sql_in_list(())
    with pytest.raises(ValueError):
        sql_in_list(("o'brien",))


# --- Project.lifecycle_status -----------------------------------------------


def test_project_lifecycle_status_vocabulary(db_session):
    for code in sorted(LIFECYCLE_STATUS_CODES) + [None]:
        _must_pass(db_session, Project(name=f"P {code}", lifecycle_status=code))
    _must_fail(db_session, Project(name="P inválido", lifecycle_status="em_obras"))


# --- inventário ---------------------------------------------------------------


@pytest.mark.parametrize("movement_type", sorted(MOVEMENT_TYPES - {MOVEMENT_AJUSTE}))
def test_movement_quantity_must_be_positive_except_adjustments(db_session, item, movement_type):
    _must_pass(db_session, InventoryMovement(item_id=item.id, movement_type=movement_type, quantity=Decimal("1.5")))
    _must_fail(db_session, InventoryMovement(item_id=item.id, movement_type=movement_type, quantity=Decimal("-1")))
    _must_fail(db_session, InventoryMovement(item_id=item.id, movement_type=movement_type, quantity=Decimal("0")))


def test_adjustment_accepts_both_signs_but_not_zero(db_session, item):
    _must_pass(db_session, InventoryMovement(item_id=item.id, movement_type=MOVEMENT_AJUSTE, quantity=Decimal("2")))
    _must_pass(db_session, InventoryMovement(item_id=item.id, movement_type=MOVEMENT_AJUSTE, quantity=Decimal("-2")))
    _must_fail(db_session, InventoryMovement(item_id=item.id, movement_type=MOVEMENT_AJUSTE, quantity=Decimal("0")))


def test_reversal_rows_are_negative_and_originals_positive(db_session, item, project):
    original = InventoryMovement(
        item_id=item.id, movement_type=MOVEMENT_RESERVA, quantity=Decimal("4"), project_id=project.id
    )
    _must_pass(db_session, original)
    _must_pass(
        db_session,
        InventoryMovement(
            item_id=item.id,
            movement_type=MOVEMENT_RESERVA,
            quantity=Decimal("-4"),
            project_id=project.id,
            reversal_of_movement_id=original.id,
        ),
    )
    other = InventoryMovement(item_id=item.id, movement_type=MOVEMENT_CONSUMO, quantity=Decimal("1"), project_id=project.id)
    _must_pass(db_session, other)
    _must_fail(  # uma anulação positiva não compensa nada
        db_session,
        InventoryMovement(
            item_id=item.id,
            movement_type=MOVEMENT_CONSUMO,
            quantity=Decimal("1"),
            project_id=project.id,
            reversal_of_movement_id=other.id,
        ),
    )


def test_movement_type_vocabulary(db_session, item):
    _must_pass(db_session, InventoryMovement(item_id=item.id, movement_type=MOVEMENT_ENTRADA, quantity=Decimal("1")))
    _must_fail(db_session, InventoryMovement(item_id=item.id, movement_type="roubo", quantity=Decimal("1")))


def test_location_type_and_owner_vocabulary(db_session):
    _must_pass(db_session, InventoryLocation(code="CHK-OK", name="ok", location_type="vehicle", owner="verde_milenar"))
    _must_fail(db_session, InventoryLocation(code="CHK-T", name="t", location_type="garagem", owner="solcor"))
    _must_fail(db_session, InventoryLocation(code="CHK-O", name="o", location_type="vehicle", owner="outra"))


def test_min_stock_and_requirement_quantities(db_session, item, project):
    _must_fail(db_session, InventoryItem(sku="CHK-MIN", name="min", min_stock=Decimal("-1")))
    _must_pass(db_session, InventoryItem(sku="CHK-MIN0", name="min", min_stock=Decimal("0")))
    _must_fail(
        db_session,
        ProjectMaterialRequirement(project_id=project.id, item_id=item.id, quantity_required=Decimal("0")),
    )
    _must_pass(
        db_session,
        ProjectMaterialRequirement(project_id=project.id, item_id=item.id, quantity_required=Decimal("3")),
    )


def test_material_request_status_and_line_quantity(db_session, project):
    for status in MATERIAL_REQUEST_STATUSES:
        _must_pass(db_session, MaterialRequest(project_id=project.id, status=status))
    _must_fail(db_session, MaterialRequest(project_id=project.id, status="perdido"))

    request = MaterialRequest(project_id=project.id)
    _must_pass(db_session, request)
    _must_pass(db_session, MaterialRequestItem(request_id=request.id, quantity=Decimal("1")))
    _must_fail(db_session, MaterialRequestItem(request_id=request.id, quantity=Decimal("0")))
    _must_fail(db_session, MaterialRequestItem(request_id=request.id, quantity=Decimal("-2")))


def test_material_request_history_status_vocabulary(db_session, project):
    request = MaterialRequest(project_id=project.id)
    _must_pass(db_session, request)
    now = dt.datetime.now(dt.timezone.utc)
    _must_pass(
        db_session,
        MaterialRequestHistory(request_id=request.id, action="create", from_status=None, to_status="rascunho", changed_at=now),
    )
    _must_fail(
        db_session,
        MaterialRequestHistory(request_id=request.id, action="send", from_status="rascunho", to_status="inventado", changed_at=now),
    )
    _must_fail(
        db_session,
        MaterialRequestHistory(request_id=request.id, action="send", from_status="inventado", to_status="aprovado", changed_at=now),
    )


# --- banco de horas -----------------------------------------------------------


def test_time_bank_vocabularies(db_session, person, user):
    today = dt.date(2026, 1, 5)
    for mode in sorted(ENTRY_MODES):
        _must_pass(
            db_session,
            TimeBankEntry(
                person_id=person.id, work_date=today, balance_seconds=60, calculation_mode=mode, created_by_user_id=user.id
            ),
        )
    _must_fail(
        db_session,
        TimeBankEntry(
            person_id=person.id, work_date=today, balance_seconds=60, calculation_mode="aleatorio", created_by_user_id=user.id
        ),
    )
    for kind in sorted(ADJUSTMENT_KINDS):
        _must_pass(
            db_session,
            TimeBankAdjustment(
                person_id=person.id, effective_date=today, delta_seconds=-60, kind=kind, reason="r", created_by_user_id=user.id
            ),
        )
    _must_fail(
        db_session,
        TimeBankAdjustment(
            person_id=person.id, effective_date=today, delta_seconds=60, kind="bonus", reason="r", created_by_user_id=user.id
        ),
    )


# --- outros vocabulários ---------------------------------------------------------


def test_task_vocabularies(db_session, project):
    _must_pass(db_session, Task(project_id=project.id, title="ok", status="blocked", priority="urgent", category="field"))
    _must_fail(db_session, Task(project_id=project.id, title="s", status="pendente"))
    _must_fail(db_session, Task(project_id=project.id, title="p", priority="altissima"))
    _must_fail(db_session, Task(project_id=project.id, title="c", category="outra"))


def test_every_model_check_constraint_is_enforced_by_the_database(db_session):
    """Todos os CHECKs declarados nos modelos existem na BD de teste."""
    from sqlalchemy import inspect

    inspector = inspect(db_session.get_bind())
    declared = {
        (table.name, constraint.name)
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    }
    assert len(declared) >= 35
    present = {
        (table_name, check["name"])
        for table_name in {name for name, _ in declared}
        for check in inspector.get_check_constraints(table_name)
    }
    assert declared <= present, sorted(declared - present)


# --- email (M8) ---------------------------------------------------------------------


def test_user_email_is_normalized_on_assignment(db_session):
    person = Person(display_name="Pessoa Email", email="x@example.invalid", is_active=True)
    db_session.add(person)
    db_session.flush()
    user = User(person_id=person.id, email="  Nome.Apelido@Example.INVALID ", is_active=True)
    assert user.email == "nome.apelido@example.invalid"
    user.email = " OUTRO@Example.invalid\n"
    assert user.email == "outro@example.invalid"
    assert normalize_email(" A@B.pt ") == "a@b.pt"


def test_emails_that_only_differ_in_case_collide(db_session):
    first = Person(display_name="Pessoa Um", email="colisao@example.invalid", is_active=True)
    second = Person(display_name="Pessoa Dois", email="outra@example.invalid", is_active=True)
    db_session.add_all([first, second])
    db_session.flush()
    _must_pass(db_session, User(person_id=first.id, email="Colisao@Example.invalid", is_active=True))
    _must_fail(db_session, User(person_id=second.id, email=" COLISAO@example.invalid", is_active=True))


def test_database_rejects_mixed_case_duplicate_even_bypassing_the_orm(db_session):
    """O índice funcional protege também escritas que não passam pelo `validates`."""
    first = Person(display_name="Pessoa Raw 1", email="raw1@example.invalid", is_active=True)
    second = Person(display_name="Pessoa Raw 2", email="raw2@example.invalid", is_active=True)
    db_session.add_all([first, second])
    db_session.flush()
    insert = text(
        "INSERT INTO users (id, person_id, email, is_active, created_at, updated_at) "
        "VALUES (:id, :person_id, :email, :active, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )
    with db_session.begin_nested():
        db_session.execute(
            insert, {"id": str(uuid.uuid4()), "person_id": str(first.id), "email": "raw@example.invalid", "active": True}
        )
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(
                insert, {"id": str(uuid.uuid4()), "person_id": str(second.id), "email": "RAW@Example.invalid", "active": True}
            )


def test_dev_header_ignores_case_and_spaces(api_client):
    resp = api_client.get("/me", headers={"X-Dev-User-Email": "  PM.Um.Sintetico@Example.invalid "})
    assert resp.status_code == 200, resp.text
    assert resp.json()["email"] == "pm.um.sintetico@example.invalid"


def test_jit_link_matches_email_claim_with_other_case_and_spaces(db_session, api_client_with_mock_entra_auth):
    from app.models.identity import AuthAuditLog
    from app.security.entra_auth import issue_mock_token

    user = db_session.query(User).filter(User.email == "financeiro.sintetico@example.invalid").one()
    assert user.entra_object_id is None
    token = issue_mock_token(object_id="oid-jit-normalizado", email="  Financeiro.Sintetico@EXAMPLE.invalid ")
    resp = api_client_with_mock_entra_auth.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    db_session.refresh(user)
    assert user.entra_object_id == "oid-jit-normalizado"
    assert db_session.query(AuthAuditLog).filter(AuthAuditLog.user_id == user.id, AuthAuditLog.event == "jit_link_by_email").count() == 1
