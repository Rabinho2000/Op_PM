"""Supplier company links are reversible without affecting supplier data."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BASE_REVISION = "c2a4e6b8d0f1"
TARGET_REVISION = "f1a3c5e7b9d0"


def _run_alembic(database_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.update({"APP_ENV": "test", "DATABASE_URL": f"sqlite:///{database_path}", "EXPECTED_DB_DIALECT": "sqlite"})
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments], cwd=Path(__file__).resolve().parents[1],
        env=environment, capture_output=True, text=True, check=False,
    )


def test_supplier_company_migration_preserves_legacy_rows_and_drops_only_its_table(tmp_path: Path):
    database_path = tmp_path / "supplier-company-migration.db"
    supplier_id = "00000000-0000-0000-0000-000000000091"
    upgraded = _run_alembic(database_path, "upgrade", BASE_REVISION)
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """INSERT INTO suppliers (id, name, category, contact, email, address, lat, lon,
            is_preferred, lead_time_days, phone, website, notes, materials, is_active)
            VALUES (?, ?, NULL, ?, ?, NULL, NULL, NULL, 0, NULL, ?, NULL, '', '', 1)""",
            (supplier_id, "Fornecedor Legado", "Contacto Legado", "legacy@example.invalid", "000 000 091"),
        )
        connection.execute(
            "INSERT INTO supplier_contacts (id, supplier_id, name, department, phone, email, position) VALUES (?, ?, ?, NULL, ?, NULL, 0)",
            ("00000000-0000-0000-0000-000000000092", supplier_id, "Contacto da Lista", "000 000 092"),
        )
        connection.commit()

    upgraded = _run_alembic(database_path, "upgrade", TARGET_REVISION)
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM supplier_company_links").fetchone() == (0,)
        connection.executemany("INSERT INTO supplier_company_links VALUES (?, ?)", [(supplier_id, "solcor"), (supplier_id, "verde_milenar")])
        connection.commit()

    down = _run_alembic(database_path, "downgrade", BASE_REVISION)
    assert down.returncode == 0, down.stdout + down.stderr
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='supplier_company_links'").fetchone() is None
        assert connection.execute("SELECT name, contact, phone FROM suppliers WHERE id=?", (supplier_id,)).fetchone() == ("Fornecedor Legado", "Contacto Legado", "000 000 091")
        assert connection.execute("SELECT supplier_id, name, phone FROM supplier_contacts WHERE supplier_id=?", (supplier_id,)).fetchone() == (supplier_id, "Contacto da Lista", "000 000 092")

    again = _run_alembic(database_path, "upgrade", TARGET_REVISION)
    assert again.returncode == 0, again.stdout + again.stderr
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM supplier_company_links").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM suppliers WHERE id=?", (supplier_id,)).fetchone() == (1,)
