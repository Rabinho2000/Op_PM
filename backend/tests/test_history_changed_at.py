"""`changed_at` dos históricos de projeto é a hora do evento, não a da transação.

No PostgreSQL, `now()` devolve a hora de início da transação. Quando várias
alterações ocorrem na mesma transação (ou numa transação longa), o histórico
ficava com uma hora anterior às marcas escritas em Python, e o rollback de
importações deixava de detetar alterações posteriores ao lote.
"""
from __future__ import annotations

import datetime as dt
import time
import uuid

from app.models.project import Project, ProjectHistory
from app.models.project_data import ProjectDataHistory


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def test_history_changed_at_is_event_time_not_transaction_start(db_session):
    project = db_session.query(Project).first()
    # Garante que a transação já começou antes do evento.
    db_session.query(ProjectHistory).count()
    time.sleep(1.1)
    before = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)

    data_entry = ProjectDataHistory(
        project_id=project.id,
        entity_type="sim_card",
        record_id=uuid.uuid4(),
        field_name="pin",
        old_value=None,
        new_value=None,
        changed_by_person_id=None,
        source="ui",
        note="",
    )
    project_entry = ProjectHistory(
        project_id=project.id,
        field_name="name",
        old_value="a",
        new_value="b",
        source="ui",
    )
    db_session.add_all([data_entry, project_entry])
    db_session.flush()
    db_session.refresh(data_entry)
    db_session.refresh(project_entry)

    assert _aware(data_entry.changed_at) >= before
    assert _aware(project_entry.changed_at) >= before
