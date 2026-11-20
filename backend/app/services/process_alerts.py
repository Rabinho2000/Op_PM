"""Alarmes de etapas do processo.

Um utilizador subscreve etapas do catálogo. Quando uma etapa subscrita fica completa
num projeto (a última subtarefa é marcada), cria-se uma notificação in-app para cada
subscritor que (a) continua ativo, (b) tem `process_alert.use` e (c) pode ver esse
projeto hoje (`can_view_project`). Quem fez a ação não recebe.

Regras:
* uma notificação por (utilizador, projeto, etapa, transição para completa);
* desmarcar não apaga notificações; voltar a completar gera uma nova;
* sem email: só notificações in-app (`app.models.notification.Notification`).
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.identity import User
from app.models.notification import Notification
from app.models.process_alerts import ProcessStageSubscription
from app.models.project import Project, ProjectSubtaskProgress
from app.models.workflow import Phase, WorkflowStage, WorkflowSubtask
from app.security.permissions import (
    AuthContext,
    can_view_project,
    is_installer_readonly_scope,
    load_auth_context,
)
from app.security.perm import Perm

PERMISSION = Perm.PROCESS_ALERT_USE
KIND_STAGE_COMPLETED = "process_stage_completed"
ENTITY_PROJECT = "project"
MAX_PAGE_SIZE = 100


class ProcessAlertError(ValueError):
    pass


class ProcessAlertForbidden(ProcessAlertError):
    pass


class ProcessAlertNotFound(ProcessAlertError):
    pass


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def require_alert_permission(ctx: AuthContext) -> None:
    if is_installer_readonly_scope(ctx) or not ctx.has_permission(PERMISSION):
        raise ProcessAlertForbidden("Sem permissão para alarmes do processo.")


# --- subscrições -----------------------------------------------------------------


def catalog_with_subscriptions(db: Session, user: User) -> list[dict]:
    """Etapas do catálogo agrupadas por fase, com a flag `subscribed` do utilizador."""
    subscribed = {
        stage_id
        for (stage_id,) in db.query(ProcessStageSubscription.stage_id)
        .filter(ProcessStageSubscription.user_id == user.id)
        .all()
    }
    phases = db.query(Phase).order_by(Phase.sort_order).all()
    result = []
    for phase in phases:
        stages = (
            db.query(WorkflowStage)
            .filter(WorkflowStage.phase_id == phase.id)
            .order_by(WorkflowStage.sort_order)
            .all()
        )
        if not stages:
            continue
        result.append(
            {
                "id": phase.id,
                "code": phase.code,
                "name": phase.name,
                "stages": [
                    {"id": s.id, "code": s.code, "title": s.title, "subscribed": s.id in subscribed}
                    for s in stages
                ],
            }
        )
    return result


def set_subscriptions(db: Session, ctx: AuthContext, stage_ids: list[uuid.UUID]) -> None:
    """Substitui o conjunto de subscrições do próprio utilizador (idempotente)."""
    require_alert_permission(ctx)
    wanted = set(stage_ids)
    if wanted:
        known = {
            sid for (sid,) in db.query(WorkflowStage.id).filter(WorkflowStage.id.in_(wanted)).all()
        }
        unknown = wanted - known
        if unknown:
            raise ProcessAlertError("Etapa do catálogo desconhecida.")
    current_rows = (
        db.query(ProcessStageSubscription)
        .filter(ProcessStageSubscription.user_id == ctx.user.id)
        .all()
    )
    current = {row.stage_id: row for row in current_rows}
    for stage_id, row in current.items():
        if stage_id not in wanted:
            db.delete(row)
    for stage_id in wanted - set(current):
        db.add(ProcessStageSubscription(user_id=ctx.user.id, stage_id=stage_id, created_at=_now()))
    db.commit()


# --- gatilho ---------------------------------------------------------------------


def _stage_is_complete(db: Session, project_id: uuid.UUID, stage_id: uuid.UUID) -> bool:
    total = (
        db.query(func.count(WorkflowSubtask.id)).filter(WorkflowSubtask.stage_id == stage_id).scalar() or 0
    )
    if total == 0:
        return False
    done = (
        db.query(func.count(ProjectSubtaskProgress.id))
        .join(WorkflowSubtask, WorkflowSubtask.id == ProjectSubtaskProgress.subtask_id)
        .filter(
            WorkflowSubtask.stage_id == stage_id,
            ProjectSubtaskProgress.project_id == project_id,
            ProjectSubtaskProgress.done.is_(True),
        )
        .scalar()
        or 0
    )
    return done == total


def stage_completion_snapshot(db: Session, project_id: uuid.UUID, stage_id: uuid.UUID) -> bool:
    """Estado de completude ANTES de uma escrita (chamar antes de alterar o progresso)."""
    return _stage_is_complete(db, project_id, stage_id)


def notify_stage_completed_if_transitioned(
    db: Session,
    *,
    project: Project,
    stage: WorkflowStage,
    was_complete: bool,
    actor: AuthContext,
) -> int:
    """Cria as notificações quando a etapa transita de incompleta para completa.

    Deve ser chamado depois de `db.flush()` das escritas de progresso e antes do commit.
    Devolve o número de notificações criadas.
    """
    db.flush()
    if was_complete or not _stage_is_complete(db, project.id, stage.id):
        return 0
    subscriber_ids = [
        uid
        for (uid,) in db.query(ProcessStageSubscription.user_id)
        .filter(ProcessStageSubscription.stage_id == stage.id)
        .order_by(ProcessStageSubscription.created_at)
        .all()
        if uid != actor.user.id
    ]
    created = 0
    message = f"Etapa concluída: {stage.title} — {project.name}"
    for uid in subscriber_ids:
        user = db.get(User, uid)
        if user is None or not user.is_active:
            continue
        sub_ctx = load_auth_context(db, user)
        if not sub_ctx.has_permission(PERMISSION) or is_installer_readonly_scope(sub_ctx):
            continue
        if not can_view_project(sub_ctx, project):
            continue
        db.add(
            Notification(
                user_id=uid,
                kind=KIND_STAGE_COMPLETED,
                message=message,
                related_entity_type=ENTITY_PROJECT,
                related_entity_id=project.id,
                project_id=project.id,
                stage_id=stage.id,
                is_read=False,
            )
        )
        created += 1
    return created


# --- notificações do próprio -------------------------------------------------------


def _visible_notifications_query(db: Session, ctx: AuthContext):
    from app.services.projects import visible_projects_query

    visible_ids = visible_projects_query(db, ctx).with_entities(Project.id).subquery()
    return (
        db.query(Notification)
        .filter(
            Notification.user_id == ctx.user.id,
            Notification.project_id.in_(db.query(visible_ids.c.id)),
        )
    )


def _to_item(notification: Notification, project_name: str | None, stage_title: str | None) -> dict:
    return {
        "id": notification.id,
        "kind": notification.kind,
        "message": notification.message,
        "project_id": notification.project_id,
        "project_name": project_name,
        "stage_id": notification.stage_id,
        "stage_title": stage_title,
        "is_read": notification.is_read,
        "created_at": notification.created_at,
        "read_at": notification.read_at,
    }


def _items(db: Session, rows: list[Notification]) -> list[dict]:
    project_ids = {r.project_id for r in rows if r.project_id}
    stage_ids = {r.stage_id for r in rows if r.stage_id}
    names = (
        dict(db.query(Project.id, Project.name).filter(Project.id.in_(project_ids)).all()) if project_ids else {}
    )
    titles = (
        dict(db.query(WorkflowStage.id, WorkflowStage.title).filter(WorkflowStage.id.in_(stage_ids)).all())
        if stage_ids
        else {}
    )
    return [_to_item(r, names.get(r.project_id), titles.get(r.stage_id)) for r in rows]


def list_notifications(
    db: Session, ctx: AuthContext, *, unread_only: bool = False, limit: int = 20, offset: int = 0
) -> dict:
    require_alert_permission(ctx)
    limit = max(1, min(limit, MAX_PAGE_SIZE))
    offset = max(0, offset)
    query = _visible_notifications_query(db, ctx)
    if unread_only:
        query = query.filter(Notification.is_read.is_(False))
    total = query.count()
    rows = (
        query.order_by(Notification.created_at.desc(), Notification.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {"items": _items(db, rows), "total": total, "limit": limit, "offset": offset}


def unread_count(db: Session, ctx: AuthContext) -> int:
    require_alert_permission(ctx)
    return _visible_notifications_query(db, ctx).filter(Notification.is_read.is_(False)).count()


def mark_read(db: Session, ctx: AuthContext, notification_id: uuid.UUID) -> dict:
    require_alert_permission(ctx)
    notification = (
        _visible_notifications_query(db, ctx).filter(Notification.id == notification_id).one_or_none()
    )
    if notification is None:
        raise ProcessAlertNotFound("Notificação não encontrada.")
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = _now()
        db.commit()
    return _items(db, [notification])[0]


def mark_all_read(db: Session, ctx: AuthContext) -> int:
    require_alert_permission(ctx)
    now = _now()
    rows = (
        _visible_notifications_query(db, ctx).filter(Notification.is_read.is_(False)).all()
    )
    for row in rows:
        row.is_read = True
        row.read_at = now
    db.commit()
    return len(rows)
