"""Camada de serviço para tarefas — ponto único onde a API verifica
permissões, valida a máquina de estados, e gera histórico. Nenhuma rota
deve escrever diretamente numa `Task` sem passar por aqui (mesmo padrão de
`app/services/projects.py`).
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import and_, or_
from sqlalchemy.orm import Query, Session

from app.audit.log import record_task_change
from app.models.people import Person
from app.models.project import Project
from app.models.task import (
    DEFAULT_TASK_TYPES,
    OPEN_TASK_STATUSES,
    STATUS_DONE,
    STATUS_TODO,
    TASK_PRIORITIES,
    TASK_STATUSES,
    Task,
)
from app.schemas.tasks import TaskCreate, TaskUpdate
from app.security.permissions import AuthContext, PermissionDenied, can_create_task, can_edit_task, can_view_task
from app.utils.timezones import today_lisbon

# Máquina de estados: de onde -> para onde é permitido ir diretamente.
# Um estado "transita" para si próprio como no-op (sempre permitido, sem
# gerar histórico — ver update_task). 'blocked' não pode saltar direto
# para 'done' (tem de desbloquear primeiro); 'cancelled'/'done' só reabrem
# para 'todo'/'in_progress' — nunca saltam entre si diretamente.
TASK_TRANSITIONS: dict[str, frozenset[str]] = {
    STATUS_TODO: frozenset({"todo", "in_progress", "blocked", "done", "cancelled"}),
    "in_progress": frozenset({"in_progress", "todo", "blocked", "done", "cancelled"}),
    "blocked": frozenset({"blocked", "todo", "in_progress", "cancelled"}),
    STATUS_DONE: frozenset({"done", "todo", "in_progress"}),
    "cancelled": frozenset({"cancelled", "todo"}),
}


class InvalidTaskTransition(ValueError):
    def __init__(self, old_status: str, new_status: str):
        super().__init__(f"Transição de estado não permitida: {old_status!r} -> {new_status!r}")
        self.old_status = old_status
        self.new_status = new_status


class InvalidTaskAssignment(ValueError):
    pass


def ensure_default_tasks_for_project(db: Session, project: Project) -> list[Task]:
    """Idempotente: cria só os tipos de tarefa padrão que ainda não existem
    para este projeto. Chamado pelo seed de desenvolvimento; disponível
    também para qualquer código futuro que precise de garantir a
    checklist padrão (ex. quando a criação de projeto existir)."""
    existing_types = {
        t.task_type for t in db.query(Task).filter(Task.project_id == project.id).all()
    }
    created: list[Task] = []
    for task_type, title in DEFAULT_TASK_TYPES:
        if task_type in existing_types:
            continue
        task = Task(project_id=project.id, title=title, task_type=task_type, status=STATUS_TODO)
        db.add(task)
        created.append(task)
    return created


def visible_tasks_query(db: Session, ctx: AuthContext) -> Query:
    if ctx.has_permission("task.view_all"):
        return db.query(Task)
    if ctx.has_permission("task.view_own"):
        return db.query(Task).join(Project, Task.project_id == Project.id).filter(
            or_(Project.pm_person_id == ctx.person_id, Task.assigned_to_person_id == ctx.person_id)
        )
    return db.query(Task).filter(False)


def list_tasks(
    db: Session,
    ctx: AuthContext,
    *,
    project_id: uuid.UUID | None = None,
    status: str | None = None,
    assigned_to_person_id: uuid.UUID | None = None,
    overdue_only: bool = False,
    due_before: dt.date | None = None,
    due_after: dt.date | None = None,
) -> list[Task]:
    query = visible_tasks_query(db, ctx)
    if project_id is not None:
        query = query.filter(Task.project_id == project_id)
    if status is not None:
        query = query.filter(Task.status == status)
    if assigned_to_person_id is not None:
        query = query.filter(Task.assigned_to_person_id == assigned_to_person_id)
    if due_before is not None:
        query = query.filter(Task.due_date <= due_before)
    if due_after is not None:
        query = query.filter(Task.due_date >= due_after)
    if overdue_only:
        query = query.filter(
            and_(Task.due_date.isnot(None), Task.due_date < today_lisbon(), Task.status.in_(OPEN_TASK_STATUSES))
        )
    return query.order_by(Task.due_date.is_(None), Task.due_date.asc(), Task.created_at.asc()).all()


def get_visible_task(db: Session, ctx: AuthContext, task_id: uuid.UUID) -> Task | None:
    task = db.get(Task, task_id)
    if task is None:
        return None
    if not can_view_task(ctx, task):
        return None
    return task


def create_task(db: Session, *, changes: TaskCreate, ctx: AuthContext) -> Task:
    project = db.get(Project, changes.project_id)
    if project is None:
        raise ValueError("Projeto não encontrado.")
    if not can_create_task(ctx, project):
        raise PermissionDenied("task.edit_all|task.edit_own")
    if changes.priority not in TASK_PRIORITIES:
        raise ValueError(f"Prioridade inválida: {changes.priority!r}")
    if changes.assigned_to_person_id is not None:
        if db.get(Person, changes.assigned_to_person_id) is None:
            raise InvalidTaskAssignment("Responsável atribuído não existe.")

    task = Task(
        project_id=changes.project_id,
        title=changes.title,
        task_type=changes.task_type,
        description=changes.description,
        priority=changes.priority,
        assigned_to_person_id=changes.assigned_to_person_id,
        due_date=changes.due_date,
        notes=changes.notes,
        status=STATUS_TODO,
        created_by_person_id=ctx.person_id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def update_task(db: Session, *, task: Task, changes: TaskUpdate, ctx: AuthContext) -> Task:
    if not can_edit_task(ctx, task):
        raise PermissionDenied("task.edit_all|task.edit_own")

    changed_fields = changes.model_dump(exclude_unset=True)

    if "priority" in changed_fields and changed_fields["priority"] not in TASK_PRIORITIES:
        raise ValueError(f"Prioridade inválida: {changed_fields['priority']!r}")

    if "assigned_to_person_id" in changed_fields:
        new_assignee = changed_fields["assigned_to_person_id"]
        if new_assignee is not None and db.get(Person, new_assignee) is None:
            raise InvalidTaskAssignment("Responsável atribuído não existe.")

    if "status" in changed_fields:
        new_status = changed_fields["status"]
        if new_status not in TASK_STATUSES:
            raise ValueError(f"Estado inválido: {new_status!r}")
        old_status = task.status
        if new_status != old_status and new_status not in TASK_TRANSITIONS.get(old_status, frozenset()):
            raise InvalidTaskTransition(old_status, new_status)

    for field_name, new_value in changed_fields.items():
        old_value = getattr(task, field_name)
        if old_value == new_value:
            continue
        record_task_change(
            db,
            task_id=task.id,
            field_name=field_name,
            old_value=str(old_value) if old_value is not None else None,
            new_value=str(new_value) if new_value is not None else None,
            source="ui",
            changed_by_person_id=ctx.person_id,
            note="Edição manual via API.",
        )
        setattr(task, field_name, new_value)

        if field_name == "status":
            if new_value == STATUS_DONE and old_value != STATUS_DONE:
                task.completed_at = dt.datetime.now(dt.timezone.utc)
            elif old_value == STATUS_DONE and new_value != STATUS_DONE:
                task.completed_at = None

    db.commit()
    db.refresh(task)
    return task
