"""Processo do projeto (D-073): carga do catálogo, delegações, responsável resolvido
por projeto, prazos, estados e progresso."""
from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path

import pytest

from app.cli.load_process import main as load_main
from app.models.people import Person
from app.models.project import Project, ProjectHistory, ProjectStageProgress, ProjectSubtaskProgress
from app.models.workflow import Phase, SupportDelegation, WorkflowStage, WorkflowSubtask
from app.services.installers import business_day
from app.services.process import _stage_status
from app.services.process_catalog import (
    CatalogError,
    load_process_catalog,
    sync_support_delegations,
    validate_catalog,
)
from app.migration.seed_dev import SYNTHETIC_PROCESS_PATH

CHEFE = "chefe.sintetico@example.invalid"
PM_UM = "pm.um.sintetico@example.invalid"
COMERCIAL = "comercial.sintetico@example.invalid"

OWN = "Instalação Sintética de Demonstração"  # PM Um; Alfa / Equipa 1 (chefe "Chefe Sintético Um")
LEGACY_PM = "Instalação Sintética F — PM Legado"  # PM sem login e sem delegação; Beta, sem equipa
NO_PM = "Instalação Sintética E — Sem PM Atribuído"
TEAM2 = "Instalação Sintética A — Início Próximo"  # PM Um; Equipa 2 (chefe "Chefe Sintético Dois")


def _h(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def _fixture() -> dict:
    return json.loads(SYNTHETIC_PROCESS_PATH.read_text(encoding="utf-8"))


def _project(db, name: str) -> Project:
    return db.query(Project).filter(Project.name == name).one()


def _get(api_client, project, email=CHEFE):
    return api_client.get(f"/api/projects/{project.id}/process", headers=_h(email))


def _stages(body) -> dict:
    return {s["code"]: s for phase in body["phases"] for s in phase["stages"]}


def _subtask_id(db, code: str):
    return db.query(WorkflowSubtask).filter(WorkflowSubtask.code == code).one().id


def _stage_id(db, code: str):
    return db.query(WorkflowStage).filter(WorkflowStage.code == code).one().id


# --- catálogo ---------------------------------------------------------------------


def test_seed_loads_the_synthetic_process_with_the_real_shape(db_session):
    assert db_session.query(Phase).count() == 6
    assert db_session.query(WorkflowStage).count() == 18
    assert db_session.query(WorkflowSubtask).count() == 77
    stage10 = db_session.query(WorkflowStage).filter(WorkflowStage.code == "etapa-10").one()
    assert len(stage10.subtasks) == 15
    # Códigos das subtarefas iguais às chaves do `done` do legado: "2.0" -> etapa-02.0
    assert db_session.query(WorkflowSubtask).filter(WorkflowSubtask.code == "etapa-02.0").count() == 1
    assert db_session.query(WorkflowSubtask).filter(WorkflowSubtask.code == "etapa-02.5").count() == 1
    assert db_session.query(WorkflowSubtask).filter(WorkflowSubtask.code == "etapa-02.6").count() == 0


def test_loader_is_idempotent_and_updates_in_place(db_session):
    again = load_process_catalog(db_session, _fixture())
    assert again == {"phases_created": 0, "phases_updated": 0, "stages_created": 0, "stages_updated": 0,
                     "subtasks_created": 0, "subtasks_updated": 0}
    data = _fixture()
    data["stages"][0]["title"] = "Título novo"
    data["stages"][0]["subtasks"][0] = "Subtarefa renomeada"
    summary = load_process_catalog(db_session, data)
    assert (summary["stages_updated"], summary["subtasks_updated"], summary["stages_created"]) == (1, 1, 0)
    assert db_session.query(WorkflowStage).filter(WorkflowStage.code == "etapa-01").one().title == "Título novo"


def test_loader_maps_responsible_contact_dependency_and_offsets(db_session):
    stages = {s.code: s for s in db_session.query(WorkflowStage).all()}
    s5, s12, s14, s4 = stages["etapa-05"], stages["etapa-12"], stages["etapa-14"], stages["etapa-04"]
    assert (s5.responsible_rule, s5.responsible_label) == ("support_delegate", "Suporte")
    assert (s12.responsible_rule, s12.responsible_label) == ("installer", "Subempreiteiro")
    assert (s14.responsible_rule, s14.responsible_label) == ("team_leader", "Chefe de equipa")
    assert stages["etapa-03"].responsible_rule == "role" and stages["etapa-03"].responsible_role_code == "chefe_operacoes"
    assert stages["etapa-02"].responsible_role_code == "comercial" and stages["etapa-02"].responsible_label == "Sales Support"
    assert (s14.planned_start_offset_days, s14.planned_end_offset_days) == (42, 49)
    assert (s4.has_contact_checkpoint, s4.contact_day, s4.contact_kind) == (True, 9, "contacto")
    assert stages["etapa-07"].contact_kind == "update"
    assert s12.has_contact_checkpoint is False and s12.contact_day is None
    assert s14.depends_on_stage_id == s12.id and s12.depends_on_stage_id == stages["etapa-10"].id
    assert stages["etapa-01"].depends_on_stage_id is None


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["stages"][1].update(responsible="Ninguém"), "responsável desconhecido"),
        (lambda d: d["stages"][1].update(phase="inexistente"), "fase desconhecida"),
        (lambda d: d["stages"][1].update(subtasks=[]), "subtasks"),
        (lambda d: d["stages"][1].update(subtasks=["ok", "  "]), "subtasks"),
        (lambda d: d["stages"][1].update(depends_on="etapa-99"), "dependência desconhecida"),
        (lambda d: d["stages"][1].update(depends_on="etapa-02"), "depende de si própria"),
        (lambda d: d["stages"][1].update(code="etapa-01"), "etapa repetida"),
        (lambda d: d["stages"][1].update(start_day=9, end_day=3), "start_day"),
        (lambda d: d["stages"][3].update(contact={"day": 5, "kind": "outro", "note": ""}), "tipo de contacto"),
        (lambda d: d["stages"][3].update(contact={"day": 0, "kind": "contacto", "note": ""}), "contacto sem"),
        (lambda d: d["phases"].append(copy.deepcopy(d["phases"][0])), "fase repetida"),
        (lambda d: d.update(stages=[]), "stages"),
    ],
)
def test_invalid_catalogs_are_rejected_before_writing_anything(db_session, mutate, message):
    data = _fixture()
    mutate(data)
    before = db_session.query(WorkflowSubtask).count()
    with pytest.raises(CatalogError, match=message):
        load_process_catalog(db_session, data)
    assert db_session.query(WorkflowSubtask).count() == before


