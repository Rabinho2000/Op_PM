from __future__ import annotations

import datetime as dt
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from app.models.identity import Permission, RolePermission, User, UserRole
from app.models.people import Person
from app.models.time_bank import TimeBankAudit, TimeBankEntry
from app.main import app
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext


ADMIN = {"X-Dev-User-Email": "admin.sintetico@example.invalid"}
CHEFE = {"X-Dev-User-Email": "chefe.sintetico@example.invalid"}
PM = {"X-Dev-User-Email": "pm.um.sintetico@example.invalid"}


def _lisbon_today() -> dt.date:
    return dt.datetime.now(ZoneInfo("Europe/Lisbon")).date()


def _previous_monday() -> dt.date:
    today = _lisbon_today()
    return today - dt.timedelta(days=today.weekday() + 7)


def _person(db_session, name: str) -> Person:
    return db_session.query(Person).filter(Person.display_name == name).one()


def _my_payload(work_date: dt.date, *, start: int = 540, end: int = 1110, lunch: bool = False) -> dict:
    return {
        "work_date": work_date.isoformat(),
        "start_minute": start,
        "end_minute": end,
        "lunch_taken": lunch,
    }


def _post_my_entry(api_client, work_date: dt.date, **kwargs):
    return api_client.post("/api/time-bank/my-entries", headers=PM, json=_my_payload(work_date, **kwargs))


def test_self_service_requires_permission(db_session, api_client):
    pm_user = db_session.query(User).filter(User.email == PM["X-Dev-User-Email"]).one()
    permission = db_session.query(Permission).filter(Permission.code == "time_bank.log_own").one()
    role_ids = [membership.role_id for membership in db_session.query(UserRole).filter(UserRole.user_id == pm_user.id)]
    db_session.query(RolePermission).filter(
        RolePermission.role_id.in_(role_ids),
        RolePermission.permission_id == permission.id,
    ).delete(synchronize_session=False)
    db_session.flush()

    response = api_client.post(
        "/api/time-bank/my-entries/preview",
        headers=PM,
        json=_my_payload(_previous_monday()),
    )

    assert response.status_code == 403


def test_self_service_requires_person_in_context(db_session, api_client):
    pm_user = db_session.query(User).filter(User.email == PM["X-Dev-User-Email"]).one()
    ctx = AuthContext(
        user=pm_user,
        person_id=None,
        role_codes=frozenset({"project_manager"}),
        permission_codes=frozenset({"time_bank.log_own"}),
    )
    app.dependency_overrides[get_auth_context] = lambda: ctx
    try:
        response = api_client.post(
            "/api/time-bank/my-entries/preview",
            headers=PM,
            json=_my_payload(_previous_monday()),
        )
    finally:
        app.dependency_overrides.pop(get_auth_context, None)

    assert response.status_code == 403


def test_self_service_body_cannot_choose_another_person(db_session, api_client):
    pm = _person(db_session, "PM Sintético Um")
    response = api_client.post(
        "/api/time-bank/my-entries",
        headers=PM,
        json={**_my_payload(_previous_monday()), "person_id": str(pm.id)},
    )

    assert response.status_code == 422


def test_self_service_uses_standard_friday_and_saturday_calculations(db_session, api_client):
    del db_session
    monday = _previous_monday()
    cases = (
        (monday, {"start": 540, "end": 1110, "lunch": False}, 3600, "standard"),
        (monday + dt.timedelta(days=4), {"start": 540, "end": 840, "lunch": False}, 3600, "standard"),
        (monday + dt.timedelta(days=5), {"start": 540, "end": 780, "lunch": False}, 21600, "saturday"),
    )

    for work_date, values, expected, mode in cases:
        response = _post_my_entry(api_client, work_date, **values)
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["balance_seconds"] == expected
        assert body["calculated_seconds"] == expected
        assert body["calculation_mode"] == mode
        assert body["provenance"] == {"source": "self_service"}


def test_self_service_rejects_sunday_future_and_non_positive_ranges(db_session, api_client):
    del db_session
    monday = _previous_monday()
    sunday = api_client.post(
        "/api/time-bank/my-entries/preview",
        headers=PM,
        json=_my_payload(monday + dt.timedelta(days=6)),
    )
    assert sunday.status_code == 422
    assert "Domingos e feriados" in sunday.json()["detail"]

    future_date = _lisbon_today() + dt.timedelta(days=1)
    future = api_client.post(
        "/api/time-bank/my-entries/preview",
        headers=PM,
        json=_my_payload(future_date),
    )
    assert future.status_code == 422
    assert future_date.isoformat() in future.json()["detail"] or _lisbon_today().isoformat() in future.json()["detail"]

    invalid_range = api_client.post(
        "/api/time-bank/my-entries/preview",
        headers=PM,
        json=_my_payload(monday, start=840, end=840),
    )
    assert invalid_range.status_code == 422
    assert "saída" in invalid_range.json()["detail"]


