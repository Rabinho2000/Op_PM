from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.config import Settings
from app.models.identity import Role, User, UserRole
from app.models.people import Person
from app.security.catalog import (
    PERMISSIONS,
    ROLE_ADMIN,
    ROLE_CHEFE_OPERACOES,
    ROLE_PERMISSIONS,
    ROLE_PM,
    ROLE_SUPORTE_OPERACOES,
)


def _headers(email: str) -> dict[str, str]:
    return {"X-Dev-User-Email": email}


def test_cost_capability_catalog_is_limited_to_edit_roles():
    assert PERMISSIONS["cable_design.view_costs"] == (
        "Abrir a ferramenta de dimensionamento (inclui preços e catálogos comerciais)"
    )
    assert "cable_design.view_costs" in ROLE_PERMISSIONS[ROLE_ADMIN]
    assert "cable_design.view_costs" in ROLE_PERMISSIONS[ROLE_CHEFE_OPERACOES]
    assert "cable_design.view_costs" in ROLE_PERMISSIONS[ROLE_PM]
    assert "cable_design.view_costs" not in ROLE_PERMISSIONS[ROLE_SUPORTE_OPERACOES]


def _user_for_role(db_session, role_code: str) -> User:
    label = role_code.replace("_", " ")
    email = f"cable-tool-{role_code}@example.invalid"
    person = Person(display_name=f"Pessoa sintética {label}", email=email, is_active=True)
    db_session.add(person)
    db_session.flush()
    user = User(person_id=person.id, email=email, is_active=True)
    db_session.add(user)
    db_session.flush()
    role = db_session.query(Role).filter(Role.code == role_code).one()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    db_session.flush()
    return user


def _settings(tool_file: Path | None) -> Settings:
    return Settings(app_env="test", auth_enabled=False, cable_tool_file=tool_file)


def _manifest_path(tool_file: Path) -> Path:
    return tool_file.with_name(f"{tool_file.stem}.manifest.json")


def test_pm_receives_embedded_tool_with_digest_and_private_headers(
    tmp_path: Path, db_session, make_api_client
):
    user = _user_for_role(db_session, "project_manager")
    tool_file = tmp_path / "cabos-engine.js"
    script = "globalThis.CabosEngine = {};"
    content = script.encode("utf-8")
    tool_file.write_bytes(content)

    with make_api_client(_settings(tool_file)) as client:
        response = client.get("/api/cable-tool", headers=_headers(user.email))

    assert response.status_code == 200, response.text
    assert set(response.json()) == {"engine_version", "sha256", "script"}
    assert response.json() == {
        "engine_version": f"cabos-engine@{hashlib.sha256(content).hexdigest()[:12]}",
        "sha256": hashlib.sha256(content).hexdigest(),
        "script": script,
    }
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_manifest_engine_version_is_used_when_valid(tmp_path: Path, db_session, make_api_client):
    user = _user_for_role(db_session, "project_manager")
    tool_file = tmp_path / "cabos-engine.js"
    tool_file.write_text("globalThis.CabosEngine = {};", encoding="utf-8")
    manifest_path = _manifest_path(tool_file)
    assert manifest_path.name == "cabos-engine.manifest.json"
    manifest_path.write_text(
        json.dumps({"engine_version": "cabos-embed@2026.10"}), encoding="utf-8"
    )

    with make_api_client(_settings(tool_file)) as client:
        response = client.get("/api/cable-tool", headers=_headers(user.email))

    assert response.status_code == 200, response.text
    assert response.json()["engine_version"] == "cabos-embed@2026.10"


@pytest.mark.parametrize(
    "manifest_content",
    [
        None,
        "not-json",
        {"engine_version": 123},
        {"engine_version": ""},
        {"engine_version": "x" * 65},
        {"engine_version": "bad\nversion"},
    ],
)
def test_invalid_or_absent_manifest_uses_digest_fallback(
    tmp_path: Path, db_session, make_api_client, manifest_content
):
    user = _user_for_role(db_session, "project_manager")
    tool_file = tmp_path / "cabos-engine.js"
    content = b"globalThis.CabosEngine = {};"
    tool_file.write_bytes(content)
    manifest_file = _manifest_path(tool_file)
    if manifest_content is None:
        pass
    elif isinstance(manifest_content, str):
        manifest_file.write_text(manifest_content, encoding="utf-8")
    else:
        manifest_file.write_text(json.dumps(manifest_content), encoding="utf-8")

    with make_api_client(_settings(tool_file)) as client:
        response = client.get("/api/cable-tool", headers=_headers(user.email))

    digest = hashlib.sha256(content).hexdigest()
    assert response.status_code == 200, response.text
    assert response.json()["engine_version"] == f"cabos-engine@{digest[:12]}"


