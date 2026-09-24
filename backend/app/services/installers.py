"""Instaladores, equipas e o plano de obra de um projeto (D-071)."""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.audit.log import record_project_change
from app.models.installer import Installer, InstallerTeam
from app.models.project import Project
from app.security.permissions import AuthContext, PermissionDenied, can_plan_project_work
from app.utils.text import clean_display, normalize_key

# Fase "Obra" do processo: do dia útil 41 ao 49 desde o arranque (`start_date`
# é o dia 1 do processo, não o início da obra). Modelo base do legado; só
# fins de semana contam como não úteis.
WORK_START_BUSINESS_DAY = 41
WORK_END_BUSINESS_DAY = 49


class PlanError(ValueError):
    """Erro de regra de negócio no plano de obra — mensagem segura para mostrar."""


def business_day(start: dt.date, n: int) -> dt.date:
    """O n-ésimo dia útil (1 = o primeiro dia útil em ou depois de `start`)."""
    day = start
    while day.weekday() >= 5:
        day += dt.timedelta(days=1)
    counted = 1
    while counted < n:
        day += dt.timedelta(days=1)
        if day.weekday() < 5:
            counted += 1
    return day


def derive_work_window(start_date: dt.date | None) -> tuple[dt.date, dt.date] | None:
    """Janela estimada da obra a partir do arranque do processo; `None` sem data."""
    if start_date is None:
        return None
    return business_day(start_date, WORK_START_BUSINESS_DAY), business_day(start_date, WORK_END_BUSINESS_DAY)


# --- instaladores e equipas ----------------------------------------------


def find_installer_by_name(db: Session, name: str, *, exclude_id: uuid.UUID | None = None) -> Installer | None:
    query = db.query(Installer).filter(Installer.name_key == normalize_key(name))
    if exclude_id is not None:
        query = query.filter(Installer.id != exclude_id)
    return query.one_or_none()


def get_or_create_installer(db: Session, name: str | None) -> Installer | None:
    """Devolve o instalador com este nome (sem maiúsculas nem acentos), criando-o
    se ainda não existir. Nome vazio → `None` (obra sem instalador)."""
    if name is None or not clean_display(str(name)):
        return None
    installer = find_installer_by_name(db, str(name))
    if installer is None:
        installer = Installer(name=clean_display(str(name)), name_key=normalize_key(str(name)))
        db.add(installer)
        db.flush()
    return installer


def find_team_by_name(
    db: Session, installer_id: uuid.UUID, name: str, *, exclude_id: uuid.UUID | None = None
) -> InstallerTeam | None:
    query = db.query(InstallerTeam).filter(
        InstallerTeam.installer_id == installer_id, InstallerTeam.name_key == normalize_key(name)
    )
    if exclude_id is not None:
        query = query.filter(InstallerTeam.id != exclude_id)
    return query.one_or_none()


def project_counts_by_installer(db: Session) -> tuple[dict[uuid.UUID, int], dict[uuid.UUID, int]]:
    """(obras por instalador, obras por equipa) — uma query cada, nunca por linha."""
    by_installer = dict(
        db.query(Project.installer_id, func.count(Project.id))
        .filter(Project.installer_id.is_not(None), Project.is_active.is_(True))
        .group_by(Project.installer_id)
        .all()
    )
    by_team = dict(
        db.query(Project.installer_team_id, func.count(Project.id))
        .filter(Project.installer_team_id.is_not(None), Project.is_active.is_(True))
        .group_by(Project.installer_team_id)
        .all()
    )
    return by_installer, by_team


# --- plano de obra de um projeto ------------------------------------------

_UNSET = object()


def update_work_plan(db: Session, *, project: Project, changes: dict, ctx: AuthContext) -> Project:
    """Só isto altera instalador, equipa e datas da obra a partir da API.

    `changes` contém apenas os campos enviados (`installer_id`,
    `installer_team_id`, `work_start_date`, `work_end_date`); `None` limpa.
    `work_dates_estimated=False` confirma as datas atuais sem as alterar.
    Regras:
    - permissão `project.plan_work` no âmbito do projeto;
    - a equipa tem de pertencer ao instalador e estar ativa (ao atribuir);
    - mudar de instalador sem indicar equipa limpa a equipa;
    - sem instalador não há equipa;
    - fim da obra nunca antes do início;
    - alterar as datas confirma-as (`work_dates_estimated` passa a falso).
    Cada campo alterado grava uma entrada em `project_history`.
    """
    if not can_plan_project_work(ctx, project):
        raise PermissionDenied("project.plan_work")

    new_installer_id = changes.get("installer_id", _UNSET)
    installer_id = project.installer_id if new_installer_id is _UNSET else new_installer_id
    team_id = changes["installer_team_id"] if "installer_team_id" in changes else _UNSET

    installer = None
    if installer_id is not None:
        installer = db.get(Installer, installer_id)
        if installer is None:
            raise PlanError("Instalador não encontrado.")
        if installer_id != project.installer_id and not installer.is_active:
            raise PlanError("Este instalador está inativo.")

    if team_id is _UNSET:
        # Sem equipa indicada: mantém-se, a não ser que o instalador tenha mudado
        # (a equipa antiga não pertence ao novo instalador) ou tenha sido retirado.
        team_id = project.installer_team_id if installer_id == project.installer_id else None
    if installer_id is None:
        if team_id is not None and "installer_team_id" in changes:
            raise PlanError("Sem instalador não pode haver equipa.")
        team_id = None
    if team_id is not None:
        team = db.get(InstallerTeam, team_id)
        if team is None or team.installer_id != installer_id:
            raise PlanError("A equipa não pertence a este instalador.")
        if team_id != project.installer_team_id and not team.is_active:
            raise PlanError("Esta equipa está inativa.")

    start = changes["work_start_date"] if "work_start_date" in changes else project.work_start_date
    end = changes["work_end_date"] if "work_end_date" in changes else project.work_end_date
    if start is not None and end is not None and end < start:
        raise PlanError("O fim da obra não pode ser anterior ao início.")

    def show(value: object) -> str | None:
        return str(value) if value is not None else None

    resulting = {
        "installer_id": installer_id,
        "installer_team_id": team_id,
        "work_start_date": start,
        "work_end_date": end,
    }
    dates_changed = False
    for field_name, new_value in resulting.items():
        old_value = getattr(project, field_name)
        if old_value == new_value:
            continue
        record_project_change(
            db,
            project_id=project.id,
            field_name=field_name,
            old_value=show(old_value),
            new_value=show(new_value),
            source="ui",
            changed_by_person_id=ctx.person_id,
            note="Plano de obra editado via API.",
        )
        setattr(project, field_name, new_value)
        if field_name in ("work_start_date", "work_end_date"):
            dates_changed = True
    confirm = changes.get("work_dates_estimated") is False
    if (dates_changed or confirm) and project.work_dates_estimated:
        record_project_change(
            db,
            project_id=project.id,
            field_name="work_dates_estimated",
            old_value="True",
            new_value="False",
            source="ui",
            changed_by_person_id=ctx.person_id,
            note="Datas da obra confirmadas." if confirm and not dates_changed else "Datas da obra editadas.",
        )
        project.work_dates_estimated = False
    elif dates_changed:
        project.work_dates_estimated = False
    db.commit()
    db.refresh(project)
    return project
