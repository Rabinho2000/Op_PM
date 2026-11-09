"""Provisionamento das permissões `client_report.*` por migração Alembic.

Regressão de produção (2026-10-19): a migração `a7c1e5d9f3b2` criou as tabelas
do relatório semanal ao cliente mas não as permissões; só `seed_dev` as criava,
e o seed não corre numa instância com dados reais. Resultado: «Permissão em
falta: client_report.view.» para todos os papéis, administrador incluído.

O que estes testes garantem (e porquê este âmbito):

* As migrações NÃO conseguem garantir o catálogo inteiro numa BD vazia: os
  papéis (`roles`) só nascem no `seed_dev.seed_catalog` (ou na migração do
  Suporte de Operações) e ~47 permissões «de base» só são criadas por esse
  seed. Por isso a paridade `ROLE_PERMISSIONS` <-> `role_permissions` é
  verificada numa BD «como a de produção» (papéis + catálogo de base já
  semeados) antes e depois da migração, para o par `client_report.*`.
* Para a classe de erro (permissão nova no catálogo sem migração) há um guarda
  estrutural: depois de `alembic upgrade head` numa BD vazia, tudo o que o
  catálogo declara e que NÃO está na tabela `permissions` tem de pertencer ao
  conjunto congelado `SEED_ONLY_PERMISSIONS` (as permissões de base). Qualquer
  permissão nova tem de trazer a sua migração — ou ser acrescentada
  deliberadamente a esse conjunto, o que é uma decisão visível em revisão.
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import app.db
import pytest
import sqlalchemy as sa

from app.security.catalog import PERMISSIONS, ROLE_PERMISSIONS, ROLES

PREVIOUS_HEAD = "d7a9c1e3f5b6"
THIS_REVISION = "e9b1d3f5a7c8"
PROVISIONING_TABLE = "client_report_permission_provisioning"

REPORT_MANAGE = "client_report.manage"
REPORT_VIEW = "client_report.view"
REPORT_CODES = {REPORT_MANAGE, REPORT_VIEW}

# Decisão de produto (task t_d6c66461): quem recebe o quê.
EXPECTED_GRANTS = {
    (REPORT_MANAGE, "administrador"),
    (REPORT_MANAGE, "chefe_operacoes"),
    (REPORT_MANAGE, "project_manager"),
    (REPORT_VIEW, "administrador"),
    (REPORT_VIEW, "comercial"),
    (REPORT_VIEW, "financeiro"),
}

# Permissões do catálogo que nenhuma migração Alembic cria (só o seed de base /
# provisionamento inicial). Congelado em 2026-10-19; NÃO acrescentar uma
# permissão nova aqui para «fazer passar» o guarda — cria antes uma migração
# idempotente como `e9b1d3f5a7c8` (ou `b5e7a9c1d3f4`).
SEED_ONLY_PERMISSIONS = frozenset(
    {
        "project.view_all",
        "project.view_own",
        "project.edit_all",
        "project.edit_own_progress",
        "project.plan_work",
        "installer.manage",
        "project.change_status",
        "cost.view",
        "cost.edit_estimate",
        "cost.edit_real",
        "inventory.view",
        "inventory.edit",
        "material_request.create",
        "material_request.approve",
        "material_request.adjudicate",
        "calendar.propose",
        "calendar.approve_send",
        "ai.use_tools",
        "ai.approve_actions",
        "admin.manage_users",
        "migration.view",
        "migration.resolve",
        "migration.link_arbitrary_project",
        "task.view_all",
        "task.edit_all",
        "absence.view_all",
        "absence.manage_all",
        "inventory.manage_central",
        "inventory.allocate_project",
        "inventory.consume_project",
        "inventory.release_project",
        "inventory.deliver_project",
        "inventory.collect_project",
        "inventory.manage_requirements",
        "project.view_communication_data",
        "project.edit_communication_data",
        "map.view",
        "supplier.manage",
        "pickup_point.manage",
        "project_issue.view",
        "project_issue.manage",
        "calendar.manage",
        "performance.view_all",
        "performance.view_own",
        "performance.manage_goals",
        "import.notes",
        "import.licensing",
    }
)

BACKEND_DIR = Path(__file__).resolve().parents[1]


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
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _alembic_ok(database_path: Path, *arguments: str) -> None:
    result = _run_alembic(database_path, *arguments)
    assert result.returncode == 0, result.stdout + result.stderr


def _engine(database_path: Path) -> sa.Engine:
    return sa.create_engine(f"sqlite:///{database_path}")


def _tables():
    permissions = sa.table(
        "permissions",
        sa.column("id", app.db.GUID()),
        sa.column("code", sa.String()),
        sa.column("description", sa.String()),
    )
    roles = sa.table(
        "roles",
        sa.column("id", app.db.GUID()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.String()),
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("id", app.db.GUID()),
        sa.column("role_id", app.db.GUID()),
        sa.column("permission_id", app.db.GUID()),
    )
    return permissions, roles, role_permissions


def _seed_production_like(engine: sa.Engine, *, skip_report: bool = True) -> None:
    """Papéis + catálogo tal como `seed_catalog` os deixou, mas SEM `client_report.*`.

    Reproduz o estado da BD live medido a 2026-10-19 (78 de 80 permissões).
    """
    permissions, roles, role_permissions = _tables()
    with engine.begin() as connection:
        role_ids = {}
        for code, name in ROLES.items():
            # Migrações anteriores (ex.: Suporte de Operações) já criam alguns papéis.
            existing_role = connection.execute(
                sa.select(roles.c.id).where(roles.c.code == code)
            ).first()
            if existing_role is not None:
                role_ids[code] = existing_role[0]
                continue
            role_ids[code] = uuid.uuid4()
            connection.execute(
                roles.insert().values(id=role_ids[code], code=code, name=name, description="")
            )
        permission_ids = {}
        for code, description in PERMISSIONS.items():
            if skip_report and code in REPORT_CODES:
                continue
            existing = connection.execute(
                sa.select(permissions.c.id).where(permissions.c.code == code)
            ).first()
            if existing is not None:
                permission_ids[code] = existing[0]
                continue
            permission_ids[code] = uuid.uuid4()
            connection.execute(
                permissions.insert().values(
                    id=permission_ids[code], code=code, description=description
                )
            )
        for role_code, codes in ROLE_PERMISSIONS.items():
            for code in codes:
                if code not in permission_ids:
                    continue
                already = connection.execute(
                    sa.select(role_permissions.c.id).where(
                        role_permissions.c.role_id == role_ids[role_code],
                        role_permissions.c.permission_id == permission_ids[code],
                    )
                ).first()
                if already is None:
                    connection.execute(
                        role_permissions.insert().values(
                            id=uuid.uuid4(),
                            role_id=role_ids[role_code],
                            permission_id=permission_ids[code],
                        )
                    )


def _report_grants(engine: sa.Engine) -> set[tuple[str, str]]:
    with engine.connect() as connection:
        rows = connection.execute(
            sa.text(
                "SELECT p.code, r.code FROM role_permissions rp "
                "JOIN permissions p ON p.id = rp.permission_id "
                "JOIN roles r ON r.id = rp.role_id "
                "WHERE p.code LIKE 'client_report.%'"
            )
        ).all()
    return {(code, role) for code, role in rows}


def _report_permissions(engine: sa.Engine) -> dict[str, str]:
    with engine.connect() as connection:
        rows = connection.execute(
            sa.text("SELECT code, description FROM permissions WHERE code LIKE 'client_report.%'")
        ).all()
    return {code: description for code, description in rows}


def _count(engine: sa.Engine, table: str) -> int:
    with engine.connect() as connection:
        return connection.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one()


def _version(engine: sa.Engine) -> str:
    with engine.connect() as connection:
        return connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()


def test_catalog_matches_the_decided_grants():
    """Se o catálogo mudar, esta migração deixa de refletir `ROLE_PERMISSIONS`."""
    catalog_grants = {
        (code, role)
        for role, codes in ROLE_PERMISSIONS.items()
        for code in codes
        if code in REPORT_CODES
    }
    assert catalog_grants == EXPECTED_GRANTS
    assert set(PERMISSIONS) >= REPORT_CODES


def test_upgrade_provisions_report_permissions_on_production_like_db(tmp_path: Path):
    database_path = tmp_path / "report-permissions.db"
    _alembic_ok(database_path, "upgrade", PREVIOUS_HEAD)
    engine = _engine(database_path)
    _seed_production_like(engine)
    assert _report_permissions(engine) == {}
    permissions_before = _count(engine, "permissions")
    grants_before = _count(engine, "role_permissions")

    _alembic_ok(database_path, "upgrade", THIS_REVISION)

    assert _version(engine) == THIS_REVISION
    assert _report_permissions(engine) == {code: PERMISSIONS[code] for code in REPORT_CODES}
    assert _report_grants(engine) == EXPECTED_GRANTS
    # Só se acrescentou o que era devido: 2 permissões, 6 atribuições.
    assert _count(engine, "permissions") == permissions_before + 2
    assert _count(engine, "role_permissions") == grants_before + 6
    # Cada linha criada fica registada para o downgrade.
    with engine.connect() as connection:
        kinds = [
            kind
            for (kind,) in connection.execute(
                sa.text(f"SELECT kind FROM {PROVISIONING_TABLE}")
            ).all()
        ]
    assert sorted(kinds) == ["permission"] * 2 + ["role_permission"] * 6

    # Administrador (o utilizador do relatório) ficou com as duas permissões.
    admin_codes = {code for code, role in _report_grants(engine) if role == "administrador"}
    assert admin_codes == REPORT_CODES


def test_upgrade_is_idempotent_and_downgrade_removes_only_what_it_provisioned(tmp_path: Path):
    database_path = tmp_path / "report-permissions-idempotent.db"
    _alembic_ok(database_path, "upgrade", PREVIOUS_HEAD)
    engine = _engine(database_path)
    # Estado pré-existente criado à mão por um operador: `client_report.view`
    # já existe (descrição própria) e o administrador já a tem.
    _seed_production_like(engine)
    permissions, roles, role_permissions = _tables()
    custom_description = "Descrição criada manualmente por um operador"
    with engine.begin() as connection:
        view_id = uuid.uuid4()
        connection.execute(
            permissions.insert().values(
                id=view_id, code=REPORT_VIEW, description=custom_description
            )
        )
        admin_id = connection.execute(
            sa.select(roles.c.id).where(roles.c.code == "administrador")
        ).scalar_one()
        connection.execute(
            role_permissions.insert().values(
                id=uuid.uuid4(), role_id=admin_id, permission_id=view_id
            )
        )

    _alembic_ok(database_path, "upgrade", THIS_REVISION)

    # Sem duplicados e sem sobrescrever a linha existente.
    assert _report_permissions(engine)[REPORT_VIEW] == custom_description
    assert _report_grants(engine) == EXPECTED_GRANTS
    assert _count(engine, "permissions") == len(PERMISSIONS) - 2 + 2
    with engine.connect() as connection:
        admin_view_rows = connection.execute(
            sa.text(
                "SELECT COUNT(*) FROM role_permissions rp "
                "JOIN permissions p ON p.id = rp.permission_id "
                "JOIN roles r ON r.id = rp.role_id "
                "WHERE p.code = :code AND r.code = 'administrador'"
            ),
            {"code": REPORT_VIEW},
        ).scalar_one()
    assert admin_view_rows == 1

    # Um operador concede depois `client_report.manage` a outro papel: esse
    # grant não é da migração e tem de sobreviver ao downgrade.
    with engine.begin() as connection:
        manage_id = connection.execute(
            sa.select(permissions.c.id).where(permissions.c.code == REPORT_MANAGE)
        ).scalar_one()
        suporte_id = connection.execute(
            sa.select(roles.c.id).where(roles.c.code == "suporte_operacoes")
        ).scalar_one()
        connection.execute(
            role_permissions.insert().values(
                id=uuid.uuid4(), role_id=suporte_id, permission_id=manage_id
            )
        )

    _alembic_ok(database_path, "downgrade", PREVIOUS_HEAD)

    assert _version(engine) == PREVIOUS_HEAD
    # `client_report.view` pré-existia: fica, com a descrição e o grant do admin.
    assert _report_permissions(engine)[REPORT_VIEW] == custom_description
    assert (REPORT_VIEW, "administrador") in _report_grants(engine)
    assert {role for code, role in _report_grants(engine) if code == REPORT_VIEW} == {
        "administrador"
    }
    # `client_report.manage` foi criada pela migração mas tem um grant de
    # operador: a permissão fica, só os grants provisionados desaparecem.
    assert _report_grants(engine) >= {(REPORT_VIEW, "administrador")}
    assert {role for code, role in _report_grants(engine) if code == REPORT_MANAGE} == {
        "suporte_operacoes"
    }
    with engine.connect() as connection:
        assert (
            connection.execute(
                sa.text(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=:name"
                ),
                {"name": PROVISIONING_TABLE},
            ).first()
            is None
        )

    # Upgrade → pode voltar a correr sem erro (estado intermédio coerente).
    _alembic_ok(database_path, "upgrade", THIS_REVISION)
    assert _version(engine) == THIS_REVISION
    assert (REPORT_VIEW, "administrador") in _report_grants(engine)


def test_downgrade_removes_permissions_it_created_when_unused(tmp_path: Path):
    database_path = tmp_path / "report-permissions-clean-downgrade.db"
    _alembic_ok(database_path, "upgrade", PREVIOUS_HEAD)
    engine = _engine(database_path)
    _seed_production_like(engine)
    permissions_before = _count(engine, "permissions")
    grants_before = _count(engine, "role_permissions")

    _alembic_ok(database_path, "upgrade", THIS_REVISION)
    _alembic_ok(database_path, "downgrade", PREVIOUS_HEAD)

    assert _report_permissions(engine) == {}
    assert _report_grants(engine) == set()
    assert _count(engine, "permissions") == permissions_before
    assert _count(engine, "role_permissions") == grants_before


def test_upgrade_on_empty_database_creates_permissions_without_roles(tmp_path: Path):
    """BD nova: ainda não há papéis; a migração cria as permissões e não falha."""
    database_path = tmp_path / "report-permissions-empty.db"
    _alembic_ok(database_path, "upgrade", THIS_REVISION)
    engine = _engine(database_path)

    assert _report_permissions(engine) == {code: PERMISSIONS[code] for code in REPORT_CODES}
    assert _report_grants(engine) == set()


def test_every_catalog_permission_is_provisioned_by_migrations_or_baseline(tmp_path: Path):
    """Guarda estrutural: permissão nova no catálogo exige migração."""
    database_path = tmp_path / "catalog-parity.db"
    _alembic_ok(database_path, "upgrade", "head")
    engine = _engine(database_path)
    with engine.connect() as connection:
        in_database = {
            code for (code,) in connection.execute(sa.text("SELECT code FROM permissions")).all()
        }

    unprovisioned = set(PERMISSIONS) - in_database
    assert unprovisioned == set(SEED_ONLY_PERMISSIONS), (
        "Permissões do catálogo sem migração (acrescenta uma migração idempotente "
        f"como e9b1d3f5a7c8): {sorted(unprovisioned - SEED_ONLY_PERMISSIONS)}; "
        "permissões do conjunto de base que entretanto passaram a ter migração "
        f"(remove-as do conjunto): {sorted(SEED_ONLY_PERMISSIONS - unprovisioned)}"
    )
    # E nenhuma permissão provisionada por migração ficou fora do catálogo.
    assert in_database - set(PERMISSIONS) == set(), sorted(in_database - set(PERMISSIONS))


@pytest.mark.parametrize("code", sorted(REPORT_CODES))
def test_report_permissions_are_in_the_catalog_with_descriptions(code: str):
    assert PERMISSIONS[code].strip()
