"""Regras do relatório semanal ao cliente.

O serviço concentra autorização, regras de âmbito e transições de estado. O
adaptador de envio é deliberadamente injetável: com `GRAPH_ENABLED=true` usa o
Microsoft Graph (`app.adapters.graph_mail`); desligado, grava um `.eml` no
outbox local e o envio fica `outbox_local` — nunca `sent`, porque o cliente
não recebeu nada.

Envio idempotente: a linha `pending` é gravada (commit) antes da chamada
externa e um índice único parcial em (project_id, iso_week) para os estados
ativos impede dois envios na mesma semana, mesmo com pedidos concorrentes.
"""
from __future__ import annotations

import datetime as dt
import html
import logging
import re
import uuid
from email.message import EmailMessage
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

from sqlalchemy import true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models.client_report import ClientReportConfig, ClientReportSend
from app.models.identity import User
from app.models.people import Person
from app.models.project import Project, ProjectHistory, ProjectStageProgress
from app.models.workflow import Phase, WorkflowStage
from app.security.permissions import AuthContext
from app.services.performance import completed_tasks_by_week
from app.utils.text import nfc_lower_strip

logger = logging.getLogger(__name__)

LISBON = ZoneInfo("Europe/Lisbon")
# Estados que ocupam a semana ISO de um projeto (índice único parcial
# `uq_client_report_sends_active_week`): um envio em curso, em revisão ou feito.
ACTIVE_SEND_STATUSES = ("pending", "pending_review", "sent")
STATUS_OUTBOX_LOCAL = "outbox_local"
OUTBOX_LOCAL_NOTE = "Graph desativado: mensagem gravada no outbox local e NÃO enviada ao cliente."
REPORT_MANAGE = "client_report.manage"
REPORT_VIEW = "client_report.view"
EXCLUDED_LIFECYCLE = {
    "entregue_cliente",
    "certificado_final",
    "on_hold",
    "on_hold_cliente",
    "entregue",
    "certificado",
    "concluido",
    "concluído",
}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ClientReportError(Exception):
    """Erro de domínio traduzido para uma resposta HTTP pela rota."""


class ClientReportNotFound(ClientReportError):
    pass


class ClientReportForbidden(ClientReportError):
    pass


class ClientReportValidationError(ClientReportError):
    pass


class GraphSenderUnavailable(ClientReportError):
    pass


class ReportSender(Protocol):
    def __call__(
        self,
        *,
        from_email: str,
        to_emails: list[str],
        cc_emails: list[str],
        subject: str,
        body_html: str,
    ) -> str: ...


def _normalise_status(value: str | None) -> str:
    if not value:
        return ""
    return nfc_lower_strip(value)


def is_project_reportable(project: Project) -> bool:
    """`NULL` é deliberadamente reportável; estados terminais/on-hold não."""
    return (
        project.deleted_at is None
        and bool(project.is_active)
        and _normalise_status(project.lifecycle_status) not in EXCLUDED_LIFECYCLE
    )


def current_iso_week(now: dt.datetime | None = None) -> str:
    local = (now or dt.datetime.now(dt.timezone.utc)).astimezone(LISBON)
    iso = local.isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


def _parse_time(value: dt.time | str) -> dt.time:
    if isinstance(value, dt.time):
        return value.replace(tzinfo=None)
    try:
        return dt.time.fromisoformat(value.strip())
    except (TypeError, ValueError) as exc:
        raise ClientReportValidationError("send_time deve estar no formato HH:MM ou HH:MM:SS.") from exc


