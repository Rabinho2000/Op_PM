"""`Task.category` — vocabulário controlado, categorização das tarefas
padrão, validação em create/update, histórico por alteração de campo.
Ver app/models/task.py e docs/DECISIONS.md (FASE A do mapa operacional).
"""
from __future__ import annotations

from app.models.people import Person
from app.models.project import Project
from app.models.task import (
    DEFAULT_TASK_TYPE_CATEGORIES,
    OPERATIONAL_TASK_CATEGORIES,
    TASK_CATEGORIES,
    TASK_CATEGORY_DOCUMENTATION,
    TASK_CATEGORY_FIELD,
    TASK_CATEGORY_MATERIAL,
    TASK_CATEGORY_OTHER,
    TASK_CATEGORY_WORKFLOW,
    Task,
    TaskHistory,
)
from app.services.tasks import ensure_default_tasks_for_project


def _headers(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def _own_project(db):
    return db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()


def test_operational_categories_are_field_and_material():
    assert OPERATIONAL_TASK_CATEGORIES == {TASK_CATEGORY_FIELD, TASK_CATEGORY_MATERIAL}
    assert TASK_CATEGORY_WORKFLOW not in OPERATIONAL_TASK_CATEGORIES
    assert TASK_CATEGORY_DOCUMENTATION not in OPERATIONAL_TASK_CATEGORIES


def test_default_task_type_categories_cover_every_default_type():
    from app.models.task import DEFAULT_TASK_TYPES

    for task_type, _title in DEFAULT_TASK_TYPES:
        assert task_type in DEFAULT_TASK_TYPE_CATEGORIES
        assert DEFAULT_TASK_TYPE_CATEGORIES[task_type] in TASK_CATEGORIES


def test_seeded_default_tasks_have_correct_category(db_session):
    db = db_session
    project = _own_project(db)
    tasks = {t.task_type: t for t in db.query(Task).filter(Task.project_id == project.id).all()}
    assert tasks["visita_tecnica"].category == TASK_CATEGORY_WORKFLOW
    assert tasks["preparacao_instalacao"].category == TASK_CATEGORY_WORKFLOW
    assert tasks["instalacao"].category == TASK_CATEGORY_WORKFLOW
    assert tasks["comissionamento"].category == TASK_CATEGORY_WORKFLOW
    assert tasks["fotos_drive"].category == TASK_CATEGORY_DOCUMENTATION


def test_ensure_default_tasks_is_idempotent_and_keeps_categories(db_session):
    db = db_session
    project = _own_project(db)
    before_count = db.query(Task).filter(Task.project_id == project.id).count()
    created = ensure_default_tasks_for_project(db, project)
    db.commit()
    assert created == []  # já existem, idempotente — nada duplicado
    after_count = db.query(Task).filter(Task.project_id == project.id).count()
    assert after_count == before_count


def test_custom_task_defaults_to_other_category(db_session, api_client):
    db = db_session
    project = _own_project(db)
    resp = api_client.post(
        "/api/tasks",
        json={"project_id": str(project.id), "title": "Tarefa ad-hoc sem categoria"},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 201
    assert resp.json()["category"] == TASK_CATEGORY_OTHER


def test_create_task_with_explicit_category(db_session, api_client):
    project = _own_project(db_session)
    resp = api_client.post(
        "/api/tasks",
        json={
            "project_id": str(project.id),
            "title": "Recolher módulos",
            "category": TASK_CATEGORY_MATERIAL,
        },
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 201
    assert resp.json()["category"] == TASK_CATEGORY_MATERIAL


def test_create_task_with_invalid_category_is_rejected(db_session, api_client):
    project = _own_project(db_session)
    resp = api_client.post(
        "/api/tasks",
        json={"project_id": str(project.id), "title": "Categoria inválida", "category": "nao_existe"},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp.status_code == 400


def test_update_task_category_generates_history(db_session, api_client):
    db = db_session
    project = _own_project(db)
    task = db.query(Task).filter(Task.project_id == project.id, Task.task_type == "custom").first()
    if task is None:
        task = Task(project_id=project.id, title="Tarefa de teste", category=TASK_CATEGORY_OTHER)
        db.add(task)
        db.commit()
        db.refresh(task)

    resp = api_client.patch(
        f"/api/tasks/{task.id}",
        json={"category": TASK_CATEGORY_FIELD},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp.status_code == 200
    assert resp.json()["category"] == TASK_CATEGORY_FIELD

    history = (
        db.query(TaskHistory)
        .filter(TaskHistory.task_id == task.id, TaskHistory.field_name == "category")
        .order_by(TaskHistory.changed_at.desc())
        .first()
    )
    assert history is not None
    assert history.new_value == TASK_CATEGORY_FIELD


def test_update_task_with_invalid_category_is_rejected(db_session, api_client):
    db = db_session
    project = _own_project(db)
    task = db.query(Task).filter(Task.project_id == project.id).first()
    resp = api_client.patch(
        f"/api/tasks/{task.id}",
        json={"category": "nao_existe"},
        headers=_headers("chefe.sintetico@example.invalid"),
    )
    assert resp.status_code == 400
