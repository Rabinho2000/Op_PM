from __future__ import annotations

import datetime as dt
import uuid

import pytest

from app.models.identity import Role, User, UserRole
from app.models.installer import Installer
from app.models.installer_access import InstallerAccessMembership
from app.models.people import Person
from app.models.project import (
    Project,
    ProjectExternalId,
    ProjectHistory,
    ProjectStageProgress,
    ProjectSubtaskProgress,
)
from app.models.task import Task
from app.security.catalog import ROLE_INSTALLER_COLLABORATOR


ADMIN = "chefe.sintetico@example.invalid"
PM = "pm.um.sintetico@example.invalid"
CONSULTA = "comercial.sintetico@example.invalid"


def _headers(email: str = ADMIN) -> dict[str, str]:
    return {"X-Dev-User-Email": email}


def _installer_user(db_session) -> str:
    installer = db_session.query(Installer).filter(Installer.name == "Instalador Sintético Alfa").one()
    email = f"manual-create-installer-{uuid.uuid4()}@example.invalid"
    person = Person(display_name="Colaborador Sintético de Teste", email=email, is_active=True)
    db_session.add(person)
    db_session.flush()
    user = User(person_id=person.id, email=email, is_active=True)
    db_session.add(user)
    db_session.flush()
    role = db_session.query(Role).filter(Role.code == ROLE_INSTALLER_COLLABORATOR).one()
    db_session.add_all(
        [
            UserRole(user_id=user.id, role_id=role.id),
            InstallerAccessMembership(person_id=person.id, installer_id=installer.id, is_active=True),
        ]
    )
    db_session.flush()
    return email


def _payload(**overrides):
    return {"name": f"Projeto Manual Sintético {uuid.uuid4()}", **overrides}


def _admin_context(db_session):
    from app.security.permissions import load_auth_context

    actor = db_session.query(User).filter(User.email == ADMIN).one()
    return load_auth_context(db_session, actor)


def test_project_create_schema_strips_name_forbids_internal_fields_and_checks_ranges():
    from fastapi import HTTPException
    from pydantic import ValidationError

    from app.schemas.projects import ProjectCreate

    body = ProjectCreate(name="  Projeto Sintético  ")
    assert body.name == "Projeto Sintético"
    assert body.lifecycle_status == "on_hold_cliente"
    for invalid in (
        {"name": " "},
        {"name": "Válido", "is_active": False},
        {"name": "Válido", "deleted_at": None},
        {"name": "Válido", "entered_at": "2026-01-01T00:00:00Z"},
        {"name": "Válido", "lat": 90.1},
        {"name": "Válido", "lon": -180.1},
        {"name": "Válido", "power_kwp": -1},
        {"name": "Válido", "lifecycle_status": "estado-inexistente"},
    ):
        with pytest.raises(ValidationError):
            ProjectCreate(**invalid)

    with pytest.raises(HTTPException) as exc_info:
        ProjectCreate(name="Válido", power_kwp=float("inf"))
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Valor numérico inválido."


@pytest.mark.parametrize(
    ("field", "max_length"),
    [
        ("name", 512),
        ("client_name", 256),
        ("client_contact", 256),
        ("client_email", 320),
        ("address", 512),
        ("power_raw", 64),
        ("role", 128),
        ("award_year_raw", 16),
        ("lifecycle_status", 32),
        ("notes", 20_000),
        ("equipment_notes", 20_000),
        ("injection_notes", 20_000),
        ("om_notes", 20_000),
        ("commercial_assumptions", 20_000),
    ],
)
def test_project_create_schema_enforces_column_text_lengths(field, max_length):
    from pydantic import ValidationError

    from app.schemas.projects import ProjectCreate

    body = {"name": "x" * (max_length + 1)} if field == "name" else {"name": "Válido", field: "x" * (max_length + 1)}
    with pytest.raises(ValidationError):
        ProjectCreate(**body)


