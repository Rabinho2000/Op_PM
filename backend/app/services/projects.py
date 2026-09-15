"""Camada de serviço para leitura/escrita de projetos — ponto único onde a
API verifica permissões e gera histórico. Nenhuma rota deve escrever
diretamente num `Project` sem passar por aqui (ver
`app/api/routes_projects.py`).
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import uuid

from sqlalchemy import func, or_
from sqlalchemy.orm import Query, Session

from app.audit.log import record_project_change
from app.models.project import Project
from app.models.task import DEFAULT_TASK_TYPES, OPEN_TASK_STATUSES, STATUS_DONE, TASK_TYPE_FOTOS_DRIVE, TASK_TYPES_REQUIRE_PHOTOS, Task
from app.schemas.projects import ProjectUpdate
from app.security.permissions import AuthContext, PermissionDenied, can_edit_project, can_view_project
from app.security.project_fields import PM_EDITABLE_PROJECT_FIELDS

_STANDARD_TASK_TYPES = frozenset(code for code, _ in DEFAULT_TASK_TYPES)


@dataclasses.dataclass
class ProjectTaskSummary:
    """Indicadores de tarefas de um projeto, para a lista/detalhe de
    projetos (ver docs sobre Fase 1.5 — MVP dashboard/workflow). Calculado
    sempre a partir das tarefas reais em base de dados, nunca hardcoded."""

    status: str  # nao_iniciado | em_curso | concluido
    next_task_title: str | None
    next_task_due_date: dt.date | None
    overdue_tasks_count: int
    workflow_progress_percent: int
    photos_pending_warning: bool


def compute_project_task_summary(db: Session, project_id: uuid.UUID) -> ProjectTaskSummary:
    tasks = db.query(Task).filter(Task.project_id == project_id).all()

    if not tasks:
        return ProjectTaskSummary(
            status="nao_iniciado",
            next_task_title=None,
            next_task_due_date=None,
            overdue_tasks_count=0,
            workflow_progress_percent=0,
            photos_pending_warning=False,
        )

    standard_tasks = [t for t in tasks if t.task_type in _STANDARD_TASK_TYPES]
    standard_done = sum(1 for t in standard_tasks if t.status == STATUS_DONE)
    standard_total = len(standard_tasks) or len(DEFAULT_TASK_TYPES)
    workflow_progress_percent = round(100 * standard_done / standard_total)

    if standard_tasks and standard_done == len(standard_tasks):
        status = "concluido"
    elif standard_done > 0 or any(t.status != "todo" for t in standard_tasks):
        status = "em_curso"
    else:
        status = "nao_iniciado"

    open_tasks = [t for t in tasks if t.status in OPEN_TASK_STATUSES]
    next_task = None
    if open_tasks:
        next_task = min(
            open_tasks,
            key=lambda t: (t.due_date is None, t.due_date or dt.date.max, t.created_at),
        )
    overdue_tasks_count = sum(1 for t in tasks if t.is_overdue)

    photos_required_done = any(t.task_type in TASK_TYPES_REQUIRE_PHOTOS and t.status == STATUS_DONE for t in tasks)
    photos_task_done = any(t.task_type == TASK_TYPE_FOTOS_DRIVE and t.status == STATUS_DONE for t in tasks)
    photos_pending_warning = photos_required_done and not photos_task_done

    return ProjectTaskSummary(
        status=status,
        next_task_title=next_task.title if next_task else None,
        next_task_due_date=next_task.due_date if next_task else None,
        overdue_tasks_count=overdue_tasks_count,
        workflow_progress_percent=workflow_progress_percent,
        photos_pending_warning=photos_pending_warning,
    )


def visible_projects_query(db: Session, ctx: AuthContext) -> Query:
    """Restringe a query à visibilidade do utilizador — nunca devolve tudo
    e filtra depois em Python (evita esquecer o filtro nalgum sítio)."""
    if ctx.has_permission("project.view_all"):
        return db.query(Project)
    if ctx.has_permission("project.view_own"):
        return db.query(Project).filter(Project.pm_person_id == ctx.person_id)
    # Sem nenhuma das duas permissões: nada visível.
    return db.query(Project).filter(False)


def list_projects(
    db: Session,
    ctx: AuthContext,
    *,
    pm_person_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    search: str | None = None,
) -> list[Project]:
    query = visible_projects_query(db, ctx)
    if pm_person_id is not None:
        query = query.filter(Project.pm_person_id == pm_person_id)
    if is_active is not None:
        query = query.filter(Project.is_active == is_active)
    if search:
        pattern = f"%{search.strip().lower()}%"
        query = query.filter(
            or_(
                func.lower(Project.name).like(pattern),
                func.lower(Project.client_name).like(pattern),
                func.lower(Project.client_contact).like(pattern),
            )
        )
    return query.order_by(Project.name.asc()).all()


def get_visible_project(db: Session, ctx: AuthContext, project_id: uuid.UUID) -> Project | None:
    project = db.get(Project, project_id)
    if project is None:
        return None
    if not can_view_project(ctx, project):
        return None
    return project


def update_project(
    db: Session,
    *,
    project: Project,
    changes: ProjectUpdate,
    ctx: AuthContext,
) -> Project:
    """Só isto escreve num `Project` a partir da API. Verifica permissão
    primeiro (nunca confia no chamador já ter verificado); gera uma
    entrada de `project_history` por campo efetivamente alterado — nunca
    uma escrita silenciosa.

    Restrição de campo (D-028): quem só tem `project.edit_own_progress`
    (nunca `project.edit_all`) está limitado à allowlist explícita
    `PM_EDITABLE_PROJECT_FIELDS` — nunca pode tocar em `name`,
    `client_email`, `client_contact`, `pm_person_id`, `is_active`, ou
    qualquer outro campo administrativo, mesmo que seja o PM do projeto.
    Um pedido com QUALQUER campo fora da allowlist é rejeitado por
    inteiro, antes de qualquer escrita — nunca aplica só os campos
    permitidos e ignora os outros em silêncio."""
    if not can_edit_project(ctx, project):
        raise PermissionDenied("project.edit_all|project.edit_own_progress")

    # exclude_unset: um campo omitido do pedido nunca é tocado; um campo
    # presente com valor `null` limpa-o explicitamente — distinção
    # importante para não apagar dados por omissão de um campo no body.
    changed_fields = changes.model_dump(exclude_unset=True)

    if not ctx.has_permission("project.edit_all"):
        # Chegou aqui só com project.edit_own_progress (can_edit_project já
        # garantiu que é o PM deste projeto) — restringe à allowlist.
        disallowed_fields = sorted(set(changed_fields) - PM_EDITABLE_PROJECT_FIELDS)
        if disallowed_fields:
            raise PermissionDenied(
                f"project.edit_all (campos administrativos não permitidos a "
                f"project.edit_own_progress: {', '.join(disallowed_fields)})"
            )

    for field_name, new_value in changed_fields.items():
        old_value = getattr(project, field_name)
        if old_value == new_value:
            continue
        record_project_change(
            db,
            project_id=project.id,
            field_name=field_name,
            old_value=str(old_value) if old_value is not None else None,
            new_value=str(new_value) if new_value is not None else None,
            source="ui",
            changed_by_person_id=ctx.person_id,
            note="Edição manual via API.",
        )
        setattr(project, field_name, new_value)

    db.commit()
    db.refresh(project)
    return project
