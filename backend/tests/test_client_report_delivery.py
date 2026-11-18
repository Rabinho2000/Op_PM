"""Entrega do relatório semanal: idempotência, scheduler e adaptador Graph.

Cobre os achados C2/A1–A4 de docs/ANALISE_OP_PM.md. Nunca toca na rede: o
Graph usa um transporte falso e os envios "reais" um sender falso.
"""
from __future__ import annotations

import datetime as dt
import io
import json
from urllib import error, parse

import pytest
from sqlalchemy.exc import IntegrityError

from app.adapters.graph_mail import GraphDeliveryError, GraphMailSender
from app.cli import client_reports as cli
from app.config import Settings
from app.models.client_report import ClientReportSend
from app.models.identity import User
from app.models.project import Project
from app.security.permissions import load_auth_context
from app.services import client_report_scheduler as scheduler
from app.services import client_reports as reports
from app.services.client_reports import (
    ClientReportValidationError,
    approve_send,
    current_iso_week,
    send_report,
    update_report,
)

NOW = dt.datetime(2026, 9, 29, 12, 0, tzinfo=dt.timezone.utc)  # terça 13:00 Lisboa
ADMIN = "admin.sintetico@example.invalid"
PM = "pm.um.sintetico@example.invalid"


def _ctx(db, email):
    return load_auth_context(db, db.query(User).filter(User.email == email).one())


def _project(db, name="Instalação Sintética de Demonstração"):
    return db.query(Project).filter(Project.name == name).one()


def _settings(tmp_path, **overrides):
    return Settings(app_env="test", graph_enabled=False, graph_fallback_dir=str(tmp_path), **overrides)


def _graph_sender(**_kwargs):
    return "graph:pm@example.com"


def _enable(db, project, ctx, **extra):
    payload = {"enabled": True, "weekday": 1, "send_time": "13:00", "to_emails": ["cliente@example.com"]}
    payload.update(extra)
    update_report(db, project.id, payload, ctx)


# --- Idempotência ---------------------------------------------------------