def test_create_project_initializes_project_and_audits_filled_fields(db_session, api_client):
    requested_at = dt.datetime.now(dt.timezone.utc)
    body = _payload(
        name="  4812_Fase Um  ",
        client_name="Cliente de Teste",
        client_contact="Contacto Sintético",
        client_email="cliente@example.invalid",
        address="Morada Sintética",
        lat=38.7,
        lon=-9.1,
        power_kwp=12.5,
        power_raw="12,5 kWp",
        start_date="2026-03-12",
        lifecycle_status="preparacao",
        notes="Nota sintética",
        role="instalador",
        equipment_notes="Equipamento de teste",
    )
    response = api_client.post("/api/projects", json=body, headers=_headers())

    assert response.status_code == 201, response.text
    created = response.json()
    assert created["name"] == "4812_Fase Um"
    assert created["client_name"] == "Cliente de Teste"
    assert created["lifecycle_status"] == "preparacao"
    entered_at = dt.datetime.fromisoformat(created["entered_at"])
    if entered_at.tzinfo is None:
        entered_at = entered_at.replace(tzinfo=dt.timezone.utc)
    assert requested_at <= entered_at <= dt.datetime.now(dt.timezone.utc)
    assert entered_at.date() != dt.date(2026, 3, 12)
    assert created["work_dates_estimated"] is True

    project = db_session.get(Project, uuid.UUID(created["id"]))
    assert project is not None
    assert project.is_active is True
    assert project.deleted_at is None
    assert project.current_phase_id is None  # igual à promoção; o processo começa sem progresso registado
    assert db_session.query(ProjectStageProgress).filter_by(project_id=project.id).count() == 0
    assert db_session.query(ProjectSubtaskProgress).filter_by(project_id=project.id).count() == 0
    assert db_session.query(Task).filter_by(project_id=project.id).count() == 0
    assert db_session.query(ProjectExternalId).filter_by(project_id=project.id).count() == 0

    history = db_session.query(ProjectHistory).filter_by(project_id=project.id).all()
    by_field = {entry.field_name: entry for entry in history}
    assert {"name", "client_name", "client_contact", "client_email", "address", "lat", "lon", "power_kwp", "power_raw", "start_date", "lifecycle_status", "notes", "role", "equipment_notes", "project_created"} <= set(by_field)
    assert all(entry.source == "ui" for entry in history)
    assert all(entry.note == "Criação manual via API." for entry in history)
    assert by_field["project_created"].old_value is None
    assert by_field["project_created"].new_value == str(project.id)


@pytest.mark.parametrize("name", ["", "   ", "\t\n"])
def test_create_rejects_empty_name(name, api_client):
    response = api_client.post("/api/projects", json={"name": name}, headers=_headers())
    assert response.status_code == 422


def test_create_rejects_normalized_duplicate_name(db_session, api_client):
    existing = Project(name="4813  Fase Um", is_active=True)
    db_session.add(existing)
    db_session.flush()

    response = api_client.post("/api/projects", json={"name": " 4813 fase   UM "}, headers=_headers())
    assert response.status_code == 409


def test_create_name_normalization_matches_shared_text_normalizer(db_session, api_client):
    db_session.add(Project(name="Instalação Solar", is_active=True))
    db_session.flush()

    response = api_client.post("/api/projects", json={"name": "  INSTALACAO   SOLAR "}, headers=_headers())
    assert response.status_code == 409


def test_create_service_name_normalization_matches_shared_text_normalizer(db_session):
    from app.schemas.projects import ProjectCreate
    from app.services.projects import DuplicateProjectName, create_project

    db_session.add(Project(name="Instalação Solar", is_active=True))
    db_session.flush()

    with pytest.raises(DuplicateProjectName):
        create_project(
            db_session,
            body=ProjectCreate(name="  INSTALACAO   SOLAR "),
            ctx=_admin_context(db_session),
        )


def test_create_allows_repeated_numeric_prefix_when_name_differs(db_session, api_client):
    db_session.add(Project(name="4814_Fase A", is_active=True))
    db_session.flush()

    response = api_client.post("/api/projects", json={"name": "4814_Fase B"}, headers=_headers())
    assert response.status_code == 201, response.text


