"""Indicadores de tarefas derivados no `ProjectRead` (estado, próxima
tarefa, tarefas atrasadas, progresso, aviso de fotos) — ver
app/services/projects.py:compute_project_task_summary. Nunca hardcoded:
sempre recalculado a partir das tarefas reais."""
from __future__ import annotations

import datetime as dt

from app.models.project import Project
from app.models.task import Task
from app.services.projects import compute_project_task_summary


def _headers(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def test_project_without_tasks_is_not_started(db_session):
    project = Project(name="Projeto Sintético Sem Tarefas")
    db_session.add(project)
    db_session.commit()

    summary = compute_project_task_summary(db_session, project.id)
    assert summary.status == "nao_iniciado"
    assert summary.workflow_progress_percent == 0
    assert summary.next_task_title is None
    assert summary.overdue_tasks_count == 0
    assert summary.photos_pending_warning is False


def test_project_with_all_standard_tasks_done_is_concluded(db_session):
    project = Project(name="Projeto Sintético Concluído")
    db_session.add(project)
    db_session.flush()
    for task_type in ("visita_tecnica", "preparacao_instalacao", "instalacao", "comissionamento", "fotos_drive"):
        db_session.add(Task(project_id=project.id, title=task_type, task_type=task_type, status="done"))
    db_session.commit()

    summary = compute_project_task_summary(db_session, project.id)
    assert summary.status == "concluido"
    assert summary.workflow_progress_percent == 100
    assert summary.photos_pending_warning is False


def test_next_task_is_earliest_open_task_by_due_date(db_session):
    project = Project(name="Projeto Sintético Próxima Tarefa")
    db_session.add(project)
    db_session.flush()
    today = dt.date.today()
    db_session.add(Task(project_id=project.id, title="Tarefa distante", due_date=today + dt.timedelta(days=20)))
    db_session.add(Task(project_id=project.id, title="Tarefa próxima", due_date=today + dt.timedelta(days=2)))
    db_session.add(Task(project_id=project.id, title="Tarefa concluída", status="done", due_date=today))
    db_session.commit()

    summary = compute_project_task_summary(db_session, project.id)
    assert summary.next_task_title == "Tarefa próxima"
    assert summary.next_task_due_date == today + dt.timedelta(days=2)


def test_overdue_tasks_counted_only_when_open(db_session):
    project = Project(name="Projeto Sintético Atrasado")
    db_session.add(project)
    db_session.flush()
    today = dt.date.today()
    db_session.add(Task(project_id=project.id, title="Atrasada aberta", due_date=today - dt.timedelta(days=3)))
    db_session.add(
        Task(project_id=project.id, title="Atrasada mas concluída", status="done", due_date=today - dt.timedelta(days=3))
    )
    db_session.commit()

    summary = compute_project_task_summary(db_session, project.id)
    assert summary.overdue_tasks_count == 1


def test_photos_warning_only_when_visit_or_commissioning_done_and_photos_not(db_session):
    project = Project(name="Projeto Sintético Aviso Fotos")
    db_session.add(project)
    db_session.flush()
    db_session.add(Task(project_id=project.id, title="Visita", task_type="visita_tecnica", status="done"))
    db_session.add(Task(project_id=project.id, title="Fotos", task_type="fotos_drive", status="todo"))
    db_session.commit()

    summary = compute_project_task_summary(db_session, project.id)
    assert summary.photos_pending_warning is True

    photos_task = db_session.query(Task).filter(Task.project_id == project.id, Task.task_type == "fotos_drive").one()
    photos_task.status = "done"
    db_session.commit()

    summary_after = compute_project_task_summary(db_session, project.id)
    assert summary_after.photos_pending_warning is False


def test_project_list_endpoint_includes_task_summary_fields(api_client):
    resp = api_client.get("/api/projects", headers=_headers("chefe.sintetico@example.invalid"))
    assert resp.status_code == 200
    body = resp.json()
    assert body
    for project in body:
        assert project["status"] in {"nao_iniciado", "em_curso", "concluido"}
        assert isinstance(project["workflow_progress_percent"], int)
        assert isinstance(project["overdue_tasks_count"], int)
        assert isinstance(project["photos_pending_warning"], bool)
