"""Execução agendada de relatórios semanais."""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.client_report import ClientReportConfig
from app.models.project import Project
from app.security.permissions import AuthContext
from app.services.client_reports import expire_pending_reviews, send_report

LISBON = ZoneInfo("Europe/Lisbon")


def due_configs(db: Session, *, now: dt.datetime) -> list[tuple[Project, ClientReportConfig]]:
    local = now.astimezone(LISBON)
    rows = (
        db.query(Project, ClientReportConfig)
        .join(ClientReportConfig, ClientReportConfig.project_id == Project.id)
        .filter(ClientReportConfig.enabled.is_(True), Project.is_active.is_(True))
        .all()
    )
    return [
        (project, config)
        for project, config in rows
        if config.weekday == local.weekday()
        and config.send_time.hour == local.hour
        and config.send_time.minute == local.minute
    ]


def run_due(db: Session, *, now: dt.datetime, system_context: AuthContext, sender=None, settings=None) -> list:
    results = []
    expire_pending_reviews(db, now=now)
    for project, _config in due_configs(db, now=now):
        try:
            results.append(send_report(db, project.id, system_context, trigger="scheduled", sender=sender, settings=settings, now=now))
        except Exception as exc:
            db.rollback()
            results.append(exc)
    db.commit()
    return results
