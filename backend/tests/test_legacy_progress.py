"""Importação do progresso do processo do legado (D-074) e progresso vindo do processo."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.cli import import_legacy_progress as cli
from app.models.project import Project, ProjectHistory, ProjectStageProgress, ProjectSubtaskProgress
from app.models.workflow import Phase, WorkflowStage, WorkflowSubtask
from app.services.legacy_progress import import_legacy_progress
from tests.test_installers import _legacy_payload, _promote

CHEFE = "chefe.sintetico@example.invalid"
PM_UM = "pm.um.sintetico@example.invalid"
OWN = "Instalação Sintética de Demonstração"


def _h(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def _with_progress(**record) -> dict:
    return _legacy_payload(**record)


def _promoted(db, **record):
    project, _r, actor = _promote(db, _with_progress(**record))
    return project, actor


def _stages(body) -> dict:
    return {s["code"]: s for phase in body["phases"] for s in phase["stages"]}


def _process(api_client, project, email=CHEFE):
    return api_client.get(f"/api/projects/{project.id}/process", headers=_h(email)).json()


# --- importação -------------------------------------------------------------------------------------


def test_imports_true_subtasks_and_contacts_marked_as_legacy(db_session, api_client):
    project, _actor = _promoted(
        db_session,
        done={"2.0": True, "2.1": True, "10.14": True, "1.0": True},
        contactsDone={"c4": True, "c7": True},
    )
    payload = _with_progress(done={"2.0": True, "2.1": True, "10.14": True, "1.0": True}, contactsDone={"c4": True, "c7": True})
    summary = import_legacy_progress(db_session, payload)
    assert (summary["subtasks_created"], summary["contacts_created"], summary["projects_matched"]) == (4, 2, 1)

    body = _process(api_client, project)
    stages = _stages(body)
    assert [t["done"] for t in stages["etapa-02"]["subtasks"]] == [True, True, False, False, False, False]
    assert stages["etapa-10"]["subtasks"][14]["done"] is True  # o índice é a partir de 0
    assert stages["etapa-01"]["status"] == "done"  # a etapa 1 só tem uma subtarefa
    assert stages["etapa-04"]["contact"]["done"] is True and stages["etapa-07"]["contact"]["done"] is True
    first = stages["etapa-02"]["subtasks"][0]
    assert first["source"] == "legacy" and first["done_at"] is None and first["done_by_display_name"] is None
    assert stages["etapa-04"]["contact"]["source"] == "legacy" and stages["etapa-04"]["contact"]["done_at"] is None
    assert body["summary"]["done"] == 4 and body["summary"]["stages_done"] == 1


def test_a_stage_is_done_only_when_every_subtask_of_the_legacy_is(db_session, api_client):
    project, _ = _promoted(db_session)
    import_legacy_progress(db_session, _with_progress(done={f"2.{i}": True for i in range(5)}))
    assert _stages(_process(api_client, project))["etapa-02"]["status"] != "done"  # falta a última (índice 5)
    import_legacy_progress(db_session, _with_progress(done={f"2.{i}": True for i in range(6)}))
    assert _stages(_process(api_client, project))["etapa-02"]["status"] == "done"


def test_is_idempotent(db_session):
    _promoted(db_session)
    payload = _with_progress(done={"2.0": True, "3.1": True}, contactsDone={"c4": True})
    first = import_legacy_progress(db_session, payload)
    again = import_legacy_progress(db_session, payload)
    assert (first["subtasks_created"], first["contacts_created"]) == (2, 1)
    assert (again["subtasks_created"], again["contacts_created"], again["subtasks_kept"], again["contacts_kept"]) == (0, 0, 2, 1)
    assert db_session.query(ProjectSubtaskProgress).filter(ProjectSubtaskProgress.source == "legacy").count() == 2


def test_never_overwrites_progress_that_already_exists(db_session, api_client):
    project, actor = _promoted(db_session)
    sid = db_session.query(WorkflowSubtask).filter(WorkflowSubtask.code == "etapa-02.0").one().id
    other = db_session.query(WorkflowSubtask).filter(WorkflowSubtask.code == "etapa-02.1").one().id
    # 02.0 marcada na aplicação; 02.1 marcada e depois desmarcada na aplicação (linha com done=False).
    db_session.add(ProjectSubtaskProgress(project_id=project.id, subtask_id=sid, done=True, done_by_person_id=actor, source="ui"))
    db_session.add(ProjectSubtaskProgress(project_id=project.id, subtask_id=other, done=False, source="ui"))
    db_session.flush()

    summary = import_legacy_progress(db_session, _with_progress(done={"2.0": True, "2.1": True, "2.2": True}))
    assert (summary["subtasks_created"], summary["subtasks_kept"]) == (1, 2)
    rows = {r.subtask_id: r for r in db_session.query(ProjectSubtaskProgress).filter(ProjectSubtaskProgress.project_id == project.id)}
    assert rows[sid].source == "ui" and rows[sid].done_by_person_id == actor  # intacta
    assert rows[other].done is False and rows[other].source == "ui"  # o Op_PM manda: continua por fazer


def test_false_values_are_ignored(db_session):
    _promoted(db_session)
    summary = import_legacy_progress(db_session, _with_progress(done={"2.0": False, "2.1": True}, contactsDone={"c4": False}))
    assert (summary["subtasks_created"], summary["contacts_created"], summary["false_ignored"]) == (1, 0, 2)


def test_keys_without_a_catalog_match_are_listed_never_hidden(db_session):
    _promoted(db_session)
    summary = import_legacy_progress(
        db_session,
        _with_progress(
            done={"99.0": True, "2.6": True, "2.x": True, "lixo": True, "2.0": True},  # etapa inexistente; índice fora; mal formadas
            contactsDone={"c12": True, "c99": True, "c4": True},  # a etapa 12 não tem ponto de contacto
        ),
    )
    assert summary["subtasks_created"] == 1 and summary["contacts_created"] == 1
    assert summary["unmapped_count"] == 6
    assert set(summary["unmapped"]) == {"synth_p001: 99.0", "synth_p001: 2.6", "synth_p001: 2.x", "synth_p001: lixo", "synth_p001: c12", "synth_p001: c99"}


def test_projects_are_matched_by_external_id_never_by_name(db_session):
    project, _ = _promoted(db_session)
    payload = _with_progress(done={"2.0": True})
    payload["projects"]["outro_id"] = {"name": project.name, "done": {"2.1": True}}  # mesmo nome, outro id
    payload["projects"]["synth_p002"]["done"] = {"2.2": True}
    summary = import_legacy_progress(db_session, payload)
    assert summary["projects_seen"] == len(payload["projects"])
    assert summary["projects_matched"] == 1  # só o synth_p001 foi promovido
    assert "outro_id" in summary["projects_not_found"] and summary["projects_not_found_count"] == len(payload["projects"]) - 1
    assert db_session.query(ProjectSubtaskProgress).filter(ProjectSubtaskProgress.project_id == project.id).count() == 1


def test_one_history_entry_per_project_and_none_when_nothing_is_created(db_session):
    project, actor = _promoted(db_session)
    payload = _with_progress(done={"2.0": True, "2.1": True, "3.0": True}, contactsDone={"c4": True, "c5": True})
    import_legacy_progress(db_session, payload, actor_person_id=actor)
    entries = db_session.query(ProjectHistory).filter(ProjectHistory.project_id == project.id, ProjectHistory.field_name == "processo:importado").all()
    assert [(e.old_value, e.new_value, e.source, e.changed_by_person_id) for e in entries] == [(None, "3 subtarefas, 2 contactos", "import_legacy", actor)]
    import_legacy_progress(db_session, payload, actor_person_id=actor)  # repetir não acrescenta
    assert db_session.query(ProjectHistory).filter(ProjectHistory.project_id == project.id, ProjectHistory.field_name == "processo:importado").count() == 1


def test_commissioning_dates_and_shifts_are_counted_but_not_imported(db_session):
    project, _ = _promoted(db_session)
    summary = import_legacy_progress(db_session, _with_progress(commissionedAt="2026-03-19", shift={"6": 3}))
    assert (summary["commissioned_ignored"], summary["shift_ignored"], summary["subtasks_created"]) == (1, 1, 0)
    assert db_session.query(ProjectSubtaskProgress).filter(ProjectSubtaskProgress.project_id == project.id).count() == 0


def test_invalid_payload_is_rejected(db_session):
    with pytest.raises(ValueError, match="projects"):
        import_legacy_progress(db_session, {"sem": "projetos"})


# --- comando --------------------------------------------------------------------------------------------


def _cli_env(monkeypatch, db_session, app_env="test"):
    monkeypatch.setattr(cli, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(app_env=app_env))


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "export.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_cli_dry_run_writes_nothing_and_real_run_writes(db_session, monkeypatch, tmp_path, capsys):
    project, _ = _promoted(db_session)
    _cli_env(monkeypatch, db_session)
    path = _write(tmp_path, _with_progress(done={"2.0": True}, contactsDone={"c4": True}))

    assert cli.main(["--file", str(path), "--dry-run"]) == 0
    assert "simulação" in capsys.readouterr().out
    assert db_session.query(ProjectSubtaskProgress).filter(ProjectSubtaskProgress.project_id == project.id).count() == 0

    assert cli.main(["--file", str(path), "--actor-email", CHEFE]) == 0
    out = capsys.readouterr().out
    assert "gravado" in out and "1 criadas" in out and "1 criados" in out
    assert db_session.query(ProjectSubtaskProgress).filter(ProjectSubtaskProgress.project_id == project.id).count() == 1
    assert db_session.query(ProjectStageProgress).filter(ProjectStageProgress.project_id == project.id).count() == 1


def test_cli_reports_unmapped_keys_and_missing_projects(db_session, monkeypatch, tmp_path, capsys):
    _promoted(db_session)
    _cli_env(monkeypatch, db_session)
    assert cli.main(["--file", str(_write(tmp_path, _with_progress(done={"99.0": True}))), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "ATENÇÃO: 1 chaves sem correspondência" in out and "synth_p001: 99.0" in out
    assert "projetos por encontrar" in out  # os outros do fixture não foram promovidos


def test_cli_refuses_production_missing_catalog_bad_files_and_tracked_paths(db_session, monkeypatch, tmp_path, capsys):
    path = _write(tmp_path, _with_progress())
    _cli_env(monkeypatch, db_session, app_env="production")
    assert cli.main(["--file", str(path)]) == 1
    assert "staging-only" in capsys.readouterr().err

    _cli_env(monkeypatch, db_session)
    assert cli.main(["--file", str(tmp_path / "nao-existe.json")]) == 1
    bad = tmp_path / "bad.json"
    bad.write_text("{não é json", encoding="utf-8")
    assert cli.main(["--file", str(bad)]) == 1
    assert cli.main(["--file", str(path), "--actor-email", "ninguem@example.invalid"]) == 1

    inside = Path(__file__).resolve().parent / "_progresso_tmp.json"
    inside.write_text(json.dumps(_with_progress()), encoding="utf-8")
    try:
        assert cli.main(["--file", str(inside)]) == 1
        assert "Git" in capsys.readouterr().err
    finally:
        inside.unlink()

    db_session.query(ProjectSubtaskProgress).delete()
    db_session.query(WorkflowSubtask).delete()
    db_session.query(WorkflowStage).update({WorkflowStage.depends_on_stage_id: None})
    db_session.query(WorkflowStage).delete()
    db_session.query(Phase).delete()
    db_session.flush()
    assert cli.main(["--file", str(path)]) == 1
    assert "catálogo do processo não está carregado" in capsys.readouterr().err


# --- o progresso da lista vem do processo ----------------------------------------------------------------


def test_project_progress_percent_comes_from_the_process(db_session, api_client):
    project, _ = _promoted(db_session)
    body = api_client.get(f"/api/projects/{project.id}", headers=_h(CHEFE)).json()
    assert body["workflow_progress_percent"] == 0
    import_legacy_progress(db_session, _with_progress(done={f"10.{i}": True for i in range(15)} | {"2.0": True, "2.1": True}))
    expected = round(100 * 17 / 77)
    assert api_client.get(f"/api/projects/{project.id}", headers=_h(CHEFE)).json()["workflow_progress_percent"] == expected
    listed = {p["id"]: p for p in api_client.get("/api/projects", headers=_h(CHEFE)).json()}
    assert listed[str(project.id)]["workflow_progress_percent"] == expected
    others = [p["workflow_progress_percent"] for pid, p in listed.items() if pid != str(project.id)]
    assert others and set(others) == {0}


def test_marking_in_the_app_moves_the_percent(db_session, api_client):
    project = db_session.query(Project).filter(Project.name == OWN).one()
    sid = db_session.query(WorkflowSubtask).filter(WorkflowSubtask.code == "etapa-01.0").one().id
    api_client.patch(f"/api/projects/{project.id}/process/subtasks/{sid}", json={"done": True}, headers=_h(CHEFE))
    assert api_client.get(f"/api/projects/{project.id}", headers=_h(PM_UM)).json()["workflow_progress_percent"] == round(100 / 77)
    api_client.patch(f"/api/projects/{project.id}/process/subtasks/{sid}", json={"done": False}, headers=_h(CHEFE))
    assert api_client.get(f"/api/projects/{project.id}", headers=_h(PM_UM)).json()["workflow_progress_percent"] == 0


def test_without_a_loaded_catalog_the_old_task_based_percent_is_kept(db_session, api_client):
    db_session.query(ProjectSubtaskProgress).delete()
    db_session.query(WorkflowSubtask).delete()
    db_session.query(WorkflowStage).update({WorkflowStage.depends_on_stage_id: None})
    db_session.query(WorkflowStage).delete()
    db_session.query(Phase).delete()
    db_session.flush()
    percents = {p["workflow_progress_percent"] for p in api_client.get("/api/projects", headers=_h(CHEFE)).json()}
    assert len(percents) > 1  # o seed tem projetos com tarefas padrão feitas em graus diferentes


def test_list_query_count_does_not_grow_with_the_progress_recorded(db_session, api_client):
    from sqlalchemy import event

    from app.db import engine

    def count() -> int:
        counter = {"n": 0}

        def _on(*_a, **_k):
            counter["n"] += 1

        event.listen(engine, "before_cursor_execute", _on)
        try:
            assert api_client.get("/api/projects", headers=_h(CHEFE)).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", _on)
        return counter["n"]

    few = count()
    subtasks = db_session.query(WorkflowSubtask).all()
    for project in db_session.query(Project).all():
        for subtask in subtasks:
            db_session.add(ProjectSubtaskProgress(project_id=project.id, subtask_id=subtask.id, done=True, source="legacy"))
    db_session.flush()
    assert count() <= few + 1, "queries a crescer com o progresso — provável N+1"
