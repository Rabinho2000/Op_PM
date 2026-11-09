from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.models.client_report import ClientReportConfig
from app.models.identity import User
from app.models.inventory import InventoryItem, InventoryLocation, InventoryMovement, MaterialRequest
from app.models.performance import GoalPeriod
from app.models.notification import Notification
from app.models.process_alerts import ProcessStageSubscription
from app.models.project import Project, ProjectHistory, ProjectSubtaskProgress
from app.models.task import STATUS_DONE, TASK_TYPE_COMISSIONAMENTO, Task
from app.models.workflow import WorkflowStage, WorkflowSubtask
from app.security.permissions import load_auth_context
from app.services.client_report_scheduler import due_configs
from app.services.installers import project_counts_by_installer
from app.services.performance import _completed_projects_query, compute_goal_progress
from app.services.process_alerts import notify_stage_completed_if_transitioned
from app.services.process_rules import complete_delivered_projects
from app.services.safety_sheet import save_safety_sheet

ADMIN = "admin.sintetico@example.invalid"
CHEFE = "chefe.sintetico@example.invalid"
PM = "pm.um.sintetico@example.invalid"
COMERCIAL = "comercial.sintetico@example.invalid"
PROJECT_NAME = "Instalação Sintética de Demonstração"


def _headers(email: str = ADMIN) -> dict[str, str]:
    return {"X-Dev-User-Email": email}


def _project(db_session) -> Project:
    return db_session.query(Project).filter(Project.name == PROJECT_NAME).one()


def _delete(api_client, project: Project, *, email: str = ADMIN, reason: str = "Motivo de teste"):
    return api_client.request(
        "DELETE",
        f"/api/projects/{project.id}",
        json={"reason": reason},
        headers=_headers(email),
    )


def test_project_delete_requires_reason_hides_and_restores_with_history(db_session, api_client):
    project = _project(db_session)
    project_id = project.id

    read = api_client.get(f"/api/projects/{project_id}", headers=_headers())
    assert read.status_code == 200
    assert read.json()["can_delete"] is True
    assert read.json()["can_restore"] is False

    assert api_client.delete(f"/api/projects/{project_id}", headers=_headers()).status_code == 422
    assert api_client.request(
        "DELETE", f"/api/projects/{project_id}", json={"reason": "   "}, headers=_headers()
    ).status_code == 422

    deleted = _delete(api_client, project, reason="Projeto duplicado")
    assert deleted.status_code == 204, deleted.text
    assert api_client.get(f"/api/projects/{project_id}", headers=_headers()).status_code == 404
    assert api_client.patch(f"/api/projects/{project_id}", json={"notes": "Não editar"}, headers=_headers()).status_code == 404
    assert project_id not in {row["id"] for row in api_client.get("/api/projects", headers=_headers()).json()}

    deleted_list = api_client.get("/api/projects/deleted", headers=_headers())
    assert deleted_list.status_code == 200, deleted_list.text
    deleted_read = next(row for row in deleted_list.json() if row["id"] == str(project_id))
    assert deleted_read["can_delete"] is False
    assert deleted_read["can_restore"] is True
    assert deleted_read["deleted_at"]
    assert deleted_read["deleted_by_person_id"]
    assert deleted_read["payments"] is None

    history = api_client.get(f"/api/projects/{project_id}/history", headers=_headers())
    assert history.status_code == 200, history.text
    assert any(entry["field_name"] == "deleted_at" and entry["note"] == "Projeto duplicado" for entry in history.json())
    assert api_client.get(f"/api/projects/{project_id}/history", headers=_headers(PM)).status_code == 404
    entries = db_session.query(ProjectHistory).filter(ProjectHistory.project_id == project_id).all()
    deletion = [entry for entry in entries if entry.field_name == "deleted_at"]
    assert len(deletion) == 1
    assert deletion[0].old_value is None
    assert deletion[0].new_value
    assert deletion[0].source == "ui"
    assert deletion[0].note == "Projeto duplicado"

    restored = api_client.post(f"/api/projects/{project_id}/restore", headers=_headers())
    assert restored.status_code == 200, restored.text
    assert restored.json()["can_delete"] is True
    assert restored.json()["can_restore"] is False
    assert restored.json()["deleted_at"] is None
    assert api_client.get(f"/api/projects/{project_id}", headers=_headers()).status_code == 200
    assert str(project_id) in {row["id"] for row in api_client.get("/api/projects", headers=_headers()).json()}
    assert api_client.get("/api/projects/deleted", headers=_headers()).json() == []
    lifecycle = [entry for entry in db_session.query(ProjectHistory).filter(ProjectHistory.project_id == project_id) if entry.field_name == "deleted_at"]
    assert len(lifecycle) == 2
    assert lifecycle[1].old_value == deletion[0].new_value
    assert lifecycle[1].new_value is None
    assert lifecycle[1].note


