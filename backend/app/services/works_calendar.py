"""Calendário de obras (D-072): as obras (janela `work_start_date`–`work_end_date`)
com instalador e equipa, no âmbito de visibilidade do utilizador.

Regras:
- só projetos **ativos** e **visíveis** (`visible_projects_query`: todos, ou só os
  próprios como PM) — o calendário nunca alarga o âmbito;
- uma obra entra na janela pedida se as suas datas a intersectam (inclusive);
- **conflito**: a *mesma equipa* com duas obras sobrepostas. Só conta entre obras
  em `preparacao` ou `construcao` (as outras já acabaram ou estão em espera, e as
  datas estimadas das obras antigas gerariam conflitos falsos) e calcula-se sobre
  todas as obras visíveis da janela **antes** dos filtros de PM/estado/instalador,
  para o filtro não esconder o outro lado do conflito. Equipas diferentes do mesmo
  instalador não entram em conflito, nem obras sem equipa;
- **por planear**: projetos ativos ainda em `preparacao`, `construcao`, `on_hold`
  (ou sem estado) a que faltam as datas da obra. Obras já concluídas não aparecem.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import uuid

from sqlalchemy.orm import Session, joinedload

from app.models.project import Project
from app.security.permissions import AuthContext
from app.services.project_lifecycle import ON_HOLD
from app.services.projects import visible_projects_query

# Estados em que uma obra ocupa a equipa (para efeitos de conflito).
CONFLICT_STATES = frozenset({"preparacao", "construcao"})
# Estados em que falta planear uma obra sem datas.
TO_PLAN_STATES = frozenset({"preparacao", "construcao", ON_HOLD})
MAX_WINDOW_DAYS = 800
MAX_UNSCHEDULED = 200


class WindowError(ValueError):
    """Janela de datas inválida — mensagem segura para mostrar."""


@dataclasses.dataclass
class WorkEntry:
    project: Project
    conflict: bool = False


@dataclasses.dataclass
class WorksCalendar:
    start: dt.date
    end: dt.date
    works: list[WorkEntry]
    unscheduled: list[Project]
    unscheduled_total: int


def _overlaps(a: Project, b: Project) -> bool:
    return a.work_start_date <= b.work_end_date and b.work_start_date <= a.work_end_date


def _conflicting_ids(projects: list[Project]) -> set[uuid.UUID]:
    """Ids das obras que se sobrepõem a outra da mesma equipa (só estados de conflito)."""
    by_team: dict[uuid.UUID, list[Project]] = {}
    for project in projects:
        if project.installer_team_id is not None and project.lifecycle_status in CONFLICT_STATES:
            by_team.setdefault(project.installer_team_id, []).append(project)
    result: set[uuid.UUID] = set()
    for group in by_team.values():
        group.sort(key=lambda p: (p.work_start_date, p.work_end_date))
        # Varrimento: cada obra é comparada com as que ainda estão em curso.
        active: list[Project] = []
        for project in group:
            active = [a for a in active if a.work_end_date >= project.work_start_date]
            for other in active:
                if _overlaps(project, other):
                    result.add(project.id)
                    result.add(other.id)
            active.append(project)
    return result


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
    if (end - start).days > MAX_WINDOW_DAYS:
        raise WindowError(f"A janela não pode exceder {MAX_WINDOW_DAYS} dias.")

    base = (
        visible_projects_query(db, ctx)
        .options(joinedload(Project.pm))
        .filter(Project.is_active.is_(True))
    )

    # Uma só ida à base para as obras da janela (o resto filtra-se em memória:
    # são, no máximo, algumas centenas).
    in_window = (
        base.filter(
            Project.work_start_date.is_not(None),
            Project.work_end_date.is_not(None),
            Project.work_start_date <= end,
            Project.work_end_date >= start,
        )
        .order_by(Project.work_start_date, Project.name)
        .all()
    )
    conflicts = _conflicting_ids(in_window)

    def wanted(project: Project) -> bool:
        if pm_person_id is not None and project.pm_person_id != pm_person_id:
            return False
        if lifecycle_statuses and project.lifecycle_status not in lifecycle_statuses:
            return False
        if installer_id is not None and project.installer_id != installer_id:
            return False
        if team_id is not None and project.installer_team_id != team_id:
            return False
        return True

    works = [WorkEntry(project=p, conflict=p.id in conflicts) for p in in_window if wanted(p)]

    to_plan = [
        p
        for p in base.filter(
            (Project.work_start_date.is_(None)) | (Project.work_end_date.is_(None))
        )
        .order_by(Project.name)
        .all()
        if (p.lifecycle_status is None or p.lifecycle_status in TO_PLAN_STATES) and wanted(p)
    ]
    return WorksCalendar(
        start=start,
        end=end,
        works=works,
        unscheduled=to_plan[:MAX_UNSCHEDULED],
        unscheduled_total=len(to_plan),
    )
