from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from app.config import Settings
from app.models.client_report import ClientReportConfig, ClientReportSend
from app.models.identity import User
from app.models.people import Person
from app.models.project import Project, ProjectHistory
from app.models.workflow import Phase
from app.security.permissions import load_auth_context
from app.services.client_reports import (
    ClientReportForbidden,
    ClientReportNotFound,
    ClientReportValidationError,
    approve_send,
    discard_send,
    expire_pending_reviews,
    get_report,
    is_project_reportable,
    list_reports,
    preview_report,
    send_report,
    update_report,
)
from app.services.client_report_scheduler import due_configs


NOW = dt.datetime(2026, 9, 29, 12, 0, tzinfo=dt.timezone.utc)


def _pm_context(db_session):
    user = db_session.query(User).filter(User.email == "pm.um.sintetico@example.invalid").one()
    return load_auth_context(db_session, user)


def _context(db_session, email: str):
    user = db_session.query(User).filter(User.email == email).one()
    return load_auth_context(db_session, user)


def _project_named(db_session, name: str):
    return db_session.query(Project).filter(Project.name == name).one()


def _project(db_session):
    return _project_named(db_session, "Instalação Sintética de Demonstração")


def _settings(tmp_path):
    return Settings(app_env="test", graph_enabled=False, graph_fallback_dir=str(tmp_path))


def test_due_configs_matches_lisbon_weekday_and_minute(db_session):
    project = _project(db_session)
    ctx = _pm_context(db_session)
    update_report(db_session, project.id, {"enabled": True, "weekday": 1, "send_time": "13:00", "to_emails": ["cliente@example.com"]}, ctx)
    assert due_configs(db_session, now=NOW)
    assert not due_configs(db_session, now=NOW + dt.timedelta(minutes=1))




def test_validate_recipient_cardinality_and_case_insensitive_duplicates():
    from app.services.client_reports import validate_report_config

    one = validate_report_config({"to_emails": ["one@example.com"], "cc_emails": []})
    ten = validate_report_config({"to_emails": [f"to{i}@example.com" for i in range(10)], "cc_emails": [f"cc{i}@example.com" for i in range(10)]})
    assert len(one["to_emails"]) == 1
    assert len(ten["to_emails"]) == 10
    assert len(ten["cc_emails"]) == 10

    with pytest.raises(ClientReportValidationError, match="entre 1 e 10"):
        validate_report_config({"to_emails": []})
    with pytest.raises(ClientReportValidationError, match="entre 1 e 10"):
        validate_report_config({"to_emails": [f"to{i}@example.com" for i in range(11)]})
    with pytest.raises(ClientReportValidationError, match="entre 0 e 10"):
        validate_report_config({"to_emails": ["one@example.com"], "cc_emails": [f"cc{i}@example.com" for i in range(11)]})
    with pytest.raises(ClientReportValidationError, match="duplicados"):
        validate_report_config({"to_emails": ["Client@example.com", "client@example.com"]})


def test_client_report_api_contract_and_read_only_permissions(db_session, api_client):
    project = _project(db_session)
    pm_headers = {"X-Dev-User-Email": "pm.um.sintetico@example.invalid"}
    viewer_headers = {"X-Dev-User-Email": "comercial.sintetico@example.invalid"}
    url = f"/api/projects/{project.id}/client-report"

    initial = api_client.get(url, headers=pm_headers)
    assert initial.status_code == 200
    assert initial.json()["can_manage"] is True

    saved = api_client.put(
        url,
        headers=pm_headers,
        json={"enabled": True, "to_emails": [" cliente@example.com "]},
    )
    assert saved.status_code == 200
    assert saved.json()["to_emails"] == ["cliente@example.com"]

    read_only = api_client.get(url, headers=viewer_headers)
    assert read_only.status_code == 200
    assert read_only.json()["can_manage"] is False
    denied = api_client.put(
        url,
        headers=viewer_headers,
        json={"enabled": True, "to_emails": ["outro@example.com"]},
    )
    assert denied.status_code == 403


def test_send_now_rejects_disabled_configuration(db_session, tmp_path):
    project = _project(db_session)
    ctx = _pm_context(db_session)
    update_report(
        db_session,
        project.id,
        {"enabled": False, "to_emails": ["cliente@example.com"]},
        ctx,
    )

    with pytest.raises(ClientReportValidationError, match="desativada"):
        send_report(db_session, project.id, ctx, settings=_settings(tmp_path), now=NOW)

    assert db_session.query(ClientReportConfig).filter_by(project_id=project.id).one().enabled is False