def test_delete_and_restore_permissions_are_separate(db_session, api_client):
    project = _project(db_session)

    assert _delete(api_client, project, email=PM).status_code == 403
    assert api_client.get("/api/projects/deleted", headers=_headers(PM)).status_code == 403
    assert _delete(api_client, project, email=CHEFE).status_code == 204
    assert api_client.post(f"/api/projects/{project.id}/restore", headers=_headers(CHEFE)).status_code == 403
    assert api_client.get(f"/api/projects/{project.id}/history", headers=_headers(CHEFE)).status_code == 404
    assert api_client.get(f"/api/projects/{project.id}/history", headers=_headers()).status_code == 200
    assert api_client.post(f"/api/projects/{project.id}/restore", headers=_headers()).status_code == 200
    assert api_client.post(f"/api/projects/{project.id}/restore", headers=_headers()).status_code == 404
    assert _delete(api_client, _project(db_session), email=COMERCIAL).status_code == 403


def test_deleted_project_is_hidden_from_operational_and_bypass_queries(db_session, api_client):
    project = _project(db_session)
    project_id = project.id
    project.lat, project.lon = 38.7, -9.1
    project.lifecycle_status = "construcao"
    project.start_date = dt.date(2026, 10, 20)
    project.work_start_date = dt.date(2026, 10, 20)
    project.work_end_date = dt.date(2026, 10, 22)

    task = db_session.query(Task).filter(Task.project_id == project_id).first()
    assert task is not None
    task.status = STATUS_DONE
    task.completed_at = dt.datetime(2026, 10, 20, 10, tzinfo=dt.timezone.utc)

    item = InventoryItem(sku=f"DELETE-{uuid.uuid4().hex[:10]}", name="Artigo sintético", unit="un")
    location = InventoryLocation(
        code=f"DELETE-{uuid.uuid4().hex[:10]}",
        name="Local sintético",
        location_type="project",
        owner="solcor",
        project_id=project_id,
    )
    report_config = ClientReportConfig(
        project_id=project_id,
        enabled=True,
        weekday=2,
        send_time=dt.time(9, 0),
        to_emails=["cliente@example.invalid"],
    )
    db_session.add_all([item, location, report_config])
    db_session.flush()
    db_session.add(
        InventoryMovement(
            item_id=item.id,
            movement_type="reserva",
            quantity=1,
            project_id=project_id,
            location_id=location.id,
            reference="movimento de teste",
        )
    )
    db_session.add(MaterialRequest(project_id=project_id, status="rascunho", notes="pedido sintético"))
    projection_stage = db_session.query(WorkflowStage).first()
    assert projection_stage is not None
    projection_stage.planned_start_offset_days = 1
    projection_stage.planned_end_offset_days = 2
    db_session.flush()

    assert _delete(api_client, project).status_code == 204

    assert api_client.get(f"/api/projects/{project_id}", headers=_headers()).status_code == 404
    assert api_client.get(f"/api/projects/{project_id}/licensing-data", headers=_headers()).status_code == 404
    assert api_client.get(f"/api/projects/{project_id}/sim-cards", headers=_headers()).status_code == 404
    assert api_client.get(f"/api/projects/{project_id}/safety-sheet", headers=_headers()).status_code == 404

    tasks = api_client.get(f"/api/tasks?project_id={project_id}", headers=_headers())
    assert tasks.status_code == 200 and tasks.json() == []
    movements = api_client.get(f"/api/inventory/movements?project_id={project_id}", headers=_headers())
    assert movements.status_code == 200 and movements.json() == []
    requests = api_client.get(f"/api/material-requests?project_id={project_id}", headers=_headers())
    assert requests.status_code == 200 and requests.json() == []

    map_data = api_client.get("/api/map/data", headers=_headers())
    assert map_data.status_code == 200, map_data.text
    assert str(project_id) not in json.dumps(map_data.json())
    works = api_client.get("/api/works/calendar?from=2026-10-19&to=2026-10-25", headers=_headers())
    assert works.status_code == 200, works.text
    assert str(project_id) not in json.dumps(works.json())
    dashboard_works = api_client.get("/api/dashboard/works", headers=_headers())
    assert dashboard_works.status_code == 200, dashboard_works.text
    assert str(project_id) not in json.dumps(dashboard_works.json())
    weekly = api_client.get(
        "/api/performance/completed-tasks-weekly?from=2026-10-19&to=2026-10-25", headers=_headers()
    )
    assert weekly.status_code == 200, weekly.text
    assert str(project_id) not in json.dumps(weekly.json())

    assert api_client.get(f"/api/projects/{project_id}/credentials", headers=_headers()).status_code == 404
    assert api_client.get(f"/api/projects/{project_id}/safety-sheet/history", headers=_headers()).status_code == 404
    assert api_client.get(f"/api/projects/{project_id}/safety-sheet/print", headers=_headers()).status_code == 404
    assert api_client.get(f"/api/projects/{project_id}/safety-sheet/workers-prefill", headers=_headers()).status_code == 404
    assert api_client.get(f"/api/projects/{project_id}/client-report", headers=_headers()).status_code == 404
    report_rows = api_client.get("/api/client-reports", headers=_headers()).json()
    assert str(project_id) not in json.dumps(report_rows)
    assert all(
        report_project.id != project_id
        for report_project, _config in due_configs(
            db_session,
            now=dt.datetime(2026, 10, 21, 8, 0, tzinfo=dt.timezone.utc),
        )
    )
    assert api_client.get(f"/api/planning/process-options/{project_id}", headers=_headers()).status_code == 404
    projected = api_client.get(
        f"/api/planning/process-events?project_id={project_id}", headers=_headers()
    )
    assert projected.status_code == 200, projected.text
    assert str(project_id) not in json.dumps(projected.json())
    assert api_client.post(
        "/api/material-requests",
        json={"project_id": str(project_id), "lines": [{"description": "Material", "quantity": "1"}]},
        headers=_headers(),
    ).status_code == 404
    with pytest.raises(LookupError, match="Projeto não encontrado"):
        save_safety_sheet(
            db_session,
            project_id=project_id,
            values={"expected_version": 0},
            changed_by_person_id=None,
        )

    db_session.refresh(project)
    assert project.deleted_at is not None
    assert project.deleted_by_person_id is not None


