"""Estado do ciclo de vida do projeto (D-069): lista única, mapeamento do
legado, alteração com permissões/âmbito/histórico, filtro e ingestão."""
from __future__ import annotations

import pytest

from app.models.project import Project, ProjectHistory
from app.services.project_lifecycle import (
    LIFECYCLE_STATUS_CODES,
    lifecycle_status_from_legacy,
    status_change_warning,
)

CHEFE = "chefe.sintetico@example.invalid"
PM_UM = "pm.um.sintetico@example.invalid"
COMERCIAL = "comercial.sintetico@example.invalid"


def _headers(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def _project(db, name: str) -> Project:
    return db.query(Project).filter(Project.name == name).one()


# --- mapeamento do legado ------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("certificado final", "certificado_final"),
        ("entregue ao cliente", "entregue_cliente"),
        ("em preparação", "preparacao"),
        ("Em Preparacao", "preparacao"),
        ("construido", "construido"),
        ("Construído", "construido"),
        ("em construção", "construcao"),
        ("on hold pelo cliente", "on_hold_cliente"),
        ("  ON HOLD PELO CLIENTE ", "on_hold_cliente"),
        ("vendido", "on_hold_cliente"),  # D2
        (None, "on_hold_cliente"),  # D2
        ("", "on_hold_cliente"),
        ("   ", "on_hold_cliente"),
        ("valor desconhecido", None),  # nunca se adivinha
    ],
)
def test_legacy_status_mapping(raw, expected):
    assert lifecycle_status_from_legacy(raw) == expected


def test_every_mapped_status_is_a_known_code():
    for raw in ("certificado final", "entregue ao cliente", "em preparação", "construido", "em construção", "vendido"):
        assert lifecycle_status_from_legacy(raw) in LIFECYCLE_STATUS_CODES


def test_skipping_states_warns_but_adjacent_and_on_hold_do_not():
    assert status_change_warning("preparacao", "construcao") is None
    assert status_change_warning("construcao", "preparacao") is None  # recuar é livre
    assert status_change_warning("on_hold_cliente", "construido") is None
    assert status_change_warning("construcao", "on_hold_cliente") is None
    assert status_change_warning(None, "certificado_final") is None
    warning = status_change_warning("preparacao", "entregue_cliente")
    assert warning is not None and "2 estados" in warning
    assert "1 estado " in status_change_warning("preparacao", "construido")


# --- lista única -----------------------------------------------------------


def test_lifecycle_statuses_endpoint_lists_the_six_in_order(api_client):
    resp = api_client.get("/api/projects/lifecycle-statuses", headers=_headers(COMERCIAL))
    assert resp.status_code == 200
    body = resp.json()
    assert [s["code"] for s in body] == [
        "on_hold_cliente",
        "preparacao",
        "construcao",
        "construido",
        "entregue_cliente",
        "certificado_final",
    ]
    assert body[0]["label"] == "On hold pelo cliente"
    assert body[0]["flow_position"] is None
    assert [s["flow_position"] for s in body[1:]] == [1, 2, 3, 4, 5]


# --- alteração -------------------------------------------------------------