def test_check_name_returns_normalized_name_and_prefix_candidates(db_session, api_client):
    same_name = Project(name="4815  Fase A", is_active=True)
    same_prefix = Project(name="4815_Fase B", is_active=True)
    db_session.add_all([same_name, same_prefix])
    db_session.flush()

    response = api_client.get("/api/projects/check-name", params={"name": " 4815 fase   a "}, headers=_headers())

    assert response.status_code == 200, response.text
    assert {(row["id"], row["name"]) for row in response.json()} == {
        (str(same_name.id), same_name.name),
        (str(same_prefix.id), same_prefix.name),
    }


@pytest.mark.parametrize("pm_person_id", ["00000000-0000-0000-0000-000000000000", "inactive"])
def test_create_rejects_missing_or_inactive_pm(pm_person_id, db_session, api_client):
    selected_pm = pm_person_id
    if pm_person_id == "inactive":
        inactive = Person(display_name="PM Inativo Sintético", is_active=False)
        db_session.add(inactive)
        db_session.flush()
        selected_pm = str(inactive.id)
    response = api_client.post("/api/projects", json=_payload(pm_person_id=selected_pm), headers=_headers())
    assert response.status_code == 422


def test_create_rejects_active_person_without_project_manager_role(db_session, api_client):
    person = Person(display_name="Pessoa Ativa sem Papel de PM", is_active=True)
    db_session.add(person)
    db_session.flush()

    response = api_client.post("/api/projects", json=_payload(pm_person_id=str(person.id)), headers=_headers())
    assert response.status_code == 422


@pytest.mark.parametrize("email", [PM, CONSULTA])
def test_create_and_check_name_require_edit_all(email, api_client):
    create_response = api_client.post("/api/projects", json=_payload(), headers=_headers(email))
    check_response = api_client.get("/api/projects/check-name", params={"name": "Teste"}, headers=_headers(email))
    assert create_response.status_code == 403
    assert check_response.status_code == 403
    assert "project.edit_all" not in create_response.text + check_response.text


def test_eligible_managers_requires_auth_and_edit_all(api_client):
    assert api_client.get("/api/projects/eligible-managers").status_code == 401
    assert api_client.get("/api/projects/eligible-managers", headers=_headers(PM)).status_code == 403


def test_eligible_managers_returns_only_active_account_project_managers_without_email(db_session, api_client):
    pm = db_session.query(Person).filter(Person.email == PM).one()
    inactive_user_person = Person(display_name="PM com conta inativa", is_active=True)
    no_user_person = Person(display_name="PM sem conta", is_active=True)
    db_session.add_all([inactive_user_person, no_user_person])
    db_session.flush()
    user = User(person_id=inactive_user_person.id, email=f"inactive-{uuid.uuid4()}@example.invalid", is_active=False)
    db_session.add(user)
    db_session.flush()
    role = db_session.query(Role).filter(Role.code == "project_manager").one()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.flush()

    response = api_client.get("/api/projects/eligible-managers", headers=_headers())
    assert response.status_code == 200, response.text
    rows = response.json()
    assert {row["id"] for row in rows} == {str(pm.id)}
    assert rows[0]["display_name"] == pm.display_name
    assert set(rows[0]) == {"id", "display_name"}


def test_installer_readonly_cannot_query_eligible_managers(db_session, api_client, monkeypatch):
    from app.api import routes_projects

    email = _installer_user(db_session)
    monkeypatch.setattr(
        routes_projects,
        "eligible_project_managers",
        lambda db: (_ for _ in ()).throw(AssertionError("query not blocked")),
    )
    response = api_client.get("/api/projects/eligible-managers", headers=_headers(email))
    assert response.status_code == 403
    assert "installer.read_only" not in response.text


def test_installer_readonly_cannot_create_or_check_name(db_session, api_client):
    email = _installer_user(db_session)
    create_response = api_client.post("/api/projects", json=_payload(), headers=_headers(email))
    check_response = api_client.get("/api/projects/check-name", params={"name": "Teste"}, headers=_headers(email))
    assert create_response.status_code == 403
    assert check_response.status_code == 403
    assert "installer.read_only" not in create_response.text + check_response.text


