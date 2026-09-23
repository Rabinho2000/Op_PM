"""Metas e indicadores — página única "Metas e indicadores" (nunca duas
áreas separadas de menu). Todo o cálculo aqui, nunca no frontend a partir
de listas completas (mesma regra já aplicada ao dashboard, D-041).

Regra de "instalação concluída" (fonte de verdade única, reaproveitada do
dashboard — ver app/services/dashboard.py e
docs/PERFORMANCE_METRICS.md): uma instalação está concluída quando a
tarefa padrão de comissionamento (`Task.task_type ==
TASK_TYPE_COMISSIONAMENTO`) está `done`, na data em que ficou `done`
(`Task.completed_at`).
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.performance import GOAL_METRICS, PERIOD_TYPES, GoalPeriod, GoalPeriodHistory
from app.models.project import Project
from app.models.project_data import ProjectLicensingData
from app.models.task import STATUS_DONE, TASK_TYPE_COMISSIONAMENTO, Task
from app.security.permissions import AuthContext

ZERO = Decimal("0")


class PerformanceError(ValueError):
    pass


def period_bounds(
    *, period_type: str, year: int, quarter: int | None, semester: int | None, month: int | None
) -> tuple[dt.date, dt.date]:
    if period_type == "year":
        return dt.date(year, 1, 1), dt.date(year, 12, 31)
    if period_type == "semester":
        if semester not in (1, 2):
            raise PerformanceError("Semestre tem de ser 1 ou 2.")
        start_month = 1 if semester == 1 else 7
        end_month = 6 if semester == 1 else 12
        return dt.date(year, start_month, 1), _last_day_of_month(year, end_month)
    if period_type == "quarter":
        if quarter not in (1, 2, 3, 4):
            raise PerformanceError("Trimestre tem de ser 1 a 4.")
        start_month = (quarter - 1) * 3 + 1
        end_month = start_month + 2
        return dt.date(year, start_month, 1), _last_day_of_month(year, end_month)
    if period_type == "month":
        if month is None or not (1 <= month <= 12):
            raise PerformanceError("Mês tem de estar entre 1 e 12.")
        return dt.date(year, month, 1), _last_day_of_month(year, month)
    raise PerformanceError(f"Tipo de período inválido: {period_type!r}")


def _last_day_of_month(year: int, month: int) -> dt.date:
    if month == 12:
        return dt.date(year, 12, 31)
    return dt.date(year, month + 1, 1) - dt.timedelta(days=1)


def _completed_projects_query(db: Session, *, start: dt.date, end: dt.date, pm_person_id: uuid.UUID | None):
    query = (
        db.query(Task, Project)
        .join(Project, Task.project_id == Project.id)
        .filter(
            Task.task_type == TASK_TYPE_COMISSIONAMENTO,
            Task.status == STATUS_DONE,
            Task.completed_at.isnot(None),
        )
    )
    if pm_person_id is not None:
        query = query.filter(Project.pm_person_id == pm_person_id)
    rows = query.all()
    return [
        (task, project)
        for task, project in rows
        if start <= task.completed_at.date() <= end
    ]


def _realized_value(
    db: Session, *, metric: str, start: dt.date, end: dt.date, pm_person_id: uuid.UUID | None
) -> Decimal:
    if metric in ("installations", "projects_completed"):
        return Decimal(len(_completed_projects_query(db, start=start, end=end, pm_person_id=pm_person_id)))
    if metric in ("kwp", "power_installed", "power_delivered"):
        rows = _completed_projects_query(db, start=start, end=end, pm_person_id=pm_person_id)
        total = sum((Decimal(str(project.power_kwp)) for _, project in rows if project.power_kwp), start=ZERO)
        return total
    if metric == "projects_certified":
        query = (
            db.query(ProjectLicensingData, Project)
            .join(Project, ProjectLicensingData.project_id == Project.id)
            .filter(ProjectLicensingData.certificate_date.isnot(None))
        )
        if pm_person_id is not None:
            query = query.filter(Project.pm_person_id == pm_person_id)
        rows = query.all()
        return Decimal(sum(1 for lic, _ in rows if start <= lic.certificate_date <= end))
    raise PerformanceError(f"Métrica desconhecida: {metric!r}")


@dataclasses.dataclass
class GoalProgress:
    goal: GoalPeriod
    realized: Decimal
    percent: float
    missing: Decimal
    expected_pace: Decimal
    projection: Decimal
    pace_status: str  # on_track | behind | ahead | no_target


def compute_goal_progress(db: Session, goal: GoalPeriod, *, today: dt.date | None = None) -> GoalProgress:
    today = today or dt.date.today()
    start, end = period_bounds(
        period_type=goal.period_type, year=goal.year, quarter=goal.quarter, semester=goal.semester, month=goal.month
    )
    realized = _realized_value(db, metric=goal.metric, start=start, end=end, pm_person_id=goal.pm_person_id)

    target = goal.target_value
    percent = float(realized / target * 100) if target > ZERO else 0.0
    missing = target - realized
    if missing < ZERO:
        missing = ZERO

    total_days = (end - start).days + 1
    elapsed_days = max(0, min((today - start).days + 1, total_days))
    # Quantizado a 3 casas decimais (mesma escala de GOAL_VALUE) — divisões
    # de Decimal sem isto produzem dízimas com dezenas de casas, inúteis
    # para apresentação.
    quantum = Decimal("0.001")
    expected_pace = (
        (target * Decimal(elapsed_days) / Decimal(total_days)).quantize(quantum) if total_days > 0 else ZERO
    )
    projection = (
        (realized / Decimal(elapsed_days) * Decimal(total_days)).quantize(quantum) if elapsed_days > 0 else ZERO
    )

    if target <= ZERO:
        pace_status = "no_target"
    elif realized >= expected_pace:
        pace_status = "ahead" if realized > expected_pace else "on_track"
    else:
        pace_status = "behind"

    return GoalProgress(
        goal=goal,
        realized=realized,
        percent=round(percent, 1),
        missing=missing,
        expected_pace=expected_pace,
        projection=projection,
        pace_status=pace_status,
    )


def visible_goals_query(db: Session, ctx: AuthContext):
    if ctx.has_permission("performance.view_all"):
        return db.query(GoalPeriod)
    if ctx.has_permission("performance.view_own"):
        return db.query(GoalPeriod).filter(
            (GoalPeriod.pm_person_id == ctx.person_id) | (GoalPeriod.scope == "company")
        )
    return db.query(GoalPeriod).filter(False)


def list_goals(
    db: Session,
    ctx: AuthContext,
    *,
    year: int | None = None,
    pm_person_id: uuid.UUID | None = None,
    period_type: str | None = None,
    quarter: int | None = None,
    semester: int | None = None,
    month: int | None = None,
) -> list[GoalPeriod]:
    query = visible_goals_query(db, ctx)
    if year is not None:
        query = query.filter(GoalPeriod.year == year)
    if pm_person_id is not None:
        query = query.filter(GoalPeriod.pm_person_id == pm_person_id)
    if period_type is not None:
        query = query.filter(GoalPeriod.period_type == period_type)
    if quarter is not None:
        query = query.filter(GoalPeriod.quarter == quarter)
    if semester is not None:
        query = query.filter(GoalPeriod.semester == semester)
    if month is not None:
        query = query.filter(GoalPeriod.month == month)
    return query.order_by(GoalPeriod.year.desc(), GoalPeriod.metric.asc()).all()


def create_goal(
    db: Session,
    *,
    period_type: str,
    year: int,
    quarter: int | None,
    semester: int | None,
    month: int | None,
    metric: str,
    target_value: Decimal,
    scope: str,
    pm_person_id: uuid.UUID | None,
    created_by_person_id: uuid.UUID | None,
    notes: str = "",
) -> GoalPeriod:
    if period_type not in PERIOD_TYPES:
        raise PerformanceError(f"Tipo de período inválido: {period_type!r}")
    if metric not in GOAL_METRICS:
        raise PerformanceError(f"Métrica inválida: {metric!r}")
    if target_value <= ZERO:
        raise PerformanceError("O objetivo tem de ser positivo.")
    period_bounds(period_type=period_type, year=year, quarter=quarter, semester=semester, month=month)

    goal = GoalPeriod(
        period_type=period_type,
        year=year,
        quarter=quarter,
        semester=semester,
        month=month,
        metric=metric,
        target_value=target_value,
        scope=scope,
        pm_person_id=pm_person_id,
        created_by_person_id=created_by_person_id,
        notes=notes,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


def update_goal(
    db: Session, *, goal: GoalPeriod, changes: dict, changed_by_person_id: uuid.UUID | None
) -> GoalPeriod:
    if "target_value" in changes and changes["target_value"] <= ZERO:
        raise PerformanceError("O objetivo tem de ser positivo.")
    for field_name, new_value in changes.items():
        old_value = getattr(goal, field_name)
        if old_value == new_value:
            continue
        db.add(
            GoalPeriodHistory(
                goal_period_id=goal.id,
                field_name=field_name,
                old_value=str(old_value) if old_value is not None else None,
                new_value=str(new_value) if new_value is not None else None,
                changed_by_person_id=changed_by_person_id,
                source="ui",
            )
        )
        setattr(goal, field_name, new_value)
    db.commit()
    db.refresh(goal)
    return goal


@dataclasses.dataclass
class PortfolioBreakdown:
    not_started: int
    in_progress: int
    completed: int
    kwp_not_started: Decimal
    kwp_in_progress: Decimal
    kwp_completed: Decimal
    certified_count: int
    pending_certification_count: int


def compute_portfolio_breakdown(db: Session, ctx: AuthContext) -> PortfolioBreakdown:
    """Distribuição do portefólio por estado — usa
    `compute_project_task_summary` (a mesma fonte de verdade do dashboard e
    da lista de projetos) para nunca divergir da definição de estado
    usada no resto da aplicação."""
    from app.services.projects import compute_project_task_summary, visible_projects_query

    projects = visible_projects_query(db, ctx).filter(Project.is_active.is_(True)).all()
    counts = {"nao_iniciado": 0, "em_curso": 0, "concluido": 0}
    kwp = {"nao_iniciado": ZERO, "em_curso": ZERO, "concluido": ZERO}
    certified = 0
    pending_certification = 0
    licensing_by_project = {
        lic.project_id: lic
        for lic in db.query(ProjectLicensingData).filter(
            ProjectLicensingData.project_id.in_([p.id for p in projects])
        )
    }
    for project in projects:
        summary = compute_project_task_summary(db, project.id)
        counts[summary.status] += 1
        if project.power_kwp:
            kwp[summary.status] += Decimal(str(project.power_kwp))
        licensing = licensing_by_project.get(project.id)
        if summary.status == "concluido":
            if licensing and licensing.certificate_date:
                certified += 1
            else:
                pending_certification += 1

    return PortfolioBreakdown(
        not_started=counts["nao_iniciado"],
        in_progress=counts["em_curso"],
        completed=counts["concluido"],
        kwp_not_started=kwp["nao_iniciado"],
        kwp_in_progress=kwp["em_curso"],
        kwp_completed=kwp["concluido"],
        certified_count=certified,
        pending_certification_count=pending_certification,
    )


def installations_and_kwp_by_year(
    db: Session, ctx: AuthContext, *, years_back: int = 5
) -> dict[int, dict[str, Decimal]]:
    """`{ano: {"installations": N, "kwp": Decimal}}` para os últimos
    `years_back` anos (incluindo o atual) — sem filtro de PM: é sempre o
    indicador histórico da operação inteira, disponível a quem tem
    `performance.view_all`/`view_own` (ver rota, que decide o âmbito)."""
    current_year = dt.date.today().year
    result: dict[int, dict[str, Decimal]] = {}
    for year in range(current_year - years_back + 1, current_year + 1):
        start, end = period_bounds(period_type="year", year=year, quarter=None, semester=None, month=None)
        rows = _completed_projects_query(db, start=start, end=end, pm_person_id=None)
        kwp_total = sum((Decimal(str(p.power_kwp)) for _, p in rows if p.power_kwp), start=ZERO)
        result[year] = {"installations": Decimal(len(rows)), "kwp": kwp_total}
    return result