def test_chefe_changes_status_and_history_is_recorded(db_session, api_client):
    project = _project(db_session, "Instalação Sintética A — Início Próximo")
    assert project.lifecycle_status == "preparacao"

    resp = api_client.patch(
        f"/api/projects/{project.id}/status",
        json={"lifecycle_status": "construcao", "note": "Equipa no local."},
        headers=_headers(CHEFE),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["project"]["lifecycle_status"] == "construcao"
    assert body["warning"] is None

    entries = (
        db_session.query(ProjectHistory)
        .filter(ProjectHistory.project_id == project.id, ProjectHistory.field_name == "lifecycle_status")
        .all()
    )
    assert len(entries) == 1
    assert (entries[0].old_value, entries[0].new_value) == ("preparacao", "construcao")
    assert entries[0].note == "Equipa no local."
    assert entries[0].changed_by_person_id is not None


def test_skipping_states_is_allowed_with_a_warning(db_session, api_client):
    project = _project(db_session, "Instalação Sintética A — Início Próximo")
    resp = api_client.patch(
        f"/api/projects/{project.id}/status",
        json={"lifecycle_status": "entregue_cliente"},
        headers=_headers(CHEFE),
    )
    assert resp.status_code == 200
    assert resp.json()["project"]["lifecycle_status"] == "entregue_cliente"
    assert "2 estados" in resp.json()["warning"]


def test_same_status_is_a_noop_without_history(db_session, api_client):
    project = _project(db_session, "Instalação Sintética A — Início Próximo")
    resp = api_client.patch(
        f"/api/projects/{project.id}/status", json={"lifecycle_status": "preparacao"}, headers=_headers(CHEFE)
    )
    assert resp.status_code == 200 and resp.json()["warning"] is None
    assert (
        db_session.query(ProjectHistory)
        .filter(ProjectHistory.project_id == project.id, ProjectHistory.field_name == "lifecycle_status")
        .count()
        == 0
    )


def test_invalid_status_is_rejected_and_changes_nothing(db_session, api_client):
    project = _project(db_session, "Instalação Sintética A — Início Próximo")
    resp = api_client.patch(
        f"/api/projects/{project.id}/status", json={"lifecycle_status": "inventado"}, headers=_headers(CHEFE)
    )
    assert resp.status_code == 422
    db_session.refresh(project)
    assert project.lifecycle_status == "preparacao"


def test_pm_changes_only_own_projects(db_session, api_client):
    own = _project(db_session, "Instalação Sintética de Demonstração")
    other = _project(db_session, "Instalação Sintética Incompleta")
    assert other.pm_person_id is None

    ok = api_client.patch(
        f"/api/projects/{own.id}/status", json={"lifecycle_status": "construido"}, headers=_headers(PM_UM)
    )
    assert ok.status_code == 200 and ok.json()["project"]["can_change_status"] is True

    # Fora do âmbito do PM: 404, nunca 403 (não revela que existe).
    out = api_client.patch(
        f"/api/projects/{other.id}/status", json={"lifecycle_status": "construido"}, headers=_headers(PM_UM)
    )
    assert out.status_code == 404
    db_session.refresh(other)
    assert other.lifecycle_status == "preparacao"


def test_read_only_role_cannot_change_status(db_session, api_client):
    project = _project(db_session, "Instalação Sintética A — Início Próximo")
    resp = api_client.patch(
        f"/api/projects/{project.id}/status", json={"lifecycle_status": "construcao"}, headers=_headers(COMERCIAL)
    )
    assert resp.status_code == 403
    db_session.refresh(project)
    assert project.lifecycle_status == "preparacao"

    detail = api_client.get(f"/api/projects/{project.id}", headers=_headers(COMERCIAL)).json()
    assert detail["can_change_status"] is False
    assert detail["lifecycle_status"] == "preparacao"


# --- filtro ----------------------------------------------------------------


def test_filter_by_one_or_several_statuses(api_client):
    def names(query: str) -> set[str]:
        resp = api_client.get(f"/api/projects?{query}", headers=_headers(CHEFE))
        assert resp.status_code == 200
        return {p["name"] for p in resp.json()}

    assert names("lifecycle_status=on_hold_cliente") == {"Instalação Sintética E — Sem PM Atribuído"}
    assert names("lifecycle_status=on_hold_cliente&lifecycle_status=certificado_final") == {
        "Instalação Sintética E — Sem PM Atribuído",
        "Instalação Sintética H — Inativa",
    }


def test_filter_rejects_unknown_status(api_client):
    resp = api_client.get("/api/projects?lifecycle_status=inventado", headers=_headers(CHEFE))
    assert resp.status_code == 400


def test_pm_filter_never_widens_scope(api_client):
    resp = api_client.get("/api/projects?lifecycle_status=on_hold_cliente", headers=_headers(PM_UM))
    assert resp.status_code == 200
    assert resp.json() == []  # o único "on hold" não é deste PM: o filtro nunca alarga o âmbito


# --- ingestão --------------------------------------------------------------


def _fixture_with_status(status):
    import json

    from tests.test_staging_persistence import FIXTURE_PATH

    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload["projects"]["synth_p001"]["clickupStatus"] = status
    return payload


def test_promotion_sets_initial_status_from_legacy_and_reimport_never_overwrites(db_session):
    import json

    from app.migration.staging import ingest_export, promote_staging_record
    from app.models.identity import User
    from app.models.migration import StagingProjectRecord

    db = db_session
    actor = db.query(User).filter(User.email == CHEFE).one().person_id

    batch = ingest_export(db, payload=_fixture_with_status("em construção"), actor_person_id=actor)
    record = (
        db.query(StagingProjectRecord)
        .filter(StagingProjectRecord.import_batch_id == batch.id, StagingProjectRecord.external_id == "synth_p001")
        .one()
    )
    project = promote_staging_record(db, staging_record_id=record.id, actor_person_id=actor)
    assert project.lifecycle_status == "construcao"
    assert project.clickup_status_mirror == "em construção"

    # Alguém muda o estado no Op_PM; reimportar com outro estado ClickUp não o desfaz.
    project.lifecycle_status = "construido"
    db.commit()
    batch2 = ingest_export(db, payload=_fixture_with_status("entregue ao cliente"), actor_person_id=actor)
    record2 = (
        db.query(StagingProjectRecord)
        .filter(StagingProjectRecord.import_batch_id == batch2.id, StagingProjectRecord.external_id == "synth_p001")
        .one()
    )
    assert record2.resolved_action == "update_existing"
    assert json.loads(record2.mapped_fields_json)["clickup_status"] == "entregue ao cliente"
    promote_staging_record(db, staging_record_id=record2.id, actor_person_id=actor)
    db.refresh(project)
    assert project.lifecycle_status == "construido"  # o Op_PM manda (D1)
    assert project.clickup_status_mirror == "entregue ao cliente"  # o espelho segue o ClickUp


def test_unknown_legacy_status_leaves_project_without_status(db_session):
    from app.migration.staging import ingest_export, promote_staging_record
    from app.models.identity import User
    from app.models.migration import StagingProjectRecord

    db = db_session
    actor = db.query(User).filter(User.email == CHEFE).one().person_id
    batch = ingest_export(db, payload=_fixture_with_status("estado que ninguém previu"), actor_person_id=actor)
    record = (
        db.query(StagingProjectRecord)
        .filter(StagingProjectRecord.import_batch_id == batch.id, StagingProjectRecord.external_id == "synth_p001")
        .one()
    )
    project = promote_staging_record(db, staging_record_id=record.id, actor_person_id=actor)
    assert project.lifecycle_status is None