def validate_report_config(payload: dict) -> dict:
    """Valida e normaliza a configuração antes de a persistir."""
    data = dict(payload)
    weekday = data.get("weekday", 0)
    if isinstance(weekday, bool) or not isinstance(weekday, int) or not 0 <= weekday <= 6:
        raise ClientReportValidationError("weekday deve ser um inteiro entre 0 e 6.")
    send_time = _parse_time(data.get("send_time", dt.time(9, 0)))
    to_emails = data.get("to_emails", [])
    cc_emails = data.get("cc_emails", [])
    if not isinstance(to_emails, list) or not 1 <= len(to_emails) <= 10:
        raise ClientReportValidationError("to_emails deve conter entre 1 e 10 endereços.")
    if not isinstance(cc_emails, list) or not 0 <= len(cc_emails) <= 10:
        raise ClientReportValidationError("cc_emails deve conter entre 0 e 10 endereços.")

    normalised_to: list[str] = []
    normalised_cc: list[str] = []
    seen: set[str] = set()
    for bucket, output in ((to_emails, normalised_to), (cc_emails, normalised_cc)):
        for raw in bucket:
            if not isinstance(raw, str):
                raise ClientReportValidationError("Todos os destinatários têm de ser texto.")
            address = raw.strip()
            key = address.casefold()
            if not EMAIL_RE.fullmatch(address):
                raise ClientReportValidationError(f"Endereço de email inválido: {address!r}.")
            if key in seen:
                raise ClientReportValidationError("Não são permitidos emails duplicados entre Para e CC.")
            seen.add(key)
            output.append(address)

    note = data.get("weekly_note")
    if note is not None and not isinstance(note, str):
        raise ClientReportValidationError("weekly_note deve ser texto ou nulo.")
    return {
        "enabled": bool(data.get("enabled", False)),
        "review_before_send": bool(data.get("review_before_send", False)),
        "weekday": weekday,
        "send_time": send_time,
        "to_emails": normalised_to,
        "cc_emails": normalised_cc,
        "weekly_note": note,
    }


def _project_or_404(db: Session, project_id: uuid.UUID) -> Project:
    project = db.query(Project).filter(Project.id == project_id, Project.deleted_at.is_(None)).one_or_none()
    if project is None:
        raise ClientReportNotFound("Projeto não encontrado.")
    return project


def _can_manage(ctx: AuthContext, project: Project) -> bool:
    if not ctx.has_permission(REPORT_MANAGE):
        return False
    # Administrador/Chefe têm âmbito global via project.view_all/edit_all. Um PM
    # só pode tocar nos projetos que lhe estão atribuídos.
    return ctx.has_permission("project.view_all") or ctx.has_permission("project.edit_all") or project.pm_person_id == ctx.person_id


def _require_project_access(ctx: AuthContext, project: Project, *, manage: bool) -> None:
    permission = REPORT_MANAGE if manage else REPORT_VIEW
    if not manage and ctx.has_permission(REPORT_MANAGE) and not _can_manage(ctx, project):
        raise ClientReportNotFound("Projeto não encontrado.")
    if not ctx.has_permission(permission) and not (not manage and _can_manage(ctx, project)):
        raise ClientReportForbidden(f"Permissão em falta: {permission}.")
    if manage:
        if not _can_manage(ctx, project):
            # Um PM autenticado tem capacidade, mas o projeto está fora do seu
            # âmbito: 404 evita revelar a existência de configurações.
            if ctx.has_permission(REPORT_MANAGE):
                raise ClientReportNotFound("Projeto não encontrado.")
            raise ClientReportForbidden(f"Permissão em falta: {REPORT_MANAGE}.")
    elif ctx.has_permission(REPORT_VIEW) and not (
        ctx.has_permission("project.view_all") or ctx.has_permission("project.edit_all") or project.pm_person_id == ctx.person_id
    ):
        raise ClientReportNotFound("Projeto não encontrado.")


def _config_or_none(db: Session, project_id: uuid.UUID) -> ClientReportConfig | None:
    return db.query(ClientReportConfig).filter(ClientReportConfig.project_id == project_id).one_or_none()


def _person_label(db: Session, person_id: uuid.UUID | None) -> str | None:
    if person_id is None:
        return None
    person = db.query(Person).filter(Person.id == person_id).one_or_none()
    return person.display_name if person else None


def _sender_email(db: Session, project: Project) -> str | None:
    if project.pm_person_id is None:
        return None
    user = (
        db.query(User)
        .filter(User.person_id == project.pm_person_id, User.is_active.is_(True))
        .one_or_none()
    )
    return user.email.strip() if user and user.email and EMAIL_RE.fullmatch(user.email.strip()) else None


