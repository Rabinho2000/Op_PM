from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text


def test_project_photo_migration_supports_up_down_up():
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "b8d0f2a4c6e7_fotografia_principal_projeto.py"
    )
    assert migration_path.is_file()
    spec = importlib.util.spec_from_file_location("migration_project_photo", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE projects (id INTEGER PRIMARY KEY)"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        columns = {column["name"] for column in inspect(connection).get_columns("projects")}
        assert {"primary_photo_storage_name", "primary_photo_content_type"} <= columns

        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        columns = {column["name"] for column in inspect(connection).get_columns("projects")}
        assert "primary_photo_storage_name" not in columns
        assert "primary_photo_content_type" not in columns

        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        columns = {column["name"] for column in inspect(connection).get_columns("projects")}
        assert {"primary_photo_storage_name", "primary_photo_content_type"} <= columns

    engine.dispose()
