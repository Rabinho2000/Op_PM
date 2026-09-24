"""Instaladores, equipas e plano de obra (D-071): datas derivadas, API,
permissões e âmbito, regras de equipa, histórico, ingestão do legado e cargas."""
from __future__ import annotations

import datetime as dt
import json

import pytest
from sqlalchemy.exc import IntegrityError

from app.cli.load_installers import load_installers, main as load_main
from app.models.installer import Installer, InstallerTeam
from app.models.project import Project, ProjectHistory
from app.services.installers import business_day, derive_work_window, get_or_create_installer

CHEFE = "chefe.sintetico@example.invalid"
PM_UM = "pm.um.sintetico@example.invalid"
COMERCIAL = "comercial.sintetico@example.invalid"


def _h(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def _project(db, name: str) -> Project:
    return db.query(Project).filter(Project.name == name).one()


OWN = "Instalação Sintética de Demonstração"  # do PM Um, já planeada no seed (Alfa / Equipa 1)
OTHER = "Instalação Sintética Incompleta"  # sem PM


def _installer(db, name: str) -> Installer:
    return db.query(Installer).filter(Installer.name == name).one()


def _team(db, installer_name: str, team_name: str) -> InstallerTeam:
    installer = _installer(db, installer_name)
    return next(t for t in installer.teams if t.name == team_name)


ALFA = "Instalador Sintético Alfa"
BETA = "Instalador Sintético Beta"


def _plan(api_client, project, email=CHEFE, **body):
    return api_client.patch(f"/api/projects/{project.id}/work-plan", json=body, headers=_h(email))


# --- datas derivadas --------------------------------------------------------


def test_business_day_counts_only_weekdays():
    tuesday = dt.date(2026, 3, 17)
    assert business_day(tuesday, 1) == tuesday
    assert business_day(tuesday, 6) == dt.date(2026, 3, 24)  # salta o fim de semana
    assert business_day(tuesday, 41) == dt.date(2026, 5, 12)  # 8 semanas depois


def test_a_weekend_start_counts_from_the_next_monday():
    saturday = dt.date(2026, 3, 14)
    assert business_day(saturday, 1) == dt.date(2026, 3, 16)
    assert business_day(saturday, 2) == dt.date(2026, 3, 17)


def test_derive_work_window_is_business_day_41_to_49():
    assert derive_work_window(dt.date(2026, 3, 17)) == (dt.date(2026, 5, 12), dt.date(2026, 5, 22))
    assert derive_work_window(None) is None
    start, end = derive_work_window(dt.date(2026, 9, 30))
    assert start.weekday() < 5 and end.weekday() < 5 and end > start


# --- instaladores e equipas (API) -------------------------------------------


def test_who_can_see_and_who_can_manage_installers(api_client):
    for email in (CHEFE, PM_UM, COMERCIAL):
        assert api_client.get("/api/installers", headers=_h(email)).status_code == 200
    assert api_client.post("/api/installers", json={"name": "Novo"}, headers=_h(CHEFE)).status_code == 201
    assert api_client.post("/api/installers", json={"name": "Outro"}, headers=_h(PM_UM)).status_code == 403
    assert api_client.post("/api/installers", json={"name": "Outro"}, headers=_h(COMERCIAL)).status_code == 403


def test_list_shows_teams_leaders_and_project_counts(api_client):
    body = api_client.get("/api/installers", headers=_h(CHEFE)).json()
    alfa = next(i for i in body if i["name"] == ALFA)
    assert [t["name"] for t in alfa["teams"]] == ["Equipa 1", "Equipa 2"]
    assert alfa["teams"][0]["leader_name"] == "Chefe Sintético Um"
    assert alfa["project_count"] == 3  # Demonstração, Início Próximo e Trabalho Urgente
    assert alfa["teams"][0]["project_count"] == 2
    assert next(i for i in body if i["name"] == BETA)["project_count"] == 1


def test_installer_names_are_unique_ignoring_case_and_accents(api_client):
    assert api_client.post("/api/installers", json={"name": "Verde Milenar"}, headers=_h(CHEFE)).status_code == 201
    dup = api_client.post("/api/installers", json={"name": "  VERDE   milenar "}, headers=_h(CHEFE))
    assert dup.status_code == 409


def test_team_crud_and_rules(api_client):
    created = api_client.post("/api/installers", json={"name": "Com Equipas"}, headers=_h(CHEFE)).json()
    iid = created["id"]
    ok = api_client.post(
        f"/api/installers/{iid}/teams",
        json={"name": " Equipa   A ", "leader_name": "Chefe A", "leader_phone": "+351 910 000 000"},
        headers=_h(CHEFE),
    )
    assert ok.status_code == 201
    team = ok.json()["teams"][0]
    assert team["name"] == "Equipa A" and team["leader_name"] == "Chefe A"

    dup = api_client.post(f"/api/installers/{iid}/teams", json={"name": "equipa a"}, headers=_h(CHEFE))
    assert dup.status_code == 409
    bad_phone = api_client.post(f"/api/installers/{iid}/teams", json={"name": "B", "leader_phone": "abc"}, headers=_h(CHEFE))
    assert bad_phone.status_code == 422
    assert api_client.post(f"/api/installers/{iid}/teams", json={"name": "B"}, headers=_h(PM_UM)).status_code == 403

    upd = api_client.patch(
        f"/api/installers/{iid}/teams/{team['id']}", json={"leader_name": None, "is_active": False}, headers=_h(CHEFE)
    )
    assert upd.status_code == 200
    assert upd.json()["teams"][0]["leader_name"] is None and upd.json()["teams"][0]["is_active"] is False

    # Uma equipa de outro instalador não se edita por este caminho.
    other = api_client.post("/api/installers", json={"name": "Outro Instalador"}, headers=_h(CHEFE)).json()
    wrong = api_client.patch(f"/api/installers/{other['id']}/teams/{team['id']}", json={"is_active": True}, headers=_h(CHEFE))
    assert wrong.status_code == 404
    for field in ("name", "is_active"):
        nul = api_client.patch(f"/api/installers/{iid}/teams/{team['id']}", json={field: None}, headers=_h(CHEFE))
        assert nul.status_code == 422, field


def test_installers_are_deactivated_never_deleted(api_client):
    created = api_client.post("/api/installers", json={"name": "Para desativar"}, headers=_h(CHEFE)).json()
    resp = api_client.patch(f"/api/installers/{created['id']}", json={"is_active": False}, headers=_h(CHEFE))
    assert resp.status_code == 200 and resp.json()["is_active"] is False
    assert api_client.delete(f"/api/installers/{created['id']}", headers=_h(CHEFE)).status_code == 405


# --- plano de obra de um projeto ----------------------------------------------


def test_project_read_exposes_installer_team_leader_and_dates(db_session, api_client):
    project = _project(db_session, OWN)
    body = api_client.get(f"/api/projects/{project.id}", headers=_h(CHEFE)).json()
    assert body["installer_name"] == ALFA
    assert body["installer_team_name"] == "Equipa 1"
    assert body["installer_team_leader_name"] == "Chefe Sintético Um"
    assert body["work_start_date"] and body["work_end_date"]
    assert body["work_dates_estimated"] is False
    assert body["can_plan_work"] is True


def test_chefe_assigns_installer_team_and_dates_with_history(db_session, api_client):
    project = _project(db_session, OTHER)
    assert project.installer_id is None
    alfa, beta = _installer(db_session, ALFA), _installer(db_session, BETA)
    equipa2 = _team(db_session, ALFA, "Equipa 2")

    resp = _plan(
        api_client, project, installer_id=str(alfa.id), installer_team_id=str(equipa2.id),
        work_start_date="2026-11-02", work_end_date="2026-11-12",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["installer_name"], body["installer_team_name"]) == (ALFA, "Equipa 2")
    assert (body["work_start_date"], body["work_end_date"]) == ("2026-11-02", "2026-11-12")

    fields = {
        e.field_name: (e.old_value, e.new_value)
        for e in db_session.query(ProjectHistory).filter(ProjectHistory.project_id == project.id).all()
        if e.source == "ui"
    }
    assert set(fields) >= {"installer_id", "installer_team_id", "work_start_date", "work_end_date"}
    assert fields["work_start_date"] == (None, "2026-11-02")

    # Mudar de instalador sem indicar equipa limpa a equipa (a antiga não é do novo instalador).
    resp2 = _plan(api_client, project, installer_id=str(beta.id))
    assert resp2.status_code == 200
    assert resp2.json()["installer_name"] == BETA and resp2.json()["installer_team_id"] is None


def test_team_must_belong_to_the_installer(db_session, api_client):
    project = _project(db_session, OTHER)
    beta = _installer(db_session, BETA)
    equipa1 = _team(db_session, ALFA, "Equipa 1")
    resp = _plan(api_client, project, installer_id=str(beta.id), installer_team_id=str(equipa1.id))
    assert resp.status_code == 422 and "não pertence" in resp.json()["detail"]
    db_session.refresh(project)
    assert project.installer_id is None  # nada foi gravado


def test_team_alone_needs_an_installer(db_session, api_client):
    project = _project(db_session, OTHER)
    equipa1 = _team(db_session, ALFA, "Equipa 1")
    resp = _plan(api_client, project, installer_team_id=str(equipa1.id))
    assert resp.status_code == 422  # sem instalador, a equipa não pertence a nenhum

    with_null = _plan(api_client, project, installer_id=None, installer_team_id=str(equipa1.id))
    assert with_null.status_code == 422 and "Sem instalador" in with_null.json()["detail"]


def test_removing_the_installer_removes_the_team(db_session, api_client):
    project = _project(db_session, OWN)
    resp = _plan(api_client, project, installer_id=None)
    assert resp.status_code == 200
    assert resp.json()["installer_id"] is None and resp.json()["installer_team_id"] is None


def test_unknown_installer_or_team_is_rejected(db_session, api_client):
    project = _project(db_session, OTHER)
    missing = "00000000-0000-0000-0000-000000000000"
    assert _plan(api_client, project, installer_id=missing).status_code == 422
    alfa = _installer(db_session, ALFA)
    assert _plan(api_client, project, installer_id=str(alfa.id), installer_team_id=missing).status_code == 422


def test_inactive_installer_or_team_cannot_be_newly_assigned_but_stays_if_unchanged(db_session, api_client):
    project = _project(db_session, OWN)  # Alfa / Equipa 1
    equipa1 = _team(db_session, ALFA, "Equipa 1")
    equipa2 = _team(db_session, ALFA, "Equipa 2")
    equipa1.is_active = False
    equipa2.is_active = False
    db_session.flush()

    # Continua atribuída (não mudou): editar só as datas não falha.
    ok = _plan(api_client, project, work_end_date="2027-01-30")
    assert ok.status_code == 200 and ok.json()["installer_team_name"] == "Equipa 1"
    # Atribuir a outra equipa inativa é recusado.
    bad = _plan(api_client, project, installer_team_id=str(equipa2.id))
    assert bad.status_code == 422 and "inativa" in bad.json()["detail"]


def test_end_before_start_is_rejected_even_against_the_existing_date(db_session, api_client):
    project = _project(db_session, OWN)
    assert _plan(api_client, project, work_start_date="2026-12-10", work_end_date="2026-12-01").status_code == 422
    # Só o fim, anterior ao início já gravado:
    project.work_start_date = dt.date(2026, 12, 10)
    project.work_end_date = dt.date(2026, 12, 20)
    db_session.flush()
    assert _plan(api_client, project, work_end_date="2026-12-01").status_code == 422
    assert _plan(api_client, project, work_start_date="2026-12-25").status_code == 422
    assert _plan(api_client, project, work_start_date="2026-12-10", work_end_date="2026-12-10").status_code == 200


def test_editing_dates_confirms_estimated_ones(db_session, api_client):
    project = _project(db_session, OWN)
    project.work_dates_estimated = True
    db_session.flush()
    only_team = _plan(api_client, project, installer_team_id=str(_team(db_session, ALFA, "Equipa 2").id))
    assert only_team.json()["work_dates_estimated"] is True  # mudar a equipa não confirma as datas
    confirmed = _plan(api_client, project, work_end_date="2027-02-26")
    assert confirmed.json()["work_dates_estimated"] is False


def test_clearing_dates_and_validation_of_the_body(db_session, api_client):
    project = _project(db_session, OWN)
    cleared = _plan(api_client, project, work_start_date=None, work_end_date=None)
    assert cleared.status_code == 200 and cleared.json()["work_start_date"] is None
    assert _plan(api_client, project).status_code == 422  # corpo vazio
    assert _plan(api_client, project, cor="azul").status_code == 422  # campo desconhecido
    assert _plan(api_client, project, work_start_date="não é data").status_code == 422


def test_no_history_when_nothing_changes(db_session, api_client):
    project = _project(db_session, OWN)
    before = db_session.query(ProjectHistory).filter(ProjectHistory.project_id == project.id).count()
    resp = _plan(api_client, project, installer_id=str(project.installer_id))
    assert resp.status_code == 200
    assert db_session.query(ProjectHistory).filter(ProjectHistory.project_id == project.id).count() == before


def test_pm_plans_only_own_projects_and_others_are_404(db_session, api_client):
    own, other = _project(db_session, OWN), _project(db_session, OTHER)
    ok = _plan(api_client, own, email=PM_UM, work_end_date="2027-03-05")
    assert ok.status_code == 200 and ok.json()["can_plan_work"] is True
    out = _plan(api_client, other, email=PM_UM, work_end_date="2027-03-05")
    assert out.status_code == 404  # nunca revela que existe


def test_read_only_role_cannot_plan(db_session, api_client):
    project = _project(db_session, OWN)
    resp = _plan(api_client, project, email=COMERCIAL, work_end_date="2027-03-05")
    assert resp.status_code == 403
    detail = api_client.get(f"/api/projects/{project.id}", headers=_h(COMERCIAL)).json()
    assert detail["can_plan_work"] is False


# --- restrições da base de dados -------------------------------------------------


def test_database_refuses_a_team_without_installer(db_session):
    project = _project(db_session, OTHER)
    project.installer_id = None
    project.installer_team_id = _team(db_session, ALFA, "Equipa 1").id
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_database_refuses_a_team_of_another_installer(db_session):
    """A chave composta (instalador, equipa) exige que a equipa seja do instalador."""
    if db_session.bind.dialect.name == "sqlite":
        from sqlalchemy import text

        if db_session.execute(text("PRAGMA foreign_keys")).scalar() != 1:
            pytest.skip("SQLite sem `PRAGMA foreign_keys` ativo — coberto no job de PostgreSQL")
    project = _project(db_session, OTHER)
    project.installer_id = _installer(db_session, BETA).id
    project.installer_team_id = _team(db_session, ALFA, "Equipa 1").id
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


# --- ingestão do legado ---------------------------------------------------------------


def _legacy_payload(**project_fields):
    from tests.test_staging_persistence import FIXTURE_PATH

    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload["projects"]["synth_p001"].update(project_fields)
    return payload


def _promote(db, payload, external_id="synth_p001"):
    from app.migration.staging import ingest_export, promote_staging_record
    from app.models.identity import User
    from app.models.migration import StagingProjectRecord

    actor = db.query(User).filter(User.email == CHEFE).one().person_id
    batch = ingest_export(db, payload=payload, actor_person_id=actor)
    record = (
        db.query(StagingProjectRecord)
        .filter(StagingProjectRecord.import_batch_id == batch.id, StagingProjectRecord.external_id == external_id)
        .one()
    )
    return promote_staging_record(db, staging_record_id=record.id, actor_person_id=actor), record, actor


def test_promotion_creates_the_installer_and_estimated_work_dates(db_session):
    project, _record, _actor = _promote(db_session, _legacy_payload(subcontractor="  Verde   Milenar "))
    assert project.installer.name == "Verde Milenar"
    assert project.installer_team_id is None  # o legado não diz a equipa
    assert project.start_date == dt.date(2026, 2, 10)
    assert (project.work_start_date, project.work_end_date) == derive_work_window(dt.date(2026, 2, 10))
    assert project.work_dates_estimated is True


def test_installer_names_from_the_legacy_are_normalized_into_one(db_session):
    first, _r, _a = _promote(db_session, _legacy_payload(subcontractor="Verde Milenar"))
    assert get_or_create_installer(db_session, "  VERDE milenar ").id == first.installer_id
    assert db_session.query(Installer).filter(Installer.name_key == "verde milenar").count() == 1


@pytest.mark.parametrize("empty", ["", "   ", None])
def test_empty_subcontractor_means_no_installer(db_session, empty):
    project, _r, _a = _promote(db_session, _legacy_payload(subcontractor=empty))
    assert project.installer_id is None


def test_project_without_start_date_gets_no_work_window(db_session):
    project, _r, _a = _promote(db_session, _legacy_payload(subcontractor="X", startDate=None))
    assert project.start_date is None
    assert project.work_start_date is None and project.work_end_date is None
    assert project.work_dates_estimated is False


def test_reimport_never_overwrites_a_planned_installer_or_dates_and_rollback_restores(db_session):
    from app.migration.staging import ingest_export, promote_staging_record, rollback_promotion
    from app.models.migration import StagingProjectRecord

    project, _record, actor = _promote(db_session, _legacy_payload(subcontractor="Um"))
    um = project.installer
    project.work_start_date = dt.date(2026, 6, 1)
    project.work_end_date = dt.date(2026, 6, 10)
    project.work_dates_estimated = False
    db_session.commit()

    batch2 = ingest_export(db_session, payload=_legacy_payload(subcontractor="Dois"), actor_person_id=actor)
    record2 = (
        db_session.query(StagingProjectRecord)
        .filter(StagingProjectRecord.import_batch_id == batch2.id, StagingProjectRecord.external_id == "synth_p001")
        .one()
    )
    assert record2.resolved_action == "update_existing"
    promote_staging_record(db_session, staging_record_id=record2.id, actor_person_id=actor)
    db_session.refresh(project)
    assert project.installer_id == um.id  # o Op_PM manda
    assert (project.work_start_date, project.work_end_date) == (dt.date(2026, 6, 1), dt.date(2026, 6, 10))
    assert project.work_dates_estimated is False

    # Um projeto sem instalador é preenchido por uma reimportação — e o rollback repõe o vazio.
    project.installer_id = None
    project.installer_team_id = None
    db_session.commit()
    batch3 = ingest_export(db_session, payload=_legacy_payload(subcontractor="Tres"), actor_person_id=actor)
    record3 = (
        db_session.query(StagingProjectRecord)
        .filter(StagingProjectRecord.import_batch_id == batch3.id, StagingProjectRecord.external_id == "synth_p001")
        .one()
    )
    promote_staging_record(db_session, staging_record_id=record3.id, actor_person_id=actor)
    db_session.refresh(project)
    assert project.installer.name == "Tres"
    rollback_promotion(db_session, staging_record_id=record3.id, actor_person_id=actor, reason="teste")
    db_session.refresh(project)
    assert project.installer_id is None


# --- carga de instaladores e equipas ---------------------------------------------------


ENTRIES = [
    {
        "name": "Verde Milenar",
        "teams": [
            {"name": "Equipa 1", "leader_name": "Chefe Um", "leader_phone": "+351 910 000 001"},
            {"name": "Equipa 2", "leader_name": "Chefe Dois"},
            {"name": "Equipa 3"},
        ],
    },
    {"name": "Sem Equipas"},
    {"name": "Inválido", "teams": [{"name": "X", "leader_phone": "abc"}]},
]


def test_loader_creates_validates_and_is_idempotent(db_session):
    summary = load_installers(db_session, ENTRIES)
    assert (summary["installers_created"], summary["teams_created"]) == (3, 3)
    assert len(summary["invalid"]) == 1 and "Inválido / X" in summary["invalid"][0]
    vm = _installer(db_session, "Verde Milenar")
    assert [(t.name, t.leader_name) for t in vm.teams] == [("Equipa 1", "Chefe Um"), ("Equipa 2", "Chefe Dois"), ("Equipa 3", None)]

    again = load_installers(db_session, ENTRIES)
    assert (again["installers_created"], again["teams_created"], again["teams_updated"]) == (0, 0, 0)


def test_loader_only_fills_empty_fields(db_session):
    load_installers(db_session, ENTRIES)
    vm = _installer(db_session, "Verde Milenar")
    equipa1 = next(t for t in vm.teams if t.name == "Equipa 1")
    equipa1.leader_name = "Editado na app"
    equipa1.is_active = False
    equipa3 = next(t for t in vm.teams if t.name == "Equipa 3")
    db_session.flush()

    changed = [{"name": "verde milenar", "teams": [
        {"name": "equipa 1", "leader_name": "Chefe Um"},
        {"name": "Equipa 3", "leader_name": "Novo Chefe", "leader_phone": "+351 910 000 003"},
    ]}]
    summary = load_installers(db_session, changed)
    assert summary["teams_updated"] == 1
    db_session.refresh(equipa1)
    db_session.refresh(equipa3)
    assert equipa1.leader_name == "Editado na app" and equipa1.is_active is False
    assert (equipa3.leader_name, equipa3.leader_phone) == ("Novo Chefe", "+351 910 000 003")


def test_loader_cli_refuses_a_file_git_would_track_and_bad_format(tmp_path, capsys):
    from pathlib import Path

    inside = Path(__file__).resolve().parent / "_instaladores_tmp.json"
    inside.write_text(json.dumps({"installers": []}), encoding="utf-8")
    try:
        assert load_main(["--file", str(inside), "--dry-run"]) == 1
        assert "Git" in capsys.readouterr().err
    finally:
        inside.unlink()
    outside = tmp_path / "instaladores.json"
    outside.write_text(json.dumps({"installers": "não é uma lista"}), encoding="utf-8")
    assert load_main(["--file", str(outside), "--dry-run"]) == 1
    assert "installers" in capsys.readouterr().err


# --- desempenho ---------------------------------------------------------------------------


def test_project_list_query_count_does_not_grow_with_distinct_installers(db_session, api_client):
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
    projects = db_session.query(Project).all()
    for i, project in enumerate(projects):
        installer = get_or_create_installer(db_session, f"Instalador extra {i}")
        project.installer_team_id = None  # a equipa antiga é de outro instalador (a chave composta recusa)
        project.installer_id = installer.id
    db_session.flush()
    many = count()
    # O nº de queries por projeto já existia (resumo de tarefas); os instaladores não acrescentam N+1.
    assert many <= few + 2, f"queries a crescer com o nº de instaladores: {few} -> {many}"


def test_dates_can_be_confirmed_without_changing_them(db_session, api_client):
    project = _project(db_session, OWN)
    project.work_dates_estimated = True
    db_session.flush()
    start, end = project.work_start_date, project.work_end_date

    resp = _plan(api_client, project, work_dates_estimated=False)
    assert resp.status_code == 200
    body = resp.json()
    assert body["work_dates_estimated"] is False
    assert (body["work_start_date"], body["work_end_date"]) == (start.isoformat(), end.isoformat())
    confirm_entries = (
        db_session.query(ProjectHistory)
        .filter(ProjectHistory.project_id == project.id, ProjectHistory.field_name == "work_dates_estimated")
        .all()
    )
    assert [(e.old_value, e.new_value, e.note) for e in confirm_entries] == [("True", "False", "Datas da obra confirmadas.")]

    # Já confirmadas: repetir não grava nada; e só se aceita `false`.
    again = _plan(api_client, project, work_dates_estimated=False)
    assert again.status_code == 200
    assert len(db_session.query(ProjectHistory).filter(ProjectHistory.project_id == project.id, ProjectHistory.field_name == "work_dates_estimated").all()) == 1
    assert _plan(api_client, project, work_dates_estimated=True).status_code == 422
