from __future__ import annotations

import datetime as dt
import pytest
from sqlalchemy import event

from app.models.identity import Permission, Role, RolePermission, User, UserRole
from app.models.installer import Installer
from app.models.installer_access import InstallerAccessMembership
from app.models.people import Person
from app.models.project import Project, ProjectHistory
from app.models.project_payments import PAYMENT_MILESTONES, ProjectPaymentMilestone

BASE_URL = "/api/projects"
DEMO_PROJECT = "Instalação Sintética de Demonstração"


def _headers(email: str) -> dict[str, str]:
    return {"X-Dev-User-Email": email}


def _project(db_session) -> Project:
    return db_session.query(Project).filter(Project.name == DEMO_PROJECT).one()


def _make_user(db_session, *, suffix: str, role_code: str | None) -> User:
    email = f"{suffix}.payments.sintetico@example.invalid"
    person = Person(display_name=f"Pessoa sintética {suffix}", email=email, is_active=True)
    db_session.add(person)
    db_session.flush()
    user = User(person_id=person.id, email=email, is_active=True)
    db_session.add(user)
    db_session.flush()
    if role_code:
        role = db_session.query(Role).filter(Role.code == role_code).one()
        db_session.add(UserRole(user_id=user.id, role_id=role.id))
        db_session.flush()
    return user


def _make_permission_user(db_session, *, suffix: str, permission_codes: tuple[str, ...]) -> User:
    user = _make_user(db_session, suffix=suffix, role_code=None)
    role = Role(code=f"{suffix}_payments_test", name=f"Papel sintético {suffix}", description="")
    db_session.add(role)
    db_session.flush()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    for code in permission_codes:
        permission = db_session.query(Permission).filter_by(code=code).one()
        db_session.add(RolePermission(role_id=role.id, permission_id=permission.id))
    db_session.flush()
    return user


@pytest.mark.parametrize(
    ("account", "get_status", "put_status"),
    [
        ("admin.sintetico@example.invalid", 200, 200),
        ("chefe.sintetico@example.invalid", 200, 403),
        ("financeiro.sintetico@example.invalid", 200, 200),
        ("pm.um.sintetico@example.invalid", 200, 403),
        ("pm-other", 404, 404),
        ("comercial.sintetico@example.invalid", 403, 403),
        ("consulta", 403, 404),
        ("suporte", 403, 404),
        ("instalador", 403, 403),
    ],
)
def test_payment_route_role_matrix(api_client, db_session, account, get_status, put_status):
    project = _project(db_session)
    if account == "pm-other":
        account = _make_user(db_session, suffix="pm-other", role_code="project_manager").email
    elif account == "consulta":
        account = _make_user(db_session, suffix="consulta", role_code=None).email
    elif account == "suporte":
        account = _make_user(db_session, suffix="suporte", role_code="suporte_operacoes").email
    elif account == "instalador":
        user = _make_user(db_session, suffix="instalador", role_code="instalador_colaborador")
        installer = Installer(name="Instalador sintético de teste", name_key="instalador sintetico de teste")
        db_session.add(installer)
        db_session.flush()
        # A equipa do projeto demo pertence ao instalador original; a FK
        # composta (installer_id, installer_team_id) recusa trocar só o
        # instalador (no SQLite sem PRAGMA foreign_keys passava sem erro).
        project.installer_team_id = None
        project.installer_id = installer.id
        db_session.add(InstallerAccessMembership(person_id=user.person_id, installer_id=installer.id))
        db_session.flush()
        account = user.email

    response = api_client.get(f"{BASE_URL}/{project.id}/payments", headers=_headers(account))
    assert response.status_code == get_status
    update = api_client.put(
        f"{BASE_URL}/{project.id}/payments/adjudicacao",
        headers=_headers(account),
        json={"received": True},
    )
    assert update.status_code == put_status


def test_payment_read_returns_four_ordered_milestones_without_identity_ids(api_client, db_session):
    project = _project(db_session)
    response = api_client.get(
        f"{BASE_URL}/{project.id}/payments",
        headers=_headers("financeiro.sintetico@example.invalid"),
    )
    assert response.status_code == 200
    body = response.json()
    assert [item["milestone"] for item in body] == list(PAYMENT_MILESTONES)
    assert all(item["received"] is False for item in body)
    assert all(item["marked_at"] is None and item["marked_by"] is None for item in body)
    assert all(set(item) == {"milestone", "label", "received", "marked_at", "marked_by"} for item in body)


