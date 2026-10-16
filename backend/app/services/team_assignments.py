"""Afectações de equipas a obras e vista operacional por equipa (PR C)."""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.audit.log import record_project_change
from app.models.installer import Installer, InstallerTeam
from app.models.project import Project, ProjectTeamAssignment
from app.security.permissions import (
    AuthContext,
    PermissionDenied,
    can_plan_project_work,
    can_view_installers,
    can_view_project,
    is_installer_readonly_scope,
)
from app.services.projects import visible_projects_query


_CONFLICT_LIFECYCLE_STATUSES = ("preparacao", "construcao")


class AssignmentError(ValueError):
    """Regra de negócio de uma afectação inválida."""


@dataclass
class TeamAssignmentData:
    assignment: ProjectTeamAssignment
    warning: str | None = None


def _scope_project(db: Session, project_id: uuid.UUID, ctx: AuthContext) -> Project | None:
    return visible_projects_query(db, ctx).filter(Project.id == project_id).one_or_none()


def _window_warning(project: Project, start: dt.date, end: dt.date) -> str | None:
    if project.work_start_date is None or project.work_end_date is None:
        return "A afectação está fora da janela da obra (a janela ainda não está definida)."
    if start < project.work_start_date or end > project.work_end_date:
        return "A afectação sai da janela definida para a obra."
    return None


def _validate_team(
    db: Session,
    project: Project,
    team_id: uuid.UUID,
    *,
    allow_inactive_existing: bool = False,
) -> InstallerTeam:
    if project.installer_id is None:
        raise AssignmentError("A obra não tem instalador atribuído.")
    team = db.query(InstallerTeam).filter(InstallerTeam.id == team_id).one_or_none()
    if team is None:
        raise AssignmentError("Equipa não encontrada.")
    if team.installer_id != project.installer_id:
        raise AssignmentError("A equipa não pertence ao instalador da obra.")
    if not team.is_active and not allow_inactive_existing:
        raise AssignmentError("A equipa está inativa.")
    return team


def _lock_project(db: Session, project_id: uuid.UUID, project: Project | None = None) -> Project:
    locked_project = (
        db.query(Project)
        .populate_existing()
        .filter(Project.id == project_id)
        .with_for_update()
        .one_or_none()
    )
    if locked_project is None:
        raise AssignmentError("A obra não existe.")
    if project is not None:
        # Do not validate against an ORM object read before the lock.
        db.refresh(project)
    return locked_project


def _reload_assignment_after_project_lock(
    db: Session, *, project_id: uuid.UUID, assignment_id: uuid.UUID
) -> ProjectTeamAssignment | None:
    return (
        db.query(ProjectTeamAssignment)
        .populate_existing()
        .filter(
            ProjectTeamAssignment.id == assignment_id,
            ProjectTeamAssignment.project_id == project_id,
        )
        .with_for_update()
        .one_or_none()
    )


def _check_same_project_overlap(
    db: Session,
    *,
    project_id: uuid.UUID,
    team_id: uuid.UUID | None,
    start: dt.date | None,
    end: dt.date | None,
    exclude_id: uuid.UUID | None = None,
    project: Project | None = None,
    assignment: ProjectTeamAssignment | None = None,
    changes: dict | None = None,
) -> tuple[ProjectTeamAssignment | None, uuid.UUID, dt.date, dt.date]:
    # The project row is the canonical lock for the (project, team) overlap
    # invariant. Every create/update path acquires this single parent lock
    # before reading assignments, so there is no opposite lock order to deadlock.
    _lock_project(db, project_id, project)
    locked_assignment = None
    if assignment is not None:
        locked_assignment = _reload_assignment_after_project_lock(
            db, project_id=project_id, assignment_id=assignment.id
        )
        if locked_assignment is None:
            raise AssignmentError("Afectação não encontrada.")
        if changes is not None:
            team_id = changes.get("team_id", locked_assignment.team_id)
            start = changes.get("start_date", locked_assignment.start_date)
            end = changes.get("end_date", locked_assignment.end_date)
        else:
            team_id = locked_assignment.team_id
            start = locked_assignment.start_date
            end = locked_assignment.end_date
    if team_id is None or start is None or end is None:
        raise AssignmentError("Os dados da afectação estão incompletos.")
    if end < start:
        raise AssignmentError("O fim da afectação não pode ser anterior ao início.")
    query = db.query(ProjectTeamAssignment).filter(
        ProjectTeamAssignment.project_id == project_id,
        ProjectTeamAssignment.team_id == team_id,
        ProjectTeamAssignment.start_date <= end,
        ProjectTeamAssignment.end_date >= start,
    )
    if exclude_id is not None:
        query = query.filter(ProjectTeamAssignment.id != exclude_id)
    if query.first() is not None:
        raise AssignmentError("Já existe uma afectação sobreposta desta equipa na obra.")
    return locked_assignment, team_id, start, end


