from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def test_weekly_series_migration_supports_up_down_up_and_preserves_events():
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "c4e6a8b0d2f1_eventos_semanais_planeamento.py"
    )
    spec = importlib.util.spec_from_file_location("migration_weekly_calendar_series", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE users (id CHAR(36) PRIMARY KEY)"))
            connection.execute(
                text("CREATE TABLE calendar_events (id CHAR(36) PRIMARY KEY, title VARCHAR(256) NOT NULL)")
            )
            connection.execute(text("INSERT INTO calendar_events (id, title) VALUES ('legacy', 'Evento legado')"))

            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            assert "calendar_event_series" in inspect(connection).get_table_names()
            columns = {column["name"]: column for column in inspect(connection).get_columns("calendar_events")}
            assert {"series_id", "series_occurrence_index"} <= columns.keys()
            assert connection.execute(text("SELECT title, series_id FROM calendar_events WHERE id='legacy'")).one() == (
                "Evento legado",
                None,
            )
            connection.execute(text("INSERT INTO users (id) VALUES ('creator')"))
            connection.execute(
                text(
                    "INSERT INTO calendar_event_series ("
                    "id, created_by_user_id, idempotency_key, request_fingerprint, recurrence_rule, "
                    "timezone, starts_on, starts_at_local, ends_day_offset, ends_at_local, starts_fold, "
                    "ends_fold, until_date, occurrence_count) VALUES ("
                    "'series', 'creator', 'rollback-key', 'fingerprint', 'weekly', 'Europe/Lisbon', "
                    "'2026-01-05', '09:00', 0, '10:00', 0, 0, '2026-01-12', 2)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO calendar_events (id, title, series_id, series_occurrence_index) "
                    "VALUES ('occurrence', 'Ocorrência semanal', 'series', 0)"
                )
            )

            with Operations.context(MigrationContext.configure(connection)):
                migration.downgrade()
            assert "calendar_event_series" not in inspect(connection).get_table_names()
            assert {column["name"] for column in inspect(connection).get_columns("calendar_events")} == {"id", "title"}
            assert connection.execute(text("SELECT title FROM calendar_events WHERE id='legacy'")).scalar_one() == "Evento legado"
            assert connection.execute(
                text("SELECT title FROM calendar_events WHERE id='occurrence'")
            ).scalar_one() == "Ocorrência semanal"

            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            assert "calendar_event_series" in inspect(connection).get_table_names()
            assert connection.execute(text("SELECT COUNT(*) FROM calendar_events")).scalar_one() == 2
            assert connection.execute(
                text("SELECT series_id, series_occurrence_index FROM calendar_events WHERE id='occurrence'")
            ).one() == (None, None)
    finally:
        engine.dispose()


def _load_migration(file_name: str, module_name: str):
    path = Path(__file__).parents[1] / "alembic" / "versions" / file_name
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_weekly_series_migration_rejects_unknown_recurrence_rule():
    migration = _load_migration(
        "c4e6a8b0d2f1_eventos_semanais_planeamento.py", "migration_weekly_calendar_series_check"
    )
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE users (id CHAR(36) PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE calendar_events (id CHAR(36) PRIMARY KEY)"))
            connection.execute(text("INSERT INTO users (id) VALUES ('creator')"))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            insert = (
                "INSERT INTO calendar_event_series ("
                "id, created_by_user_id, idempotency_key, request_fingerprint, recurrence_rule, "
                "timezone, starts_on, starts_at_local, ends_day_offset, ends_at_local, starts_fold, "
                "ends_fold, until_date, occurrence_count) VALUES ("
                "'{id}', 'creator', '{id}', 'fp', '{rule}', 'Europe/Lisbon', "
                "'2026-01-05', '09:00', 0, '10:00', 0, 0, '2026-01-12', 2)"
            )
            connection.execute(text(insert.format(id="ok", rule="weekly")))
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(text(insert.format(id="bad", rule="daily")))
    finally:
        engine.dispose()


def test_calendar_audit_migration_supports_up_down_up_and_checks_action():
    migration = _load_migration(
        "d7a9c3e5f1b2_auditoria_eventos_calendario.py", "migration_calendar_event_audit"
    )
    engine = create_engine("sqlite://")
    insert = (
        "INSERT INTO calendar_event_audit (id, event_id, actor_user_id, action, field_changes) "
        "VALUES ('{id}', 'event', 'actor', '{action}', '{{}}')"
    )
    try:
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            inspector = inspect(connection)
            assert "calendar_event_audit" in inspector.get_table_names()
            assert {index["name"] for index in inspector.get_indexes("calendar_event_audit")} == {
                "ix_calendar_event_audit_event_id",
                "ix_calendar_event_audit_series_id",
            }
            for action in ("create", "update", "cancel"):
                connection.execute(text(insert.format(id=action, action=action)))
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(text(insert.format(id="bad", action="delete")))

            with Operations.context(MigrationContext.configure(connection)):
                migration.downgrade()
            assert "calendar_event_audit" not in inspect(connection).get_table_names()
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            assert connection.execute(text("SELECT COUNT(*) FROM calendar_event_audit")).scalar_one() == 0
    finally:
        engine.dispose()
