from __future__ import annotations

import datetime as dt
import importlib.util
import uuid
from pathlib import Path

import pytest

from app.models.project import Project, ProjectTeamAssignment
from app.models.people import Person
from app.models.task import Task
from app.models.time_bank import TimeBankEntry
from app.models.identity import User
from app.security.catalog import ROLE_INSTALLER_COLLABORATOR, ROLE_PERMISSIONS
from app.security.permissions import (
    AuthContext,
    can_view_calendar_event,
    can_view_project,
    can_view_task,
    is_installer_readonly_scope,
)
from app.services.installer_inventory import list_installer_inventory
from app.services.time_bank_ledger import TimeBankForbidden, list_entries, summary


PERSON_ID = uuid.uuid4()
INSTALLER_ID = uuid.uuid4()
OTHER_INSTALLER_ID = uuid.uuid4()
PROJECT_ID = uuid.uuid4()


def installer_context(*permissions: str, installer_ids=(INSTALLER_ID,)) -> AuthContext:
    return AuthContext(
        user=None,
        person_id=PERSON_ID,
        role_codes=frozenset({ROLE_INSTALLER_COLLABORATOR}),
        permission_codes=frozenset(permissions),
        active_installer_ids=frozenset(installer_ids),
    )


def project(*, installer_id=None, assignments=None) -> Project:
    return Project(
        id=PROJECT_ID,
        name="Projeto sintético",
        installer_id=installer_id,
        team_assignments=list(assignments or []),
    )


def test_installer_role_has_only_scoped_read_permissions():
    assert set(ROLE_PERMISSIONS[ROLE_INSTALLER_COLLABORATOR]) == {
        "project.view_assigned_installer",
        "task.view_assigned_installer",
        "works_calendar.view_assigned_installer",
        "installer_team.view_assigned_installer",
        "inventory.view_assigned_installer",
        "time_bank.view_own",
    }


def test_assignment_scope_includes_historical_project_assignment():
    assignment = ProjectTeamAssignment(
        project_id=PROJECT_ID,
        installer_id=INSTALLER_ID,
        team_id=uuid.uuid4(),
        start_date=dt.date(2025, 1, 1),
        end_date=dt.date(2025, 12, 31),
    )
    ctx = installer_context("project.view_assigned_installer")
    assert can_view_project(ctx, project(assignments=[assignment])) is True
    assert can_view_project(ctx, project(installer_id=OTHER_INSTALLER_ID)) is False


def test_direct_task_assignment_cannot_bypass_installer_project_scope():
    task = Task(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        title="Tarefa sintética",
        assigned_to_person_id=PERSON_ID,
    )
    task.project = project(installer_id=OTHER_INSTALLER_ID)
    ctx = installer_context("project.view_assigned_installer", "task.view_assigned_installer")
    assert can_view_task(ctx, task) is False


def test_calendar_scoped_capability_is_read_only_and_project_bound():
    ctx = installer_context("project.view_assigned_installer", "works_calendar.view_assigned_installer")
    assert is_installer_readonly_scope(ctx) is True
    assert can_view_calendar_event(ctx, project(installer_id=INSTALLER_ID)) is True
    assert can_view_calendar_event(ctx, project(installer_id=OTHER_INSTALLER_ID)) is False
    assert can_view_calendar_event(ctx, None) is False


def test_existing_broad_permission_remains_additive():
    ctx = installer_context(
        "project.view_assigned_installer",
        "works_calendar.view_assigned_installer",
        "project.view_all",
        "calendar.view",
    )
    assert is_installer_readonly_scope(ctx) is False
    assert can_view_calendar_event(ctx, project(installer_id=OTHER_INSTALLER_ID)) is True


def test_new_migration_is_chained_after_time_bank_migration():
    migration_path = next(
        Path(__file__).parents[1].glob("alembic/versions/d9e1f3a5b7c2_*.py")
    )
    spec = importlib.util.spec_from_file_location("installer_access_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    assert migration.revision == "d9e1f3a5b7c2"
    assert migration.down_revision == "c8f0a2b4d6e1"


def test_installer_collaborator_time_bank_is_own_person_only(db_session):
    own = Person(display_name="Colaborador instalador sintético", email="installer.synthetic@example.invalid")
    other = Person(display_name="Outra pessoa sintética", email="other.synthetic@example.invalid")
    db_session.add_all([own, other])
    db_session.flush()
    actor = db_session.query(User).first()
    assert actor is not None
    db_session.add_all(
        [
            TimeBankEntry(
                person_id=own.id,
                work_date=dt.date(2026, 10, 16),
                start_minute=540,
                end_minute=840,
                lunch_taken=False,
                balance_seconds=3600,
                calculated_seconds=3600,
                calculation_mode="standard",
                needs_review=False,
                review_flags={},
                provenance={"source": "synthetic-test"},
                created_by_user_id=actor.id,
            ),
            TimeBankEntry(
                person_id=other.id,
                work_date=dt.date(2026, 10, 16),
                start_minute=540,
                end_minute=840,
                lunch_taken=False,
                balance_seconds=7200,
                calculated_seconds=7200,
                calculation_mode="standard",
                needs_review=False,
                review_flags={},
                provenance={"source": "synthetic-test"},
                created_by_user_id=actor.id,
            ),
        ]
    )
    db_session.flush()
    ctx = AuthContext(
        user=actor,
        person_id=own.id,
        role_codes=frozenset({ROLE_INSTALLER_COLLABORATOR}),
        permission_codes=frozenset({"time_bank.view_own"}),
        active_installer_ids=frozenset({INSTALLER_ID}),
    )

    rows, total = list_entries(db_session, ctx, person_id=None, from_date=None, to_date=None, limit=100, offset=0)
    assert total == 1
    assert [row.person_id for row in rows] == [own.id]
    assert summary(db_session, ctx, person_id=None, year=2026, month=None)[0]["person_id"] == own.id
    try:
        list_entries(db_session, ctx, person_id=other.id, from_date=None, to_date=None, limit=100, offset=0)
    except TimeBankForbidden:
        pass
    else:
        raise AssertionError("o colaborador externo não pode consultar o Banco de Horas de outra pessoa")


def test_installer_inventory_reuses_project_scope_and_uniformly_hides_foreign_project(db_session):
    projects = db_session.query(Project).filter(Project.is_active.is_(True), Project.installer_id.is_not(None)).all()
    if len({project.installer_id for project in projects}) < 2:
        pytest.skip("seed sintético sem dois instaladores distintos")
    visible_project = projects[0]
    foreign_project = next(project for project in projects if project.installer_id != visible_project.installer_id)
    actor = db_session.query(User).first()
    assert actor is not None
    ctx = AuthContext(
        user=actor,
        person_id=actor.person_id,
        role_codes=frozenset({ROLE_INSTALLER_COLLABORATOR}),
        permission_codes=frozenset({"project.view_assigned_installer", "inventory.view_assigned_installer"}),
        active_installer_ids=frozenset({visible_project.installer_id}),
    )

    rows, total = list_installer_inventory(db_session, ctx, project_id=visible_project.id, limit=100, offset=0)
    assert total >= len(rows)
    assert all(row["project_id"] == visible_project.id for row in rows)
    if rows:
        assert set(rows[0]) == {
            "project_id", "project_name", "item_name", "unit", "required_quantity",
            "reserved_quantity", "consumed_quantity", "delivered_quantity", "locations",
        }
    with pytest.raises(LookupError, match="Projeto não encontrado"):
        list_installer_inventory(db_session, ctx, project_id=foreign_project.id, limit=100, offset=0)
