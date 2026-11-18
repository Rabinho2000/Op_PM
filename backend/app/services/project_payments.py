"""Read and record project payment receipt milestones."""
from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence

from sqlalchemy import and_, case, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.log import record_project_change
from app.models.project import Project
from app.models.project_payments import (
    PAYMENT_MILESTONES,
    PAYMENT_MILESTONE_LABELS,
    ProjectPaymentMilestone,
)
from app.schemas.project_payments import ProjectPaymentMilestoneRead
from app.security.permissions import (
    AuthContext,
    PermissionDenied,
    can_edit_project_payments,
    can_view_project,
    can_view_project_payments,
)
from app.services.projects import visible_projects_query


class ProjectPaymentsNotFound(LookupError):
    """The project is deleted or outside the caller's project scope."""


class InvalidPaymentMilestone(ValueError):
    """The path milestone is not one of the stable payment codes."""


def _read(row: ProjectPaymentMilestone | None, milestone: str) -> ProjectPaymentMilestoneRead:
    return ProjectPaymentMilestoneRead(
        milestone=milestone,
        label=PAYMENT_MILESTONE_LABELS[milestone],
        received=bool(row.received) if row is not None else False,
        marked_at=row.marked_at if row is not None else None,
        marked_by=row.marked_by_person.display_name if row is not None and row.marked_by_person else None,
    )


def _visible_project(db: Session, ctx: AuthContext, project_id: uuid.UUID) -> Project:
    project = visible_projects_query(db, ctx).filter(Project.id == project_id).one_or_none()
    if project is None or not can_view_project(ctx, project):
        raise ProjectPaymentsNotFound
    return project


def get_project_payment_milestones(
    db: Session, *, ctx: AuthContext, project_id: uuid.UUID
) -> list[ProjectPaymentMilestoneRead]:
    ctx.require("payment.view")
    project = _visible_project(db, ctx, project_id)
    if not can_view_project_payments(ctx, project):
        raise PermissionDenied("payment.view")
    rows = (
        db.query(ProjectPaymentMilestone)
        .filter(ProjectPaymentMilestone.project_id == project.id)
        .all()
    )
    by_code = {row.milestone: row for row in rows}
    return [_read(by_code.get(code), code) for code in PAYMENT_MILESTONES]


def payment_summaries_by_project(
    db: Session,
    *,
    ctx: AuthContext,
    projects: Sequence[Project],
) -> dict[uuid.UUID, dict[str, bool]]:
    """Return one aggregate query for every project in a visible page."""
    ctx.require("payment.view")
    visible = [project for project in projects if can_view_project_payments(ctx, project)]
    if not visible:
        return {}

    project_ids = [project.id for project in visible]
    aggregate_columns = [
        func.max(
            case(
                (
                    and_(
                        ProjectPaymentMilestone.milestone == code,
                        ProjectPaymentMilestone.received.is_(True),
                    ),
                    1,
                ),
                else_=0,
            )
        ).label(code)
        for code in PAYMENT_MILESTONES
    ]
    rows = (
        db.query(ProjectPaymentMilestone.project_id, *aggregate_columns)
        .filter(ProjectPaymentMilestone.project_id.in_(project_ids))
        .group_by(ProjectPaymentMilestone.project_id)
        .all()
    )
    result = {
        project_id: {code: False for code in PAYMENT_MILESTONES}
        for project_id in project_ids
    }
    for row in rows:
        for code in PAYMENT_MILESTONES:
            result[row.project_id][code] = bool(getattr(row, code))
    return result


def set_project_payment_milestone(
    db: Session,
    *,
    ctx: AuthContext,
    project_id: uuid.UUID,
    milestone: str,
    received: bool,
) -> ProjectPaymentMilestoneRead:
    # Lock the project row so all milestone updates for it are serialized on
    # databases that support row locks. SQLite treats FOR UPDATE as a no-op;
    # the unique constraint below remains the final guard there.
    # Scope and permissions are checked before taking the lock, so callers
    # outside the project scope can never block authorised writers.
    _visible_project(db, ctx, project_id)
    ctx.require("payment.edit")
    ctx.require("payment.view")
    project = db.query(Project).filter(Project.id == project_id).with_for_update().one_or_none()
    if project is None or not can_view_project(ctx, project):
        raise ProjectPaymentsNotFound
    if not can_edit_project_payments(ctx, project):
        raise PermissionDenied("payment.edit")
    if milestone not in PAYMENT_MILESTONES:
        raise InvalidPaymentMilestone(milestone)

    row = (
        db.query(ProjectPaymentMilestone)
        .filter(
            ProjectPaymentMilestone.project_id == project.id,
            ProjectPaymentMilestone.milestone == milestone,
        )
        .populate_existing()
        .one_or_none()
    )
    previous = bool(row.received) if row is not None else False
    if previous == received:
        return _read(row, milestone)

    creating = row is None
    marked_at = dt.datetime.now(dt.timezone.utc)
    if row is None:
        row = ProjectPaymentMilestone(
            project_id=project.id,
            milestone=milestone,
            received=received,
            marked_at=marked_at,
            marked_by_person_id=ctx.person_id,
        )
        db.add(row)
    else:
        row.received = received
        row.marked_at = marked_at
        row.marked_by_person_id = ctx.person_id

    record_project_change(
        db,
        project_id=project.id,
        field_name=f"payment.{milestone}",
        old_value="true" if previous else "false",
        new_value="true" if received else "false",
        source="ui",
        changed_by_person_id=ctx.person_id,
        note=PAYMENT_MILESTONE_LABELS[milestone],
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if creating:
            # Another request may have inserted the same (project, milestone)
            # after our read. Return its result when it already satisfies this
            # request; if it recorded the opposite value, retry as an update.
            current = (
                db.query(ProjectPaymentMilestone)
                .filter(
                    ProjectPaymentMilestone.project_id == project.id,
                    ProjectPaymentMilestone.milestone == milestone,
                )
                .populate_existing()
                .one_or_none()
            )
            if current is not None:
                if bool(current.received) == received:
                    return _read(current, milestone)
                return set_project_payment_milestone(
                    db,
                    ctx=ctx,
                    project_id=project_id,
                    milestone=milestone,
                    received=received,
                )
        raise
    db.refresh(row)
    return _read(row, milestone)
