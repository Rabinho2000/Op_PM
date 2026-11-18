from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from app.models.identity import Role, User, UserRole
from app.models.people import Person


MANAGER_EMAIL = "operacoes@example.invalid"


def _headers(email: str) -> dict[str, str]:
    return {"X-Dev-User-Email": email}


def _user(db_session, *, name: str, email: str, role_code: str | None = "project_manager") -> User:
    person = Person(display_name=name, email=email, is_active=True)
    db_session.add(person)
    db_session.flush()
    user = User(person_id=person.id, email=email, is_active=True)
    db_session.add(user)
    db_session.flush()
    if role_code is not None:
        role = db_session.query(Role).filter(Role.code == role_code).one()
        db_session.add(UserRole(user_id=user.id, role_id=role.id))
        db_session.flush()
    return user


def _request(api_client, email: str, body: object = "Preciso de ajuda", **extra):
    payload = {"body": body, **extra}
    return api_client.post("/api/requests", headers=_headers(email), json=payload)


def test_author_can_create_and_read_a_request(db_session, api_client):
    _user(db_session, name="PM A", email="pm.a@example.invalid")

    created = _request(api_client, "pm.a@example.invalid", "  Pedido de ajuda  ", page_path="/projects")

    assert created.status_code == 201, created.text
    created_body = created.json()
    request_id = created_body["id"]
    assert created_body["status"] == "open"
    assert created_body["page_path"] == "/projects"
    assert created_body["author_name"] == "PM A"
    assert created_body["messages"][0]["body"] == "Pedido de ajuda"
    assert created_body["messages"][0]["author_name"] == "PM A"
    assert created_body["messages"][0]["is_mine"] is True
    assert "email" not in created.text

    listed = api_client.get("/api/requests", headers=_headers("pm.a@example.invalid"))
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == request_id
    assert listed.json()["items"][0]["message_count"] == 1

    read = api_client.get(f"/api/requests/{request_id}", headers=_headers("pm.a@example.invalid"))
    assert read.status_code == 200, read.text
    assert read.json()["id"] == request_id
    assert read.json()["messages"][0]["is_mine"] is True
    assert "email" not in read.text


def test_other_user_gets_404_and_mine_list_is_scoped(db_session, api_client):
    _user(db_session, name="PM A", email="pm.a@example.invalid")
    _user(db_session, name="PM B", email="pm.b@example.invalid")
    created = _request(api_client, "pm.a@example.invalid")
    request_id = created.json()["id"]

    hidden = api_client.get(f"/api/requests/{request_id}", headers=_headers("pm.b@example.invalid"))
    assert hidden.status_code == 404

    listed = api_client.get("/api/requests?scope=mine", headers=_headers("pm.b@example.invalid"))
    assert listed.status_code == 200, listed.text
    assert listed.json() == {"items": [], "total": 0}


def test_all_scope_requires_manage_and_manager_sees_all(db_session, api_client):
    _user(db_session, name="PM A", email="pm.a@example.invalid")
    _user(db_session, name="PM B", email="pm.b@example.invalid")
    _user(db_session, name="Operações", email=MANAGER_EMAIL, role_code="chefe_operacoes")
    _request(api_client, "pm.a@example.invalid", "Pedido A")
    _request(api_client, "pm.b@example.invalid", "Pedido B")

    forbidden = api_client.get("/api/requests?scope=all", headers=_headers("pm.a@example.invalid"))
    assert forbidden.status_code == 403

    all_requests = api_client.get("/api/requests?scope=all", headers=_headers(MANAGER_EMAIL))
    assert all_requests.status_code == 200, all_requests.text
    assert all_requests.json()["total"] == 2
    assert {item["author_name"] for item in all_requests.json()["items"]} == {"PM A", "PM B"}


