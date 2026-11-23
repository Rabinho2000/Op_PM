"""Migração `e4c7a9b1d3f5` (tabela `inventory_categories`), em SQLite:
semeia as categorias da lista fechada anterior, não toca em artigos e o
downgrade remove a tabela."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from app.models.inventory import INVENTORY_CATEGORIES
from app.utils.text import alnum_casefold_key

BASE_REVISION = "d3f5a7c9e1b2"
THIS_REVISION = "e4c7a9b1d3f5"
BACKEND_DIR = Path(__file__).resolve().parents[1]


def _alembic(database_path: Path, *arguments: str) -> None:
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
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_inventory_categories_migration_seeds_builtins_and_round_trips(tmp_path):
    database = tmp_path / "categories.db"
    _alembic(database, "upgrade", BASE_REVISION)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO inventory_items (id, sku, name, unit, category, min_stock, is_active,"
            " created_at, updated_at) VALUES ('legacy-id', 'LEG-1', 'Legado', 'un',"
            " 'Módulos antigos', 0, 1, '2026-01-01', '2026-01-01')"
        )
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'inventory_categories'"
        ).fetchone() is None

    _alembic(database, "upgrade", THIS_REVISION)
    with sqlite3.connect(database) as connection:
        rows = dict(connection.execute("SELECT name, normalized_key FROM inventory_categories"))
        assert rows == {name: alnum_casefold_key(name) for name in INVENTORY_CATEGORIES}
        assert connection.execute(
            "SELECT category FROM inventory_items WHERE id = 'legacy-id'"
        ).fetchone() == ("Módulos antigos",)

    _alembic(database, "downgrade", BASE_REVISION)
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'inventory_categories'"
        ).fetchone() is None
        assert connection.execute(
            "SELECT category FROM inventory_items WHERE id = 'legacy-id'"
        ).fetchone() == ("Módulos antigos",)

    _alembic(database, "upgrade", THIS_REVISION)
