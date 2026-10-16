"""Migração D-090: manter dados de contacto legados ao criar a lista nova."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path


BASE_REVISION = "a7c1e5d9f3b2"


def _run_alembic(database_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.update(
        {
            "APP_ENV": "test",
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


def test_supplier_contacts_migration_backfills_legacy_fields(tmp_path: Path):
    database_path = tmp_path / "supplier-contacts-migration.db"
    supplier_id = "00000000-0000-0000-0000-000000000001"
    empty_supplier_id = "00000000-0000-0000-0000-000000000002"

    before = _run_alembic(database_path, "upgrade", BASE_REVISION)
    assert before.returncode == 0, before.stdout + before.stderr
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO suppliers (
                id, name, category, contact, email, address, lat, lon,
                is_preferred, lead_time_days, phone, website, notes, materials, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                supplier_id,
                "Fornecedor Legado",
                None,
                "Contacto Legado",
                "legado@example.invalid",
                None,
                None,
                None,
                0,
                None,
                "+351 000 000 001",
                None,
                "",
                "",
                1,
            ),
        )
        connection.execute(
            """
            INSERT INTO suppliers (
                id, name, category, contact, email, address, lat, lon,
                is_preferred, lead_time_days, phone, website, notes, materials, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                empty_supplier_id,
                "Fornecedor Sem Contacto",
                None,
                None,
                None,
                None,
                None,
                None,
                0,
                None,
                None,
                None,
                "",
                "",
                1,
            ),
        )
        connection.commit()

    after = _run_alembic(database_path, "upgrade", "head")
    assert after.returncode == 0, after.stdout + after.stderr

    with sqlite3.connect(database_path) as connection:
        migrated = connection.execute(
            "SELECT name, department, phone, email, position FROM supplier_contacts WHERE supplier_id = ?",
            (supplier_id,),
        ).fetchall()
        empty = connection.execute(
            "SELECT COUNT(*) FROM supplier_contacts WHERE supplier_id = ?",
            (empty_supplier_id,),
        ).fetchone()[0]

    assert migrated == [("Contacto Legado", None, "+351 000 000 001", "legado@example.invalid", 0)]
    assert empty == 0