def _phase_and_stage(db: Session, project: Project) -> tuple[str, str]:
    phase_name = "Fase não definida"
    if project.current_phase_id:
        phase = db.query(Phase).filter(Phase.id == project.current_phase_id).one_or_none()
        if phase:
            phase_name = phase.name
    stages = (
        db.query(WorkflowStage)
        # Sem fase atual: `true()` (sem filtro de fase).
        .filter(WorkflowStage.phase_id == project.current_phase_id if project.current_phase_id else true())
        .order_by(WorkflowStage.sort_order, WorkflowStage.id)
        .all()
    )
    if not stages:
        stages = db.query(WorkflowStage).order_by(WorkflowStage.sort_order, WorkflowStage.id).all()
    progress = {
        row.stage_id: row
        for row in db.query(ProjectStageProgress).filter(ProjectStageProgress.project_id == project.id).all()
    }
    current = next((stage for stage in stages if not progress.get(stage.id) or not progress[stage.id].contact_done), None)
    return phase_name, current.title if current else "Processo concluído"


def _planned_date(project: Project, offset: int | None) -> str | None:
    if project.start_date is None or offset is None:
        return None
    return (project.start_date + dt.timedelta(days=max(0, offset))).isoformat()


def _date_key(value: dt.datetime | None) -> dt.datetime:
    if value is None:
        return dt.datetime.min.replace(tzinfo=dt.timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def _recent_change_items(
    db: Session,
    project: Project,
    since: dt.datetime,
    until: dt.datetime,
) -> list[str]:
    """Recolhe alterações de estado do projeto no período do relatório."""
    items: list[tuple[dt.datetime, str]] = []
    allowed_fields = {"lifecycle_status", "current_phase_id", "stage_id", "contact_done", "done", "status"}
    labels = {
        "lifecycle_status": "Estado do projeto",
        "current_phase_id": "Fase atual",
        "stage_id": "Etapa atual",
        "contact_done": "Ponto de contacto",
        "done": "Passo concluído",
        "status": "Estado",
    }
    history = (
        db.query(ProjectHistory)
        .filter(
            ProjectHistory.project_id == project.id,
            ProjectHistory.changed_at >= since,
            ProjectHistory.changed_at <= until,
        )
        .order_by(ProjectHistory.changed_at.desc())
        .limit(50)
        .all()
    )
    for row in history:
        if row.field_name not in allowed_fields:
            continue
        old_value = html.escape(row.old_value or "—")
        new_value = html.escape(row.new_value or "—")
        text = f"{labels[row.field_name]}: {old_value} → {new_value}"
        items.append((row.changed_at, text))

    items.sort(key=lambda item: _date_key(item[0]), reverse=True)
    return [f"<li>{text}</li>" for _, text in items[:20]]


def _as_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def _as_lisbon(value: dt.datetime) -> dt.datetime:
    return _as_utc(value).astimezone(LISBON)


def _report_period_start(db: Session, project: Project, reference: dt.datetime) -> dt.datetime:
    """Use the latest successful send; before the first send use the existing 7-day window."""
    candidates = (
        db.query(ClientReportSend.sent_at)
        .filter(
            ClientReportSend.project_id == project.id,
            ClientReportSend.status == "sent",
            ClientReportSend.sent_at.isnot(None),
        )
        .order_by(ClientReportSend.sent_at.desc())
        .all()
    )
    reference_key = _date_key(reference)
    last_sent = next(
        (sent_at for (sent_at,) in candidates if sent_at is not None and _date_key(sent_at) <= reference_key),
        None,
    )
    return _as_utc(last_sent) if last_sent is not None else _as_utc(reference) - dt.timedelta(days=7)


def _completed_work_section(
    db: Session,
    project: Project,
    ctx: AuthContext,
    *,
    since: dt.datetime,
    until: dt.datetime,
) -> str:
    weeks = completed_tasks_by_week(
        db,
        ctx,
        from_date=_as_lisbon(since).date(),
        to_date=_as_lisbon(until).date(),
        project_id=project.id,
    )
    since_key = _date_key(since)
    until_key = _date_key(until)
    grouped: list[str] = []
    for week in weeks:
        entries: list[tuple[dt.datetime, str]] = []
        for pm in week.pms:
            for task in pm.tasks:
                if task.project_id != project.id:
                    continue
                completed_key = _date_key(task.completed_at)
                if not since_key <= completed_key <= until_key:
                    continue
                completed_date = _as_lisbon(task.completed_at).strftime("%d/%m/%Y")
                entries.append(
                    (
                        completed_key,
                        f"<li>{completed_date} — Tarefa: {html.escape(task.title)}</li>",
                    )
                )
            for step in pm.process_steps:
                completed_key = _date_key(step.completed_at)
                if not since_key <= completed_key <= until_key:
                    continue
                completed_date = _as_lisbon(step.completed_at).strftime("%d/%m/%Y")
                if step.kind == "stage":
                    label = f"Etapa concluída: {html.escape(step.title)}"
                else:
                    label = f"Subtarefa concluída: {html.escape(step.title)}"
                    if step.stage_title:
                        label += f" (etapa: {html.escape(step.stage_title)})"
                entries.append((completed_key, f"<li>{completed_date} — {label}</li>"))
        if not entries:
            continue
        entries.sort(key=lambda item: (item[0], item[1]))
        start = week.week_start.strftime("%d/%m/%Y")
        end = week.week_end.strftime("%d/%m/%Y")
        grouped.append(
            f"<h3>Semana ISO {week.iso_year}-W{week.iso_week:02d} ({start}–{end})</h3>"
            f"<ul>{''.join(text for _, text in entries)}</ul>"
        )
    if not grouped:
        grouped.append("<p>Sem trabalho concluído neste período</p>")
    return f"<h2>Trabalho concluído</h2>{''.join(grouped)}"


def _body_html(
    db: Session,
    project: Project,
    config: ClientReportConfig,
    ctx: AuthContext,
    now: dt.datetime | None = None,
) -> str:
    """Constrói apenas campos de processo/obra explicitamente permitidos."""
    reference = _as_utc(now or dt.datetime.now(dt.timezone.utc))
    since = _report_period_start(db, project, reference)
    phase, stage = _phase_and_stage(db, project)
    changes = _recent_change_items(db, project, since, reference)
    if not changes:
        changes = ["<li>Sem alterações registadas neste período.</li>"]
    completed_work = _completed_work_section(db, project, ctx, since=since, until=reference)

    stages = db.query(WorkflowStage).order_by(WorkflowStage.sort_order, WorkflowStage.id).all()
    progress = {
        row.stage_id: row
        for row in db.query(ProjectStageProgress).filter(ProjectStageProgress.project_id == project.id).all()
    }
    next_steps: list[str] = []
    for candidate in stages:
        record = progress.get(candidate.id)
        if record and record.contact_done:
            continue
        date_text = _planned_date(project, candidate.planned_end_offset_days)
        label = html.escape(candidate.title)
        if date_text:
            label += f" — data prevista: {html.escape(date_text)}"
        next_steps.append(f"<li>{label}</li>")
        if len(next_steps) == 3:
            break
    if not next_steps:
        next_steps = ["<li>Sem próximos passos registados.</li>"]

    dates: list[str] = []
    if project.work_start_date:
        dates.append(f"Início previsto: {project.work_start_date.isoformat()}")
    if project.work_end_date:
        dates.append(f"Fim previsto: {project.work_end_date.isoformat()}")
    dates_html = "<li>" + "</li><li>".join(html.escape(value) for value in dates) + "</li>" if dates else "<li>Sem datas previstas registadas.</li>"
    note = html.escape(config.weekly_note or "")
    return (
        "<html><body>"
        f"<h1>Relatório semanal — {html.escape(project.name)}</h1>"
        f"<p><strong>Fase:</strong> {html.escape(phase)}<br><strong>Etapa:</strong> {html.escape(stage)}</p>"
        f"<h2>Alterações registadas</h2><ul>{''.join(changes)}</ul>"
        f"{completed_work}"
        f"<h2>Próximos passos</h2><ul>{''.join(next_steps)}</ul>"
        f"<h2>Datas previstas</h2><ul>{dates_html}</ul>"
        f"<h2>Nota do PM</h2><p>{note}</p>"
        "</body></html>"
    )


def _subject(project: Project, iso_week: str) -> str:
    return f"Relatório semanal — {project.name} — {iso_week}"


def _warning_for_project(db: Session, project: Project, config: ClientReportConfig | None) -> list[str]:
    warnings: list[str] = []
    if project.pm_person_id is None:
        warnings.append("Sem PM atribuído.")
    elif _sender_email(db, project) is None:
        warnings.append("PM sem User ativo ou sem email.")
    if config is not None and not config.to_emails:
        warnings.append("Sem destinatários em Para.")
    return warnings


def _send_row_dict(row: ClientReportSend) -> dict:
    return {
        "id": str(row.id),
        "iso_week": row.iso_week,
        "status": row.status,
        "trigger": row.trigger,
        "subject": row.subject,
        "to_emails": list(row.to_emails or []),
        "cc_emails": list(row.cc_emails or []),
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "error": row.error,
    }


def _response(db: Session, project: Project, config: ClientReportConfig | None, ctx: AuthContext) -> dict:
    sends = (
        db.query(ClientReportSend)
        .filter(ClientReportSend.project_id == project.id)
        .order_by(ClientReportSend.created_at.desc())
        .limit(10)
        .all()
    )
    config_data = {
        "enabled": config.enabled if config else False,
        "review_before_send": config.review_before_send if config else False,
        "weekday": config.weekday if config else 0,
        "send_time": config.send_time.strftime("%H:%M:%S") if config else "09:00:00",
        "to_emails": list(config.to_emails or []) if config else [],
        "cc_emails": list(config.cc_emails or []) if config else [],
        "weekly_note": config.weekly_note if config else None,
    }
    return {
        "enabled": config_data["enabled"],
        "review_before_send": config_data["review_before_send"],
        "weekday": config_data["weekday"],
        "send_time": config_data["send_time"],
        "to_emails": config_data["to_emails"],
        "cc_emails": config_data["cc_emails"],
        "weekly_note": config_data["weekly_note"],
        "config": config_data if config else None,
        "can_manage": _can_manage(ctx, project),
        "delivery_mode": "graph" if get_settings().graph_enabled else "local",
        "preview_available": config is not None,
        "next_send_at": None,
        "warnings": _warning_for_project(db, project, config),
        "last_sends": [_send_row_dict(row) for row in sends],
    }


def get_report(db: Session, project_id: uuid.UUID, ctx: AuthContext) -> dict:
    project = _project_or_404(db, project_id)
    _require_project_access(ctx, project, manage=False)
    return _response(db, project, _config_or_none(db, project.id), ctx)


def update_report(db: Session, project_id: uuid.UUID, payload: dict, ctx: AuthContext) -> dict:
    project = _project_or_404(db, project_id)
    _require_project_access(ctx, project, manage=True)
    values = validate_report_config(payload)
    config = _config_or_none(db, project.id)
    if config is None:
        config = ClientReportConfig(project_id=project.id)
        db.add(config)
    for key, value in values.items():
        setattr(config, key, value)
    config.updated_by_person_id = ctx.person_id
    db.flush()
    return _response(db, project, config, ctx)


def preview_report(db: Session, project_id: uuid.UUID, ctx: AuthContext) -> dict:
    project = _project_or_404(db, project_id)
    _require_project_access(ctx, project, manage=False)
    config = _config_or_none(db, project.id)
    if config is None:
        raise ClientReportValidationError("Configure os destinatários antes de pré-visualizar.")
    from_email = _sender_email(db, project)
    iso_week = current_iso_week()
    return {
        "subject": _subject(project, iso_week),
        "body_html": _body_html(db, project, config, ctx),
        "from_email": from_email,
        "to": list(config.to_emails or []),
        "cc": list(config.cc_emails or []),
    }


def local_eml_sender(settings: Settings) -> ReportSender:
    """Cria um `.eml` no outbox configurado e devolve `local:<ficheiro>`."""
    def send(*, from_email: str, to_emails: list[str], cc_emails: list[str], subject: str, body_html: str) -> str:
        directory = Path(settings.graph_fallback_dir).expanduser()
        directory.mkdir(parents=True, exist_ok=True)
        filename = f"client-report-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex}.eml"
        target = directory / filename
        message = EmailMessage()
        message["From"] = from_email
        message["To"] = ", ".join(to_emails)
        if cc_emails:
            message["Cc"] = ", ".join(cc_emails)
        message["Subject"] = subject
        message.set_content("Este email está disponível em HTML.")
        message.add_alternative(body_html, subtype="html")
        target.write_bytes(bytes(message))
        return f"local:{target}"
    return send


def _find_existing_send(db: Session, project_id: uuid.UUID, iso_week: str) -> ClientReportSend | None:
    return (
        db.query(ClientReportSend)
        .filter(
            ClientReportSend.project_id == project_id,
            ClientReportSend.iso_week == iso_week,
            ClientReportSend.status.in_(ACTIVE_SEND_STATUSES),
        )
        .order_by(ClientReportSend.created_at.desc())
        .first()
    )


def _resolve_or_skip(db: Session, project: Project, config: ClientReportConfig, iso_week: str, trigger: str, body: str, subject: str) -> ClientReportSend | None:
    from_email = _sender_email(db, project)
    if from_email:
        return None
    if project.pm_person_id is None:
        reason = "Sem PM atribuído."
    else:
        reason = "PM sem User ativo ou sem email."
    row = ClientReportSend(
        project_id=project.id,
        iso_week=iso_week,
        status="skipped",
        trigger=trigger,
        subject=subject,
        body_html=body,
        from_email="",
        to_emails=list(config.to_emails or []),
        cc_emails=list(config.cc_emails or []),
        error=reason,
    )
    db.add(row)
    db.flush()
    return row


def _deliver(
    db: Session,
    row: ClientReportSend,
    *,
    sender: ReportSender | None,
    settings: Settings,
    now: dt.datetime | None = None,
) -> ClientReportSend:
    try:
        # A construção do sender fica dentro do try: um segredo Graph em falta
        # tem de resultar num envio `failed` auditado, não num 500 genérico.
        if sender is None:
            if settings.graph_enabled:
                from app.adapters.graph_mail import graph_sender
                sender = graph_sender(settings)
            else:
                sender = local_eml_sender(settings)
        message_id = sender(
            from_email=row.from_email,
            to_emails=list(row.to_emails or []),
            cc_emails=list(row.cc_emails or []),
            subject=row.subject,
            body_html=row.body_html,
        )
    except Exception as exc:  # erro fica auditado e registado no log
        logger.exception("Falha ao entregar o relatório semanal send=%s projeto=%s", row.id, row.project_id)
        row.status = "failed"
        row.error = str(exc)[:2000]
        db.flush()
        return row
    row.graph_message_id = message_id
    row.sent_at = now or dt.datetime.now(dt.timezone.utc)
    if message_id.startswith("local:"):
        row.status = STATUS_OUTBOX_LOCAL
        row.error = OUTBOX_LOCAL_NOTE
        logger.warning("Relatório semanal send=%s projeto=%s ficou no outbox local (Graph desativado)", row.id, row.project_id)
    else:
        row.status = "sent"
        row.error = None
    db.flush()
    return row


def send_report(
    db: Session,
    project_id: uuid.UUID,
    ctx: AuthContext,
    *,
    trigger: str = "manual",
    sender: ReportSender | None = None,
    settings: Settings | None = None,
    now: dt.datetime | None = None,
) -> ClientReportSend:
    project = _project_or_404(db, project_id)
    _require_project_access(ctx, project, manage=True)
    if not is_project_reportable(project):
        raise ClientReportValidationError("O projeto não está elegível para relatório semanal.")
    config = _config_or_none(db, project.id)
    if config is None:
        raise ClientReportValidationError("O projeto não tem configuração de relatório.")
    if not config.enabled:
        raise ClientReportValidationError("A configuração do relatório está desativada.")
    if not config.to_emails:
        raise ClientReportValidationError("Configure pelo menos um destinatário em Para.")
    iso_week = current_iso_week(now)
    existing = _find_existing_send(db, project.id, iso_week)
    if existing is not None:
        return existing
    body = _body_html(db, project, config, ctx, now=now)
    subject = _subject(project, iso_week)
    skipped = _resolve_or_skip(db, project, config, iso_week, trigger, body, subject)
    if skipped is not None:
        return skipped
    row = ClientReportSend(
        project_id=project.id,
        iso_week=iso_week,
        status="pending_review" if config.review_before_send else "pending",
        trigger=trigger,
        subject=subject,
        body_html=body,
        from_email=_sender_email(db, project) or "",
        to_emails=list(config.to_emails or []),
        cc_emails=list(config.cc_emails or []),
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        # Outro pedido (scheduler, outra aba) ocupou a semana entretanto.
        db.rollback()
        existing = _find_existing_send(db, project_id, iso_week)
        if existing is not None:
            return existing
        raise
    if row.status == "pending_review":
        return row
    # A intenção de envio fica gravada antes da chamada externa: se o processo
    # cair depois de o email sair, a linha `pending` impede um reenvio.
    db.commit()
    result = _deliver(db, row, sender=sender, settings=settings or get_settings(), now=now)
    if result.status == "sent":
        config.weekly_note = None
    db.flush()
    return result


def approve_send(
    db: Session,
    send_id: uuid.UUID,
    ctx: AuthContext,
    *,
    sender: ReportSender | None = None,
    settings: Settings | None = None,
    now: dt.datetime | None = None,
) -> ClientReportSend:
    row = db.query(ClientReportSend).filter(ClientReportSend.id == send_id).one_or_none()
    if row is None:
        raise ClientReportNotFound("Rascunho não encontrado.")
    project = _project_or_404(db, row.project_id)
    _require_project_access(ctx, project, manage=True)
    if row.status != "pending_review":
        raise ClientReportValidationError("Só um rascunho pendente pode ser aprovado.")
    # Transição atómica pending_review -> pending: dois cliques ou duas abas
    # nunca aprovam (e enviam) o mesmo rascunho duas vezes.
    claimed = (
        db.query(ClientReportSend)
        .filter(ClientReportSend.id == row.id, ClientReportSend.status == "pending_review")
        .update(
            {ClientReportSend.status: "pending", ClientReportSend.approved_by_person_id: ctx.person_id},
            synchronize_session=False,
        )
    )
    if claimed != 1:
        raise ClientReportValidationError("Só um rascunho pendente pode ser aprovado.")
    db.commit()
    db.refresh(row)
    result = _deliver(db, row, sender=sender, settings=settings or get_settings(), now=now)
    if result.status == "sent":
        config = _config_or_none(db, project.id)
        if config:
            config.weekly_note = None
    db.flush()
    return result


def discard_send(db: Session, send_id: uuid.UUID, ctx: AuthContext) -> ClientReportSend:
    row = db.query(ClientReportSend).filter(ClientReportSend.id == send_id).one_or_none()
    if row is None:
        raise ClientReportNotFound("Rascunho não encontrado.")
    project = _project_or_404(db, row.project_id)
    _require_project_access(ctx, project, manage=True)
    if row.status != "pending_review":
        raise ClientReportValidationError("Só um rascunho pendente pode ser descartado.")
    row.status = "discarded"
    db.flush()
    return row


def expire_pending_reviews(db: Session, *, now: dt.datetime | None = None) -> int:
    current = current_iso_week(now)
    rows = db.query(ClientReportSend).filter(ClientReportSend.status == "pending_review").all()
    count = 0
    for row in rows:
        if row.iso_week != current:
            row.status = "expired"
            row.error = "Rascunho expirado no fim da semana ISO."
            count += 1
    db.flush()
    return count


def list_reports(db: Session, ctx: AuthContext, *, status: str | None = None, pm_person_id: uuid.UUID | None = None) -> list[dict]:
    if not ctx.has_permission(REPORT_VIEW) and not ctx.has_permission(REPORT_MANAGE):
        raise ClientReportForbidden(f"Permissão em falta: {REPORT_VIEW}.")
    query = (
        db.query(Project, ClientReportConfig)
        .join(ClientReportConfig, ClientReportConfig.project_id == Project.id)
        .filter(Project.deleted_at.is_(None))
    )
    if pm_person_id is not None:
        query = query.filter(Project.pm_person_id == pm_person_id)
    if not (ctx.has_permission("project.view_all") or ctx.has_permission("project.edit_all")):
        query = query.filter(Project.pm_person_id == ctx.person_id)
    result = []
    for project, config in query.order_by(Project.name).all():
        sends_query = db.query(ClientReportSend).filter(ClientReportSend.project_id == project.id)
        if status:
            sends_query = sends_query.filter(ClientReportSend.status == status)
        last = sends_query.order_by(ClientReportSend.created_at.desc()).first()
        if status and last is None:
            continue
        pending_count = db.query(ClientReportSend).filter(
            ClientReportSend.project_id == project.id,
            ClientReportSend.status == "pending_review",
        ).count()
        result.append({
            "project_id": str(project.id),
            "project_name": project.name,
            "client_name": project.client_name,
            "pm": _person_label(db, project.pm_person_id),
            "lifecycle_status": project.lifecycle_status,
            "status_label": last.status if last else None,
            "enabled": config.enabled,
            "next_send_at": None,
            "last_send": _send_row_dict(last) if last else None,
            "pending_review_count": pending_count,
            "to_emails": list(config.to_emails or []),
            "cc_emails": list(config.cc_emails or []),
        })
    return result