def test_validate_config_rejects_invalid_or_duplicate_recipients():
    from app.services.client_reports import validate_report_config

    with pytest.raises(ClientReportValidationError, match="inválido"):
        validate_report_config({"to_emails": ["sem-email"]})
    with pytest.raises(ClientReportValidationError, match="duplicados"):
        validate_report_config(
            {"to_emails": ["client@example.com"], "cc_emails": ["CLIENT@example.com"]}
        )
    with pytest.raises(ClientReportValidationError, match="entre 1 e 10"):
        validate_report_config({"to_emails": []})


def test_update_report_normalises_valid_config(db_session):
    project = _project(db_session)
    result = update_report(
        db_session,
        project.id,
        {
            "enabled": True,
            "review_before_send": True,
            "weekday": 2,
            "send_time": "10:30",
            "to_emails": [" client@example.com "],
            "cc_emails": [],
            "weekly_note": "Nota pública",
        },
        _pm_context(db_session),
    )
    assert result["enabled"] is True
    assert result["send_time"] == "10:30:00"
    assert result["to_emails"] == ["client@example.com"]
    assert result["review_before_send"] is True


def test_manual_send_uses_local_eml_and_clears_note_after_success(db_session, tmp_path):
    project = _project(db_session)
    ctx = _pm_context(db_session)
    update_report(
        db_session,
        project.id,
        {
            "enabled": True,
            "review_before_send": False,
            "to_emails": ["cliente@example.com"],
            "weekly_note": "Nota <script>alert('x')</script>",
        },
        ctx,
    )

    row = send_report(
        db_session,
        project.id,
        ctx,
        settings=_settings(tmp_path),
        now=NOW,
    )

    assert row.status == "sent"
    assert row.graph_message_id.startswith("local:")
    assert "Modo de teste" in row.error
    eml_path = Path(row.graph_message_id.removeprefix("local:"))
    assert eml_path.parent == tmp_path
    assert eml_path.exists()
    assert "saveToSentItems" not in row.body_html
    assert db_session.query(ClientReportConfig).filter_by(project_id=project.id).one().weekly_note is None


def test_manual_and_scheduled_send_are_idempotent_within_iso_week(db_session, tmp_path):
    project = _project(db_session)
    ctx = _pm_context(db_session)
    update_report(
        db_session,
        project.id,
        {"enabled": True, "to_emails": ["cliente@example.com"]},
        ctx,
    )

    first = send_report(db_session, project.id, ctx, trigger="manual", settings=_settings(tmp_path), now=NOW)
    second = send_report(
        db_session,
        project.id,
        ctx,
        trigger="scheduled",
        settings=_settings(tmp_path),
        now=NOW + dt.timedelta(hours=2),
    )

    assert first.id == second.id
    assert first.status == "sent"
    assert db_session.query(ClientReportSend).filter_by(project_id=project.id).count() == 1


def test_review_flow_pending_approve_discard_and_expire(db_session, tmp_path):
    project = _project(db_session)
    ctx = _pm_context(db_session)
    update_report(
        db_session,
        project.id,
        {
            "enabled": True,
            "review_before_send": True,
            "to_emails": ["cliente@example.com"],
            "weekly_note": "Nota para revisão",
        },
        ctx,
    )

    pending = send_report(db_session, project.id, ctx, settings=_settings(tmp_path), now=NOW)
    assert pending.status == "pending_review"
    assert db_session.query(ClientReportConfig).filter_by(project_id=project.id).one().weekly_note == "Nota para revisão"

    approved = approve_send(
        db_session,
        pending.id,
        ctx,
        settings=_settings(tmp_path),
        now=NOW,
    )
    assert approved.status == "sent"
    assert db_session.query(ClientReportConfig).filter_by(project_id=project.id).one().weekly_note is None

    update_report(
        db_session,
        project.id,
        {
            "enabled": True,
            "review_before_send": True,
            "to_emails": ["cliente@example.com"],
            "weekly_note": "Nota a descartar",
        },
        ctx,
    )
    discarded = send_report(
        db_session,
        project.id,
        ctx,
        settings=_settings(tmp_path),
        now=NOW + dt.timedelta(days=7),
    )
    assert discarded.status == "pending_review"
    assert discard_send(db_session, discarded.id, ctx).status == "discarded"

    old = send_report(
        db_session,
        project.id,
        ctx,
        settings=_settings(tmp_path),
        now=NOW - dt.timedelta(days=14),
    )
    assert old.status == "pending_review"
    assert expire_pending_reviews(db_session, now=NOW) == 1
    assert db_session.get(ClientReportSend, old.id).status == "expired"