def test_validate_accepts_the_fixture():
    validate_catalog(_fixture())


# --- delegações --------------------------------------------------------------------------


def test_delegations_are_authoritative(db_session):
    assert db_session.query(SupportDelegation).count() == 1  # do seed: PM Um -> Comercial
    summary = sync_support_delegations(
        db_session, [{"pm": "pm sintetico um", "support": "Financeiro Sintético"}, {"pm": "Chefe Sintético", "support": "Comercial Sintético"}]
    )
    assert (summary["updated"], summary["created"], summary["removed"]) == (1, 1, 0)
    assert summary["invalid"] == []
    just_one = sync_support_delegations(db_session, [{"pm": "Chefe Sintético", "support": "Comercial Sintético"}])
    assert (just_one["removed"], just_one["unchanged"]) == (1, 1)
    assert db_session.query(SupportDelegation).count() == 1
    assert sync_support_delegations(db_session, [])["removed"] == 1
    assert db_session.query(SupportDelegation).count() == 0


def test_invalid_delegation_entries_change_nothing(db_session):
    summary = sync_support_delegations(
        db_session,
        [{"pm": "PM Sintético Um", "support": "Alguém Que Não Existe"}, {"pm": "Chefe Sintético", "support": "Chefe Sintético"}, "lixo"],
    )
    assert len(summary["invalid"]) == 3
    assert db_session.query(SupportDelegation).count() == 1  # a do seed intacta (nem removida)


# --- comando -----------------------------------------------------------------------------------


