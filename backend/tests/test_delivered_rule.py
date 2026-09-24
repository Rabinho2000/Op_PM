"""Projetos entregues ao cliente (D-075): o atraso deixa de aparecer, e a regra que conclui
as etapas deixa só a inspeção final e o certificado."""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from app.cli import close_delivered_stages as cli
from app.models.project import Project, ProjectHistory, ProjectStageProgress, ProjectSubtaskProgress
from app.models.workflow import Phase, WorkflowStage, WorkflowSubtask
from app.services.process import _stage_status
from app.services.process_rules import RuleError, complete_delivered_projects

CHEFE = "chefe.sintetico@example.invalid"
OWN = "Instalação Sintética de Demonstração"
TEAM2 = "Instalação Sintética A — Início Próximo"


def _h(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def _project(db, name=OWN, state="entregue_cliente", start=dt.date(2024, 1, 8)) -> Project:
    project = db.query(Project).filter(Project.name == name).one()
    project.lifecycle_status = state
    project.start_date = start
    db.flush()
    return project


def _process(api_client, project):
    return api_client.get(f"/api/projects/{project.id}/process", headers=_h(CHEFE)).json()


def _stages(body) -> dict:
    return {s["code"]: s for phase in body["phases"] for s in phase["stages"]}


def _subtask(db, code: str) -> WorkflowSubtask:
    return db.query(WorkflowSubtask).filter(WorkflowSubtask.code == code).one()


# --- o atraso deixa de aparecer nos projetos entregues ----------------------------------------------


@pytest.mark.parametrize(
    ("done", "hide", "expected"),
    [
        (False, False, "overdue"),
        (False, True, "pending"),
        (True, True, "done"),  # o que está feito continua feito
        (True, False, "done"),
    ],
)
def test_stage_status_hides_overdue_for_delivered_projects(done, hide, expected):
    start, end, today = dt.date(2024, 1, 8), dt.date(2024, 1, 12), dt.date(2026, 9, 1)
    assert _stage_status(done, start, end, today, hide) == expected


def test_a_delivered_project_never_shows_overdue_stages_or_contacts(db_session, api_client):
    project = _project(db_session, state="entregue_cliente")
    body = _process(api_client, project)
    assert {s["status"] for s in _stages(body).values()} == {"pending"}
    assert body["summary"]["overdue_stages"] == 0 and body["summary"]["overdue_contacts"] == 0
    assert all(s["contact"]["overdue"] is False for s in _stages(body).values() if s["contact"])
    assert _stages(body)["etapa-04"]["planned_end"]  # as datas planeadas continuam a ver-se


def test_a_certified_project_also_hides_overdue(db_session, api_client):
    body = _process(api_client, _project(db_session, state="certificado_final"))
    assert body["summary"]["overdue_stages"] == 0 and {s["status"] for s in _stages(body).values()} == {"pending"}


@pytest.mark.parametrize("state", ["preparacao", "construcao", "on_hold_cliente", None])
def test_other_states_keep_showing_overdue(db_session, api_client, state):
    body = _process(api_client, _project(db_session, state=state))
    assert body["summary"]["overdue_stages"] == 18 and body["summary"]["overdue_contacts"] == 12


def test_moving_a_project_out_of_delivered_brings_the_overdue_back(db_session, api_client):
    project = _project(db_session, state="entregue_cliente")
    assert _process(api_client, project)["summary"]["overdue_stages"] == 0
    project.lifecycle_status = "construcao"
    db_session.flush()
    assert _process(api_client, project)["summary"]["overdue_stages"] == 18


# --- a regra que conclui as etapas ---------------------------------------------------------------------


def test_completes_everything_except_the_inspection_stage(db_session, api_client):
    project = _project(db_session)
    summary = complete_delivered_projects(db_session)
    assert summary["projects"] >= 1 and summary["projects_changed"] >= 1
    body = _process(api_client, project)
    stages = _stages(body)
    assert all(s["status"] == "done" for code, s in stages.items() if code != "etapa-18")
    assert stages["etapa-18"]["status"] == "pending" and stages["etapa-18"]["done_count"] == 0
    assert body["summary"]["done"] == 77 - 4 and body["summary"]["stages_done"] == 17 and body["summary"]["percent"] == round(100 * 73 / 77)
    # os pontos de contacto das outras etapas ficam feitos; o da etapa 18 continua por fazer
    contacts = {c: s["contact"] for c, s in stages.items() if s["contact"]}
    assert all(c["done"] for code, c in contacts.items() if code != "etapa-18")
    assert contacts["etapa-18"]["done"] is False


def test_what_the_rule_completes_is_marked_inferred_without_author_or_date(db_session, api_client):
    project = _project(db_session)
    complete_delivered_projects(db_session)
    stages = _stages(_process(api_client, project))
    sub = stages["etapa-05"]["subtasks"][0]
    assert (sub["done"], sub["source"], sub["done_at"], sub["done_by_display_name"]) == (True, "inferred", None, None)
    assert stages["etapa-04"]["contact"]["source"] == "inferred"


def test_never_overwrites_existing_progress(db_session, api_client):
    project = _project(db_session)
    legacy = _subtask(db_session, "etapa-05.0")
    unmarked = _subtask(db_session, "etapa-05.1")
    db_session.add(ProjectSubtaskProgress(project_id=project.id, subtask_id=legacy.id, done=True, source="legacy"))
    db_session.add(ProjectSubtaskProgress(project_id=project.id, subtask_id=unmarked.id, done=False, source="ui"))  # desmarcada na app
    db_session.flush()

    summary = complete_delivered_projects(db_session)
    assert summary["kept_unmarked_in_app"] >= 1
    rows = {r.subtask_id: r for r in db_session.query(ProjectSubtaskProgress).filter(ProjectSubtaskProgress.project_id == project.id)}
    assert rows[legacy.id].source == "legacy" and rows[legacy.id].done is True
    assert rows[unmarked.id].done is False and rows[unmarked.id].source == "ui"  # o Op_PM manda
    assert _stages(_process(api_client, project))["etapa-05"]["status"] != "done"  # falta a que foi desmarcada


def test_only_active_delivered_projects_are_touched(db_session):
    delivered = _project(db_session, OWN, "entregue_cliente")
    other_state = _project(db_session, TEAM2, "construcao")
    inactive = db_session.query(Project).filter(Project.name == "Instalação Sintética H — Inativa").one()
    inactive.lifecycle_status, inactive.is_active = "entregue_cliente", False
    db_session.flush()

    complete_delivered_projects(db_session)
    count = lambda p: db_session.query(ProjectSubtaskProgress).filter(ProjectSubtaskProgress.project_id == p.id).count()  # noqa: E731
    assert count(delivered) == 73
    assert count(other_state) == 0 and count(inactive) == 0


def test_is_idempotent_and_writes_one_history_entry_per_project(db_session):
    project = _project(db_session)
    complete_delivered_projects(db_session)
    again = complete_delivered_projects(db_session)
    assert (again["subtasks_marked"], again["contacts_marked"], again["projects_changed"]) == (0, 0, 0)
    entries = db_session.query(ProjectHistory).filter(ProjectHistory.project_id == project.id, ProjectHistory.field_name == "processo:concluído por regra").all()
    assert [(e.old_value, e.new_value, e.source) for e in entries] == [(None, "73 subtarefas, 11 contactos", "rule")]
    assert "etapa-18" in entries[0].note


def test_a_custom_exception_and_unknown_stage(db_session, api_client):
    project = _project(db_session)
    complete_delivered_projects(db_session, except_stage_codes=("etapa-17", "etapa-18"))
    stages = _stages(_process(api_client, project))
    assert stages["etapa-17"]["done_count"] == 0 and stages["etapa-18"]["done_count"] == 0 and stages["etapa-16"]["status"] == "done"
    with pytest.raises(RuleError, match="desconhecida"):
        complete_delivered_projects(db_session, except_stage_codes=("etapa-99",))


def test_requires_a_loaded_catalog(db_session):
    db_session.query(ProjectSubtaskProgress).delete()
    db_session.query(WorkflowSubtask).delete()
    db_session.query(WorkflowStage).update({WorkflowStage.depends_on_stage_id: None})
    db_session.query(WorkflowStage).delete()
    db_session.query(Phase).delete()
    db_session.flush()
    with pytest.raises(RuleError, match="catálogo"):
        complete_delivered_projects(db_session)


def test_the_percent_of_the_project_list_follows_the_rule(db_session, api_client):
    project = _project(db_session)
    complete_delivered_projects(db_session)
    body = api_client.get(f"/api/projects/{project.id}", headers=_h(CHEFE)).json()
    assert body["workflow_progress_percent"] == round(100 * 73 / 77)


# --- comando ------------------------------------------------------------------------------------------------


def _cli_env(monkeypatch, db_session, app_env="test"):
    monkeypatch.setattr(cli, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(app_env=app_env))


def test_cli_dry_run_then_real_run(db_session, monkeypatch, capsys):
    project = _project(db_session)
    db_session.commit()  # o --dry-run faz rollback: o estado do projeto tem de estar confirmado antes
    _cli_env(monkeypatch, db_session)
    assert cli.main(["--dry-run"]) == 0
    assert "simulação" in capsys.readouterr().out
    assert db_session.query(ProjectSubtaskProgress).filter(ProjectSubtaskProgress.project_id == project.id).count() == 0

    assert cli.main(["--actor-email", CHEFE]) == 0
    out = capsys.readouterr().out
    assert "gravado" in out and "etapa-18" in out
    assert db_session.query(ProjectSubtaskProgress).filter(ProjectSubtaskProgress.project_id == project.id).count() == 73
    assert db_session.query(ProjectStageProgress).filter(ProjectStageProgress.project_id == project.id).count() == 11


def test_cli_refuses_production_bad_actor_and_unknown_stage(db_session, monkeypatch, capsys):
    _cli_env(monkeypatch, db_session, app_env="production")
    assert cli.main([]) == 1
    assert "staging-only" in capsys.readouterr().err
    _cli_env(monkeypatch, db_session)
    assert cli.main(["--actor-email", "ninguem@example.invalid"]) == 1
    assert cli.main(["--except-stage", "etapa-99"]) == 1
    assert "desconhecida" in capsys.readouterr().err