def list_project_assignments(
    db: Session, *, project: Project, ctx: AuthContext
) -> list[TeamAssignmentData]:
    if not can_view_project(ctx, project):
        raise PermissionDenied("project.view")
    query = (
        db.query(ProjectTeamAssignment)
        .filter(ProjectTeamAssignment.project_id == project.id)
        .options(joinedload(ProjectTeamAssignment.team).joinedload(InstallerTeam.installer))
        .order_by(ProjectTeamAssignment.start_date, ProjectTeamAssignment.created_at)
    )
    if is_installer_readonly_scope(ctx):
        # A project can be visible through its legacy installer while carrying
        # assignments for another installer.  The assignment's canonical
        # installer_id, not the project's legacy owner, defines the scoped row.
        query = query.filter(ProjectTeamAssignment.installer_id.in_(ctx.active_installer_ids))
    rows = query.all()
    return [TeamAssignmentData(row, _window_warning(project, row.start_date, row.end_date)) for row in rows]


def create_project_assignment(
    db: Session,
    *,
    project: Project,
    team_id: uuid.UUID,
    start_date: dt.date,
    end_date: dt.date,
    note: str,
    ctx: AuthContext,
) -> TeamAssignmentData:
    if not can_plan_project_work(ctx, project):
        raise PermissionDenied("project.plan_work")
    _, team_id, start_date, end_date = _check_same_project_overlap(
        db, project_id=project.id, team_id=team_id, start=start_date, end=end_date, project=project
    )
    team = _validate_team(db, project, team_id)
    assignment = ProjectTeamAssignment(
        project_id=project.id,
        installer_id=project.installer_id,
        team_id=team.id,
        start_date=start_date,
        end_date=end_date,
        note=note,
        created_by_person_id=ctx.person_id,
    )
    db.add(assignment)
    # O campo legado continua a representar a equipa principal: a primeira
    # afectação. Não alteramos a janela da obra, que é independente.
    if project.installer_team_id is None:
        record_project_change(
            db,
            project_id=project.id,
            field_name="installer_team_id",
            old_value=None,
            new_value=str(team.id),
            source="ui",
            changed_by_person_id=ctx.person_id,
            note="Primeira afectação definida como equipa principal.",
        )
        project.installer_team_id = team.id
    record_project_change(
        db,
        project_id=project.id,
        field_name="team_assignment",
        old_value=None,
        new_value=f"{team.id}:{start_date.isoformat()}:{end_date.isoformat()}",
        source="ui",
        changed_by_person_id=ctx.person_id,
        note="Afectação de equipa criada.",
    )
    db.commit()
    db.refresh(assignment)
    return TeamAssignmentData(assignment, _window_warning(project, start_date, end_date))


