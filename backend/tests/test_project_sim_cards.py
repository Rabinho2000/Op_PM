"""Cartões SIM por projeto (lista 0..n): CRUD, cifra em repouso, PIN/PUK ausentes de
leituras e do histórico, reveal com/sem permissão (no-store), falha fechada sem
chave, 422 sem eco, remoção lógica, isolamento por visibilidade e flags can_*.

Ver app/api/routes_project_sim_cards.py e docs/PLANO_LICENCIAMENTO_SIM.md.
Chaves Fernet geradas em tmp_path — nunca ficheiros de chave reais.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.config import Settings
from app.models.identity import Role, User, UserRole
from app.models.installer import Installer
from app.models.installer_access import InstallerAccessMembership
from app.models.people import Person
from app.models.project import Project
from app.models.project_data import ProjectDataHistory, ProjectSimCard
from app.security.catalog import ROLE_INSTALLER_COLLABORATOR

ADMIN = "admin.sintetico@example.invalid"
CHEFE = "chefe.sintetico@example.invalid"
PM = "pm.um.sintetico@example.invalid"
COMERCIAL = "comercial.sintetico@example.invalid"
PIN = "PIN-Segredo-4417-unico"
PUK = "PUK-Segredo-98812-unico"
PIN_2 = "PIN-Segredo-2nd-7731"


def _headers(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def _own_project(db):
    return db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()


def _other_project(db):
    """Sem PM atribuído: o PM sintético não o vê."""
    return db.query(Project).filter(Project.name == "Instalação Sintética Incompleta").one()


def _baseline_ids(db, project_id) -> list:
    """SIMs ativos que a seed já deixa no projeto (antes de qualquer teste criar)."""
    return [str(s.id) for s in db.query(ProjectSimCard).filter(ProjectSimCard.project_id == project_id, ProjectSimCard.deleted_at.is_(None)).all()]


@pytest.fixture()
def key_file(tmp_path: Path) -> Path:
    path = tmp_path / "secrets.key"
    path.write_text(Fernet.generate_key().decode("ascii") + "\n", encoding="utf-8")
    return path


@pytest.fixture()
def client(key_file, make_api_client):
    return make_api_client(Settings(app_env="test", auth_enabled=False, oppm_secrets_key_file=str(key_file)))


def _history_dump(db, project_id) -> str:
    rows = db.query(ProjectDataHistory).filter(ProjectDataHistory.project_id == project_id).all()
    return json.dumps(
        [
            {
                "entity_type": r.entity_type,
                "record_id": str(r.record_id),
                "field_name": r.field_name,
                "old_value": r.old_value,
                "new_value": r.new_value,
                "note": r.note,
            }
            for r in rows
        ],
        ensure_ascii=False,
    )


def _create_sim(client, project_id, headers=None, **extra) -> dict:
    body = {"purpose": "comunicacoes", "operator": "Operador Sintético", "phone_number": "910000002", "iccid": "ICCID-A-1"}
    body.update(extra)
    resp = client.post(f"/api/projects/{project_id}/sim-cards", json=body, headers=headers or _headers(PM))
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- CRUD ----------------------------------------------------------------------


def test_sim_crud_by_pm(db_session, client):
    project = _own_project(db_session)
    base = f"/api/projects/{project.id}/sim-cards"
    # A seed cria 1 SIM de demonstração neste projeto: a linha de base vem ANTES de criar.
    baseline_ids = _baseline_ids(db_session, project.id)
    assert len(baseline_ids) == 1
    created = _create_sim(client, project.id, pin=PIN, puk=PUK)
    sim_id = created["id"]
    assert created["purpose"] == "comunicacoes"
    assert created["has_pin"] is True and created["has_puk"] is True

    listed = client.get(base, headers=_headers(PM))
    assert listed.status_code == 200
    assert sorted(s["id"] for s in listed.json()) == sorted(baseline_ids + [sim_id])

    patched = client.patch(f"{base}/{sim_id}", json={"operator": "Outro Operador"}, headers=_headers(PM))
    assert patched.status_code == 200, patched.text
    assert patched.json()["operator"] == "Outro Operador"
    assert patched.json()["has_pin"] is True  # omitido = mantém

    cleared = client.patch(f"{base}/{sim_id}", json={"pin": None}, headers=_headers(PM))
    assert cleared.status_code == 200
    assert cleared.json()["has_pin"] is False
    assert cleared.json()["has_puk"] is True

    deleted = client.delete(f"{base}/{sim_id}", headers=_headers(PM))
    assert deleted.status_code == 204
    assert [s["id"] for s in client.get(base, headers=_headers(PM)).json()] == baseline_ids


def test_pin_and_puk_encrypted_at_rest(db_session, client, key_file):
    project = _own_project(db_session)
    created = _create_sim(client, project.id, pin=PIN, puk=PUK)
    row = db_session.get(ProjectSimCard, uuid.UUID(created["id"]))
    assert row.pin_encrypted is not None and row.puk_encrypted is not None
    for stored, clear in ((row.pin_encrypted, PIN), (row.puk_encrypted, PUK)):
        assert stored != clear
        assert clear not in stored
    fernet = Fernet(key_file.read_text(encoding="utf-8").strip().encode("ascii"))
    assert fernet.decrypt(row.pin_encrypted.encode("ascii")).decode("utf-8") == PIN
    assert fernet.decrypt(row.puk_encrypted.encode("ascii")).decode("utf-8") == PUK


def test_pin_puk_absent_from_every_read_and_history(db_session, client):
    project = _own_project(db_session)
    base = f"/api/projects/{project.id}"
    created = _create_sim(client, project.id, pin=PIN, puk=PUK)
    sim_id = created["id"]
    responses = [
        json.dumps(created, ensure_ascii=False),
        client.get(f"{base}/sim-cards", headers=_headers(PM)).text,
        client.get(f"{base}/sim-cards", headers=_headers(CHEFE)).text,
        client.get(base, headers=_headers(PM)).text,
        client.get(base, headers=_headers(ADMIN)).text,
        client.patch(f"{base}/sim-cards/{sim_id}", json={"pin": PIN_2}, headers=_headers(PM)).text,
        client.get(f"{base}/data-history", headers=_headers(CHEFE)).text,
        client.get(f"{base}/history", headers=_headers(CHEFE)).text,
    ]
    for text in responses:
        for secret in (PIN, PUK, PIN_2):
            assert secret not in text
    history_rows = _history_dump(db_session, project.id)
    for secret in (PIN, PUK, PIN_2):
        assert secret not in history_rows
    # O histórico regista o facto (marcador), nunca o valor.
    assert "PIN/PUK definidos" in history_rows
    assert "PIN alterado" in history_rows


# --- Reveal --------------------------------------------------------------------


def test_reveal_with_permission_returns_values_no_store_and_logs_without_value(db_session, client):
    project = _own_project(db_session)
    sim_id = _create_sim(client, project.id, pin=PIN, puk=PUK)["id"]

    revealed = client.post(f"/api/projects/{project.id}/sim-cards/{sim_id}/reveal", headers=_headers(PM))
    assert revealed.status_code == 200, revealed.text
    assert revealed.json()["pin"] == PIN
    assert revealed.json()["puk"] == PUK
    assert revealed.headers.get("cache-control") == "no-store"
    assert revealed.headers.get("pragma") == "no-cache"

    entries = (
        db_session.query(ProjectDataHistory)
        .filter(
            ProjectDataHistory.project_id == project.id,
            ProjectDataHistory.field_name == "secrets_revealed",
        )
        .all()
    )
    assert len(entries) == 1
    assert str(entries[0].record_id) == sim_id
    assert entries[0].old_value is None and entries[0].new_value is None
    assert entries[0].changed_by_person_id is not None
    dump = _history_dump(db_session, project.id)
    assert PIN not in dump and PUK not in dump


def test_reveal_without_permission_is_403_and_logs_nothing(db_session, client):
    project = _own_project(db_session)
    sim_id = _create_sim(client, project.id, pin=PIN, puk=PUK)["id"]
    before = db_session.query(ProjectDataHistory).filter(ProjectDataHistory.project_id == project.id).count()

    # Comercial vê o projeto mas não tem `project.credentials.reveal`.
    resp = client.post(f"/api/projects/{project.id}/sim-cards/{sim_id}/reveal", headers=_headers(COMERCIAL))
    assert resp.status_code == 403, resp.text
    assert PIN not in resp.text and PUK not in resp.text
    assert "secrets_revealed" not in _history_dump(db_session, project.id)

    after = db_session.query(ProjectDataHistory).filter(ProjectDataHistory.project_id == project.id).count()
    assert after == before


def test_reveal_without_secrets_is_409(db_session, client):
    project = _own_project(db_session)
    sim_id = _create_sim(client, project.id)["id"]
    resp = client.post(f"/api/projects/{project.id}/sim-cards/{sim_id}/reveal", headers=_headers(PM))
    assert resp.status_code == 409


# --- Falha fechada, validação ----------------------------------------------------


def test_without_key_writing_pin_fails_closed_nothing_written(db_session, make_api_client, tmp_path):
    project = _own_project(db_session)
    no_key = make_api_client(Settings(app_env="test", auth_enabled=False, oppm_secrets_key_file=""))
    resp = no_key.post(
        f"/api/projects/{project.id}/sim-cards",
        json={"purpose": "outro", "operator": "Sem Chave", "pin": PIN},
        headers=_headers(PM),
    )
    assert resp.status_code == 503
    assert PIN not in resp.text
    assert db_session.query(ProjectSimCard).filter(ProjectSimCard.operator == "Sem Chave").count() == 0

    # Chave apontada mas inexistente: mesma falha fechada.
    missing = make_api_client(
        Settings(app_env="test", auth_enabled=False, oppm_secrets_key_file=str(tmp_path / "inexistente.key"))
    )
    resp2 = missing.post(
        f"/api/projects/{project.id}/sim-cards",
        json={"purpose": "outro", "operator": "Chave Inexistente", "puk": PUK},
        headers=_headers(PM),
    )
    assert resp2.status_code == 503
    assert PUK not in resp2.text
    assert db_session.query(ProjectSimCard).filter(ProjectSimCard.operator == "Chave Inexistente").count() == 0


def test_without_key_setting_pin_on_existing_sim_fails_closed(db_session, make_api_client, client):
    project = _own_project(db_session)
    sim_id = _create_sim(client, project.id, operator="Sem PIN ainda")["id"]
    no_key = make_api_client(Settings(app_env="test", auth_enabled=False, oppm_secrets_key_file=""))
    patched = no_key.patch(f"/api/projects/{project.id}/sim-cards/{sim_id}", json={"puk": PUK}, headers=_headers(PM))
    assert patched.status_code == 503
    assert PUK not in patched.text
    assert db_session.get(ProjectSimCard, uuid.UUID(sim_id)).puk_encrypted is None


def test_invalid_body_422_does_not_echo_secrets(db_session, client):
    project = _own_project(db_session)
    marker = "Texto-Sensivel-SIM-42"
    resp = client.post(
        f"/api/projects/{project.id}/sim-cards",
        json={"purpose": "nao_existe", "notes": marker, "pin": PIN, "puk": PUK},
        headers=_headers(PM),
    )
    assert resp.status_code == 422
    assert resp.json() == {"detail": "Corpo inválido."}
    assert PIN not in resp.text and PUK not in resp.text and marker not in resp.text

    resp2 = client.post(
        f"/api/projects/{project.id}/sim-cards",
        json={"purpose": "outro", "pin": PIN, "campo_extra": marker},
        headers=_headers(PM),
    )
    assert resp2.status_code == 422
    assert PIN not in resp2.text and marker not in resp2.text


# --- Remoção lógica e isolamento -------------------------------------------------


def test_logical_delete_wipes_pin_puk_and_hides_row(db_session, client):
    project = _own_project(db_session)
    base = f"/api/projects/{project.id}/sim-cards"
    sim_id = _create_sim(client, project.id, pin=PIN, puk=PUK)["id"]
    assert client.delete(f"{base}/{sim_id}", headers=_headers(PM)).status_code == 204

    row = db_session.get(ProjectSimCard, uuid.UUID(sim_id))
    assert row is not None
    assert row.deleted_at is not None
    assert row.pin_encrypted is None and row.puk_encrypted is None
    assert client.post(f"{base}/{sim_id}/reveal", headers=_headers(PM)).status_code == 404
    assert client.delete(f"{base}/{sim_id}", headers=_headers(PM)).status_code == 404
    assert sim_id not in [s["id"] for s in client.get(base, headers=_headers(PM)).json()]


def test_pm_without_access_gets_404_on_every_sim_route(db_session, client):
    other = _other_project(db_session)
    base = f"/api/projects/{other.id}/sim-cards"
    fake = "00000000-0000-0000-0000-000000000001"
    assert client.get(base, headers=_headers(PM)).status_code == 404
    assert client.post(base, json={"purpose": "outro", "pin": PIN}, headers=_headers(PM)).status_code == 404
    assert client.patch(f"{base}/{fake}", json={"operator": "x"}, headers=_headers(PM)).status_code == 404
    assert client.delete(f"{base}/{fake}", headers=_headers(PM)).status_code == 404
    assert client.post(f"{base}/{fake}/reveal", headers=_headers(PM)).status_code == 404
    assert db_session.query(ProjectSimCard).filter(ProjectSimCard.project_id == other.id).count() == 0


def test_sim_of_other_project_is_404_through_this_project(db_session, client):
    own = _own_project(db_session)
    other = _other_project(db_session)
    sim_id = _create_sim(client, own.id, pin=PIN)["id"]
    # Um SIM de outro projeto não é acessível pelo caminho deste projeto.
    assert client.post(f"/api/projects/{other.id}/sim-cards/{sim_id}/reveal", headers=_headers(ADMIN)).status_code == 404
    assert client.patch(f"/api/projects/{other.id}/sim-cards/{sim_id}", json={"operator": "x"}, headers=_headers(ADMIN)).status_code == 404


# --- Flags can_* em ProjectRead ----------------------------------------------------

SIM_FLAGS = ("can_edit_credentials", "can_reveal_credentials", "can_edit_sim_cards", "can_reveal_sim_secrets", "can_edit_surplus_contracts")


def test_flags_true_for_admin_and_pm_of_project(db_session, client):
    project = _own_project(db_session)
    for email in (ADMIN, PM):
        body = client.get(f"/api/projects/{project.id}", headers=_headers(email)).json()
        for flag in SIM_FLAGS:
            assert body[flag] is True, (email, flag)


def test_flags_false_for_non_owner_with_view_only(db_session, client):
    project = _own_project(db_session)
    body = client.get(f"/api/projects/{project.id}", headers=_headers(COMERCIAL)).json()
    for flag in SIM_FLAGS:
        assert body[flag] is False, flag


def test_flags_false_for_pm_without_access(db_session, client):
    other = _other_project(db_session)
    response = client.get(f"/api/projects/{other.id}", headers=_headers(PM))
    assert response.status_code == 200
    body = response.json()
    assert body["can_view_project_scope"] is False
    assert body["can_change_status"] is True
    assert body["payments"] is None
    for flag in SIM_FLAGS:
        assert body[flag] is False, flag


def test_flags_false_for_installer_read_only_scope(db_session, client):
    project = _own_project(db_session)
    alfa = db_session.query(Installer).filter(Installer.name == "Instalador Sintético Alfa").one()
    email = "sim.installer.flags@example.invalid"
    person = Person(display_name="SIM Installer Flags", email=email, is_active=True)
    db_session.add(person)
    db_session.flush()
    user = User(person_id=person.id, email=email, is_active=True)
    db_session.add(user)
    db_session.flush()
    role = db_session.query(Role).filter(Role.code == ROLE_INSTALLER_COLLABORATOR).one()
    db_session.add_all(
        [
            UserRole(user_id=user.id, role_id=role.id),
            InstallerAccessMembership(person_id=person.id, installer_id=alfa.id, is_active=True),
        ]
    )
    project.installer_id = alfa.id
    db_session.flush()
    resp = client.get(f"/api/projects/{project.id}", headers=_headers(email))
    assert resp.status_code == 200, resp.text
    for flag in SIM_FLAGS:
        assert resp.json()[flag] is False, flag