def test_cli_dry_run_writes_nothing_and_bad_input_is_refused(tmp_path, capsys, db_session):
    inside = Path(__file__).resolve().parent / "_processo_tmp.json"
    inside.write_text(json.dumps(_fixture()), encoding="utf-8")
    try:
        assert load_main(["--file", str(inside), "--dry-run"]) == 1
        assert "Git" in capsys.readouterr().err
    finally:
        inside.unlink()

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"phases": [], "stages": []}), encoding="utf-8")
    assert load_main(["--file", str(bad)]) == 1
    assert "catálogo inválido" in capsys.readouterr().err

    missing = tmp_path / "nao-existe.json"
    assert load_main(["--file", str(missing)]) == 1

    ok = tmp_path / "process.json"
    ok.write_text(json.dumps(_fixture()), encoding="utf-8")
    weird = tmp_path / "deleg.json"
    weird.write_text(json.dumps({"delegations": "não é lista"}), encoding="utf-8")
    assert load_main(["--file", str(ok), "--delegations", str(weird)]) == 1


# --- leitura do processo -------------------------------------------------------------------------


def test_process_lists_phases_stages_and_subtasks_in_order(db_session, api_client):
    project = _project(db_session, OWN)
    project.start_date = dt.date(2026, 3, 17)
    db_session.flush()
    body = _get(api_client, project).json()
    assert body["has_catalog"] is True and body["can_update"] is True
    assert [p["code"] for p in body["phases"]] == ["handover", "licenc", "visita", "prep", "obra", "fecho"]
    assert [s["code"] for s in body["phases"][0]["stages"]] == ["etapa-01", "etapa-02", "etapa-03", "etapa-04"]
    stage2 = _stages(body)["etapa-02"]
    assert [t["title"] for t in stage2["subtasks"]][:2] == ["Subtarefa 02.0 (exemplo)", "Subtarefa 02.1 (exemplo)"]
    assert stage2["total_count"] == 6 and stage2["done_count"] == 0
    assert body["summary"] == {"done": 0, "total": 77, "percent": 0, "stages_done": 0, "stages_total": 18,
                               "overdue_stages": 18, "overdue_contacts": 12}
    assert _stages(body)["etapa-14"]["depends_on_code"] == "etapa-12"


def test_planned_dates_use_business_days_from_the_project_start(db_session, api_client):
    project = _project(db_session, OWN)
    project.start_date = dt.date(2026, 3, 17)
    db_session.flush()
    stages = _stages(_get(api_client, project).json())
    s14 = stages["etapa-14"]
    assert s14["planned_start"] == business_day(dt.date(2026, 3, 17), 42).isoformat()
    assert s14["planned_end"] == business_day(dt.date(2026, 3, 17), 49).isoformat() == "2026-05-22"
    assert s14["contact"]["planned_date"] == business_day(dt.date(2026, 3, 17), 45).isoformat()
    assert stages["etapa-12"]["contact"] is None


@pytest.mark.parametrize(
    ("done", "start", "end", "today", "expected"),
    [
        (True, None, None, dt.date(2026, 6, 1), "done"),
        (True, dt.date(2026, 1, 1), dt.date(2026, 1, 5), dt.date(2026, 6, 1), "done"),  # feita e atrasada: fica feita
        (False, None, None, dt.date(2026, 6, 1), "no_date"),
        (False, dt.date(2026, 6, 2), dt.date(2026, 6, 9), dt.date(2026, 6, 1), "upcoming"),
        (False, dt.date(2026, 6, 1), dt.date(2026, 6, 9), dt.date(2026, 6, 1), "active"),
        (False, dt.date(2026, 5, 1), dt.date(2026, 6, 1), dt.date(2026, 6, 1), "active"),  # o último dia ainda conta
        (False, dt.date(2026, 5, 1), dt.date(2026, 5, 31), dt.date(2026, 6, 1), "overdue"),
    ],
)
def test_stage_status_rules(done, start, end, today, expected):
    assert _stage_status(done, start, end, today) == expected