def test_payment_put_is_idempotent_and_history_is_written_only_for_real_changes(api_client, db_session):
    project = _project(db_session)
    headers = _headers("financeiro.sintetico@example.invalid")
    history_query = db_session.query(ProjectHistory).filter(
        ProjectHistory.project_id == project.id,
        ProjectHistory.field_name == "payment.adjudicacao",
    )

    no_op_false = api_client.put(
        f"{BASE_URL}/{project.id}/payments/adjudicacao", headers=headers, json={"received": False}
    )
    assert no_op_false.status_code == 200
    assert db_session.query(ProjectPaymentMilestone).filter_by(project_id=project.id).count() == 0
    assert history_query.count() == 0

    first = api_client.put(
        f"{BASE_URL}/{project.id}/payments/adjudicacao", headers=headers, json={"received": True}
    )
    assert first.status_code == 200
    first_marked_at = first.json()["marked_at"]
    assert first.json()["marked_by"] == "Financeiro Sintético"
    assert history_query.count() == 1
    event_row = history_query.one()
    assert (event_row.old_value, event_row.new_value, event_row.changed_by_person_id) == (
        "false",
        "true",
        db_session.query(User).filter_by(email=headers["X-Dev-User-Email"]).one().person_id,
    )

    repeated = api_client.put(
        f"{BASE_URL}/{project.id}/payments/adjudicacao", headers=headers, json={"received": True}
    )
    assert repeated.status_code == 200
    assert repeated.json()["marked_at"] == first_marked_at
    assert history_query.count() == 1

    cleared = api_client.put(
        f"{BASE_URL}/{project.id}/payments/adjudicacao", headers=headers, json={"received": False}
    )
    assert cleared.status_code == 200
    assert cleared.json()["received"] is False
    assert history_query.count() == 2
    assert [(row.old_value, row.new_value) for row in history_query.order_by(ProjectHistory.changed_at)] == [
        ("false", "true"),
        ("true", "false"),
    ]


def test_project_history_hides_payment_events_without_payment_view(api_client, db_session):
    project = _project(db_session)
    update = api_client.put(
        f"{BASE_URL}/{project.id}/payments/adjudicacao",
        headers=_headers("financeiro.sintetico@example.invalid"),
        json={"received": True},
    )
    assert update.status_code == 200, update.text

    commercial_history = api_client.get(
        f"{BASE_URL}/{project.id}/history", headers=_headers("comercial.sintetico@example.invalid")
    )
    assert commercial_history.status_code == 200, commercial_history.text
    assert all(not item["field_name"].startswith("payment.") for item in commercial_history.json())

    chief_history = api_client.get(
        f"{BASE_URL}/{project.id}/history", headers=_headers("chefe.sintetico@example.invalid")
    )
    assert chief_history.status_code == 200, chief_history.text
    assert any(item["field_name"] == "payment.adjudicacao" for item in chief_history.json())


def test_payment_put_requires_payment_view_to_return_audit_identity(api_client, db_session):
    project = _project(db_session)
    editor = _make_permission_user(
        db_session,
        suffix="edit-without-view",
        permission_codes=("project.view_all", "payment.edit"),
    )
    response = api_client.put(
        f"{BASE_URL}/{project.id}/payments/adjudicacao",
        headers=_headers(editor.email),
        json={"received": True},
    )
    assert response.status_code == 403
    assert db_session.query(ProjectPaymentMilestone).filter_by(project_id=project.id).count() == 0


def test_invalid_milestone_and_invisible_or_deleted_projects(api_client, db_session):
    project = _project(db_session)
    finance = _headers("financeiro.sintetico@example.invalid")
    invalid = api_client.put(
        f"{BASE_URL}/{project.id}/payments/not-a-milestone", headers=finance, json={"received": True}
    )
    assert invalid.status_code == 422

    scoped_pm = _make_user(db_session, suffix="scoped-pm", role_code="project_manager")
    role = db_session.query(Role).filter_by(code="project_manager").one()
    edit_permission = db_session.query(Permission).filter_by(code="payment.edit").one()
    db_session.add(RolePermission(role_id=role.id, permission_id=edit_permission.id))
    db_session.flush()
    scoped_headers = _headers(scoped_pm.email)
    assert api_client.get(f"{BASE_URL}/{project.id}/payments", headers=scoped_headers).status_code == 404
    assert api_client.put(
        f"{BASE_URL}/{project.id}/payments/adjudicacao", headers=scoped_headers, json={"received": True}
    ).status_code == 404

    project.deleted_at = dt.datetime.now(dt.timezone.utc)
    db_session.flush()
    assert api_client.get(f"{BASE_URL}/{project.id}/payments", headers=finance).status_code == 404
    assert api_client.put(
        f"{BASE_URL}/{project.id}/payments/adjudicacao", headers=finance, json={"received": True}
    ).status_code == 404


def test_project_list_payment_summary_is_one_query_and_hidden_without_permission(api_client, db_session):
    project = _project(db_session)
    db_session.add(
        ProjectPaymentMilestone(
            project_id=project.id,
            milestone="fim_obra",
            received=True,
            marked_at=dt.datetime.now(dt.timezone.utc),
        )
    )
    db_session.flush()
    connection = db_session.connection()
    payment_selects: list[str] = []

    def count_payment_query(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT") and "project_payment_milestones" in statement.lower():
            payment_selects.append(statement)

    event.listen(connection, "before_cursor_execute", count_payment_query)
    try:
        finance_response = api_client.get(
            f"{BASE_URL}?is_active=true", headers=_headers("financeiro.sintetico@example.invalid")
        )
    finally:
        event.remove(connection, "before_cursor_execute", count_payment_query)
    assert finance_response.status_code == 200
    assert len(payment_selects) == 1
    row = next(item for item in finance_response.json() if item["id"] == str(project.id))
    assert row["payments"] == {
        "adjudicacao": False,
        "entrada_obra": False,
        "fim_obra": True,
        "certificado_final": False,
    }
    assert row["can_edit_payments"] is True

    commercial_response = api_client.get(
        f"{BASE_URL}?is_active=true", headers=_headers("comercial.sintetico@example.invalid")
    )
    assert commercial_response.status_code == 200
    commercial_row = next(item for item in commercial_response.json() if item["id"] == str(project.id))
    assert commercial_row["payments"] is None
    assert commercial_row["can_edit_payments"] is False
