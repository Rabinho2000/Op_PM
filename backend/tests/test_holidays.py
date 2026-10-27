from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.identity import Permission, Role, RolePermission
from app.services.holidays import easter_sunday


def test_easter_sunday_uses_gregorian_computus_for_known_years():
    assert easter_sunday(2025) == dt.date(2025, 4, 20)
    assert easter_sunday(2026) == dt.date(2026, 4, 5)
    assert easter_sunday(2027) == dt.date(2027, 3, 28)


ADMIN = "admin.sintetico@example.invalid"
CHEFE = "chefe.sintetico@example.invalid"
COMERCIAL = "comercial.sintetico@example.invalid"


def _headers(email: str) -> dict[str, str]:
    return {"X-Dev-User-Email": email}


def test_holidays_are_listed_by_inclusive_date_interval_and_can_be_deactivated(api_client):
    created = api_client.post(
        "/api/holidays",
        headers=_headers(ADMIN),
        json={"date": "2026-06-10", "name": "Dia de Portugal", "scope": "nacional"},
    )
    assert created.status_code == 201, created.text
    holiday = created.json()
    assert holiday["is_active"] is True

    visible = api_client.get(
        "/api/holidays?from=2026-06-10&to=2026-06-10", headers=_headers(COMERCIAL)
    )
    assert visible.status_code == 200, visible.text
    assert [item["id"] for item in visible.json()] == [holiday["id"]]

    outside = api_client.get(
        "/api/holidays?from=2026-06-11&to=2026-06-12", headers=_headers(COMERCIAL)
    )
    assert outside.status_code == 200, outside.text
    assert outside.json() == []

    deactivated = api_client.delete(f"/api/holidays/{holiday['id']}", headers=_headers(ADMIN))
    assert deactivated.status_code == 200, deactivated.text
    assert deactivated.json()["is_active"] is False
    assert api_client.get(
        "/api/holidays?from=2026-06-10&to=2026-06-10", headers=_headers(COMERCIAL)
    ).json() == []
    inactive = api_client.get(
        "/api/holidays?from=2026-06-10&to=2026-06-10&include_inactive=true",
        headers=_headers(ADMIN),
    )
    assert [item["id"] for item in inactive.json()] == [holiday["id"]]


def test_holiday_writes_require_holiday_manage(api_client):
    created = api_client.post(
        "/api/holidays",
        headers=_headers(ADMIN),
        json={"date": "2026-08-15", "name": "Assunção", "scope": "nacional"},
    )
    assert created.status_code == 201, created.text
    holiday_id = created.json()["id"]

    assert api_client.post(
        "/api/holidays",
        headers=_headers(COMERCIAL),
        json={"date": "2026-06-13", "name": "Feriado municipal", "scope": "municipal"},
    ).status_code == 403
    assert api_client.patch(
        f"/api/holidays/{holiday_id}",
        headers=_headers(COMERCIAL),
        json={"name": "Alterado"},
    ).status_code == 403
    assert api_client.delete(f"/api/holidays/{holiday_id}", headers=_headers(COMERCIAL)).status_code == 403
    assert api_client.patch(
        f"/api/holidays/{holiday_id}",
        headers=_headers(CHEFE),
        json={"name": "Feriado atualizado"},
    ).json()["name"] == "Feriado atualizado"


BACKEND_DIR = Path(__file__).resolve().parents[1]
PREVIOUS_REVISION = "f6b8d0e2a4c5"
HOLIDAY_REVISION = "a7c9e1f3b5d6"


def _run_alembic(database_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.update(
        {
            "APP_ENV": "test",
            "AUTH_ENABLED": "false",
            "DATABASE_URL": f"sqlite:///{database_path}",
            "EXPECTED_DB_DIALECT": "sqlite",
            "LC_ALL": "C.UTF-8",
        }
    )
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _alembic_ok(database_path: Path, *arguments: str) -> None:
    result = _run_alembic(database_path, *arguments)
    assert result.returncode == 0, result.stdout + result.stderr


def test_migration_seeds_portugal_holidays_and_supports_up_down_up(tmp_path: Path):
    database_path = tmp_path / "holidays-migration.db"
    _alembic_ok(database_path, "upgrade", PREVIOUS_REVISION)
    engine = sa.create_engine(f"sqlite:///{database_path}")
    with Session(engine) as session:
        admin = Role(code="administrador", name="Administrador")
        chief = Role(code="chefe_operacoes", name="Chefe de Operações")
        pm = Role(code="project_manager", name="Project Manager")
        permission = Permission(code="holiday.manage", description="permissão pré-existente")
        session.add_all([admin, chief, pm, permission])
        session.flush()
        session.add(RolePermission(role_id=admin.id, permission_id=permission.id))
        session.commit()

    _alembic_ok(database_path, "upgrade", HOLIDAY_REVISION)
    with engine.connect() as connection:
        rows = connection.execute(
            sa.text("SELECT date, name, scope, is_active FROM holidays ORDER BY date, name")
        ).all()
        grants = connection.execute(
            sa.text(
                "SELECT r.code FROM role_permissions rp "
                "JOIN roles r ON r.id = rp.role_id "
                "JOIN permissions p ON p.id = rp.permission_id "
                "WHERE p.code = 'holiday.manage' ORDER BY r.code"
            )
        ).scalars().all()
        assert connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == HOLIDAY_REVISION

    fixed = (
        (1, 1, "Ano Novo"),
        (4, 25, "Dia da Liberdade"),
        (5, 1, "Dia do Trabalhador"),
        (6, 10, "Dia de Portugal, de Camões e das Comunidades Portuguesas"),
        (8, 15, "Assunção de Nossa Senhora"),
        (10, 5, "Implantação da República"),
        (11, 1, "Dia de Todos os Santos"),
        (12, 1, "Restauração da Independência"),
        (12, 8, "Imaculada Conceição"),
        (12, 25, "Natal"),
    )
    expected = set()
    for year in range(2025, 2031):
        expected.update((dt.date(year, month, day).isoformat(), name, "nacional", 1) for month, day, name in fixed)
        easter = easter_sunday(year)
        expected.update(
            {
                ((easter - dt.timedelta(days=2)).isoformat(), "Sexta-feira Santa", "nacional", 1),
                (easter.isoformat(), "Domingo de Páscoa", "nacional", 1),
                ((easter + dt.timedelta(days=60)).isoformat(), "Corpo de Deus", "nacional", 1),
            }
        )
    assert len(rows) == 78
    assert {(date, name, scope, int(active)) for date, name, scope, active in rows} == expected
    assert grants == ["administrador", "chefe_operacoes"]

    _alembic_ok(database_path, "downgrade", PREVIOUS_REVISION)
    with engine.connect() as connection:
        assert not sa.inspect(connection).has_table("holidays")
        assert connection.execute(
            sa.text("SELECT COUNT(*) FROM permissions WHERE code = 'holiday.manage'")
        ).scalar_one() == 1
        assert connection.execute(
            sa.text(
                "SELECT r.code FROM role_permissions rp JOIN roles r ON r.id = rp.role_id "
                "JOIN permissions p ON p.id = rp.permission_id WHERE p.code = 'holiday.manage'"
            )
        ).scalars().all() == ["administrador"]

    _alembic_ok(database_path, "upgrade", HOLIDAY_REVISION)
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT COUNT(*) FROM holidays")).scalar_one() == 78
        assert connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == HOLIDAY_REVISION
    engine.dispose()