def test_manager_can_reply_resolve_and_reopen_and_author_reply_reopens(db_session, api_client):
    _user(db_session, name="PM A", email="pm.a@example.invalid")
    _user(db_session, name="Operações", email=MANAGER_EMAIL, role_code="chefe_operacoes")
    request_id = _request(api_client, "pm.a@example.invalid").json()["id"]

    staff_message = api_client.post(
        f"/api/requests/{request_id}/messages",
        headers=_headers(MANAGER_EMAIL),
        json={"body": "Estamos a verificar."},
    )
    assert staff_message.status_code == 201, staff_message.text
    assert staff_message.json()["is_staff_reply"] is True

    resolved = api_client.post(
        f"/api/requests/{request_id}/status",
        headers=_headers(MANAGER_EMAIL),
        json={"status": "resolved"},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "resolved"

    reopened_by_manager = api_client.post(
        f"/api/requests/{request_id}/status",
        headers=_headers(MANAGER_EMAIL),
        json={"status": "open"},
    )
    assert reopened_by_manager.status_code == 200, reopened_by_manager.text
    assert reopened_by_manager.json()["status"] == "open"

    api_client.post(
        f"/api/requests/{request_id}/status",
        headers=_headers(MANAGER_EMAIL),
        json={"status": "resolved"},
    )
    author_message = api_client.post(
        f"/api/requests/{request_id}/messages",
        headers=_headers("pm.a@example.invalid"),
        json={"body": "Ainda preciso de ajuda."},
    )
    assert author_message.status_code == 201, author_message.text
    assert author_message.json()["is_staff_reply"] is False

    detail = api_client.get(f"/api/requests/{request_id}", headers=_headers("pm.a@example.invalid"))
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "open"
    assert detail.json()["messages"][-1]["body"] == "Ainda preciso de ajuda."


def test_non_manager_cannot_change_status(db_session, api_client):
    _user(db_session, name="PM A", email="pm.a@example.invalid")
    request_id = _request(api_client, "pm.a@example.invalid").json()["id"]

    response = api_client.post(
        f"/api/requests/{request_id}/status",
        headers=_headers("pm.a@example.invalid"),
        json={"status": "resolved"},
    )
    assert response.status_code == 403


def test_create_requires_requests_create(db_session, api_client):
    _user(db_session, name="PM A", email="pm.a@example.invalid", role_code=None)

    response = _request(api_client, "pm.a@example.invalid")

    assert response.status_code == 403


def test_author_has_at_most_twenty_open_requests(db_session, api_client):
    _user(db_session, name="PM A", email="pm.a@example.invalid")
    for index in range(20):
        response = _request(api_client, "pm.a@example.invalid", f"Pedido {index}")
        assert response.status_code == 201, response.text

    rejected = _request(api_client, "pm.a@example.invalid", "Pedido 21")

    assert rejected.status_code == 409


def test_body_validation_rejects_empty_long_and_non_string_values(db_session, api_client):
    _user(db_session, name="PM A", email="pm.a@example.invalid")
    for value in ("", "   ", "x" * 2001, 123, [], {}):
        response = _request(api_client, "pm.a@example.invalid", value)
        assert response.status_code == 422, (value, response.text)


def test_invalid_page_paths_are_stored_as_none(db_session, api_client):
    _user(db_session, name="PM A", email="pm.a@example.invalid")

    for path in ("projects", "/projects?tab=all", "/projects#details", "/" + "x" * 256, 123, []):
        response = _request(api_client, "pm.a@example.invalid", page_path=path)
        assert response.status_code == 201, response.text
        assert response.json()["page_path"] is None


def test_summary_is_scoped_for_author_and_global_for_manager(db_session, api_client):
    _user(db_session, name="PM A", email="pm.a@example.invalid")
    _user(db_session, name="PM B", email="pm.b@example.invalid")
    _user(db_session, name="Operações", email=MANAGER_EMAIL, role_code="chefe_operacoes")
    _request(api_client, "pm.a@example.invalid", "A")
    _request(api_client, "pm.b@example.invalid", "B")

    mine = api_client.get("/api/requests/summary", headers=_headers("pm.a@example.invalid"))
    assert mine.status_code == 200, mine.text
    assert mine.json() == {"open": 1}

    all_open = api_client.get("/api/requests/summary", headers=_headers(MANAGER_EMAIL))
    assert all_open.status_code == 200, all_open.text
    assert all_open.json() == {"open": 2}


def test_list_is_ordered_by_last_activity(db_session, api_client):
    _user(db_session, name="PM A", email="pm.a@example.invalid")
    first = _request(api_client, "pm.a@example.invalid", "Primeiro").json()["id"]
    second = _request(api_client, "pm.a@example.invalid", "Segundo").json()["id"]

    response = api_client.post(
        f"/api/requests/{first}/messages",
        headers=_headers("pm.a@example.invalid"),
        json={"body": "Atividade mais recente."},
    )
    assert response.status_code == 201, response.text

    listed = api_client.get("/api/requests?scope=mine", headers=_headers("pm.a@example.invalid"))
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()["items"]] == [first, second]


def test_non_uuid_request_id_is_validation_error_not_server_error(api_client):
    response = api_client.get(
        "/api/requests/not-a-uuid",
        headers=_headers("pm.um.sintetico@example.invalid"),
    )

    assert response.status_code == 422


def _run_alembic(database_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.update(
        {
            "APP_ENV": "test",
            "AUTH_ENABLED": "false",
            "DATABASE_URL": f"sqlite:///{database_path}",
            "EXPECTED_DB_DIALECT": "sqlite",
        }
    )
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_m2_migration_up_down_up_creates_expected_tables_and_indexes(tmp_path: Path):
    database_path = tmp_path / "user-requests-migration.db"
    base = _run_alembic(database_path, "upgrade", "b5e7a9c1d3f4")
    assert base.returncode == 0, base.stdout + base.stderr

    upgraded = _run_alembic(database_path, "upgrade", "c6f8b0d2e4a5")
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {"user_requests", "user_request_messages"} <= tables
        request_indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(user_requests)")
        }
        message_indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(user_request_messages)")
        }
        assert "ix_user_requests_status_updated_at" in request_indexes
        assert "ix_user_request_messages_request_id_created_at" in message_indexes
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "c6f8b0d2e4a5"

    downgraded = _run_alembic(database_path, "downgrade", "b5e7a9c1d3f4")
    assert downgraded.returncode == 0, downgraded.stdout + downgraded.stderr
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'user_requests'"
        ).fetchone() is None
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'user_request_messages'"
        ).fetchone() is None

    upgraded_again = _run_alembic(database_path, "upgrade", "c6f8b0d2e4a5")
    assert upgraded_again.returncode == 0, upgraded_again.stdout + upgraded_again.stderr
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "c6f8b0d2e4a5"