def test_failed_delivery_keeps_weekly_note(db_session, tmp_path):
    project = _project(db_session)
    ctx = _pm_context(db_session)
    update_report(
        db_session,
        project.id,
        {
            "enabled": True,
            "to_emails": ["cliente@example.com"],
            "weekly_note": "Nota não enviada",
        },
        ctx,
    )

    def failing_sender(**_kwargs):
        raise RuntimeError("falha sintética")

    row = send_report(
        db_session,
        project.id,
        ctx,
        sender=failing_sender,
        settings=_settings(tmp_path),
        now=NOW,
    )
    assert row.status == "failed"
    assert "falha sintética" in row.error
    assert db_session.query(ClientReportConfig).filter_by(project_id=project.id).one().weekly_note == "Nota não enviada"


def test_global_list_honors_visibility_and_status_filters(db_session, tmp_path):
    admin = _context(db_session, "admin.sintetico@example.invalid")
    pm = _pm_context(db_session)
    demo = _project_named(db_session, "Instalação Sintética de Demonstração")
    upcoming = _project_named(db_session, "Instalação Sintética A — Início Próximo")
    no_pm = _project_named(db_session, "Instalação Sintética E — Sem PM Atribuído")

    for project, review in ((demo, False), (upcoming, True), (no_pm, False)):
        update_report(
            db_session,
            project.id,
            {
                "enabled": True,
                "review_before_send": review,
                "to_emails": ["cliente@example.com"],
            },
            admin,
        )
    sent = send_report(db_session, demo.id, admin, settings=_settings(tmp_path), now=NOW)
    pending = send_report(db_session, upcoming.id, admin, settings=_settings(tmp_path), now=NOW)
    assert sent.status == "sent"
    assert pending.status == "pending_review"

    visible_to_pm = list_reports(db_session, pm)
    assert {row["project_id"] for row in visible_to_pm} == {str(demo.id), str(upcoming.id)}

    global_rows = list_reports(db_session, admin)
    assert {row["project_id"] for row in global_rows} == {str(demo.id), str(upcoming.id), str(no_pm.id)}
    assert {row["project_id"] for row in list_reports(db_session, admin, status="sent")} == {str(demo.id)}
    assert {row["project_id"] for row in list_reports(db_session, admin, status="pending_review")} == {str(upcoming.id)}
    assert {row["project_id"] for row in list_reports(db_session, admin, pm_person_id=pm.person_id)} == {
        str(demo.id),
        str(upcoming.id),
    }


def test_missing_sender_identity_warns_and_does_not_send(db_session, tmp_path):
    ctx = _context(db_session, "admin.sintetico@example.invalid")
    projects = [
        Project(name="Sem PM", lifecycle_status="construcao", is_active=True),
    ]
    legacy_person = Person(display_name="PM sem User", email=None, is_active=False)
    db_session.add(legacy_person)
    db_session.flush()
    projects.append(
        Project(
            name="PM sem User ativo",
            lifecycle_status="construcao",
            is_active=True,
            pm_person_id=legacy_person.id,
        )
    )
    invalid_person = Person(display_name="PM sem email válido", email="sem-email", is_active=True)
    db_session.add(invalid_person)
    db_session.flush()
    db_session.add(User(person_id=invalid_person.id, email="sem-email", is_active=True))
    projects.append(
        Project(
            name="PM sem email válido",
            lifecycle_status="construcao",
            is_active=True,
            pm_person_id=invalid_person.id,
        )
    )
    db_session.add_all(projects)
    db_session.flush()

    rows = []
    for project in projects:
        update_report(
            db_session,
            project.id,
            {"enabled": True, "to_emails": ["cliente@example.com"]},
            ctx,
        )
        rows.append(send_report(db_session, project.id, ctx, settings=_settings(tmp_path), now=NOW))

    assert [row.status for row in rows] == ["skipped", "skipped", "skipped"]
    assert "Sem PM atribuído" in rows[0].error
    assert all("PM sem User ativo ou sem email" in (row.error or "") for row in rows[1:])
    assert not list(tmp_path.glob("*.eml"))