def test_deleted_projects_do_not_contribute_to_goal_realization(db_session, api_client):
    project = _project(db_session)
    goal = GoalPeriod(
        period_type="year",
        year=2026,
        metric="installations",
        target_value=1,
        scope="company",
    )
    today = dt.date(2026, 10, 21)
    baseline = compute_goal_progress(db_session, goal, today=today).realized

    task = Task(
        project_id=project.id,
        title="Comissionamento sintético concluído",
        task_type=TASK_TYPE_COMISSIONAMENTO,
        status=STATUS_DONE,
        completed_at=dt.datetime(2026, 10, 20, 10, tzinfo=dt.timezone.utc),
    )
    db_session.add(task)
    db_session.flush()

    def completed_task_ids() -> set[uuid.UUID]:
        return {
            completed.id
            for completed, _project in _completed_projects_query(
                db_session,
                start=dt.date(2026, 1, 1),
                end=dt.date(2026, 12, 31),
                pm_person_id=None,
            )
        }

    assert task.id in completed_task_ids()
    assert compute_goal_progress(db_session, goal, today=today).realized == baseline + 1

    assert _delete(api_client, project).status_code == 204

    assert task.id not in completed_task_ids()
    assert compute_goal_progress(db_session, goal, today=today).realized == baseline

    restored = api_client.post(f"/api/projects/{project.id}/restore", headers=_headers())
    assert restored.status_code == 200, restored.text
    assert task.id in completed_task_ids()
    assert compute_goal_progress(db_session, goal, today=today).realized == baseline + 1