def test_unique_index_rejects_second_active_send_in_same_week(db_session):
    project = _project(db_session)
    week = current_iso_week(NOW)

    def row(status):
        return ClientReportSend(
            project_id=project.id, iso_week=week, status=status, trigger="manual",
            subject="s", body_html="b", from_email="pm@example.com",
        )

    db_session.add(row("sent"))
    db_session.flush()
    # Estados inativos não ocupam a semana.
    db_session.add_all([row("failed"), row("outbox_local"), row("discarded")])
    db_session.flush()
    nested = db_session.begin_nested()
    db_session.add(row("pending"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    nested.rollback()


def test_concurrent_insert_returns_the_existing_send_instead_of_failing(db_session, tmp_path, monkeypatch):
    project = _project(db_session)
    ctx = _ctx(db_session, PM)
    _enable(db_session, project, ctx)
    winner = send_report(db_session, project.id, ctx, sender=_graph_sender, settings=_settings(tmp_path), now=NOW)
    db_session.commit()

    # Simula a corrida: a verificação prévia não vê o envio do outro pedido.
    calls = {"n": 0}
    real_find = reports._find_existing_send

    def racing_find(db, project_id, iso_week):
        calls["n"] += 1
        return None if calls["n"] == 1 else real_find(db, project_id, iso_week)

    monkeypatch.setattr(reports, "_find_existing_send", racing_find)
    sent_twice = []
    again = send_report(
        db_session, project.id, ctx, sender=lambda **kw: sent_twice.append(kw) or "graph:x",
        settings=_settings(tmp_path), now=NOW,
    )
    assert again.id == winner.id
    assert sent_twice == []
    assert db_session.query(ClientReportSend).filter_by(project_id=project.id).count() == 1


def test_approve_is_atomic_and_never_delivers_twice(db_session, tmp_path):
    project = _project(db_session)
    ctx = _ctx(db_session, PM)
    _enable(db_session, project, ctx, review_before_send=True)
    draft = send_report(db_session, project.id, ctx, settings=_settings(tmp_path), now=NOW)
    assert draft.status == "pending_review"

    # Outra aba já reclamou o rascunho (UPDATE por trás do objeto em memória).
    db_session.query(ClientReportSend).filter_by(id=draft.id).update({"status": "pending"}, synchronize_session=False)
    delivered = []
    with pytest.raises(ClientReportValidationError):
        approve_send(
            db_session, draft.id, ctx, sender=lambda **kw: delivered.append(kw) or "graph:x",
            settings=_settings(tmp_path), now=NOW,
        )
    assert delivered == []


def test_missing_graph_secret_is_an_audited_failure_not_a_crash(db_session, tmp_path):
    project = _project(db_session)
    ctx = _ctx(db_session, PM)
    _enable(db_session, project, ctx, weekly_note="Nota a manter")
    settings = Settings(
        app_env="test", graph_enabled=True, graph_tenant_id="tenant-sintetico",
        graph_client_id="client-sintetico", graph_client_secret_file=str(tmp_path / "nao-existe"),
        graph_fallback_dir=str(tmp_path),
    )
    row = send_report(db_session, project.id, ctx, settings=settings, now=NOW)
    assert row.status == "failed"
    assert "GRAPH_CLIENT_SECRET_FILE" in row.error
    assert not list(tmp_path.glob("*.eml"))


# --- Scheduler -------------------------------------------------------------


def test_run_due_isolates_failures_and_keeps_earlier_sends(db_session, tmp_path, monkeypatch):
    admin = _ctx(db_session, ADMIN)
    first = _project(db_session)
    second = _project(db_session, "Instalação Sintética A — Início Próximo")
    for project in (first, second):
        _enable(db_session, project, admin)
    db_session.commit()

    real_send = scheduler.send_report
    calls = {"n": 0}

    def flaky_send(db, project_id, ctx, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("falha sintética a meio do ciclo")
        return real_send(db, project_id, ctx, **kwargs)

    monkeypatch.setattr(scheduler, "send_report", flaky_send)
    results = scheduler.run_due(db_session, now=NOW, system_context=admin, sender=_graph_sender, settings=_settings(tmp_path))

    assert scheduler.summarize(results) == {"error": 1, "sent": 1}
    # O envio feito antes da falha não foi desfeito pelo rollback.
    assert db_session.query(ClientReportSend).filter(ClientReportSend.status == "sent").count() == 1
    # E não volta a ser enviado no ciclo seguinte.
    monkeypatch.setattr(scheduler, "send_report", real_send)
    again = scheduler.run_due(
        db_session, now=NOW + dt.timedelta(minutes=5), system_context=admin,
        sender=_graph_sender, settings=_settings(tmp_path),
    )
    assert scheduler.summarize(again) == {"sent": 1}
    assert db_session.query(ClientReportSend).filter(ClientReportSend.status == "sent").count() == 2


def test_failed_scheduled_send_is_not_retried_in_a_loop(db_session, tmp_path):
    admin = _ctx(db_session, ADMIN)
    _enable(db_session, _project(db_session), admin)

    def failing(**_kwargs):
        raise RuntimeError("Graph em baixo")

    first = scheduler.run_due(db_session, now=NOW, system_context=admin, sender=failing, settings=_settings(tmp_path))
    assert scheduler.summarize(first) == {"failed": 1}
    later = scheduler.run_due(
        db_session, now=NOW + dt.timedelta(minutes=5), system_context=admin,
        sender=failing, settings=_settings(tmp_path),
    )
    assert later == []


def test_scheduler_identity_requires_manage_and_global_scope(db_session, tmp_path):
    ctx = cli.resolve_system_context(db_session, _settings(tmp_path))
    assert ctx.has_permission("client_report.manage")
    assert ctx.has_permission("project.view_all") or ctx.has_permission("project.edit_all")

    explicit = cli.resolve_system_context(db_session, _settings(tmp_path, client_report_scheduler_email=ADMIN.upper()))
    assert explicit.has_permission("client_report.manage")

    with pytest.raises(cli.SchedulerIdentityError):
        cli.resolve_system_context(db_session, _settings(tmp_path, client_report_scheduler_email=PM))
    with pytest.raises(cli.SchedulerIdentityError):
        cli.resolve_system_context(db_session, _settings(tmp_path, client_report_scheduler_email="ninguem@example.invalid"))


def test_health_command_reads_the_heartbeat(tmp_path, monkeypatch):
    heartbeat = tmp_path / "hb"
    settings = _settings(tmp_path, client_report_scheduler_heartbeat_file=str(heartbeat))
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    assert cli.main(["health"]) == 1
    cli.write_heartbeat(heartbeat, dt.datetime.now(dt.timezone.utc))
    assert cli.main(["health", "--max-age", "60"]) == 0
    cli.write_heartbeat(heartbeat, dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1))
    assert cli.main(["health", "--max-age", "60"]) == 1


# --- Adaptador Microsoft Graph ---------------------------------------------


class _Response:
    def __init__(self, body: bytes = b""):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _graph_settings(tmp_path):
    secret = tmp_path / "graph_secret"
    secret.write_text("segredo-sintetico\n", encoding="utf-8")
    return Settings(
        app_env="test", graph_enabled=True, graph_tenant_id="tenant-sintetico",
        graph_client_id="client-sintetico", graph_client_secret_file=str(secret),
    )


def test_graph_token_request_is_form_urlencoded_and_sender_is_quoted(tmp_path):
    requests = []

    def transport(req, timeout):
        requests.append(req)
        if "oauth2" in req.full_url:
            return _Response(json.dumps({"access_token": "token-sintetico"}).encode())
        return _Response()

    sender = GraphMailSender(_graph_settings(tmp_path), transport=transport)
    result = sender(
        from_email="pm+ops@example.com", to_emails=["c@example.com"], cc_emails=[],
        subject="Assunto", body_html="<p>x</p>",
    )

    token_req, mail_req = requests
    assert token_req.get_header("Content-type") == "application/x-www-form-urlencoded"
    form = parse.parse_qs(token_req.data.decode())
    assert form["grant_type"] == ["client_credentials"]
    assert form["client_secret"] == ["segredo-sintetico"]
    assert form["scope"] == ["https://graph.microsoft.com/.default"]
    assert mail_req.full_url == "https://graph.microsoft.com/v1.0/users/pm%2Bops@example.com/sendMail"
    assert mail_req.get_header("Authorization") == "Bearer token-sintetico"
    assert json.loads(mail_req.data)["message"]["toRecipients"] == [{"emailAddress": {"address": "c@example.com"}}]
    assert result == "graph:pm+ops@example.com"


def test_graph_http_error_keeps_entra_code_but_never_the_secret(tmp_path):
    def transport(req, timeout):
        body = json.dumps({"error": "invalid_client", "error_description": "AADSTS7000215: Invalid client secret."})
        raise error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(body.encode()))

    sender = GraphMailSender(_graph_settings(tmp_path), transport=transport)
    with pytest.raises(GraphDeliveryError) as excinfo:
        sender(from_email="pm@example.com", to_emails=["c@example.com"], cc_emails=[], subject="s", body_html="b")
    message = str(excinfo.value)
    assert "HTTP 401" in message and "AADSTS7000215" in message
    assert "segredo-sintetico" not in message


def test_graph_without_access_token_fails_closed(tmp_path):
    sender = GraphMailSender(_graph_settings(tmp_path), transport=lambda req, timeout: _Response(b"{}"))
    with pytest.raises(reports.GraphSenderUnavailable):
        sender(from_email="pm@example.com", to_emails=["c@example.com"], cc_emails=[], subject="s", body_html="b")