def test_preview_does_not_write_and_reports_duplicate(db_session, api_client):
    monday = _previous_monday()
    created = _post_my_entry(api_client, monday)
    assert created.status_code == 201, created.text
    before_entries = db_session.query(TimeBankEntry).count()
    before_audits = db_session.query(TimeBankAudit).count()

    preview = api_client.post(
        "/api/time-bank/my-entries/preview",
        headers=PM,
        json=_my_payload(monday),
    )

    assert preview.status_code == 200, preview.text
    assert preview.json()["duplicate"] is True
    assert preview.json()["balance_seconds"] == 3600
    assert db_session.query(TimeBankEntry).count() == before_entries
    assert db_session.query(TimeBankAudit).count() == before_audits


def test_duplicate_is_rejected_then_can_be_relaunched_after_self_reversal(db_session, api_client):
    monday = _previous_monday()
    first = _post_my_entry(api_client, monday)
    assert first.status_code == 201, first.text
    entry_id = first.json()["id"]

    duplicate = _post_my_entry(api_client, monday)
    assert duplicate.status_code == 409
    assert "Anule-o primeiro" in duplicate.json()["detail"]

    reversed_response = api_client.post(
        f"/api/time-bank/my-entries/{entry_id}/reverse",
        headers=PM,
        json={"reason": "Correção sintética."},
    )
    assert reversed_response.status_code == 200, reversed_response.text
    assert reversed_response.json()["balance_seconds"] == -3600

    relaunched = _post_my_entry(api_client, monday)
    assert relaunched.status_code == 201, relaunched.text
    assert db_session.query(TimeBankEntry).count() == 3


def test_self_reversal_returns_balance_to_previous_value_and_audits(db_session, api_client):
    pm = _person(db_session, "PM Sintético Um")
    monday = _previous_monday()
    created = _post_my_entry(api_client, monday)
    assert created.status_code == 201, created.text

    before = api_client.get(
        f"/api/time-bank/summary?person_id={pm.id}&year={monday.year}",
        headers=PM,
    )
    assert before.status_code == 200, before.text
    assert before.json()["people"][0]["balance_seconds"] == 3600

    reversed_response = api_client.post(
        f"/api/time-bank/my-entries/{created.json()['id']}/reverse",
        headers=PM,
        json={"reason": "Anulação sintética."},
    )
    assert reversed_response.status_code == 200, reversed_response.text
    assert reversed_response.json()["provenance"]["source"] == "reversal"
    assert reversed_response.json()["reversal_of_id"] == created.json()["id"]

    after = api_client.get(
        f"/api/time-bank/summary?person_id={pm.id}&year={monday.year}",
        headers=PM,
    )
    assert after.status_code == 200, after.text
    assert after.json()["people"][0]["balance_seconds"] == 0
    assert db_session.query(TimeBankAudit).filter(TimeBankAudit.action == "entry.reverse_self").count() == 1


def test_self_reversal_rejects_management_imported_and_other_person_entries(db_session, api_client):
    pm = _person(db_session, "PM Sintético Um")
    other = _person(db_session, "Chefe Sintético")
    monday = _previous_monday()

    managed = api_client.post(
        "/api/time-bank/entries",
        headers=ADMIN,
        json={
            "person_id": str(pm.id),
            **_my_payload(monday + dt.timedelta(days=1)),
            "calculation_mode": "standard",
        },
    )
    assert managed.status_code == 201, managed.text
    rejected_managed = api_client.post(
        f"/api/time-bank/my-entries/{managed.json()['id']}/reverse",
        headers=PM,
        json={"reason": "Não permitido."},
    )
    assert rejected_managed.status_code == 403

    pm_user = db_session.query(User).filter(User.email == PM["X-Dev-User-Email"]).one()
    imported = TimeBankEntry(
        person_id=pm.id,
        work_date=monday + dt.timedelta(days=2),
        start_minute=540,
        end_minute=840,
        lunch_taken=False,
        balance_seconds=3600,
        calculated_seconds=3600,
        calculation_mode="imported",
        reason="Importação sintética.",
        needs_review=False,
        review_flags={},
        provenance={"source": "import"},
        created_by_user_id=pm_user.id,
        occurred_at=dt.datetime.now(dt.timezone.utc),
    )
    db_session.add(imported)
    db_session.flush()
    rejected_import = api_client.post(
        f"/api/time-bank/my-entries/{imported.id}/reverse",
        headers=PM,
        json={"reason": "Não permitido."},
    )
    assert rejected_import.status_code == 403

    other_entry = api_client.post(
        "/api/time-bank/entries",
        headers=ADMIN,
        json={
            "person_id": str(other.id),
            **_my_payload(monday + dt.timedelta(days=3)),
            "calculation_mode": "standard",
        },
    )
    assert other_entry.status_code == 201, other_entry.text
    rejected_other = api_client.post(
        f"/api/time-bank/my-entries/{other_entry.json()['id']}/reverse",
        headers=PM,
        json={"reason": "Não permitido."},
    )
    assert rejected_other.status_code == 404


