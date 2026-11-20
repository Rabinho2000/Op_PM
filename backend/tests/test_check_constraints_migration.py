"""Migração `d2f4a6c8e0b1` (CHECKs de vocabulários/quantidades + email único
sem distinção de maiúsculas), em SQLite:

- aborta, sem alterar nada, quando há dados que violariam as novas regras, e
  a mensagem diz tabela, coluna, contagem e valores distintos (nunca emails);
- com dados válidos aplica-se, normaliza os emails e o downgrade desfaz;
- o esquema migrado declara os mesmos CHECKs que os modelos (o Alembic não
  compara CHECKs, por isso `test_alembic_schema.py` não vê esta deriva);
- a recriação das tabelas (`batch_alter_table`) não perde índices.
"""
from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import CheckConstraint, create_engine, inspect

import app.models  # noqa: F401  — regista todas as tabelas em Base.metadata
from app.db import Base

BASE_REVISION = "b9e1d3f5a7c2"
THIS_REVISION = "d2f4a6c8e0b1"
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


def _assert_ok(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, result.stdout + result.stderr


def _insert(connection: sqlite3.Connection, table: str, **values: object) -> None:
    """INSERT que preenche as colunas NOT NULL sem valor por omissão com
    valores neutros, para o teste só dizer o que importa."""
    for _cid, name, column_type, notnull, default, primary_key in connection.execute(f"PRAGMA table_info({table})"):
        if name in values or default is not None or not (notnull or primary_key):
            continue
        upper = column_type.upper()
        if name == "id":
            values[name] = str(uuid.uuid4())
        elif "DATETIME" in upper or "TIMESTAMP" in upper:
            values[name] = "2026-01-01 00:00:00"
        elif "DATE" in upper:
            values[name] = "2026-01-01"
        elif "JSON" in upper:
            values[name] = "{}"
        elif any(token in upper for token in ("INT", "BOOL", "NUMERIC", "FLOAT")):
            values[name] = 0
        else:
            values[name] = ""
    columns = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    connection.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})", tuple(values.values()))


def _sql(connection: sqlite3.Connection, name: str) -> str:
    row = connection.execute("SELECT sql FROM sqlite_master WHERE name = ?", (name,)).fetchone()
    return row[0] if row else ""


def _indexes(connection: sqlite3.Connection) -> dict[str, str]:
    return {
        name: " ".join(sql.split())
        for name, sql in connection.execute("SELECT name, sql FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL")
    }


@pytest.fixture()
def database_at_base(tmp_path: Path) -> Path:
    database_path = tmp_path / "checks.db"
    _assert_ok(_run_alembic(database_path, "upgrade", BASE_REVISION))
    return database_path


def _people_and_users(connection: sqlite3.Connection, *emails: str) -> None:
    for index, email in enumerate(emails):
        person_id = str(uuid.uuid4())
        _insert(connection, "people", id=person_id, display_name=f"Pessoa {index}", is_active=1)
        _insert(connection, "users", person_id=person_id, email=email, is_active=1)


def test_migration_aborts_with_a_clear_message_and_changes_nothing(database_at_base: Path):
    with sqlite3.connect(database_at_base) as connection:
        item_id = str(uuid.uuid4())
        _insert(connection, "inventory_items", id=item_id, sku="SKU-1", name="Artigo")
        _insert(connection, "projects", name="P1", lifecycle_status="em_obras")
        _insert(connection, "projects", name="P2", lifecycle_status="em_obras")
        _insert(connection, "projects", name="P3", lifecycle_status="preparacao")
        _insert(connection, "inventory_movements", item_id=item_id, movement_type="entrada", quantity=-3)
        _insert(connection, "inventory_movements", item_id=item_id, movement_type="ajuste", quantity=-3)  # válido
        _insert(connection, "inventory_movements", item_id=item_id, movement_type="roubo", quantity=1)
        _people_and_users(connection, "Duplicado.Secreto@example.invalid", "duplicado.secreto@example.invalid ")

    result = _run_alembic(database_at_base, "upgrade", "head")
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "abortada sem alterar nada" in output
    assert "projects [ck_projects_lifecycle_status]: 2 linha(s)" in output and "'em_obras' (2)" in output
    assert "inventory_movements [ck_inventory_movements_movement_type]" in output and "'roubo' (1)" in output
    assert "inventory_movements [ck_inventory_movements_quantity_sign]" in output
    assert "'entrada com quantidade negativa' (1)" in output
    assert "users.email" in output and "1 grupo(s)" in output
    assert "secreto" not in output.lower()  # nada de emails nas mensagens
    assert "preparacao" not in output  # valores válidos não são listados

    with sqlite3.connect(database_at_base) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (BASE_REVISION,)
        assert "ck_projects_lifecycle_status" not in _sql(connection, "projects")
        assert "ck_inventory_movements_quantity_sign" not in _sql(connection, "inventory_movements")
        assert "uq_users_email_lower" not in _indexes(connection)


