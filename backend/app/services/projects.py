"""Camada de serviço para leitura/escrita de projetos — ponto único onde a
API verifica permissões e gera histórico. Nenhuma rota deve escrever
diretamente num `Project` sem passar por aqui (ver
`app/api/routes_projects.py`).
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import re
import uuid

from sqlalchemy import case, func, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Query, Session

from app.audit.log import record_project_change
from app.models.identity import Role, User, UserRole
from app.models.people import Person
from app.models.project import Project
from app.models.task import DEFAULT_TASK_TYPES, OPEN_TASK_STATUSES, STATUS_DONE, TASK_TYPE_FOTOS_DRIVE, TASK_TYPES_REQUIRE_PHOTOS, Task
from app.schemas.projects import ProjectCreate, ProjectUpdate
from app.security.catalog import ROLE_PM
from app.security.permissions import (
    AuthContext,
    DENIED_INSTALLER_READ_ONLY,
    PermissionDenied,
    can_change_project_status,
    can_edit_project,
    is_installer_readonly_scope,
    installer_project_scope_conditions,
)
from app.services.project_lifecycle import (
    COMPLETED_LIFECYCLE_STATUSES,
    LIFECYCLE_FLOW,
    LIFECYCLE_STATUS_CODES,
    status_change_warning,
)
from app.services.installers import derive_work_window
from app.security.project_fields import PM_EDITABLE_PROJECT_FIELDS
from app.utils.text import normalize_key
from app.security.perm import Perm

_STANDARD_TASK_TYPES = frozenset(code for code, _ in DEFAULT_TASK_TYPES)
_NUMERIC_PROJECT_PREFIX = re.compile(r"^\s*(\d+)_")


class DuplicateProjectName(ValueError):
    """A normalized project name is already used by a non-deleted project."""


def _normalize_project_name(value: str) -> str:
    return normalize_key(value)


def _project_numeric_prefix(value: str) -> str | None:
    match = _NUMERIC_PROJECT_PREFIX.match(value)
    return match.group(1) if match else None


def _query_numeric_prefix(value: str) -> str | None:
    # A pesquisa aceita o separador visual usado pela pessoa ou o `_`
    # canónico usado nos nomes guardados; candidatos continuam estritos.
    match = re.match(r"^\s*(\d+)(?:_|\s+)", value)
    return match.group(1) if match else None


def eligible_project_managers(db: Session) -> list[tuple[uuid.UUID, str]]:
    """People who can be assigned as PM on a manually created project."""
    return (
        db.query(Person.id, Person.display_name)
        .join(User, User.person_id == Person.id)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .filter(
            Person.is_active.is_(True),
            User.is_active.is_(True),
            Role.code == ROLE_PM,
        )
        .distinct()
        .order_by(Person.display_name, Person.id)
        .all()
    )


def check_project_name(db: Session, *, name: str, ctx: AuthContext) -> list[Project]:
    """Return active project candidates sharing a normalized name or numeric prefix."""
    if is_installer_readonly_scope(ctx):
        raise PermissionDenied(DENIED_INSTALLER_READ_ONLY)
    ctx.require(Perm.PROJECT_EDIT_ALL)

    normalized = _normalize_project_name(name)
    prefix = _query_numeric_prefix(name)
    projects = db.query(Project).filter(Project.deleted_at.is_(None)).order_by(Project.name).all()
    return [
        project
        for project in projects
        if _normalize_project_name(project.name) == normalized
        or (prefix is not None and _project_numeric_prefix(project.name) == prefix)
    ]


def create_project(db: Session, *, body: ProjectCreate, ctx: AuthContext, commit: bool = True) -> Project:
    """Create a project and its audit trail atomically. Permission is checked
    here as well as by the route so no alternate caller can bypass RBAC.
    With the default ``commit=True`` the service commits and returns the ORM
    object; ``commit=False`` leaves the flushed project and audit rows in the
    caller's transaction, without refreshing or committing, so a route can
    build its response before deciding to commit."""
    if is_installer_readonly_scope(ctx):
        raise PermissionDenied(DENIED_INSTALLER_READ_ONLY)
    ctx.require(Perm.PROJECT_EDIT_ALL)

    name = body.name
    normalized_name = _normalize_project_name(name)
    if db.get_bind().dialect.name == "postgresql":
        # Uma colisão de hash só serializa nomes diferentes em conjunto.
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:normalized_name))"),
            {"normalized_name": normalized_name},
        )
    candidates = db.query(Project).filter(Project.deleted_at.is_(None)).all()
    if any(_normalize_project_name(project.name) == normalized_name for project in candidates):
        raise DuplicateProjectName("Já existe um projeto com este nome.")

    pm_person_id = body.pm_person_id
    if pm_person_id is not None:
        if pm_person_id not in {person_id for person_id, _ in eligible_project_managers(db)}:
            raise ValueError("O PM selecionado não existe, está inativo ou não tem o papel de PM.")

    provided_fields = body.model_dump(exclude_unset=True)
    provided_fields.pop("name", None)
    provided_fields.pop("pm_person_id", None)
    try:
        project = Project(
            name=name,
            is_active=True,
            pm_person_id=pm_person_id,
            lifecycle_status=body.lifecycle_status,
        )
        for field_name, value in provided_fields.items():
            # `notes` is non-nullable in the model; null means leave its
            # normal empty-string default in place.
            if value is not None:
                setattr(project, field_name, value)

        # A criação pela UI entra no programa agora. A promoção de staging
        # mantém a data de início do ClickUp, que representa o legado.
        project.entered_at = dt.datetime.now(dt.timezone.utc)
        work_window = derive_work_window(project.start_date)
        if work_window is not None:
            project.work_start_date, project.work_end_date = work_window
            project.work_dates_estimated = True

        db.add(project)
        db.flush()

        audit_values = {"name": name, "lifecycle_status": project.lifecycle_status, **provided_fields}
        if pm_person_id is not None:
            audit_values["pm_person_id"] = pm_person_id
        for field_name, value in audit_values.items():
            if value is None:
                continue
            record_project_change(
                db,
                project_id=project.id,
                field_name=field_name,
                old_value=None,
                new_value=str(value),
                source="ui",
                changed_by_person_id=ctx.person_id,
                note="Criação manual via API.",
            )
        record_project_change(
            db,
            project_id=project.id,
            field_name="project_created",
            old_value=None,
            new_value=str(project.id),
            source="ui",
            changed_by_person_id=ctx.person_id,
            note="Criação manual via API.",
        )

        if commit:
            db.commit()
        return project
    except IntegrityError as exc:
        db.rollback()
        duplicate = any(
            _normalize_project_name(existing_name) == normalized_name
            for (existing_name,) in db.query(Project.name)
            .filter(Project.deleted_at.is_(None))
            .all()
        )
        if duplicate:
            raise DuplicateProjectName("Já existe um projeto com este nome.") from exc
        raise
    except Exception:
        db.rollback()
        raise


def _utc_isoformat(value: dt.datetime) -> str:
    """Serializa datas em UTC também quando SQLite remove o tzinfo ao ler."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    else:
        value = value.astimezone(dt.timezone.utc)
    return value.isoformat()