def test_deleted_projects_are_not_counted_or_used_to_generate_process_alerts(db_session, api_client):
    project = Project(name="Projeto Sintético Apagado para regras", lifecycle_status="entregue_cliente", is_active=True)
    db_session.add(project)
    db_session.flush()
    installer = db_session.query(Project).filter(Project.installer_id.isnot(None)).first()
    counts_before = None
    if installer is not None:
        project.installer_id = installer.installer_id
        counts_before, _team_counts = project_counts_by_installer(db_session)
        counts_before = counts_before[project.installer_id]
    stage = db_session.query(WorkflowStage).first()
    assert stage is not None
    subtasks = db_session.query(WorkflowSubtask).filter(WorkflowSubtask.stage_id == stage.id).all()
    assert subtasks
    pm = db_session.query(User).filter(User.email == PM).one()
    db_session.add(ProcessStageSubscription(user_id=pm.id, stage_id=stage.id))
    for subtask in subtasks:
        db_session.add(
            ProjectSubtaskProgress(project_id=project.id, subtask_id=subtask.id, done=True, source="ui")
        )
    db_session.flush()

    assert _delete(api_client, project).status_code == 204

    stage = db_session.query(WorkflowStage).filter(WorkflowStage.id == stage.id).one()
    actor = load_auth_context(db_session, db_session.query(User).filter(User.email == CHEFE).one())
    assert notify_stage_completed_if_transitioned(
        db_session, project=project, stage=stage, was_complete=False, actor=actor
    ) == 0
    assert db_session.query(Notification).filter(Notification.project_id == project.id).count() == 0

    summary = complete_delivered_projects(db_session)
    assert summary["projects"] == db_session.query(Project).filter(
        Project.lifecycle_status == "entregue_cliente", Project.is_active.is_(True), Project.deleted_at.is_(None)
    ).count()

    if installer is not None:
        assert project.installer_id is not None and counts_before is not None
        counts_after, _team_counts = project_counts_by_installer(db_session)
        assert counts_after.get(project.installer_id, 0) == counts_before - 1


def test_project_deletion_migration_upgrade_downgrade_upgrade(tmp_path):
    database_path = tmp_path / "project-deletion-migration.db"
    backend_path = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "test",
            "DATABASE_URL": f"sqlite:///{database_path}",
            "PYTHONPATH": str(backend_path),
        }
    )

    def run_alembic(*arguments: str) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *arguments],
            cwd=backend_path,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    parent, revision = "e5a7c9d1f3b4", "f6b8d0e2a4c5"
    run_alembic("upgrade", parent)
    local_engine = create_engine(f"sqlite:///{database_path}")
    roles = {code: str(uuid.uuid4()) for code in ("administrador", "chefe_operacoes", "project_manager")}
    with local_engine.begin() as connection:
        for code, role_id in roles.items():
            connection.execute(
                text(
                    "INSERT INTO roles (id, code, name, description, created_at, updated_at) "
                    "VALUES (:id, :code, :name, '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"id": role_id, "code": code, "name": code},
            )

    run_alembic("upgrade", revision)
    with local_engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == revision
        assert connection.execute(
            text("SELECT COUNT(*) FROM pragma_table_info('projects') WHERE name IN ('deleted_at', 'deleted_by_person_id')")
        ).scalar_one() == 2
        assert connection.execute(
            text("SELECT COUNT(*) FROM permissions WHERE code IN ('project.delete', 'project.restore')")
        ).scalar_one() == 2
        grants = connection.execute(
            text(
                "SELECT p.code, r.code FROM role_permissions rp "
                "JOIN permissions p ON p.id = rp.permission_id JOIN roles r ON r.id = rp.role_id "
                "WHERE p.code IN ('project.delete', 'project.restore')"
            )
        ).all()
        assert set(grants) == {
            ("project.delete", "administrador"),
            ("project.delete", "chefe_operacoes"),
            ("project.restore", "administrador"),
        }

    run_alembic("downgrade", parent)
    with local_engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == parent
        assert connection.execute(
            text("SELECT COUNT(*) FROM pragma_table_info('projects') WHERE name IN ('deleted_at', 'deleted_by_person_id')")
        ).scalar_one() == 0
        assert connection.execute(
            text("SELECT COUNT(*) FROM permissions WHERE code IN ('project.delete', 'project.restore')")
        ).scalar_one() == 0

    run_alembic("upgrade", revision)
    with local_engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == revision
        assert connection.execute(
            text("SELECT COUNT(*) FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id WHERE p.code IN ('project.delete', 'project.restore')")
        ).scalar_one() == 3
    local_engine.dispose()