def test_migration_applies_normalizes_emails_and_downgrades(database_at_base: Path):
    with sqlite3.connect(database_at_base) as connection:
        item_id = str(uuid.uuid4())
        _insert(connection, "inventory_items", id=item_id, sku="SKU-1", name="Artigo")
        _insert(connection, "projects", name="P1", lifecycle_status="construcao")
        _insert(connection, "projects", name="P2", lifecycle_status=None)
        _insert(connection, "inventory_movements", item_id=item_id, movement_type="ajuste", quantity=-2)
        _people_and_users(connection, "  Mistura@Example.INVALID ", "outra@example.invalid")
        indexes_before = _indexes(connection)

    _assert_ok(_run_alembic(database_at_base, "upgrade", "head"))
    with sqlite3.connect(database_at_base) as connection:
        emails = sorted(email for (email,) in connection.execute("SELECT email FROM users"))
        assert emails == ["mistura@example.invalid", "outra@example.invalid"]
        indexes_after = _indexes(connection)
        # a recriação das tabelas (batch) não perdeu nenhum índice, nem os parciais
        assert indexes_before.items() <= indexes_after.items()
        assert set(indexes_after) - set(indexes_before) == {"uq_users_email_lower"}
        assert "WHERE" in indexes_after["uq_inventory_locations_one_active_central_per_owner"]
        with pytest.raises(sqlite3.IntegrityError):
            _insert(connection, "projects", name="P3", lifecycle_status="inventado")
        with pytest.raises(sqlite3.IntegrityError):
            _people_and_users(connection, "MISTURA@example.invalid")
        connection.rollback()

    _assert_ok(_run_alembic(database_at_base, "downgrade", BASE_REVISION))
    with sqlite3.connect(database_at_base) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (BASE_REVISION,)
        assert "ck_projects_lifecycle_status" not in _sql(connection, "projects")
        assert "ck_tasks_status" not in _sql(connection, "tasks")
        assert _indexes(connection) == indexes_before
        # sem os CHECKs, volta a aceitar-se um valor fora do vocabulário
        _insert(connection, "projects", name="P3", lifecycle_status="inventado")
        connection.rollback()

    _assert_ok(_run_alembic(database_at_base, "upgrade", "head"))


def _normalize_check(sqltext: str) -> str:
    """Compara só o significado: sem espaços/parênteses de embrulho e com as
    listas `IN (...)` ordenadas."""
    text = " ".join(sqltext.split())
    while text.startswith("(") and text.endswith(")") and _balanced(text[1:-1]):
        text = text[1:-1].strip()

    def _sorted_list(match: re.Match[str]) -> str:
        items = sorted(item.strip() for item in match.group(1).split(","))
        return "IN (" + ", ".join(items) + ")"

    return re.sub(r"IN \(([^)]*)\)", _sorted_list, text)


def _balanced(text: str) -> bool:
    depth = 0
    for char in text:
        depth += (char == "(") - (char == ")")
        if depth < 0:
            return False
    return depth == 0


def test_migrated_schema_has_the_same_checks_as_the_models(tmp_path: Path):
    database_path = tmp_path / "drift.db"
    _assert_ok(_run_alembic(database_path, "upgrade", "head"))
    declared: dict[tuple[str, str], str] = {}
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            if isinstance(constraint, CheckConstraint) and constraint.name:
                declared[(table.name, str(constraint.name))] = _normalize_check(str(constraint.sqltext))

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        inspector = inspect(engine)
        migrated = {
            (table_name, check["name"]): _normalize_check(check["sqltext"])
            for table_name in inspector.get_table_names()
            for check in inspector.get_check_constraints(table_name)
            if check["name"]
        }
    finally:
        engine.dispose()

    assert migrated == declared, {
        "só nos modelos": sorted(set(declared) - set(migrated)),
        "só nas migrações": sorted(set(migrated) - set(declared)),
        "texto diferente": sorted(k for k in set(declared) & set(migrated) if declared[k] != migrated[k]),
    }