def test_status_follows_the_project_start(db_session, api_client):
    project = _project(db_session, OWN)
    project.start_date = dt.date.today() + dt.timedelta(days=400)
    db_session.flush()
    assert {s["status"] for s in _stages(_get(api_client, project).json()).values()} == {"upcoming"}
    project.start_date = dt.date.today() - dt.timedelta(days=400)
    db_session.flush()
    assert {s["status"] for s in _stages(_get(api_client, project).json()).values()} == {"overdue"}
    project.start_date = None
    db_session.flush()
    body = _get(api_client, project).json()
    assert {s["status"] for s in _stages(body).values()} == {"no_date"}
    assert body["summary"]["overdue_stages"] == 0
    assert all(s["planned_start"] is None for s in _stages(body).values())


def test_without_a_loaded_catalog_the_process_is_empty(db_session, api_client):
    db_session.query(ProjectSubtaskProgress).delete()
    db_session.query(WorkflowSubtask).delete()
    db_session.query(WorkflowStage).update({WorkflowStage.depends_on_stage_id: None})
    db_session.query(WorkflowStage).delete()
    db_session.query(Phase).delete()
    db_session.flush()
    body = _get(api_client, _project(db_session, OWN)).json()
    assert body["has_catalog"] is False and body["phases"] == [] and body["summary"]["total"] == 0


# --- responsável resolvido por projeto -------------------------------------------------------------


def test_support_stages_go_to_the_delegate_or_else_to_the_pm(db_session, api_client):
    delegated = _stages(_get(api_client, _project(db_session, OWN)).json())
    for code in ("etapa-05", "etapa-09", "etapa-13", "etapa-18"):  # as etapas de suporte
        r = delegated[code]["responsible"]
        assert (r["names"], r["delegated"], r["unresolved"], r["label"]) == (["Comercial Sintético"], True, False, "Suporte")

    own_work = _stages(_get(api_client, _project(db_session, LEGACY_PM)).json())["etapa-05"]["responsible"]
    assert own_work["delegated"] is False and own_work["unresolved"] is False
    assert len(own_work["names"]) == 1 and own_work["names"][0] != "Comercial Sintético"

    orphan = _stages(_get(api_client, _project(db_session, NO_PM)).json())["etapa-05"]["responsible"]
    assert orphan["unresolved"] is True and orphan["names"] == []


def test_removing_a_delegation_moves_the_stage_back_to_the_pm(db_session, api_client):
    db_session.query(SupportDelegation).delete()
    db_session.flush()
    r = _stages(_get(api_client, _project(db_session, OWN)).json())["etapa-05"]["responsible"]
    assert r["delegated"] is False and r["names"] == ["PM Sintético Um"]


def test_pm_installer_team_leader_and_role_rules(db_session, api_client):
    own = _stages(_get(api_client, _project(db_session, OWN)).json())
    assert own["etapa-04"]["responsible"]["names"] == ["PM Sintético Um"]
    assert own["etapa-12"]["responsible"]["names"] == ["Instalador Sintético Alfa"]
    assert own["etapa-14"]["responsible"]["names"] == ["Chefe Sintético Um"]  # o CE: chefe da equipa do projeto
    assert own["etapa-03"]["responsible"]["names"] == ["Chefe Sintético"]  # papel: quem tem o papel de chefe
    assert own["etapa-02"]["responsible"]["names"] == ["Comercial Sintético"]
    assert own["etapa-02"]["responsible"]["label"] == "Sales Support"

    team2 = _stages(_get(api_client, _project(db_session, TEAM2)).json())
    assert team2["etapa-14"]["responsible"]["names"] == ["Chefe Sintético Dois"]

    legacy = _stages(_get(api_client, _project(db_session, LEGACY_PM)).json())  # instalador Beta, sem equipa
    assert legacy["etapa-12"]["responsible"]["names"] == ["Instalador Sintético Beta"]
    assert legacy["etapa-14"]["responsible"] == {"rule": "team_leader", "label": "Chefe de equipa", "names": [], "unresolved": True, "delegated": False}

    no_installer = _project(db_session, NO_PM)
    assert no_installer.installer_id is None
    assert _stages(_get(api_client, no_installer).json())["etapa-12"]["responsible"]["unresolved"] is True


def test_a_team_without_a_leader_is_unresolved(db_session, api_client):
    project = _project(db_session, TEAM2)
    project.installer_team.leader_name = None
    db_session.flush()
    assert _stages(_get(api_client, project).json())["etapa-14"]["responsible"]["unresolved"] is True