def test_self_reversal_twice_is_a_clear_conflict_without_double_credit(db_session, api_client):
    monday = _previous_monday()
    created = _post_my_entry(api_client, monday)
    assert created.status_code == 201, created.text
    entry_id = created.json()["id"]

    first = api_client.post(
        f"/api/time-bank/my-entries/{entry_id}/reverse",
        headers=PM,
        json={"reason": "Primeira anulação."},
    )
    assert first.status_code == 200, first.text
    count_after_first = db_session.query(TimeBankEntry).count()

    second = api_client.post(
        f"/api/time-bank/my-entries/{entry_id}/reverse",
        headers=PM,
        json={"reason": "Segunda anulação."},
    )
    assert second.status_code == 409
    assert "compensação" in second.json()["detail"]
    assert db_session.query(TimeBankEntry).count() == count_after_first


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


def _seed_m1_roles(database_path: Path) -> subprocess.CompletedProcess[str]:
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
from app.models.identity import Permission, Role, RolePermission

db = SessionLocal()
roles = {}
for code in ('administrador', 'chefe_operacoes', 'project_manager', 'comercial', 'financeiro', 'suporte_operacoes', 'instalador_colaborador', 'consulta', 'sem_relacao'):
    role = db.query(Role).filter(Role.code == code).one_or_none()
    if role is None:
        role = Role(code=code, name=code)
        db.add(role)
    roles[code] = role
db.flush()
view_own = db.query(Permission).filter(Permission.code == 'time_bank.view_own').one()
db.add(RolePermission(role_id=roles['consulta'].id, permission_id=view_own.id))
preexisting = Permission(code='requests.create', description='pré-existente')
db.add(preexisting)
db.flush()
db.add(RolePermission(role_id=roles['consulta'].id, permission_id=preexisting.id))
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


def _clear_m1_roles(database_path: Path) -> subprocess.CompletedProcess[str]:
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


def test_m1_provisions_expected_grants_and_downgrade_only_removes_owned_rows(tmp_path: Path):
    database_path = tmp_path / "time-bank-m1.db"
    base = _run_alembic(database_path, "upgrade", "a1c3e5f7b9d0")
    assert base.returncode == 0, base.stdout + base.stderr
    seeded = _seed_m1_roles(database_path)
    assert seeded.returncode == 0, seeded.stdout + seeded.stderr

    upgraded = _run_alembic(database_path, "upgrade", "b5e7a9c1d3f4")
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
    with sqlite3.connect(database_path) as connection:
        grants = connection.execute(
            """
            SELECT r.code, p.code
            FROM role_permissions rp
            JOIN roles r ON r.id = rp.role_id
            JOIN permissions p ON p.id = rp.permission_id
            ORDER BY r.code, p.code
            """
        ).fetchall()
        grant_map = {}
        for role_code, permission_code in grants:
            grant_map.setdefault(role_code, set()).add(permission_code)
        assert {
            role for role, permission in grants if permission == "requests.create"
        } == {
            "administrador", "chefe_operacoes", "project_manager", "comercial",
            "financeiro", "suporte_operacoes", "instalador_colaborador", "consulta", "sem_relacao",
        }
        assert {
            role for role, permission in grants if permission == "requests.manage"
        } == {"administrador", "chefe_operacoes"}
        assert {
            role for role, permission in grants if permission == "time_bank.log_own"
        } == {
            "project_manager", "comercial", "financeiro",
            "suporte_operacoes", "instalador_colaborador", "consulta",
        }
        assert connection.execute(
            "SELECT COUNT(*) FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id WHERE p.code = 'requests.create'"
        ).fetchone()[0] == 9
        assert connection.execute(
            "SELECT COUNT(*) FROM pedidos_jornada_permission_provisioning"
        ).fetchone()[0] > 0

    downgraded = _run_alembic(database_path, "downgrade", "a1c3e5f7b9d0")
    assert downgraded.returncode == 0, downgraded.stdout + downgraded.stderr
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM permissions WHERE code IN ('time_bank.log_own', 'requests.manage')"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM permissions WHERE code = 'requests.create'"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id WHERE p.code = 'requests.create'"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'pedidos_jornada_permission_provisioning'"
        ).fetchone()[0] == 0

    upgraded_again = _run_alembic(database_path, "upgrade", "b5e7a9c1d3f4")
    assert upgraded_again.returncode == 0, upgraded_again.stdout + upgraded_again.stderr


def test_m1_is_safe_when_no_roles_exist(tmp_path: Path):
    database_path = tmp_path / "time-bank-m1-empty.db"
    base = _run_alembic(database_path, "upgrade", "a1c3e5f7b9d0")
    assert base.returncode == 0, base.stdout + base.stderr
    cleared = _clear_m1_roles(database_path)
    assert cleared.returncode == 0, cleared.stdout + cleared.stderr

    upgraded = _run_alembic(database_path, "upgrade", "b5e7a9c1d3f4")
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM roles").fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM permissions WHERE code IN ('time_bank.log_own', 'requests.create', 'requests.manage')"
        ).fetchone()[0] == 3
        assert connection.execute(
            "SELECT COUNT(*) FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id WHERE p.code IN ('time_bank.log_own', 'requests.create', 'requests.manage')"
        ).fetchone()[0] == 0

    downgraded = _run_alembic(database_path, "downgrade", "a1c3e5f7b9d0")
    assert downgraded.returncode == 0, downgraded.stdout + downgraded.stderr
