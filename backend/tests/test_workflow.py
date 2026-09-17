"""Percurso de obra (D-052): definição, datas em dias úteis, estados,
permissões e histórico."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from app.cli.workflow import main as workflow_cli
from app.models.identity import User
from app.models.project import Project, ProjectHistory, ProjectSubtaskProgress
from app.models.workflow import WorkflowStage, WorkflowSubtask
from app.security.permissions import load_auth_context
from app.services.workflow import (
    STAGE_DONE,
    STAGE_IN_PROGRESS,
    STAGE_NOT_STARTED,
    STAGE_OVERDUE,
    STAGE_WAITING,
    build_project_workflow,
    business_day,
)
from app.workflow.definition import (
    EXAMPLE_DEFINITION_PATH,
    WorkflowDefinition,
    WorkflowDefinitionConflict,
    apply_definition,
    load_definition,
)

PM = "pm.um.sintetico@example.invalid"
CHEFE = "chefe.sintetico@example.invalid"
COMERCIAL = "comercial.sintetico@example.invalid"


def _headers(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def _project(db, name="Instalação Sintética de Demonstração") -> Project:
    return db.query(Project).filter(Project.name == name).one()


def _ctx(db, email):
    return load_auth_context(db, db.query(User).filter(User.email == email).one())


def _definition_dict() -> dict:
    return json.loads(EXAMPLE_DEFINITION_PATH.read_text(encoding="utf-8"))


# --- definição ---------------------------------------------------------


def test_example_definition_has_18_stages_in_6_phases(db_session):
    definition = load_definition(EXAMPLE_DEFINITION_PATH)
    assert len(definition.phases) == 6
    assert [s.number for s in definition.stages] == list(range(1, 19))
    assert db_session.query(WorkflowStage).count() == 18
    assert db_session.query(WorkflowSubtask).count() == sum(len(s.subtasks) for s in definition.stages)


def test_example_definition_responsibles_are_functions():
    # Responsáveis são funções, nunca nomes de pessoas (D-052).
    functions = {"Comercial", "Apoio comercial", "Chefe de Operações", "PM", "Licenciamento", "Subempreiteiro", "Chefe de equipa"}
    definition = load_definition(EXAMPLE_DEFINITION_PATH)
    assert {s.responsible_label for s in definition.stages} <= functions


def test_apply_is_idempotent(db_session):
    report = apply_definition(db_session, load_definition(EXAMPLE_DEFINITION_PATH))
    assert not report.changed


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d["stages"][1].update(depends_on=99), "não existe"),
        (lambda d: d["stages"][1].update(phase="inexistente"), "fase desconhecida"),
        (lambda d: d["stages"][1].update(start_day=10, end_day=2), "antes de start_day"),
        (lambda d: d["stages"][1].update(responsible_role="pessoa_qualquer"), "papel desconhecido"),
        (lambda d: d["stages"][2].update(number=1), "repetidos"),
    ],
)
def test_invalid_definitions_are_rejected(mutate, message):
    data = _definition_dict()
    mutate(data)
    with pytest.raises(ValueError, match=message):
        WorkflowDefinition.model_validate(data)


def test_update_renames_subtask_in_place(db_session):
    data = _definition_dict()
    data["stages"][0]["title"] = "Título alterado"
    report = apply_definition(db_session, WorkflowDefinition.model_validate(data))
    assert report.stages_updated == 1
    assert db_session.query(WorkflowStage).filter(WorkflowStage.code == "etapa.01").one().title == "Título alterado"


def test_removing_item_with_progress_is_refused(db_session, api_client):
    project = _project(db_session)
    resp = api_client.put(
        f"/api/projects/{project.id}/workflow/subtasks/etapa.18.4", json={"done": True}, headers=_headers(CHEFE)
    )
    assert resp.status_code == 200
    data = _definition_dict()
    data["stages"][17]["subtasks"] = data["stages"][17]["subtasks"][:3]
    with pytest.raises(WorkflowDefinitionConflict, match="etapa.18.4"):
        apply_definition(db_session, WorkflowDefinition.model_validate(data))


def test_removing_item_without_progress_is_allowed(db_session):
    data = _definition_dict()
    data["stages"][17]["subtasks"] = data["stages"][17]["subtasks"][:3]
    report = apply_definition(db_session, WorkflowDefinition.model_validate(data))
    assert report.subtasks_removed == 1
    assert db_session.query(WorkflowSubtask).filter(WorkflowSubtask.code == "etapa.18.4").count() == 0


def test_cli_load_is_dry_run_by_default(db_session, tmp_path, capsys, monkeypatch):
    data = _definition_dict()
    data["stages"][0]["title"] = "Alterado pelo CLI"
    path = tmp_path / "processo.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr("app.db.SessionLocal", lambda: db_session)

    assert workflow_cli(["load", "--file", str(path)]) == 0
    assert "Simulação" in capsys.readouterr().out
    stage = db_session.query(WorkflowStage).filter(WorkflowStage.code == "etapa.01").one()
    assert stage.title != "Alterado pelo CLI"


def test_cli_rejects_invalid_file(tmp_path, capsys):
    path = tmp_path / "mau.json"
    path.write_text(json.dumps({"phases": [], "stages": []}), encoding="utf-8")
    assert workflow_cli(["load", "--file", str(path)]) == 1
    assert "inválida" in capsys.readouterr().err


# --- datas e estados ---------------------------------------------------


def test_business_day_skips_weekends():
    friday = dt.date(2026, 9, 18)
    assert business_day(friday, 1) == friday
    assert business_day(friday, 2) == dt.date(2026, 9, 21)  # segunda
    saturday = dt.date(2026, 9, 19)
    assert business_day(saturday, 1) == dt.date(2026, 9, 21)
    assert business_day(dt.date(2026, 9, 14), 6) == dt.date(2026, 9, 21)


def test_view_without_start_date_has_no_dates(db_session):
    project = _project(db_session)
    project.start_date = None
    view = build_project_workflow(db_session, project, _ctx(db_session, CHEFE))
    assert view.planned_end is None
    assert all(s.planned_start is None for s in view.stages)
    assert view.stages[0].status == STAGE_NOT_STARTED
    assert view.stages[1].status == STAGE_WAITING  # depende da etapa 1
    assert view.progress_percent == 0


def test_statuses_follow_dates_and_progress(db_session, api_client):
    project = _project(db_session)
    monday = dt.date(2026, 9, 7)
    project.start_date = monday
    db_session.flush()
    ctx = _ctx(db_session, CHEFE)

    # Etapa 1 feita; etapa 2 a meio.
    api_client.put(f"/api/projects/{project.id}/workflow/subtasks/etapa.01.1", json={"done": True}, headers=_headers(CHEFE))
    api_client.put(f"/api/projects/{project.id}/workflow/subtasks/etapa.02.1", json={"done": True}, headers=_headers(CHEFE))

    view = build_project_workflow(db_session, project, ctx, today=monday)
    by_number = {s.number: s for s in view.stages}
    assert by_number[1].status == STAGE_DONE
    assert by_number[2].status == STAGE_IN_PROGRESS
    assert by_number[3].status == STAGE_WAITING
    assert by_number[2].planned_end == dt.date(2026, 9, 11)  # dia útil 5
    assert view.planned_end == business_day(monday, 65)
    assert view.current_stage_number == 2

    # Um mês depois: a etapa 2 (prazo dia 5) está atrasada, e o contacto da
    # etapa 4 (dia 9) está por fazer.
    later = dt.date(2026, 10, 7)
    view = build_project_workflow(db_session, project, ctx, today=later)
    by_number = {s.number: s for s in view.stages}
    assert by_number[2].status == STAGE_OVERDUE
    assert by_number[4].contact_overdue is True
    assert view.overdue_stages_count >= 1
    assert view.pending_contacts_count >= 1


# --- API e permissões --------------------------------------------------


def test_get_workflow_shape(db_session, api_client):
    project = _project(db_session)
    resp = api_client.get(f"/api/projects/{project.id}/workflow", headers=_headers(PM))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["stages"]) == 18
    assert len(body["phases"]) == 6
    assert body["can_edit"] is True
    stage4 = body["stages"][3]
    assert stage4["contact_type"] == "contacto"
    assert any(s["is_client_contact"] for s in stage4["subtasks"])


def test_workflow_requires_authentication(db_session, api_client):
    project = _project(db_session)
    assert api_client.get(f"/api/projects/{project.id}/workflow").status_code == 401


def test_pm_marks_own_project_and_history_is_recorded(db_session, api_client):
    project = _project(db_session)
    url = f"/api/projects/{project.id}/workflow/subtasks/etapa.06.2"
    resp = api_client.put(url, json={"done": True}, headers=_headers(PM))
    assert resp.status_code == 200
    stage6 = resp.json()["stages"][5]
    assert stage6["done_count"] == 1
    assert stage6["subtasks"][1]["done"] is True

    progress = db_session.query(ProjectSubtaskProgress).filter(ProjectSubtaskProgress.project_id == project.id).one()
    assert progress.done_by_person_id is not None
    history = db_session.query(ProjectHistory).filter(ProjectHistory.field_name == "percurso.etapa.06.2").one()
    assert (history.old_value, history.new_value) == ("por fazer", "feito")

    # Repetir não gera histórico novo; desmarcar gera.
    api_client.put(url, json={"done": True}, headers=_headers(PM))
    api_client.put(url, json={"done": False}, headers=_headers(PM))
    assert db_session.query(ProjectHistory).filter(ProjectHistory.field_name == "percurso.etapa.06.2").count() == 2


def test_contact_checkpoint_toggle(db_session, api_client):
    project = _project(db_session)
    resp = api_client.put(
        f"/api/projects/{project.id}/workflow/stages/etapa.04/contact", json={"done": True}, headers=_headers(PM)
    )
    assert resp.status_code == 200
    assert resp.json()["stages"][3]["contact_done"] is True
    # Etapa sem ponto de contacto.
    resp = api_client.put(
        f"/api/projects/{project.id}/workflow/stages/etapa.02/contact", json={"done": True}, headers=_headers(PM)
    )
    assert resp.status_code == 404


def test_pm_cannot_mark_other_project(db_session, api_client):
    other = _project(db_session, "Instalação Sintética Incompleta")
    resp = api_client.put(
        f"/api/projects/{other.id}/workflow/subtasks/etapa.01.1", json={"done": True}, headers=_headers(PM)
    )
    assert resp.status_code == 404  # nem sequer o vê


def test_read_only_profile_cannot_mark(db_session, api_client):
    project = _project(db_session)
    resp = api_client.get(f"/api/projects/{project.id}/workflow", headers=_headers(COMERCIAL))
    assert resp.status_code == 200
    assert resp.json()["can_edit"] is False
    resp = api_client.put(
        f"/api/projects/{project.id}/workflow/subtasks/etapa.01.1", json={"done": True}, headers=_headers(COMERCIAL)
    )
    assert resp.status_code == 403


def test_unknown_subtask_is_404(db_session, api_client):
    project = _project(db_session)
    resp = api_client.put(
        f"/api/projects/{project.id}/workflow/subtasks/etapa.99.1", json={"done": True}, headers=_headers(CHEFE)
    )
    assert resp.status_code == 404


def test_progress_does_not_leak_between_projects(db_session, api_client):
    project = _project(db_session)
    other = _project(db_session, "Instalação Sintética Incompleta")
    api_client.put(f"/api/projects/{project.id}/workflow/subtasks/etapa.01.1", json={"done": True}, headers=_headers(CHEFE))
    body = api_client.get(f"/api/projects/{other.id}/workflow", headers=_headers(CHEFE)).json()
    assert body["done_count"] == 0


def test_seed_replaces_legacy_generic_workflow_but_not_a_loaded_one(db_session):
    from app.migration.seed_dev import seed_workflow
    from app.models.workflow import Phase

    db = db_session
    db.query(WorkflowSubtask).delete()
    db.query(WorkflowStage).update({WorkflowStage.depends_on_stage_id: None})
    db.query(WorkflowStage).delete()
    phase = db.query(Phase).filter(Phase.code == "handover").one()
    old = WorkflowStage(phase_id=phase.id, code="handover.entrega", title="Antigo", sort_order=0)
    db.add(old)
    db.flush()
    db.add(WorkflowSubtask(stage_id=old.id, code="handover.entrega.0", title="Antiga", sort_order=0))
    db.flush()

    seed_workflow(db)
    codes = {c for (c,) in db.query(WorkflowStage.code).all()}
    assert len(codes) == 18 and "handover.entrega" not in codes

    # Um percurso já carregado (ex. o oficial, com outro título) não é tocado.
    db.query(WorkflowStage).filter(WorkflowStage.code == "etapa.01").update({WorkflowStage.title: "Oficial"})
    seed_workflow(db)
    assert db.query(WorkflowStage).filter(WorkflowStage.code == "etapa.01").one().title == "Oficial"
