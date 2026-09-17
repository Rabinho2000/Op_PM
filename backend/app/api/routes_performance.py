"""Endpoints da página única "Metas e indicadores" — ver
app/services/performance.py e docs/PERFORMANCE_METRICS.md.
"""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.people import Person
from app.models.performance import GoalPeriod
from app.schemas.performance import (
    GoalPeriodCreate,
    GoalPeriodRead,
    GoalPeriodUpdate,
    PerformanceSummary,
    PortfolioBreakdownRead,
    YearlyIndicator,
)
from app.security.current_user import get_auth_context
from app.security.permissions import AuthContext, can_manage_goals, can_view_performance
from app.services.performance import (
    PerformanceError,
    compute_goal_progress,
    compute_portfolio_breakdown,
    create_goal,
    installations_and_kwp_by_year,
    list_goals,
    update_goal,
)

router = APIRouter(prefix="/api/performance", tags=["performance"])


def _require_view(ctx: AuthContext) -> None:
    if not can_view_performance(ctx):
        raise HTTPException(status_code=403, detail="Sem permissão para ver metas e indicadores.")


def _goal_to_read(db: Session, goal: GoalPeriod) -> GoalPeriodRead:
    progress = compute_goal_progress(db, goal)
    data = GoalPeriodRead.model_validate(goal)
    if goal.pm_person_id:
        person = db.get(Person, goal.pm_person_id)
        data.pm_display_name = person.display_name if person else None
    data.realized = progress.realized
    data.percent = progress.percent
    data.missing = progress.missing
    data.expected_pace = progress.expected_pace
    data.projection = progress.projection
    data.pace_status = progress.pace_status
    return data


@router.get("/summary", response_model=PerformanceSummary)
def performance_summary_endpoint(
    year: int | None = Query(default=None),
    pm_person_id: uuid.UUID | None = Query(default=None),
    period_type: str | None = Query(default=None, description="year | quarter | semester | month"),
    quarter: int | None = Query(default=None),
    semester: int | None = Query(default=None),
    month: int | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> PerformanceSummary:
    _require_view(ctx)
    effective_year = year or dt.date.today().year
    goals = list_goals(
        db,
        ctx,
        year=effective_year,
        pm_person_id=pm_person_id,
        period_type=period_type,
        quarter=quarter,
        semester=semester,
        month=month,
    )
    portfolio = compute_portfolio_breakdown(db, ctx)
    yearly = installations_and_kwp_by_year(db, ctx)

    return PerformanceSummary(
        goals=[_goal_to_read(db, g) for g in goals],
        portfolio=PortfolioBreakdownRead(
            not_started=portfolio.not_started,
            in_progress=portfolio.in_progress,
            completed=portfolio.completed,
            kwp_not_started=portfolio.kwp_not_started,
            kwp_in_progress=portfolio.kwp_in_progress,
            kwp_completed=portfolio.kwp_completed,
            certified_count=portfolio.certified_count,
            pending_certification_count=portfolio.pending_certification_count,
        ),
        yearly=[YearlyIndicator(year=y, installations=v["installations"], kwp=v["kwp"]) for y, v in yearly.items()],
    )


@router.get("/goals", response_model=list[GoalPeriodRead])
def list_goals_endpoint(
    year: int | None = Query(default=None),
    pm_person_id: uuid.UUID | None = Query(default=None),
    period_type: str | None = Query(default=None, description="year | quarter | semester | month"),
    quarter: int | None = Query(default=None),
    semester: int | None = Query(default=None),
    month: int | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> list[GoalPeriodRead]:
    _require_view(ctx)
    goals = list_goals(
        db,
        ctx,
        year=year,
        pm_person_id=pm_person_id,
        period_type=period_type,
        quarter=quarter,
        semester=semester,
        month=month,
    )
    return [_goal_to_read(db, g) for g in goals]


@router.post("/goals", response_model=GoalPeriodRead, status_code=201)
def create_goal_endpoint(
    body: GoalPeriodCreate, db: Session = Depends(get_db), ctx: AuthContext = Depends(get_auth_context)
) -> GoalPeriodRead:
    if not can_manage_goals(ctx):
        raise HTTPException(status_code=403, detail="Sem permissão para criar metas.")
    try:
        goal = create_goal(
            db,
            period_type=body.period_type,
            year=body.year,
            quarter=body.quarter,
            semester=body.semester,
            month=body.month,
            metric=body.metric,
            target_value=body.target_value,
            scope=body.scope,
            pm_person_id=body.pm_person_id,
            created_by_person_id=ctx.person_id,
            notes=body.notes,
        )
    except PerformanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _goal_to_read(db, goal)


@router.patch("/goals/{goal_id}", response_model=GoalPeriodRead)
def update_goal_endpoint(
    goal_id: uuid.UUID,
    body: GoalPeriodUpdate,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
) -> GoalPeriodRead:
    if not can_manage_goals(ctx):
        raise HTTPException(status_code=403, detail="Sem permissão para editar metas.")
    goal = db.get(GoalPeriod, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="Meta não encontrada.")
    try:
        updated = update_goal(
            db, goal=goal, changes=body.model_dump(exclude_unset=True), changed_by_person_id=ctx.person_id
        )
    except PerformanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _goal_to_read(db, updated)