@pytest.mark.parametrize(
    "body",
    [
        {"name": "Projeto Coordenada", "lat": 91},
        {"name": "Projeto Coordenada", "lon": -181},
        {"name": "Projeto Potência", "power_kwp": -0.01},
    ],
)
def test_create_rejects_invalid_coordinates_and_power(body, api_client):
    response = api_client.post("/api/projects", json=body, headers=_headers())
    assert response.status_code == 422


@pytest.mark.parametrize("number", ["Infinity", "-Infinity", "NaN", "1e999"])
def test_create_rejects_infinity_sent_as_raw_json(number, api_client):
    response = api_client.post(
        "/api/projects",
        content=f'{{"name":"Projeto Potência","power_kwp": {number}}}',
        headers={**_headers(), "Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "Valor numérico inválido."}


@pytest.mark.parametrize(
    ("field", "max_length"),
    [
        ("name", 512),
        ("client_name", 256),
        ("client_contact", 256),
        ("client_email", 320),
        ("address", 512),
        ("power_raw", 64),
        ("role", 128),
        ("award_year_raw", 16),
        ("lifecycle_status", 32),
        ("notes", 20_000),
        ("equipment_notes", 20_000),
        ("injection_notes", 20_000),
        ("om_notes", 20_000),
        ("commercial_assumptions", 20_000),
    ],
)
def test_create_rejects_text_longer_than_model_column(field, max_length, api_client):
    body = {"name": "x" * (max_length + 1)} if field == "name" else {"name": "Projeto Limites", field: "x" * (max_length + 1)}
    response = api_client.post("/api/projects", json=body, headers=_headers())
    assert response.status_code == 422, response.text


def test_created_project_is_in_list_and_visible_detail_for_assigned_pm(db_session, api_client):
    pm = db_session.query(Person).filter(Person.email == PM).one()
    response = api_client.post("/api/projects", json=_payload(pm_person_id=str(pm.id)), headers=_headers())
    assert response.status_code == 201, response.text
    project_id = response.json()["id"]

    listed = api_client.get("/api/projects", headers=_headers(PM))
    detail = api_client.get(f"/api/projects/{project_id}", headers=_headers(PM))
    assert listed.status_code == 200
    assert project_id in {item["id"] for item in listed.json()}
    assert detail.status_code == 200
    assert detail.json()["id"] == project_id


def test_create_rolls_back_project_and_history_when_audit_fails_midway(db_session, monkeypatch):
    from app.schemas.projects import ProjectCreate
    from app.security.permissions import load_auth_context
    from app.services import projects as project_service

    ctx = _admin_context(db_session)
    before_projects = db_session.query(Project).count()
    before_history = db_session.query(ProjectHistory).count()
    original = project_service.record_project_change
    calls = 0

    def fail_on_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("falha sintética durante a auditoria")
        return original(*args, **kwargs)

    monkeypatch.setattr(project_service, "record_project_change", fail_on_second)
    with pytest.raises(RuntimeError):
        project_service.create_project(
            db_session,
            body=ProjectCreate(name=f"Projeto Atomicidade {uuid.uuid4()}", client_name="Cliente Sintético"),
            ctx=ctx,
        )

    assert db_session.query(Project).count() == before_projects
    assert db_session.query(ProjectHistory).count() == before_history


def test_http_create_rolls_back_when_read_dto_construction_fails(db_session, api_client, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api import routes_projects

    before_projects = db_session.query(Project).count()
    before_history = db_session.query(ProjectHistory).count()
    monkeypatch.setattr(
        routes_projects,
        "_to_read",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("dto failure")),
    )
    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/projects", json=_payload(), headers=_headers()
    )
    assert response.status_code == 500
    assert db_session.query(Project).count() == before_projects
    assert db_session.query(ProjectHistory).count() == before_history


def test_http_create_rolls_back_when_commit_fails(db_session, api_client, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    before_projects = db_session.query(Project).count()
    before_history = db_session.query(ProjectHistory).count()
    monkeypatch.setattr(db_session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit failure")))
    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/projects", json=_payload(), headers=_headers()
    )
    assert response.status_code == 500
    assert db_session.query(Project).count() == before_projects
    assert db_session.query(ProjectHistory).count() == before_history


def test_http_create_returns_dto_without_select_after_commit(db_session, api_client, monkeypatch):
    from sqlalchemy.sql import Select

    original_commit = db_session.commit
    original_execute = db_session.execute
    after_commit = False

    def guarded_commit():
        nonlocal after_commit
        original_commit()
        after_commit = True

    def guarded_execute(statement, *args, **kwargs):
        if after_commit and isinstance(statement, Select):
            raise AssertionError("SELECT executado após commit da criação")
        return original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(db_session, "commit", guarded_commit)
    monkeypatch.setattr(db_session, "execute", guarded_execute)
    response = api_client.post("/api/projects", json=_payload(), headers=_headers())
    assert response.status_code == 201, response.text
    created_id = uuid.UUID(response.json()["id"])
    assert after_commit is True
    monkeypatch.setattr(db_session, "execute", original_execute)
    assert db_session.get(Project, created_id) is not None


def test_create_service_uses_manual_defaults_and_checks_pm_before_writing(db_session):
    from app.schemas.projects import ProjectCreate
    from app.services.projects import create_project

    pm = db_session.query(Person).filter(Person.email == PM).one()
    requested_at = dt.datetime.now(dt.timezone.utc)
    project = create_project(
        db_session,
        body=ProjectCreate(name="Projeto Serviço Sintético", start_date="2026-04-15", pm_person_id=pm.id),
        ctx=_admin_context(db_session),
    )
    assert project.lifecycle_status == "on_hold_cliente"
    assert project.entered_at is not None
    entered_at = project.entered_at
    if entered_at.tzinfo is None:
        entered_at = entered_at.replace(tzinfo=dt.timezone.utc)
    assert requested_at <= entered_at <= dt.datetime.now(dt.timezone.utc)
    assert entered_at.date() != dt.date(2026, 4, 15)
    assert project.work_dates_estimated is True
    assert db_session.query(ProjectExternalId).filter_by(project_id=project.id).count() == 0
    assert db_session.query(Task).filter_by(project_id=project.id).count() == 0

    before = db_session.query(Project).count()
    inactive_pm = db_session.query(Person).filter(Person.is_active.is_(False)).first()
    with pytest.raises(ValueError, match="PM selecionado"):
        create_project(
            db_session,
            body=ProjectCreate(name="Projeto Sem PM Ativo", pm_person_id=inactive_pm.id),
            ctx=_admin_context(db_session),
        )
    assert db_session.query(Project).count() == before

    active_non_pm = Person(display_name="Pessoa Ativa sem Papel de PM", is_active=True)
    db_session.add(active_non_pm)
    db_session.flush()
    with pytest.raises(ValueError, match="papel de PM"):
        create_project(
            db_session,
            body=ProjectCreate(name="Projeto sem Papel PM", pm_person_id=active_non_pm.id),
            ctx=_admin_context(db_session),
        )


def test_create_service_rejects_duplicate_but_allows_and_reports_shared_prefix(db_session):
    from app.schemas.projects import ProjectCreate
    from app.security.permissions import PermissionDenied, load_auth_context
    from app.services.projects import DuplicateProjectName, check_project_name, create_project

    db_session.add_all([Project(name="4820_Fase A"), Project(name="4820_Fase B")])
    db_session.flush()
    ctx = _admin_context(db_session)

    with pytest.raises(DuplicateProjectName):
        create_project(db_session, body=ProjectCreate(name=" 4820_fase   a "), ctx=ctx)
    created = create_project(db_session, body=ProjectCreate(name="4820_Fase C"), ctx=ctx)
    assert created.name == "4820_Fase C"
    assert {project.name for project in check_project_name(db_session, name="4820 Fase D", ctx=ctx)} == {
        "4820_Fase A", "4820_Fase B", "4820_Fase C"
    }

    pm = db_session.query(User).filter(User.email == PM).one()
    pm_ctx = load_auth_context(db_session, pm)
    with pytest.raises(PermissionDenied):
        check_project_name(db_session, name="4820_Fase D", ctx=pm_ctx)
    with pytest.raises(PermissionDenied):
        create_project(db_session, body=ProjectCreate(name="4820_Fase D"), ctx=pm_ctx)
