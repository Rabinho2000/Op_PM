"""Calendário de obras (D-072/D-080).

As atribuições são a fonte das linhas do calendário. Uma obra com várias
atribuições aparece uma vez por janela/equipa; uma obra antiga sem atribuições
continua a aparecer numa linha sem equipa, usando a janela legada da obra.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import uuid

from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.installer import InstallerTeam
from app.models.project import Project, ProjectTeamAssignment
from app.security.permissions import AuthContext, is_installer_readonly_scope
from app.services.project_lifecycle import ON_HOLD
from app.services.projects import visible_projects_query

# Uma equipa só está ocupada para conflitos quando a obra está em preparação ou
# construção. Estados concluídos/em espera não ocupam a equipa (D-072).
CONFLICT_STATES = frozenset({"preparacao", "construcao"})
TO_PLAN_STATES = frozenset({"preparacao", "construcao", ON_HOLD})
MAX_WINDOW_DAYS = 800
MAX_UNSCHEDULED = 200


class WindowError(ValueError):
    """Janela de datas inválida — mensagem segura para mostrar."""


@dataclasses.dataclass
class WorkEntry:
    project: Project
    assignment: ProjectTeamAssignment | None = None
    conflict: bool = False

    @property
    def start_date(self) -> dt.date:
        if self.assignment is not None:
            return self.assignment.start_date
        assert self.project.work_start_date is not None
        return self.project.work_start_date

    @property
    def end_date(self) -> dt.date:
        if self.assignment is not None:
            return self.assignment.end_date
        assert self.project.work_end_date is not None
        return self.project.work_end_date

    @property
    def installer_id(self) -> uuid.UUID | None:
        return self.assignment.installer_id if self.assignment is not None else self.project.installer_id

    @property
    def team_id(self) -> uuid.UUID | None:
        return self.assignment.team_id if self.assignment is not None else None

    @property
    def team_name(self) -> str | None:
        return self.assignment.team.name if self.assignment is not None and self.assignment.team else None

    @property
    def team_leader_name(self) -> str | None:
        team = self.assignment.team if self.assignment is not None else None
        return team.leader_name if team is not None else None


@dataclasses.dataclass
class WorksCalendar:
    start: dt.date
    end: dt.date
    works: list[WorkEntry]
    unscheduled: list[Project]
    unscheduled_total: int


def _dates_overlap(left_start: dt.date, left_end: dt.date, right_start: dt.date, right_end: dt.date) -> bool:
    return left_start <= right_end and right_start <= left_end


def _entry_overlaps(entry: WorkEntry, start: dt.date, end: dt.date) -> bool:
    return _dates_overlap(entry.start_date, entry.end_date, start, end)


def _entries_for_project(
    project: Project,
    start: dt.date,
    end: dt.date,
    *,
    has_any_assignments: bool | None = None,
    allow_legacy_fallback: bool = False,
) -> list[WorkEntry]:
    """Constrói as linhas sem aplicar filtros de PM/estado/equipa.

    In the scoped external channel the relationship may be SQL-filtered to the
    authenticated installer.  ``has_any_assignments`` keeps a foreign-only
    project from being mistaken for an unassigned one, while an A-owned legacy
    project may still use its own legacy bar without exposing B's assignment.
    """
    assignments = project.team_assignments
    if assignments:
        return [
            WorkEntry(project=project, assignment=assignment)
            for assignment in assignments
            if _entry_overlaps(WorkEntry(project, assignment), start, end)
        ]
    if has_any_assignments is None:
        has_any_assignments = bool(assignments)
    if has_any_assignments and not allow_legacy_fallback:
        return []
    if project.work_start_date is None or project.work_end_date is None:
        return []
    fallback = WorkEntry(project=project)
    return [fallback] if _entry_overlaps(fallback, start, end) else []


def _conflicting_assignment_ids(entries: list[WorkEntry]) -> set[uuid.UUID]:
    """Devolve as atribuições em conflito, antes dos filtros da resposta.

    A chave é a atribuição, não o projeto: duas equipas da mesma obra não
    entram em conflito entre si e a mesma equipa só conflita entre obras
    diferentes. As linhas de compatibilidade sem equipa nunca são marcadas.
    """
    by_team: dict[uuid.UUID, list[WorkEntry]] = {}
    for entry in entries:
        if (
            entry.assignment is not None
            and entry.project.lifecycle_status in CONFLICT_STATES
            and entry.team_id is not None
        ):
            by_team.setdefault(entry.team_id, []).append(entry)

    conflicts: set[uuid.UUID] = set()
    for group in by_team.values():
        group.sort(key=lambda item: (item.start_date, item.end_date, str(item.assignment.id)))
        active: list[WorkEntry] = []
        for entry in group:
            active = [other for other in active if other.end_date >= entry.start_date]
            for other in active:
                if other.project.id != entry.project.id and _dates_overlap(
                    other.start_date, other.end_date, entry.start_date, entry.end_date
                ):
                    other_assignment = other.assignment
                    entry_assignment = entry.assignment
                    if other_assignment is not None and entry_assignment is not None:
                        conflicts.add(other_assignment.id)
                        conflicts.add(entry_assignment.id)
            active.append(entry)
    return conflicts


def get_works_calendar(
    db: Session,
    ctx: AuthContext,
    *,
    start: dt.date,
    end: dt.date,
    pm_person_id: uuid.UUID | None = None,
    lifecycle_statuses: list[str] | None = None,
    installer_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
) -> WorksCalendar:
    if end < start:
        raise WindowError("O fim da janela não pode ser anterior ao início.")
    if (end - start).days + 1 > MAX_WINDOW_DAYS:
        raise WindowError(f"A janela não pode exceder {MAX_WINDOW_DAYS} dias.")

    scoped = is_installer_readonly_scope(ctx)
    if scoped:
        assignment_loader = selectinload(
            Project.team_assignments.and_(
                ProjectTeamAssignment.installer_id.in_(ctx.active_installer_ids)
            )
        ).joinedload(ProjectTeamAssignment.team).joinedload(InstallerTeam.installer)
    else:
        assignment_loader = (
            selectinload(Project.team_assignments)
            .joinedload(ProjectTeamAssignment.team)
            .joinedload(InstallerTeam.installer)
        )

    projects = (
        visible_projects_query(db, ctx)
        .filter(Project.is_active.is_(True))
        .options(
            joinedload(Project.pm),
            joinedload(Project.installer),
            joinedload(Project.installer_team),
            assignment_loader,
        )
        .all()
    )

    # The scoped relationship loader intentionally excludes foreign assignment
    # rows.  Keep only their project IDs to distinguish a foreign-only project
    # from a truly legacy/unassigned one, without materialising foreign team
    # contacts, notes, or creator data.
    if scoped and projects:
        visible_project_ids = [project.id for project in projects]
        assignment_project_ids = {
            project_id
            for (project_id,) in db.query(ProjectTeamAssignment.project_id)
            .filter(ProjectTeamAssignment.project_id.in_(visible_project_ids))
            .distinct()
            .all()
        }
    else:
        assignment_project_ids = {
            project.id for project in projects if project.team_assignments
        }

    in_window: list[WorkEntry] = []
    for project in projects:
        in_window.extend(
            _entries_for_project(
                project,
                start,
                end,
                has_any_assignments=project.id in assignment_project_ids,
                allow_legacy_fallback=scoped and project.installer_id in ctx.active_installer_ids,
            )
        )
    conflicts = _conflicting_assignment_ids(in_window)

    def wanted(entry: WorkEntry) -> bool:
        project = entry.project
        if pm_person_id is not None and project.pm_person_id != pm_person_id:
            return False
        if lifecycle_statuses and project.lifecycle_status not in lifecycle_statuses:
            return False
        if installer_id is not None and entry.installer_id != installer_id:
            return False
        if team_id is not None and entry.team_id != team_id:
            return False
        return True

    works = [
        WorkEntry(
            project=entry.project,
            assignment=entry.assignment,
            conflict=entry.assignment is not None and entry.assignment.id in conflicts,
        )
        for entry in in_window
        if wanted(entry)
    ]
    works.sort(key=lambda item: (item.start_date, item.project.name, str(item.assignment.id) if item.assignment else ""))

    # Uma obra com atribuições já tem uma janela explícita para o calendário,
    # mesmo que os campos legados da obra estejam vazios. Sem atribuições, a
    # lista "por planear" mantém a compatibilidade D-072.
    to_plan = [
        project
        for project in projects
        if not project.team_assignments
        and (
            project.id not in assignment_project_ids
            or (scoped and project.installer_id in ctx.active_installer_ids)
        )
        and (project.work_start_date is None or project.work_end_date is None)
        and (project.lifecycle_status is None or project.lifecycle_status in TO_PLAN_STATES)
    ]
    if pm_person_id is not None:
        to_plan = [project for project in to_plan if project.pm_person_id == pm_person_id]
    if lifecycle_statuses:
        to_plan = [project for project in to_plan if project.lifecycle_status in lifecycle_statuses]
    if installer_id is not None:
        to_plan = [project for project in to_plan if project.installer_id == installer_id]
    # Uma linha sem atribuição é, por definição, "sem equipa".
    if team_id is not None:
        to_plan = []
    to_plan.sort(key=lambda project: project.name)

    return WorksCalendar(
        start=start,
        end=end,
        works=works,
        unscheduled=to_plan[:MAX_UNSCHEDULED],
        unscheduled_total=len(to_plan),
    )
