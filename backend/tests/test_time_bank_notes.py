import importlib.util
import datetime as dt
from pathlib import Path

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import inspect, text

from app.models.people import Person
from app.models.identity import User
from app.models.time_bank import TimeBankAudit, TimeBankEntry, TimeBankNote
from app.schemas.time_bank import TimeBankNoteRead

ADMIN = {"X-Dev-User-Email": "admin.sintetico@example.invalid"}
PM = {"X-Dev-User-Email": "pm.um.sintetico@example.invalid"}


def _person(db, name):
    return db.query(Person).filter(Person.display_name == name).one()


def test_note_read_normalizes_naive_utc_and_aware_instants_to_utc():
    common = {"id": "00000000-0000-0000-0000-000000000001", "person_id": "00000000-0000-0000-0000-000000000002", "body": "Nota", "author_display_name": "Gestor"}
    naive = TimeBankNoteRead(**common, created_at=dt.datetime(2026, 10, 27, 10))
    aware = TimeBankNoteRead(**common, created_at=dt.datetime(2026, 10, 27, 12, tzinfo=dt.timezone(dt.timedelta(hours=2))))
    assert naive.created_at.isoformat() == "2026-10-27T10:00:00+00:00"
    assert aware.created_at == naive.created_at


def test_manager_creates_and_reads_independent_note_with_id_only_audit(db_session, api_client):
    person = _person(db_session, "PM Sintético Um")
    before = db_session.query(TimeBankEntry).count()
    response = api_client.post("/api/time-bank/notes", headers=ADMIN, json={"person_id": str(person.id), "body": "  Nota histórica  "})
    assert response.status_code == 201, response.text
    note = response.json()
    assert note["body"] == "Nota histórica"
    assert note["person_id"] == str(person.id)
    assert note["author_display_name"]
    assert "created_by_user_id" not in note
    audit = db_session.query(TimeBankAudit).filter_by(action="note.create", entity_id=note["id"]).one()
    assert audit.data == {"note_id": note["id"], "person_id": str(person.id)}
    assert "Nota histórica" not in str(audit.data)
    assert db_session.query(TimeBankEntry).count() == before
    read = api_client.get(f"/api/time-bank/notes?person_id={person.id}", headers=PM)
    assert read.status_code == 200, read.text
    assert read.json() == {"items": [note], "total": 1}


def test_note_scope_manage_and_body_validation(db_session, api_client):
    own = _person(db_session, "PM Sintético Um")
    other = _person(db_session, "Chefe Sintético")
    assert api_client.get(f"/api/time-bank/notes?person_id={other.id}", headers=PM).status_code == 403
    assert api_client.post("/api/time-bank/notes", headers=PM, json={"person_id": str(own.id), "body": "no"}).status_code == 403
    assert api_client.get(f"/api/time-bank/notes?person_id={own.id}").status_code == 401
    unprivileged_person = Person(display_name="Sem capability")
    db_session.add(unprivileged_person)
    db_session.flush()
    db_session.add(User(person_id=unprivileged_person.id, email="sem.capability@example.invalid", is_active=True))
    db_session.flush()
    no_capability = {"X-Dev-User-Email": "sem.capability@example.invalid"}
    assert api_client.get(f"/api/time-bank/notes?person_id={own.id}", headers=no_capability).status_code == 403
    assert api_client.post("/api/time-bank/notes", headers=no_capability, json={"person_id": str(own.id), "body": "sem acesso"}).status_code == 403
    for body in ("", "   ", "x" * 2001, None, 12):
        response = api_client.post("/api/time-bank/notes", headers=ADMIN, json={"person_id": str(own.id), "body": body})
        assert response.status_code == 422
    assert api_client.post("/api/time-bank/notes", headers=ADMIN, json={"person_id": str(own.id), "body": "ok", "created_by_user_id": "spoof"}).status_code == 422


def test_notes_pagination(db_session, api_client):
    person = _person(db_session, "PM Sintético Um")
    for index in range(3):
        response = api_client.post("/api/time-bank/notes", headers=ADMIN, json={"person_id": str(person.id), "body": f"Nota {index}"})
        assert response.status_code == 201
    page = api_client.get(f"/api/time-bank/notes?person_id={person.id}&limit=2&offset=1", headers=ADMIN)
    assert page.status_code == 200
    assert page.json()["total"] == 3
    assert len(page.json()["items"]) == 2
    assert api_client.get(f"/api/time-bank/notes?person_id={person.id}&limit=101", headers=ADMIN).status_code == 422


def test_note_commit_failure_rolls_back(db_session, api_client, monkeypatch):
    person = _person(db_session, "PM Sintético Um")
    monkeypatch.setattr(db_session, "commit", lambda: (_ for _ in ()).throw(SQLAlchemyError("commit failed")))
    response = api_client.post("/api/time-bank/notes", headers=ADMIN, json={"person_id": str(person.id), "body": "Não persistir"})
    assert response.status_code == 503
    assert db_session.query(TimeBankNote).filter_by(person_id=person.id).count() == 0
    assert db_session.query(TimeBankAudit).filter_by(action="note.create").count() == 0


def test_notes_migration_empty_and_with_legacy_ledger_supports_up_down_up():
    migration_path = Path(__file__).parents[1] / "alembic" / "versions" / "f2a4b6c8d0e1_time_bank_notes.py"
    spec = importlib.util.spec_from_file_location("migration_time_bank_notes", migration_path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE people (id CHAR(32) PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE users (id CHAR(32) PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE time_bank_entries (id INTEGER PRIMARY KEY, balance_seconds INTEGER NOT NULL)"))
            connection.execute(text("INSERT INTO time_bank_entries VALUES (1, 7200)"))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            assert "time_bank_notes" in inspect(connection).get_table_names()
            with Operations.context(MigrationContext.configure(connection)):
                migration.downgrade()
            assert "time_bank_notes" not in inspect(connection).get_table_names()
            assert connection.execute(text("SELECT balance_seconds FROM time_bank_entries WHERE id = 1")).scalar_one() == 7200
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            assert "time_bank_notes" in inspect(connection).get_table_names()
    finally:
        engine.dispose()
