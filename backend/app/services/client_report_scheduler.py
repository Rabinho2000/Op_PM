"""Execução agendada dos relatórios semanais ao cliente.

Cada configuração dispara no máximo uma vez por semana ISO (Europe/Lisbon):
fica "devida" a partir do dia/hora configurados e durante `CATCH_UP_WINDOW`,
desde que ainda não exista nenhuma linha de envio do projeto nessa semana
(enviado, em revisão, outbox local, falhado, ignorado, descartado, expirado).

Consequências deliberadas:
- um ciclo de 5 minutos (ou um reinício do container) nunca salta a hora;
- uma falha não é repetida automaticamente em ciclo — fica `failed`, visível
  na UI, e o PM pode usar "Enviar agora";
- cada projeto é confirmado (commit) isoladamente: a falha de um não desfaz
  os envios já feitos aos outros.
"""
from __future__ import annotations

import datetime as dt
import logging
from collections import Counter
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.client_report import ClientReportConfig, ClientReportSend
from app.models.project import Project
from app.security.permissions import AuthContext
from app.services.client_reports import (
    current_iso_week,
    expire_pending_reviews,
    is_project_reportable,
    send_report,
)

logger = logging.getLogger(__name__)

LISBON = ZoneInfo("Europe/Lisbon")
CATCH_UP_WINDOW = dt.timedelta(hours=48)


def scheduled_at(config: ClientReportConfig, now: dt.datetime) -> dt.datetime:
    """Data/hora (Lisboa) em que a configuração dispara na semana ISO de `now`."""
    local = now.astimezone(LISBON)
    monday = local.date() - dt.timedelta(days=local.weekday())
    day = monday + dt.timedelta(days=config.weekday)
    return dt.datetime.combine(day, config.send_time, tzinfo=LISBON)


def due_configs(db: Session, *, now: dt.datetime) -> list[tuple[Project, ClientReportConfig]]:
    local = now.astimezone(LISBON)
    iso_week = current_iso_week(now)
    rows = (
        db.query(Project, ClientReportConfig)
        .join(ClientReportConfig, ClientReportConfig.project_id == Project.id)
        .filter(
            ClientReportConfig.enabled.is_(True),
            Project.is_active.is_(True),
            Project.deleted_at.is_(None),
        )
        .all()
    )
    handled = {
        project_id
        for (project_id,) in db.query(ClientReportSend.project_id)
        .filter(ClientReportSend.iso_week == iso_week)
        .distinct()
    }
    due: list[tuple[Project, ClientReportConfig]] = []
    for project, config in rows:
        if project.id in handled or not config.to_emails or not is_project_reportable(project):
            continue
        start = scheduled_at(config, local)
        if start <= local < start + CATCH_UP_WINDOW:
            due.append((project, config))
    return due


def run_due(db: Session, *, now: dt.datetime, system_context: AuthContext, sender=None, settings=None) -> list:
    """Envia os relatórios devidos. Devolve uma linha `ClientReportSend` ou a
    exceção por projeto; nunca deixa a falha de um projeto afetar os outros."""
    expired = expire_pending_reviews(db, now=now)
    db.commit()
    if expired:
        logger.info("Rascunhos de relatório expirados: %d", expired)
    results: list = []
    for project, _config in due_configs(db, now=now):
        project_id = project.id
        try:
            row = send_report(
                db, project_id, system_context, trigger="scheduled", sender=sender, settings=settings, now=now
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.exception("Relatório semanal agendado falhou: projeto=%s", project_id)
            results.append(exc)
            continue
        logger.info("Relatório semanal agendado: projeto=%s estado=%s send=%s", project_id, row.status, row.id)
        results.append(row)
    return results


def summarize(results: list) -> dict[str, int]:
    """Contagem por estado final (`error` para exceções)."""
    counts: Counter[str] = Counter()
    for result in results:
        counts["error" if isinstance(result, Exception) else str(result.status)] += 1
    return dict(sorted(counts.items()))