def test_role_with_no_active_holder_still_shows_the_label(db_session, api_client):
    from app.models.identity import User

    for user in db_session.query(User).all():
        if user.email == CHEFE:
            user.is_active = False
    db_session.flush()
    r = _stages(_get(api_client, _project(db_session, OWN), email=PM_UM).json())["etapa-03"]["responsible"]
    assert r["names"] == [] and r["unresolved"] is False and r["label"] == "Chefe do departamento"


# --- escrita do progresso ----------------------------------------------------------------------------


def _mark(api_client, project, subtask_id, done=True, email=CHEFE):
    return api_client.patch(
        f"/api/projects/{project.id}/process/subtasks/{subtask_id}", json={"done": done}, headers=_h(email)
    )


def test_marking_a_subtask_records_who_when_and_history(db_session, api_client):
    project = _project(db_session, OWN)
    sid = _subtask_id(db_session, "etapa-01.0")
    resp = _mark(api_client, project, sid)
    assert resp.status_code == 200
    body = resp.json()
    stage1 = _stages(body)["etapa-01"]
    assert stage1["subtasks"][0]["done"] is True and stage1["subtasks"][0]["done_by_display_name"] == "Chefe Sintético"
    assert stage1["subtasks"][0]["done_at"]
    assert stage1["status"] == "done"  # só tem uma subtarefa
    assert body["summary"]["done"] == 1 and body["summary"]["stages_done"] == 1

    entries = db_session.query(ProjectHistory).filter(ProjectHistory.project_id == project.id, ProjectHistory.field_name == "processo:etapa-01.0").all()
    assert [(e.old_value, e.new_value, e.source) for e in entries] == [("pendente", "feita", "ui")]
    assert entries[0].changed_by_person_id is not None

    again = _mark(api_client, project, sid)  # repetir não faz nada
    assert again.status_code == 200
    assert db_session.query(ProjectHistory).filter(ProjectHistory.project_id == project.id, ProjectHistory.field_name == "processo:etapa-01.0").count() == 1

    undone = _mark(api_client, project, sid, done=False)
    assert _stages(undone.json())["etapa-01"]["subtasks"][0]["done"] is False
    assert _stages(undone.json())["etapa-01"]["subtasks"][0]["done_at"] is None
    assert undone.json()["summary"]["done"] == 0


def test_a_stage_is_done_only_when_every_subtask_is(db_session, api_client):
    project = _project(db_session, OWN)
    for index in range(5):
        _mark(api_client, project, _subtask_id(db_session, f"etapa-02.{index}"))
    body = _get(api_client, project).json()
    assert _stages(body)["etapa-02"]["done_count"] == 5 and _stages(body)["etapa-02"]["status"] != "done"
    body = _mark(api_client, project, _subtask_id(db_session, "etapa-02.5")).json()
    assert _stages(body)["etapa-02"]["status"] == "done"
    assert body["phases"][0]["done_count"] == 6 and body["summary"]["percent"] == round(100 * 6 / 77)


def test_progress_is_per_project(db_session, api_client):
    a, b = _project(db_session, OWN), _project(db_session, TEAM2)
    _mark(api_client, a, _subtask_id(db_session, "etapa-01.0"))
    assert _get(api_client, b).json()["summary"]["done"] == 0
    assert _get(api_client, a).json()["summary"]["done"] == 1


def test_pm_marks_own_projects_only_and_others_are_404(db_session, api_client):
    own, other = _project(db_session, OWN), _project(db_session, LEGACY_PM)
    sid = _subtask_id(db_session, "etapa-01.0")
    assert _mark(api_client, own, sid, email=PM_UM).status_code == 200
    assert _mark(api_client, other, sid, email=PM_UM).status_code == 404
    assert _get(api_client, other, email=PM_UM).status_code == 404
    assert db_session.query(ProjectSubtaskProgress).filter(ProjectSubtaskProgress.project_id == other.id).count() == 0


def test_read_only_roles_see_the_process_but_cannot_mark(db_session, api_client):
    project = _project(db_session, OWN)
    body = _get(api_client, project, email=COMERCIAL).json()
    assert body["can_update"] is False and body["summary"]["total"] == 77
    assert _mark(api_client, project, _subtask_id(db_session, "etapa-01.0"), email=COMERCIAL).status_code == 403