@dataclasses.dataclass
class ProjectTaskSummary:
    """Indicadores de tarefas de um projeto, para a lista/detalhe de
    projetos (ver docs sobre Fase 1.5 — MVP dashboard/workflow). Calculado
    a partir das tarefas reais; o `status` também considera os estados finais
    do ciclo de vida definidos em `project_lifecycle.py`."""

    status: str  # nao_iniciado | em_curso | concluido
    next_task_title: str | None
    next_task_due_date: dt.date | None
    overdue_tasks_count: int
    workflow_progress_percent: int
    photos_pending_warning: bool


def compute_project_task_summary(db: Session, project_id: uuid.UUID) -> ProjectTaskSummary:
    project = db.get(Project, project_id)
    tasks = db.query(Task).filter(Task.project_id == project_id).all()
    return compute_project_task_summary_from_tasks(
        tasks,
        lifecycle_status=project.lifecycle_status if project else None,
    )


def compute_project_task_summary_from_tasks(
    tasks: list[Task], *, lifecycle_status: str | None = None
) -> ProjectTaskSummary:
    """Mesmo cálculo de `compute_project_task_summary`, mas a partir de uma
    lista de tarefas já carregada — usada por quem precisa do resumo de
    vários projetos de uma vez (ex. app/services/map.py) sem repetir uma
    query de tarefas por projeto (padrão N+1 — ver docs/DECISIONS.md,
    mapa operacional). `lifecycle_status` só altera o estado derivado;
    os restantes indicadores continuam a refletir as tarefas recebidas."""
    if not tasks:
        return ProjectTaskSummary(
            status="concluido" if lifecycle_status in COMPLETED_LIFECYCLE_STATUSES else "nao_iniciado",
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

    if lifecycle_status in COMPLETED_LIFECYCLE_STATUSES:
        status = "concluido"

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


# D-077: agrupa por estado (na ordem do fluxo) e, dentro de cada um, por ordem
# cronológica de entrada no programa; desempata pela data de ligação (texto ISO)
# e pelo nome. Sem estado no fim.
_STATE_ORDER = ("on_hold_cliente", *LIFECYCLE_FLOW)
PROJECT_LIST_ORDER = (
    case({code: i for i, code in enumerate(_STATE_ORDER)}, value=Project.lifecycle_status, else_=len(_STATE_ORDER)).asc(),
    func.coalesce(Project.entered_at, Project.created_at).asc(),
    func.coalesce(Project.upac_connection_date_raw, "9999-99-99").asc(),
    Project.name.asc(),
)


def visible_projects_query(db: Session, ctx: AuthContext) -> Query:
    """Restringe a query à visibilidade do utilizador — nunca devolve tudo
    e filtra depois em Python (evita esquecer o filtro nalgum sítio)."""
    query = db.query(Project).filter(Project.deleted_at.is_(None))
    if ctx.has_permission(Perm.PROJECT_VIEW_ALL):
        return query

    conditions = []
    if ctx.has_permission(Perm.PROJECT_VIEW_OWN):
        conditions.append(Project.pm_person_id == ctx.person_id)
    if ctx.has_permission(Perm.PROJECT_VIEW_DELEGATED) and ctx.delegating_pm_ids:
        conditions.append(Project.pm_person_id.in_(ctx.delegating_pm_ids))
    conditions.extend(installer_project_scope_conditions(ctx))
    if conditions:
        return query.filter(or_(*conditions))
    # Sem nenhuma das permissões, ou sem delegações/associações atribuídas: nada visível.
    return query.filter(False)


def list_projects(
    db: Session,
    ctx: AuthContext,
    *,
    pm_person_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    search: str | None = None,
    start_from: dt.date | None = None,
    start_to: dt.date | None = None,
    lifecycle_statuses: list[str] | None = None,
) -> list[Project]:
    query = visible_projects_query(db, ctx)
    if lifecycle_statuses:
        query = query.filter(Project.lifecycle_status.in_(lifecycle_statuses))
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
    if start_from is not None:
        query = query.filter(Project.start_date >= start_from)
    if start_to is not None:
        query = query.filter(Project.start_date <= start_to)
    return query.order_by(*PROJECT_LIST_ORDER).all()


def get_visible_project(db: Session, ctx: AuthContext, project_id: uuid.UUID) -> Project | None:
    """Read a project through the same SQL scope used by list endpoints."""
    return visible_projects_query(db, ctx).filter(Project.id == project_id).one_or_none()


def delete_project(db: Session, *, project: Project, reason: str, ctx: AuthContext) -> Project:
    """Remove um projeto da operação sem apagar os seus dados nem o histórico."""
    ctx.require(Perm.PROJECT_DELETE)
    note = reason.strip()
    if not note:
        raise ValueError("Indique o motivo da remoção.")
    if project.deleted_at is not None:
        raise ValueError("O projeto já está apagado.")
    deleted_at = dt.datetime.now(dt.timezone.utc)
    record_project_change(
        db,
        project_id=project.id,
        field_name="deleted_at",
        old_value=None,
        new_value=deleted_at.isoformat(),
        source="ui",
        changed_by_person_id=ctx.person_id,
        note=note,
    )
    project.deleted_at = deleted_at
    project.deleted_by_person_id = ctx.person_id
    db.commit()
    db.refresh(project)
    return project


def restore_project(db: Session, *, project: Project, ctx: AuthContext) -> Project:
    """Restaura um projeto apagado, preservando a auditoria de ambas ações."""
    ctx.require(Perm.PROJECT_RESTORE)
    if project.deleted_at is None:
        raise ValueError("O projeto não está apagado.")
    deleted_at = project.deleted_at
    deleted_by_person_id = project.deleted_by_person_id
    for field_name, old_value in (
        ("deleted_at", _utc_isoformat(deleted_at)),
        ("deleted_by_person_id", str(deleted_by_person_id) if deleted_by_person_id else None),
    ):
        record_project_change(
            db,
            project_id=project.id,
            field_name=field_name,
            old_value=old_value,
            new_value=None,
            source="ui",
            changed_by_person_id=ctx.person_id,
            note="Restauro do projeto via API.",
        )
    project.deleted_at = None
    project.deleted_by_person_id = None
    db.commit()
    db.refresh(project)
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
    if is_installer_readonly_scope(ctx):
        raise PermissionDenied(DENIED_INSTALLER_READ_ONLY)
    if not can_edit_project(ctx, project):
        raise PermissionDenied(f"{Perm.PROJECT_EDIT_ALL}|{Perm.PROJECT_EDIT_OWN_PROGRESS}")

    # exclude_unset: um campo omitido do pedido nunca é tocado; um campo
    # presente com valor `null` limpa-o explicitamente — distinção
    # importante para não apagar dados por omissão de um campo no body.
    changed_fields = changes.model_dump(exclude_unset=True)

    if not ctx.has_permission(Perm.PROJECT_EDIT_ALL):
        # Chegou aqui só com project.edit_own_progress (can_edit_project já
        # garantiu que é o PM deste projeto) — restringe à allowlist.
        disallowed_fields = sorted(set(changed_fields) - PM_EDITABLE_PROJECT_FIELDS)
        if disallowed_fields:
            raise PermissionDenied(
                f"{Perm.PROJECT_EDIT_ALL} (campos administrativos não permitidos a "
                f"{Perm.PROJECT_EDIT_OWN_PROGRESS}: {', '.join(disallowed_fields)})"
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


def change_lifecycle_status(
    db: Session,
    *,
    project: Project,
    new_status: str,
    note: str,
    ctx: AuthContext,
) -> tuple[Project, str | None]:
    """Só isto altera `Project.lifecycle_status` a partir da API. Verifica a
    permissão primeiro, valida o código, escreve uma entrada de
    `project_history` (quem, quando, de/para, nota) e devolve, além do
    projeto, um aviso opcional quando a mudança salta estados (D6 — livre, só
    avisa). Repetir o estado atual é um no-op: sem histórico, sem aviso."""
    if not can_change_project_status(ctx, project):
        raise PermissionDenied(Perm.PROJECT_CHANGE_STATUS)
    if new_status not in LIFECYCLE_STATUS_CODES:
        raise ValueError(f"Estado de projeto inválido: {new_status!r}")
    old_status = project.lifecycle_status
    if old_status == new_status:
        return project, None
    record_project_change(
        db,
        project_id=project.id,
        field_name="lifecycle_status",
        old_value=old_status,
        new_value=new_status,
        source="ui",
        changed_by_person_id=ctx.person_id,
        note=note.strip() or "Mudança de estado via API.",
    )
    project.lifecycle_status = new_status
    db.commit()
    db.refresh(project)
    return project, status_change_warning(old_status, new_status)
