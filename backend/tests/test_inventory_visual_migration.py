from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text


def test_inventory_visual_migration_supports_up_down_up():
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "d1f3b5c7e9a2_inventario_visual.py"
    )
    assert migration_path.is_file()
    spec = importlib.util.spec_from_file_location("migration_inventory_visual", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE inventory_items (id CHAR(32) PRIMARY KEY)"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        columns = {column["name"] for column in inspect(connection).get_columns("inventory_items")}
        assert {"manufacturer", "model", "subcategory", "power_w", "cross_section_mm2", "photo_storage_name", "photo_content_type"} <= columns
        assert {"inventory_item_documents", "inventory_category_images"} <= set(inspect(connection).get_table_names())

        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        columns = {column["name"] for column in inspect(connection).get_columns("inventory_items")}
        assert not {"manufacturer", "model", "subcategory", "power_w", "cross_section_mm2", "photo_storage_name", "photo_content_type"} & columns
        assert not {"inventory_item_documents", "inventory_category_images"} & set(inspect(connection).get_table_names())

        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        columns = {column["name"] for column in inspect(connection).get_columns("inventory_items")}
        assert {"manufacturer", "model", "subcategory", "power_w", "cross_section_mm2", "photo_storage_name", "photo_content_type"} <= columns
        assert {"inventory_item_documents", "inventory_category_images"} <= set(inspect(connection).get_table_names())
    engine.dispose()