def test_unknown_subtask_or_stage_and_invalid_bodies(db_session, api_client):
    project = _project(db_session, OWN)
    missing = "00000000-0000-0000-0000-000000000000"
    assert _mark(api_client, project, missing).status_code == 404
    assert api_client.patch(f"/api/projects/{project.id}/process/subtasks/{_subtask_id(db_session, 'etapa-01.0')}", json={}, headers=_h(CHEFE)).status_code == 422
    assert api_client.patch(f"/api/projects/{project.id}/process/subtasks/{_subtask_id(db_session, 'etapa-01.0')}", json={"done": True, "x": 1}, headers=_h(CHEFE)).status_code == 422
    assert api_client.patch(f"/api/projects/{project.id}/process/stages/{missing}/contact", json={"done": True}, headers=_h(CHEFE)).status_code == 404


def test_contact_checkpoint_can_be_marked_and_cleared(db_session, api_client):
    project = _project(db_session, OWN)
    project.start_date = dt.date.today() - dt.timedelta(days=400)
    db_session.flush()
    stage_id = _stage_id(db_session, "etapa-04")
    before = _get(api_client, project).json()
    assert _stages(before)["etapa-04"]["contact"]["overdue"] is True and before["summary"]["overdue_contacts"] == 12

    resp = api_client.patch(f"/api/projects/{project.id}/process/stages/{stage_id}/contact", json={"done": True}, headers=_h(PM_UM))
    assert resp.status_code == 200
    contact = _stages(resp.json())["etapa-04"]["contact"]
    assert contact["done"] is True and contact["overdue"] is False and contact["done_at"]
    assert resp.json()["summary"]["overdue_contacts"] == 11
    assert db_session.query(ProjectStageProgress).filter(ProjectStageProgress.project_id == project.id).one().contact_done is True

    entries = db_session.query(ProjectHistory).filter(ProjectHistory.project_id == project.id, ProjectHistory.field_name == "processo:etapa-04:contacto").all()
    assert [(e.old_value, e.new_value) for e in entries] == [("pendente", "feito")]
    cleared = api_client.patch(f"/api/projects/{project.id}/process/stages/{stage_id}/contact", json={"done": False}, headers=_h(PM_UM))
    assert _stages(cleared.json())["etapa-04"]["contact"]["done"] is False


def test_a_stage_without_a_contact_checkpoint_refuses_it(db_session, api_client):
    project = _project(db_session, OWN)
    resp = api_client.patch(f"/api/projects/{project.id}/process/stages/{_stage_id(db_session, 'etapa-12')}/contact", json={"done": True}, headers=_h(CHEFE))
    assert resp.status_code == 422 and "ponto de contacto" in resp.json()["detail"]


def test_contact_never_counts_as_a_subtask(db_session, api_client):
    project = _project(db_session, OWN)
    api_client.patch(f"/api/projects/{project.id}/process/stages/{_stage_id(db_session, 'etapa-04')}/contact", json={"done": True}, headers=_h(CHEFE))
    body = _get(api_client, project).json()
    assert body["summary"]["done"] == 0 and _stages(body)["etapa-04"]["status"] != "done"


# --- desempenho ---------------------------------------------------------------------------------------------


def test_query_count_does_not_grow_with_the_progress_recorded(db_session, api_client):
    from sqlalchemy import event

    from app.db import engine

    project = _project(db_session, OWN)

    def count() -> int:
        counter = {"n": 0}

        def _on(*_a, **_k):
            counter["n"] += 1

        event.listen(engine, "before_cursor_execute", _on)
        try:
            assert _get(api_client, project).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", _on)
        return counter["n"]

    few = count()
    person = db_session.query(Person).filter(Person.display_name == "Chefe Sintético").one()
    for subtask in db_session.query(WorkflowSubtask).all():
        db_session.add(ProjectSubtaskProgress(project_id=project.id, subtask_id=subtask.id, done=True, done_by_person_id=person.id))
    db_session.flush()
    assert count() <= few + 1, "queries a crescer com o progresso — provável N+1"
    assert _get(api_client, project).json()["summary"]["percent"] == 100