def update_project_assignment(
    db: Session,
    *,
    project: Project,
    assignment: ProjectTeamAssignment,
    changes: dict,
    ctx: AuthContext,
) -> TeamAssignmentData:
    if not can_plan_project_work(ctx, project):
        raise PermissionDenied("project.plan_work")
    locked_assignment, team_id, start, end = _check_same_project_overlap(
        db,
        project_id=project.id,
        team_id=None,
        start=None,
        end=None,
        exclude_id=assignment.id,
        project=project,
        assignment=assignment,
        changes=changes,
    )
    assert locked_assignment is not None
    assignment = locked_assignment
    team = _validate_team(
        db,
        project,
        team_id,
        allow_inactive_existing=team_id == assignment.team_id,
    )
    old = {
        "team_id": assignment.team_id,
        "start_date": assignment.start_date,
        "end_date": assignment.end_date,
        "note": assignment.note,
    }
    assignment.installer_id = project.installer_id
    assignment.team_id = team_id
    assignment.start_date = start
    assignment.end_date = end
    if "note" in changes:
        assignment.note = changes["note"] or ""
    if project.installer_team_id == old["team_id"] and old["team_id"] != team_id:
        record_project_change(
            db,
            project_id=project.id,
            field_name="installer_team_id",
            old_value=str(old["team_id"]),
            new_value=str(team_id),
            source="ui",
            changed_by_person_id=ctx.person_id,
            note="Afectação principal alterada; compatibilidade actualizada.",
        )
        project.installer_team_id = team_id
    for field in ("team_id", "start_date", "end_date", "note"):
        if old[field] != getattr(assignment, field):
            record_project_change(
                db,
                project_id=project.id,
                field_name=f"team_assignment.{field}",
                old_value=str(old[field]) if old[field] is not None else None,
                new_value=str(getattr(assignment, field)) if getattr(assignment, field) is not None else None,
                source="ui",
                changed_by_person_id=ctx.person_id,
                note="Afectação de equipa alterada.",
            )
    db.commit()
    db.refresh(assignment)
    return TeamAssignmentData(assignment, _window_warning(project, start, end))


def delete_project_assignment(
    db: Session,
    *,
    project: Project,
    assignment: ProjectTeamAssignment,
    ctx: AuthContext,
) -> None:
    if not can_plan_project_work(ctx, project):
        raise PermissionDenied("project.plan_work")
    _lock_project(db, project.id, project)
    locked_assignment = _reload_assignment_after_project_lock(
        db, project_id=project.id, assignment_id=assignment.id
    )
    if locked_assignment is None:
        # A concurrent delete already won the Project lock. Treat DELETE as
        # idempotent and, importantly, do not create a phantom audit row.
        return
    assignment = locked_assignment
    deleted_team = assignment.team_id
    replacement = (
        db.query(ProjectTeamAssignment)
        .filter(
            ProjectTeamAssignment.project_id == project.id,
            ProjectTeamAssignment.id != assignment.id,
        )
        .order_by(ProjectTeamAssignment.start_date, ProjectTeamAssignment.created_at)
        .first()
    )
    record_project_change(
        db,
        project_id=project.id,
        field_name="team_assignment",
        old_value=f"{assignment.team_id}:{assignment.start_date.isoformat()}:{assignment.end_date.isoformat()}",
        new_value=None,
        source="ui",
        changed_by_person_id=ctx.person_id,
        note="Afectação de equipa removida.",
    )
    db.delete(assignment)
    if project.installer_team_id == deleted_team:
        new_primary = replacement.team_id if replacement else None
        record_project_change(
            db,
            project_id=project.id,
            field_name="installer_team_id",
            old_value=str(deleted_team),
            new_value=str(new_primary) if new_primary is not None else None,
            source="ui",
            changed_by_person_id=ctx.person_id,
            note="Equipa principal actualizada após remoção da afectação.",
        )
        project.installer_team_id = new_primary
    db.commit()


@dataclass
class TeamLocationAssignment:
    assignment: ProjectTeamAssignment
    conflict: bool


@dataclass
class TeamLocationTeam:
    team: InstallerTeam
    assignments: list[TeamLocationAssignment]
    status: str = "livre"


@dataclass
class TeamLocationInstaller:
    installer: Installer
    teams: list[TeamLocationTeam]


