"""Calendário de obras (D-072). Ver `app/services/works_calendar.py`.

Visível a quem consegue ver projetos, sempre no âmbito de visibilidade de cada
um (um PM só vê as suas obras).
"""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.installers import (
    TeamLocationAssignmentRead,
    TeamLocationInstallerRead,
    TeamLocationTeamRead,
    TeamsViewRead,
)
from app.schemas.works import UnscheduledProjectRead, WorkItemRead, WorksCalendarRead, WorksSummary
from app.security.current_user import get_auth_context
from app.security.permissions import (
    AuthContext,
    PermissionDenied,
    can_plan_project_work,
    can_view_installers,
    is_installer_readonly_scope,
)
from app.services.project_lifecycle import LIFECYCLE_STATUS_CODES
from app.services.team_assignments import AssignmentError, get_teams_view
from app.services.works_calendar import WindowError, get_works_calendar

router = APIRouter(prefix="/api/works", tags=["works"])


@router.get("/teams", response_model=TeamsViewRead)
def works_teams_endpoint(
    date: dt.date = Query(default_factory=dt.date.today),
    days: int = Query(default=1, ge=1, le=62),
    installer_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> TeamsViewRead:
    try:
        view_date, view_days, installers = get_teams_view(
            db, ctx, date=date, days=days, installer_id=installer_id
        )
    except PermissionDenied:
        raise HTTPException(status_code=403, detail="Sem permissão para ver equipas.")
    except AssignmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    result_installers: list[TeamLocationInstallerRead] = []
    scoped = is_installer_readonly_scope(ctx)
    for item in installers:
        teams: list[TeamLocationTeamRead] = []
        for team_item in item.teams:
            assignments: list[TeamLocationAssignmentRead] = []
            for row in team_item.assignments:
                assignment = row.assignment
                project = assignment.project
                assignments.append(
                    TeamLocationAssignmentRead(
                        id=assignment.id,
                        project_id=project.id,
                        project_name=project.name,
                        address=project.address,
                        lat=project.lat,
                        lon=project.lon,
                        pm_person_id=None if scoped else project.pm_person_id,
                        pm_display_name=None if scoped else (project.pm.display_name if project.pm else None),
                        lifecycle_status=project.lifecycle_status,
                        start_date=assignment.start_date,
                        end_date=assignment.end_date,
                        note="" if scoped else assignment.note,
                        conflict=row.conflict,
                    )
                )
            teams.append(
                TeamLocationTeamRead(
                    id=team_item.team.id,
                    installer_id=item.installer.id,
                    name=team_item.team.name,
                    assignments=assignments,
                    status=team_item.status,
                    free=team_item.status == "livre",
                )
            )
        result_installers.append(
            TeamLocationInstallerRead(id=item.installer.id, name=item.installer.name, teams=teams)
        )
    return TeamsViewRead(date=view_date, days=view_days, installers=result_installers)


@router.get("/calendar", response_model=WorksCalendarRead)
def works_calendar_endpoint(
    start: dt.date = Query(alias="from", description="Início da janela (inclusive)"),
    end: dt.date = Query(alias="to", description="Fim da janela (inclusive)"),
    pm_person_id: uuid.UUID | None = None,
    lifecycle_status: list[str] | None = Query(default=None, description="Estado do projeto (repetível)"),
    installer_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> WorksCalendarRead:
    if not (
        can_view_installers(ctx)
        or ctx.has_permission("works_calendar.view_assigned_installer")
    ):
        raise HTTPException(status_code=403, detail="Sem permissão para ver o calendário de obras.")
    invalid = sorted(set(lifecycle_status or []) - LIFECYCLE_STATUS_CODES)
    if invalid:
        raise HTTPException(status_code=400, detail=f"Estado do ciclo de vida inválido: {', '.join(invalid)}")
    try:
        calendar = get_works_calendar(
            db,
            ctx,
            start=start,
            end=end,
            pm_person_id=pm_person_id,
            lifecycle_statuses=lifecycle_status,
            installer_id=installer_id,
            team_id=team_id,
        )
    except WindowError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    scoped = is_installer_readonly_scope(ctx)
    works = [
        WorkItemRead(
            project_id=e.project.id,
            name=e.project.name,
            client_name=e.project.client_name,
            pm_person_id=None if scoped else e.project.pm_person_id,
            pm_display_name=None if scoped else (e.project.pm.display_name if e.project.pm else None),
            lifecycle_status=e.project.lifecycle_status,
            installer_id=e.installer_id,
            installer_name=(
                e.assignment.team.installer.name
                if scoped and e.assignment is not None and e.assignment.team and e.assignment.team.installer
                else (e.project.installer.name if e.project.installer else None)
            ),
            installer_team_id=e.team_id,
            installer_team_name=e.team_name,
            work_start_date=e.start_date,
            work_end_date=e.end_date,
            work_dates_estimated=e.project.work_dates_estimated,
            conflict=e.conflict,
            assignment_id=e.assignment.id if e.assignment else None,
            assignment_start_date=e.assignment.start_date if e.assignment else None,
            assignment_end_date=e.assignment.end_date if e.assignment else None,
            assignment_start=e.assignment.start_date if e.assignment else None,
            assignment_end=e.assignment.end_date if e.assignment else None,
            team_id=e.team_id,
            team_name=e.team_name,
            team_leader_name=None if scoped else e.team_leader_name,
            can_plan_work=False if scoped else can_plan_project_work(ctx, e.project),
        )
        for e in calendar.works
    ]
    unscheduled = [
        UnscheduledProjectRead(
            project_id=p.id,
            name=p.name,
            pm_display_name=None if scoped else (p.pm.display_name if p.pm else None),
            lifecycle_status=p.lifecycle_status,
            installer_name=(p.installer.name if p.installer and (not scoped or p.installer_id in ctx.active_installer_ids) else None),
            installer_team_name=(p.installer_team.name if p.installer_team and (not scoped or p.installer_id in ctx.active_installer_ids) else None),
            work_start_date=p.work_start_date,
            work_end_date=p.work_end_date,
        )
        for p in calendar.unscheduled
    ]
    return WorksCalendarRead(
        start=calendar.start,
        end=calendar.end,
        works=works,
        unscheduled=unscheduled,
        summary=WorksSummary(
            works=len(works),
            conflicts=sum(1 for w in works if w.conflict),
            estimated=sum(1 for w in works if w.work_dates_estimated),
            unscheduled=calendar.unscheduled_total,
        ),
    )