def test_support_is_forbidden_before_missing_file_is_touched(
    tmp_path: Path, db_session, make_api_client
):
    user = _user_for_role(db_session, "suporte_operacoes")
    tool_file = tmp_path / "cabos-engine.js"
    tool_file.write_text("globalThis.CabosEngine = {};", encoding="utf-8")
    tool_file.unlink()

    with make_api_client(_settings(tool_file)) as client:
        response = client.get("/api/cable-tool", headers=_headers(user.email))

    assert response.status_code == 403, response.text


@pytest.mark.parametrize(
    "role_code",
    ["comercial", "financeiro", "instalador_colaborador"],
)
def test_non_cost_roles_are_forbidden(tmp_path: Path, db_session, make_api_client, role_code):
    user = _user_for_role(db_session, role_code)
    tool_file = tmp_path / "cabos-engine.js"
    tool_file.write_text("globalThis.CabosEngine = {};", encoding="utf-8")

    with make_api_client(_settings(tool_file)) as client:
        response = client.get("/api/cable-tool", headers=_headers(user.email))

    assert response.status_code == 403, response.text


def test_cable_tool_requires_a_session(tmp_path: Path, make_api_client):
    tool_file = tmp_path / "cabos-engine.js"
    tool_file.write_text("globalThis.CabosEngine = {};", encoding="utf-8")

    with make_api_client(_settings(tool_file)) as client:
        response = client.get("/api/cable-tool")

    assert response.status_code == 401, response.text


def test_missing_setting_returns_sanitised_503(tmp_path: Path, db_session, make_api_client):
    user = _user_for_role(db_session, "project_manager")
    marker = "private-cable-tool-path-marker"

    with make_api_client(_settings(None)) as client:
        response = client.get("/api/cable-tool", headers=_headers(user.email))

    assert response.status_code == 503, response.text
    assert marker not in response.text
    assert "CABLE_TOOL_FILE" not in response.text


def test_missing_file_returns_sanitised_503(tmp_path: Path, db_session, make_api_client):
    user = _user_for_role(db_session, "project_manager")
    tool_file = tmp_path / "private-cable-tool-path-marker.js"

    with make_api_client(_settings(tool_file)) as client:
        response = client.get("/api/cable-tool", headers=_headers(user.email))

    assert response.status_code == 503, response.text
    assert str(tool_file) not in response.text


def test_oversized_file_returns_503(tmp_path: Path, db_session, make_api_client):
    user = _user_for_role(db_session, "project_manager")
    tool_file = tmp_path / "cabos-engine.js"
    tool_file.write_bytes(b"x" * (8 * 1024 * 1024 + 1))

    with make_api_client(_settings(tool_file)) as client:
        response = client.get("/api/cable-tool", headers=_headers(user.email))

    assert response.status_code == 503, response.text


def test_invalid_utf8_returns_503(tmp_path: Path, db_session, make_api_client):
    user = _user_for_role(db_session, "project_manager")
    tool_file = tmp_path / "cabos-engine.js"
    tool_file.write_bytes(b"globalThis.CabosEngine = {};\xff")

    with make_api_client(_settings(tool_file)) as client:
        response = client.get("/api/cable-tool", headers=_headers(user.email))

    assert response.status_code == 503, response.text


def test_changed_file_invalidates_content_cache(tmp_path: Path, db_session, make_api_client):
    user = _user_for_role(db_session, "project_manager")
    tool_file = tmp_path / "cabos-engine.js"
    first = b"globalThis.CabosEngine = {version: 1};"
    second = b"globalThis.CabosEngine = {version: 2};"
    tool_file.write_bytes(first)

    with make_api_client(_settings(tool_file)) as client:
        first_response = client.get("/api/cable-tool", headers=_headers(user.email))
        tool_file.write_bytes(second)
        second_response = client.get("/api/cable-tool", headers=_headers(user.email))

    assert first_response.status_code == 200, first_response.text
    assert second_response.status_code == 200, second_response.text
    assert first_response.json()["script"] == first.decode()
    assert second_response.json()["script"] == second.decode()
    assert second_response.json()["sha256"] == hashlib.sha256(second).hexdigest()


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