def test_preview_contains_safe_process_content_and_excludes_internal_data(db_session):
    project = _project(db_session)
    phase = db_session.query(Phase).order_by(Phase.sort_order).first()
    project.name = "Projeto <Cliente> & especial"
    project.current_phase_id = phase.id
    project.start_date = dt.date(2026, 9, 1)
    project.work_start_date = dt.date(2026, 10, 1)
    project.work_end_date = dt.date(2026, 10, 10)
    db_session.add(
        ProjectHistory(
            project_id=project.id,
            field_name="status",
            old_value="Em curso",
            new_value="<alteração> & segura",
            source="ui",
            changed_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1),
        )
    )
    db_session.add(
        ProjectHistory(
            project_id=project.id,
            field_name="cost",
            old_value="1000€",
            new_value="2000€",
            source="financial",
            changed_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1),
        )
    )
    ctx = _pm_context(db_session)
    update_report(
        db_session,
        project.id,
        {
            "enabled": True,
            "to_emails": ["cliente@example.com"],
            "weekly_note": "Nota <script>perigosa</script>",
        },
        ctx,
    )

    body = preview_report(db_session, project.id, ctx)["body_html"]

    assert "Projeto &lt;Cliente&gt; &amp; especial" in body
    assert "Nota &lt;script&gt;perigosa&lt;/script&gt;" in body
    assert phase.name in body
    assert "&lt;alteração&gt; &amp; segura" in body
    assert "data prevista:" in body
    assert "1000€" not in body and "2000€" not in body
    assert "licenciamento" not in body.lower()
    assert "comunica" not in body.lower()


def test_reportability_includes_null_and_excludes_terminal_client_states(db_session):
    null_status = Project(name="Projeto Sintético sem Estado", lifecycle_status=None, is_active=True)
    db_session.add(null_status)
    db_session.flush()

    assert is_project_reportable(null_status) is True

    pm_person_id = _project(db_session).pm_person_id
    terminal_projects = [
        Project(
            name=f"Projeto Sintético estado {status}",
            lifecycle_status=status,
            pm_person_id=pm_person_id,
            is_active=True,
        )
        for status in ("on_hold_cliente", "entregue_cliente", "certificado_final")
    ]
    db_session.add_all(terminal_projects)
    db_session.flush()
    assert all(is_project_reportable(project) is False for project in terminal_projects)

    inactive = Project(
        name="Projeto Sintético inativo",
        lifecycle_status="construcao",
        pm_person_id=pm_person_id,
        is_active=False,
    )
    db_session.add(inactive)
    db_session.flush()
    assert is_project_reportable(inactive) is False

    for name in (
        "Instalação Sintética E — Sem PM Atribuído",
        "Instalação Sintética F — PM Legado",
    ):
        assert is_project_reportable(_project_named(db_session, name)) is False


def test_pm_outside_project_scope_gets_not_found(db_session):
    project = _project_named(db_session, "Instalação Sintética Incompleta")

    with pytest.raises(ClientReportNotFound):
        get_report(db_session, project.id, _pm_context(db_session))

    with pytest.raises(ClientReportNotFound):
        update_report(
            db_session,
            project.id,
            {"enabled": True, "to_emails": ["cliente@example.com"]},
            _pm_context(db_session),
        )


def test_view_only_roles_can_read_but_not_write(db_session):
    project = _project(db_session)
    for email in (
        "comercial.sintetico@example.invalid",
        "financeiro.sintetico@example.invalid",
    ):
        ctx = _context(db_session, email)
        report = get_report(db_session, project.id, ctx)
        assert report["can_manage"] is False

        with pytest.raises(ClientReportForbidden):
            update_report(
                db_session,
                project.id,
                {"enabled": True, "to_emails": ["cliente@example.com"]},
                ctx,
            )


@pytest.mark.parametrize("email", ["chefe.sintetico@example.invalid", "admin.sintetico@example.invalid"])
def test_global_manage_roles_can_manage_any_project(db_session, email):
    project = _project_named(db_session, "Instalação Sintética E — Sem PM Atribuído")
    result = update_report(
        db_session,
        project.id,
        {"enabled": False, "to_emails": ["cliente@example.com"]},
        _context(db_session, email),
    )
    assert result["can_manage"] is True
