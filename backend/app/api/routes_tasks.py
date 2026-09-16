"""Endpoints de tarefa: listagem/filtros, detalhe, criação, edição
autorizada (incl. transição de estado/atribuição), e histórico. Toda a
escrita passa por `app/services/tasks.py` — nenhuma rota aqui manipula
`Task`/`TaskHistory` diretamente.
"""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.people import Person
from app.models.project import Project
from app.models.task import Task, TaskHistory
from app.schemas.tasks import TaskCreate, TaskHistoryRead, TaskRead, TaskUpdate
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext, PermissionDenied, can_edit_task
from app.services.tasks import InvalidTaskAssignment, InvalidTaskTransition, create_task, get_visible_task, list_tasks
from app.services.tasks import update_task as update_task_service

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _to_read(db: Session, task: Task, ctx: AuthContext) -> TaskRead:
    data = TaskRead.model_validate(task)
    project = task.project or db.get(Project, task.project_id)
    data.project_name = project.name if project else None
    if task.assigned_to_person_id:
        assignee = task.assigned_to or db.get(Person, task.assigned_to_person_id)
        data.assigned_to_display_name = assignee.display_name if assignee else None
    data.is_overdue = task.is_overdue
    data.can_edit = can_edit_task(ctx, task)
    return data


@router.get("", response_model=list[TaskRead])
def list_tasks_endpoint(
    project_id: uuid.UUID | None = None,
    status: str | None = None,
    assigned_to_person_id: uuid.UUID | None = None,
    overdue_only: bool = False,
    due_before: dt.date | None = Query(default=None),
    due_after: dt.date | None = Query(default=None),
    priority: str | None = Query(default=None, description="low | medium | high | urgent"),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[TaskRead]:
    tasks = list_tasks(
        db,
        ctx,
        project_id=project_id,
        status=status,
        assigned_to_person_id=assigned_to_person_id,
        overdue_only=overdue_only,
        due_before=due_before,
        due_after=due_after,
        priority=priority,
    )
    return [_to_read(db, t, ctx) for t in tasks]


@router.get("/{task_id}", response_model=TaskRead)
def get_task_endpoint(
    task_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> TaskRead:
    task = get_visible_task(db, ctx, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada ou sem permissão para a ver.")
    return _to_read(db, task, ctx)


@router.post("", response_model=TaskRead, status_code=201)
def create_task_endpoint(
    body: TaskCreate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> TaskRead:
    try:
        task = create_task(db, changes=body, ctx=ctx)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=f"Sem permissão para criar tarefas neste projeto: {exc}")
    except InvalidTaskAssignment as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _to_read(db, task, ctx)


@router.patch("/{task_id}", response_model=TaskRead)
def update_task_endpoint(
    task_id: uuid.UUID,
    body: TaskUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> TaskRead:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.")
    try:
        updated = update_task_service(db, task=task, changes=body, ctx=ctx)
    except PermissionDenied as exc:
        raise HTTPException(status_code=403, detail=f"Sem permissão para editar esta tarefa: {exc}")
    except InvalidTaskTransition as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except InvalidTaskAssignment as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _to_read(db, updated, ctx)


@router.get("/{task_id}/history", response_model=list[TaskHistoryRead])
def get_task_history_endpoint(
    task_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[TaskHistoryRead]:
    task = get_visible_task(db, ctx, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada ou sem permissão para a ver.")

    entries = (
        db.query(TaskHistory)
        .filter(TaskHistory.task_id == task_id)
        .order_by(TaskHistory.changed_at.desc())
        .all()
    )
    result: list[TaskHistoryRead] = []
    for entry in entries:
        data = TaskHistoryRead.model_validate(entry)
        if entry.changed_by_person_id:
            person = db.get(Person, entry.changed_by_person_id)
            data.changed_by_person_name = person.display_name if person else None
        result.append(data)
    return result