def _seed_m3_roles(database_path: Path) -> subprocess.CompletedProcess[str]:
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
    script = """
from app.db import SessionLocal
from app.models.identity import Permission, Role, RolePermission, UserRole

db = SessionLocal()
db.query(UserRole).delete(synchronize_session=False)
db.query(RolePermission).delete(synchronize_session=False)
db.query(Role).delete(synchronize_session=False)
db.commit()
roles = {}
for code in ('administrador', 'chefe_operacoes', 'project_manager', 'suporte_operacoes', 'custom_edit', 'sem_relacao'):
    role = Role(code=code, name=code)
    db.add(role)
    db.flush()
    roles[code] = role
edit = db.query(Permission).filter(Permission.code == 'cable_design.edit').one()
db.add(RolePermission(role_id=roles['custom_edit'].id, permission_id=edit.id))
db.commit()
db.close()
"""
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _clear_m3_roles(database_path: Path) -> subprocess.CompletedProcess[str]:
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
    script = """
from app.db import SessionLocal
from app.models.identity import Role, RolePermission, UserRole

db = SessionLocal()
db.query(UserRole).delete(synchronize_session=False)
db.query(RolePermission).delete(synchronize_session=False)
db.query(Role).delete(synchronize_session=False)
db.commit()
db.close()
"""
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_m3_provisions_cost_capability_for_named_and_edit_roles_only(tmp_path: Path):
    database_path = tmp_path / "cable-tool-m3.db"
    base = _run_alembic(database_path, "upgrade", "c6f8b0d2e4a5")
    assert base.returncode == 0, base.stdout + base.stderr
    seeded = _seed_m3_roles(database_path)
    assert seeded.returncode == 0, seeded.stdout + seeded.stderr

    upgraded = _run_alembic(database_path, "upgrade", "d7a9c1e3f5b6")
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
    with sqlite3.connect(database_path) as connection:
        grants = connection.execute(
            """
            SELECT r.code, p.code
            FROM role_permissions rp
            JOIN roles r ON r.id = rp.role_id
            JOIN permissions p ON p.id = rp.permission_id
            WHERE p.code = 'cable_design.view_costs'
            ORDER BY r.code
            """
        ).fetchall()
        assert grants == [
            ("administrador", "cable_design.view_costs"),
            ("chefe_operacoes", "cable_design.view_costs"),
            ("custom_edit", "cable_design.view_costs"),
            ("project_manager", "cable_design.view_costs"),
        ]
        assert connection.execute(
            "SELECT COUNT(*) FROM cable_tool_costs_provisioning WHERE kind = 'permission'"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM cable_tool_costs_provisioning WHERE kind = 'role_permission'"
        ).fetchone()[0] == 4
        assert connection.execute("SELECT COUNT(*) FROM user_roles").fetchone()[0] == 0

    downgraded = _run_alembic(database_path, "downgrade", "c6f8b0d2e4a5")
    assert downgraded.returncode == 0, downgraded.stdout + downgraded.stderr
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM permissions WHERE code = 'cable_design.view_costs'"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id WHERE p.code = 'cable_design.view_costs'"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id WHERE p.code = 'cable_design.edit'"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'cable_tool_costs_provisioning'"
        ).fetchone() is None

    upgraded_again = _run_alembic(database_path, "upgrade", "d7a9c1e3f5b6")
    assert upgraded_again.returncode == 0, upgraded_again.stdout + upgraded_again.stderr


def test_m3_is_safe_with_no_roles(tmp_path: Path):
    database_path = tmp_path / "cable-tool-m3-empty.db"
    base = _run_alembic(database_path, "upgrade", "c6f8b0d2e4a5")
    assert base.returncode == 0, base.stdout + base.stderr
    cleared = _clear_m3_roles(database_path)
    assert cleared.returncode == 0, cleared.stdout + cleared.stderr

    upgraded = _run_alembic(database_path, "upgrade", "d7a9c1e3f5b6")
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM roles").fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM permissions WHERE code = 'cable_design.view_costs'"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id WHERE p.code = 'cable_design.view_costs'"
        ).fetchone()[0] == 0

    downgraded = _run_alembic(database_path, "downgrade", "c6f8b0d2e4a5")
    assert downgraded.returncode == 0, downgraded.stdout + downgraded.stderr
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM permissions WHERE code = 'cable_design.view_costs'"
        ).fetchone()[0] == 0