def get_teams_view(
    db: Session,
    ctx: AuthContext,
    *,
    date: dt.date,
    days: int = 1,
    installer_id: uuid.UUID | None = None,
) -> tuple[dt.date, int, list[TeamLocationInstaller]]:
    if not (
        can_view_installers(ctx)
        or ctx.has_permission("installer_team.view_assigned_installer")
    ):
        raise PermissionDenied("installer.view")
    if days < 1 or days > 62:
        raise AssignmentError("O período deve ter entre 1 e 62 dias.")
    end = date + dt.timedelta(days=days - 1)
    installers_query = db.query(Installer).filter(Installer.is_active.is_(True))
    if is_installer_readonly_scope(ctx):
        if not ctx.active_installer_ids:
            return date, days, []
        installers_query = installers_query.filter(Installer.id.in_(ctx.active_installer_ids))
    if installer_id is not None:
        installers_query = installers_query.filter(Installer.id == installer_id)
    installers = installers_query.options(joinedload(Installer.teams)).order_by(Installer.name).all()
    # Lê todas as ocupações do período para não declarar "livre" uma equipa
    # que está numa obra fora do âmbito do PM. Só as linhas de projetos
    # visíveis seguem para a resposta.
    rows = (
        db.query(ProjectTeamAssignment)
        .join(Project, Project.id == ProjectTeamAssignment.project_id)
        .options(
            joinedload(ProjectTeamAssignment.team).joinedload(InstallerTeam.installer),
            joinedload(ProjectTeamAssignment.project).joinedload(Project.pm),
        )
        .filter(
            Project.is_active.is_(True),
            ProjectTeamAssignment.start_date <= end,
            ProjectTeamAssignment.end_date >= date,
            or_(
                Project.lifecycle_status.in_(_CONFLICT_LIFECYCLE_STATUSES),
                Project.lifecycle_status.is_(None),
            ),
        )
    )
    if installer_id is not None:
        rows = rows.filter(ProjectTeamAssignment.installer_id == installer_id)
    if is_installer_readonly_scope(ctx):
        # Occupancy and response rows use the assignment's canonical installer;
        # the visible project's legacy installer must not widen this population.
        rows = rows.filter(ProjectTeamAssignment.installer_id.in_(ctx.active_installer_ids))
        # The scoped branch must not build occupancy from projects outside the
        # canonical visible-project query.
        visible_ids = visible_projects_query(db, ctx).with_entities(Project.id).subquery()
        rows = rows.filter(ProjectTeamAssignment.project_id.in_(select(visible_ids.c.id)))
    rows = rows.all()
    by_team: dict[uuid.UUID, list[ProjectTeamAssignment]] = {}
    visible_by_team: dict[uuid.UUID, list[ProjectTeamAssignment]] = {}
    for row in rows:
        by_team.setdefault(row.team_id, []).append(row)
        if can_view_project(ctx, row.project):
            visible_by_team.setdefault(row.team_id, []).append(row)
    conflicts: set[uuid.UUID] = set()
    for visible_rows in visible_by_team.values():
        group = [
            row
            for row in visible_rows
            if row.project.lifecycle_status in _CONFLICT_LIFECYCLE_STATUSES
        ]
        group.sort(key=lambda row: (row.start_date, row.end_date, str(row.id)))
        for index, left in enumerate(group):
            for right in group[index + 1 :]:
                if (
                    left.project_id != right.project_id
                    and left.start_date <= right.end_date
                    and right.start_date <= left.end_date
                ):
                    conflicts.add(left.id)
                    conflicts.add(right.id)
    result: list[TeamLocationInstaller] = []
    for installer in installers:
        teams: list[TeamLocationTeam] = []
        for team in sorted((item for item in installer.teams if item.is_active), key=lambda item: item.name_key):
            all_rows = by_team.get(team.id, [])
            visible_rows = visible_by_team.get(team.id, [])
            assignment_rows = [
                TeamLocationAssignment(row, row.id in conflicts)
                for row in visible_rows
            ]
            status = "livre"
            if all_rows:
                status = "ocupada" if visible_rows else "ocupada_noutra_obra"
            teams.append(TeamLocationTeam(team, assignment_rows, status))
        result.append(TeamLocationInstaller(installer, teams))
    return date, days, result
