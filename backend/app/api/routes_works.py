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
from app.schemas.works import UnscheduledProjectRead, WorkItemRead, WorksCalendarRead, WorksSummary
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext, can_view_installers
from app.services.project_lifecycle import LIFECYCLE_STATUS_CODES
from app.services.works_calendar import WindowError, get_works_calendar

router = APIRouter(prefix="/api/works", tags=["works"])


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
    if not can_view_installers(ctx):
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

    works = [
        WorkItemRead(
            project_id=e.project.id,
            name=e.project.name,
            client_name=e.project.client_name,
            pm_person_id=e.project.pm_person_id,
            pm_display_name=e.project.pm.display_name if e.project.pm else None,
            lifecycle_status=e.project.lifecycle_status,
            installer_id=e.project.installer_id,
            installer_name=e.project.installer.name if e.project.installer else None,
            installer_team_id=e.project.installer_team_id,
            installer_team_name=e.project.installer_team.name if e.project.installer_team else None,
            work_start_date=e.project.work_start_date,
            work_end_date=e.project.work_end_date,
            work_dates_estimated=e.project.work_dates_estimated,
            conflict=e.conflict,
        )
        for e in calendar.works
    ]
    unscheduled = [
        UnscheduledProjectRead(
            project_id=p.id,
            name=p.name,
            pm_display_name=p.pm.display_name if p.pm else None,
            lifecycle_status=p.lifecycle_status,
            installer_name=p.installer.name if p.installer else None,
            installer_team_name=p.installer_team.name if p.installer_team else None,
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
