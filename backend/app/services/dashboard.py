"""Cálculo dos indicadores do dashboard inicial — sempre a partir de dados
reais em base de dados, nunca hardcoded. Cada indicador respeita a mesma
visibilidade já aplicada a projetos/tarefas/ausências (ver
app/services/projects.py, app/services/tasks.py, app/services/absences.py)
— um PM só vê os seus projetos/tarefas; um perfil sem `absence.view_all`
só vê as suas próprias férias/aniversário (ver docs/OPEN_QUESTIONS.md
sobre esta escolha de privacidade por omissão).

Sem dados financeiros em nenhum indicador — o módulo Financial está fora
deste MVP (ver docs/PLAN.md), por isso o requisito "vista Comercial não
mostra dados financeiros sem permissão" fica automaticamente satisfeito
nesta fase; nenhum indicador aqui depende de `cost.view`.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from app.models.absence import STATUS_APROVADA, Absence
from app.models.people import Person
from app.models.project import Project
from app.models.task import (
    OPEN_TASK_STATUSES,
    PRIORITY_URGENT,
    STATUS_DONE,
    TASK_TYPE_COMISSIONAMENTO,
    TASK_TYPE_VISITA_TECNICA,
    Task,
)
from app.schemas.dashboard import AbsenceMini, BirthdayMini, DashboardSummary, ProjectMini, TaskMini, WeekDaySummary
from app.security.permissions import AuthContext
from app.services.absences import visible_absences_query
from app.services.projects import compute_project_task_summary, visible_projects_query
from app.services.tasks import visible_tasks_query
from app.utils.timezones import LISBON_TZ, today_lisbon, week_range_lisbon

PROJECT_STARTING_WINDOW_DAYS = 30
UPCOMING_ABSENCE_WINDOW_DAYS = 30
UPCOMING_BIRTHDAY_WINDOW_DAYS = 30
MAX_LIST_ITEMS = 50


def _project_missing_fields(project: Project) -> list[str]:
    missing = []
    if not project.has_email:
        missing.append("email")
    if not project.has_contact:
        missing.append("contacto")
    if not project.has_coordinates:
        missing.append("coordenadas")
    return missing


def _project_mini(project: Project) -> ProjectMini:
    return ProjectMini(
        id=project.id,
        name=project.name,
        pm_display_name=project.pm.display_name if project.pm else None,
        start_date=project.start_date,
        missing_fields=_project_missing_fields(project),
    )


def _task_mini(task: Task) -> TaskMini:
    return TaskMini(
        id=task.id,
        title=task.title,
        task_type=task.task_type,
        priority=task.priority,
        project_id=task.project_id,
        project_name=task.project.name if task.project else "",
        assigned_to_display_name=task.assigned_to.display_name if task.assigned_to else None,
        due_date=task.due_date,
    )


def _absence_mini(absence: Absence) -> AbsenceMini:
    return AbsenceMini(
        id=absence.id,
        person_id=absence.person_id,
        person_display_name=absence.person.display_name if absence.person else "",
        start_date=absence.start_date,
        end_date=absence.end_date,
        type=absence.type,
    )


def _next_birthday_days_until(birth_date: dt.date, today: dt.date) -> int:
    month, day = birth_date.month, birth_date.day
    if month == 2 and day == 29:
        # Ano não bissexto: aproxima a 28 de fevereiro (limitação conhecida
        # e documentada — ver docs/OPEN_QUESTIONS.md).
        try:
            next_occurrence = dt.date(today.year, month, day)
        except ValueError:
            next_occurrence = dt.date(today.year, 2, 28)
    else:
        next_occurrence = dt.date(today.year, month, day)
    if next_occurrence < today:
        try:
            next_occurrence = dt.date(today.year + 1, month, day)
        except ValueError:
            next_occurrence = dt.date(today.year + 1, 2, 28)
    return (next_occurrence - today).days


def _birthday_scoped_people_query(db: Session, ctx: AuthContext):
    if ctx.has_permission("absence.view_all"):
        return db.query(Person).filter(Person.is_active.is_(True), Person.birth_date.isnot(None))
    if ctx.has_permission("absence.view_own"):
        return db.query(Person).filter(Person.id == ctx.person_id, Person.birth_date.isnot(None))
    return db.query(Person).filter(False)


def _week_overview(
    week_start: dt.date, open_tasks: list[Task], tasks: list[Task], absences: list[Absence]
) -> list[WeekDaySummary]:
    """Contagens por dia da semana corrente (segunda a domingo, Europe/Lisbon):
    tarefas abertas com prazo nesse dia, tarefas concluídas nesse dia, e
    pessoas ausentes (ausências aprovadas visíveis ao utilizador)."""
    # SQLite devolve DateTime sem fuso (gravado em UTC) — tratado como UTC.
    completed_dates = [
        (t.completed_at if t.completed_at.tzinfo else t.completed_at.replace(tzinfo=dt.timezone.utc))
        .astimezone(LISBON_TZ)
        .date()
        for t in tasks
        if t.status == STATUS_DONE and t.completed_at is not None
    ]
    days = []
    for offset in range(7):
        day = week_start + dt.timedelta(days=offset)
        days.append(
            WeekDaySummary(
                date=day,
                tasks_due_count=sum(1 for t in open_tasks if t.due_date == day),
                tasks_completed_count=sum(1 for d in completed_dates if d == day),
                people_absent_count=len({a.person_id for a in absences if a.start_date <= day <= a.end_date}),
            )
        )
    return days


def compute_dashboard_summary(db: Session, ctx: AuthContext) -> DashboardSummary:
    today = today_lisbon()
    week_start, week_end = week_range_lisbon(today)

    if ctx.has_permission("project.view_all"):
        scope = "all"
    elif ctx.has_permission("project.view_own"):
        scope = "own"
    else:
        scope = "none"

    projects = visible_projects_query(db, ctx).all()
    active_projects = [p for p in projects if p.is_active]

    projects_starting_soon = [
        p
        for p in active_projects
        if p.start_date is not None and today <= p.start_date <= today + dt.timedelta(days=PROJECT_STARTING_WINDOW_DAYS)
    ]
    projects_without_pm = [p for p in active_projects if not p.has_pm]
    projects_missing_data = [p for p in active_projects if not (p.has_email and p.has_contact and p.has_coordinates)]

    # Só tarefas de projetos ativos entram no backlog operacional — um
    # projeto inativo/arquivado não deve gerar "visitas pendentes" fantasma
    # (mesmo critério "só ativo" já aplicado acima aos projetos). Filtra
    # pelo projeto da própria tarefa (não pela lista `active_projects`
    # acima) para não excluir uma tarefa atribuída diretamente ao
    # utilizador num projeto ativo que não é o seu como PM.
    tasks = [t for t in visible_tasks_query(db, ctx).all() if t.project.is_active]
    open_tasks = [t for t in tasks if t.status in OPEN_TASK_STATUSES]

    overdue_tasks = sorted((t for t in open_tasks if t.is_overdue), key=lambda t: t.due_date or dt.date.max)
    tasks_due_this_week = sorted(
        (t for t in open_tasks if t.due_date is not None and week_start <= t.due_date <= week_end),
        key=lambda t: t.due_date or dt.date.max,
    )
    pending_technical_visits = [t for t in open_tasks if t.task_type == TASK_TYPE_VISITA_TECNICA]
    pending_commissioning = [t for t in open_tasks if t.task_type == TASK_TYPE_COMISSIONAMENTO]
    urgent_tasks = sorted(
        (t for t in open_tasks if t.priority == PRIORITY_URGENT),
        key=lambda t: (t.due_date is None, t.due_date or dt.date.max),
    )

    # Só ausências 'aprovada' aparecem no dashboard — uma cancelada não é
    # informação acionável para ninguém (ver app/models/absence.py).
    absences = [a for a in visible_absences_query(db, ctx).all() if a.status == STATUS_APROVADA]
    current_absences = [a for a in absences if a.start_date <= today <= a.end_date]
    upcoming_absences = [
        a
        for a in absences
        if a.start_date > today and a.start_date <= today + dt.timedelta(days=UPCOMING_ABSENCE_WINDOW_DAYS)
    ]

    # Aviso de fotografias (D-043) agregado no dashboard — mesma regra da
    # lista/detalhe de projetos, nunca uma segunda lógica divergente.
    projects_photos_pending = [
        p for p in active_projects if compute_project_task_summary(db, p.id).photos_pending_warning
    ]

    birthday_people = _birthday_scoped_people_query(db, ctx).all()
    upcoming_birthdays = []
    for person in birthday_people:
        days_until = _next_birthday_days_until(person.birth_date, today)
        if days_until <= UPCOMING_BIRTHDAY_WINDOW_DAYS:
            upcoming_birthdays.append(
                BirthdayMini(
                    person_id=person.id,
                    person_display_name=person.display_name,
                    birth_date=person.birth_date,
                    days_until=days_until,
                )
            )
    upcoming_birthdays.sort(key=lambda b: b.days_until)

    return DashboardSummary(
        generated_at=dt.datetime.now(dt.timezone.utc),
        scope=scope,
        week_start=week_start,
        week_end=week_end,
        active_projects_count=len(active_projects),
        projects_starting_next_30_days=[_project_mini(p) for p in projects_starting_soon[:MAX_LIST_ITEMS]],
        overdue_tasks=[_task_mini(t) for t in overdue_tasks[:MAX_LIST_ITEMS]],
        tasks_due_this_week=[_task_mini(t) for t in tasks_due_this_week[:MAX_LIST_ITEMS]],
        pending_technical_visits=[_task_mini(t) for t in pending_technical_visits[:MAX_LIST_ITEMS]],
        pending_commissioning=[_task_mini(t) for t in pending_commissioning[:MAX_LIST_ITEMS]],
        projects_without_pm=[_project_mini(p) for p in projects_without_pm[:MAX_LIST_ITEMS]],
        projects_missing_data=[_project_mini(p) for p in projects_missing_data[:MAX_LIST_ITEMS]],
        current_absences=[_absence_mini(a) for a in current_absences[:MAX_LIST_ITEMS]],
        upcoming_absences=[_absence_mini(a) for a in upcoming_absences[:MAX_LIST_ITEMS]],
        upcoming_birthdays=upcoming_birthdays[:MAX_LIST_ITEMS],
        urgent_tasks=[_task_mini(t) for t in urgent_tasks[:MAX_LIST_ITEMS]],
        projects_photos_pending=[_project_mini(p) for p in projects_photos_pending[:MAX_LIST_ITEMS]],
        week_overview=_week_overview(week_start, open_tasks, tasks, absences),
    )
