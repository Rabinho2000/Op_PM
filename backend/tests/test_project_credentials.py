"""Credenciais de portais por projeto: CRUD, cifra em repouso, password ausente
de leituras e do histórico, reveal com/sem permissão, falha fechada sem chave,
422 sem eco e isolamento por visibilidade. Ver app/api/routes_project_credentials.py.

Chaves Fernet geradas em tmp_path — nunca ficheiros de chave reais.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.config import Settings
from app.models.project import Project
from app.models.project_data import ProjectDataHistory, ProjectPortalCredential

PM = "pm.um.sintetico@example.invalid"
CHEFE = "chefe.sintetico@example.invalid"
COMERCIAL = "comercial.sintetico@example.invalid"
SECRET = "Pw-Segredo-7f3QzLk-unico"


def _headers(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def _own_project(db):
    return db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()


def _other_project(db):
    """Sem PM atribuído: o PM sintético não tem acesso (404)."""
    return db.query(Project).filter(Project.name == "Instalação Sintética Incompleta").one()


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


def test_credential_crud_by_pm(db_session, client):
    project = _own_project(db_session)
    created = client.post(
        f"/api/projects/{project.id}/credentials",
        json={"portal": "dgeg_login_geral", "username": "user-a", "password": SECRET},
        headers=_headers(PM),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["has_password"] is True
    assert body["username"] == "user-a"
    cred_id = body["id"]

    listed = client.get(f"/api/projects/{project.id}/credentials", headers=_headers(PM))
    assert listed.status_code == 200
    assert [c["id"] for c in listed.json()] == [cred_id]

    patched = client.patch(
        f"/api/projects/{project.id}/credentials/{cred_id}",
        json={"username": "user-b"},
        headers=_headers(PM),
    )
    assert patched.status_code == 200
    assert patched.json()["username"] == "user-b"
    assert patched.json()["has_password"] is True  # não mexer na password ao omitir o campo

    cleared = client.patch(
        f"/api/projects/{project.id}/credentials/{cred_id}",
        json={"password": None},
        headers=_headers(PM),
    )
    assert cleared.status_code == 200
    assert cleared.json()["has_password"] is False

    deleted = client.delete(f"/api/projects/{project.id}/credentials/{cred_id}", headers=_headers(PM))
    assert deleted.status_code == 204
    assert client.get(f"/api/projects/{project.id}/credentials", headers=_headers(PM)).json() == []


def test_password_is_encrypted_at_rest(db_session, client, key_file):
    project = _own_project(db_session)
    resp = client.post(
        f"/api/projects/{project.id}/credentials",
        json={"portal": "mastervantagem", "username": "mv-user", "password": SECRET},
        headers=_headers(PM),
    )
    assert resp.status_code == 201
    row = db_session.get(ProjectPortalCredential, resp.json()["id"])
    assert row.password_encrypted is not None
    assert row.password_encrypted != SECRET
    assert SECRET not in row.password_encrypted
    fernet = Fernet(key_file.read_text(encoding="utf-8").strip().encode("ascii"))
    assert fernet.decrypt(row.password_encrypted.encode("ascii")).decode("utf-8") == SECRET


def test_password_absent_from_every_read_and_history(db_session, client):
    project = _own_project(db_session)
    created = client.post(
        f"/api/projects/{project.id}/credentials",
        json={"portal": "outro", "username": "u-hist", "password": SECRET},
        headers=_headers(PM),
    )
    assert created.status_code == 201
    cred_id = created.json()["id"]
    responses = [
        created.text,
        client.get(f"/api/projects/{project.id}/credentials", headers=_headers(PM)).text,
        client.get(f"/api/projects/{project.id}/credentials", headers=_headers(CHEFE)).text,
        client.patch(
            f"/api/projects/{project.id}/credentials/{cred_id}",
            json={"password": SECRET + "-2"},
            headers=_headers(PM),
        ).text,
        client.get(f"/api/projects/{project.id}/data-history?entity_type=credential", headers=_headers(CHEFE)).text,
        client.get(f"/api/projects/{project.id}/data-history", headers=_headers(CHEFE)).text,
    ]
    for text in responses:
        assert SECRET not in text
        assert SECRET + "-2" not in text
    history_rows = _history_dump(db_session, project.id)
    assert SECRET not in history_rows
    assert SECRET + "-2" not in history_rows
    # O histórico regista o facto da alteração (nota), nunca o valor.
    assert "password alterada" in history_rows


def test_reveal_with_permission_returns_password_and_logs_without_value(db_session, client):
    project = _own_project(db_session)
    cred_id = client.post(
        f"/api/projects/{project.id}/credentials",
        json={"portal": "dgeg_login_geral", "username": "rev-user", "password": SECRET},
        headers=_headers(PM),
    ).json()["id"]

    revealed = client.post(f"/api/projects/{project.id}/credentials/{cred_id}/reveal", headers=_headers(PM))
    assert revealed.status_code == 200, revealed.text
    assert revealed.json()["password"] == SECRET

    entries = (
        db_session.query(ProjectDataHistory)
        .filter(
            ProjectDataHistory.project_id == project.id,
            ProjectDataHistory.field_name == "password_revealed",
        )
        .all()
    )
    assert len(entries) == 1
    assert entries[0].record_id is not None and str(entries[0].record_id) == cred_id
    assert entries[0].old_value is None and entries[0].new_value is None
    assert entries[0].changed_by_person_id is not None
    assert SECRET not in _history_dump(db_session, project.id)


def test_reveal_response_is_not_cacheable(db_session, client):
    project = _own_project(db_session)
    cred_id = client.post(
        f"/api/projects/{project.id}/credentials",
        json={"portal": "dgeg_login_geral", "username": "nocache-user", "password": SECRET},
        headers=_headers(PM),
    ).json()["id"]

    revealed = client.post(f"/api/projects/{project.id}/credentials/{cred_id}/reveal", headers=_headers(PM))
    assert revealed.status_code == 200, revealed.text
    assert revealed.headers.get("cache-control") == "no-store"
    assert revealed.headers.get("pragma") == "no-cache"


def test_reveal_without_permission_is_403_and_logs_nothing(db_session, client):
    project = _own_project(db_session)
    cred_id = client.post(
        f"/api/projects/{project.id}/credentials",
        json={"portal": "dgeg_login_geral", "username": "noreveal", "password": SECRET},
        headers=_headers(PM),
    ).json()["id"]
    before = db_session.query(ProjectDataHistory).filter(ProjectDataHistory.project_id == project.id).count()

    # Comercial não tem `project.credentials.reveal` nem `project.view_communication_data`.
    resp = client.post(f"/api/projects/{project.id}/credentials/{cred_id}/reveal", headers=_headers(COMERCIAL))
    assert resp.status_code == 403, resp.text
    assert SECRET not in resp.text
    listed = client.get(f"/api/projects/{project.id}/credentials", headers=_headers(COMERCIAL))
    assert listed.status_code == 403

    after = db_session.query(ProjectDataHistory).filter(ProjectDataHistory.project_id == project.id).count()
    assert after == before
    assert "password_revealed" not in _history_dump(db_session, project.id)


def test_reveal_without_password_is_409(db_session, client):
    project = _own_project(db_session)
    cred_id = client.post(
        f"/api/projects/{project.id}/credentials",
        json={"portal": "outro", "username": "sem-pass"},
        headers=_headers(PM),
    ).json()["id"]
    resp = client.post(f"/api/projects/{project.id}/credentials/{cred_id}/reveal", headers=_headers(PM))
    assert resp.status_code == 409


def test_without_key_writing_password_fails_closed(db_session, make_api_client, tmp_path):
    project = _own_project(db_session)
    no_key = make_api_client(Settings(app_env="test", auth_enabled=False, oppm_secrets_key_file=""))
    resp = no_key.post(
        f"/api/projects/{project.id}/credentials",
        json={"portal": "dgeg_login_geral", "username": "nokey", "password": SECRET},
        headers=_headers(PM),
    )
    assert resp.status_code == 503
    assert SECRET not in resp.text
    assert db_session.query(ProjectPortalCredential).filter(ProjectPortalCredential.username == "nokey").count() == 0

    missing = make_api_client(
        Settings(app_env="test", auth_enabled=False, oppm_secrets_key_file=str(tmp_path / "inexistente.key"))
    )
    resp2 = missing.post(
        f"/api/projects/{project.id}/credentials",
        json={"portal": "dgeg_login_geral", "username": "nokey2", "password": SECRET},
        headers=_headers(PM),
    )
    assert resp2.status_code == 503
    assert db_session.query(ProjectPortalCredential).filter(ProjectPortalCredential.username == "nokey2").count() == 0


def test_without_key_listing_and_username_only_still_work(db_session, make_api_client):
    project = _own_project(db_session)
    no_key = make_api_client(Settings(app_env="test", auth_enabled=False, oppm_secrets_key_file=""))
    resp = no_key.post(
        f"/api/projects/{project.id}/credentials",
        json={"portal": "outro", "username": "so-utilizador"},
        headers=_headers(PM),
    )
    assert resp.status_code == 201
    assert resp.json()["has_password"] is False


def test_invalid_body_422_does_not_echo_password(db_session, client):
    project = _own_project(db_session)
    resp = client.post(
        f"/api/projects/{project.id}/credentials",
        json={"portal": "portal-invalido", "username": "u", "password": SECRET},
        headers=_headers(PM),
    )
    assert resp.status_code == 422
    assert resp.json() == {"detail": "Corpo inválido."}
    assert SECRET not in resp.text

    resp2 = client.patch(
        f"/api/projects/{project.id}/credentials/00000000-0000-0000-0000-000000000000",
        json={"password": SECRET, "campo_extra": 1},
        headers=_headers(PM),
    )
    assert resp2.status_code == 422
    assert SECRET not in resp2.text


def test_surplus_422_does_not_echo_body(db_session, client):
    project = _own_project(db_session)
    marker = "Texto-Sensivel-Excedente-42"
    resp = client.post(
        f"/api/projects/{project.id}/surplus-contracts",
        json={"duration_months": -5, "notes": marker, "password": SECRET},
        headers=_headers(PM),
    )
    assert resp.status_code == 422
    assert resp.json() == {"detail": "Corpo inválido."}
    assert marker not in resp.text
    assert SECRET not in resp.text


def test_pm_without_access_gets_404_on_every_credential_route(db_session, client):
    other = _other_project(db_session)
    headers = _headers(PM)
    base = f"/api/projects/{other.id}/credentials"
    fake = "00000000-0000-0000-0000-000000000001"
    assert client.get(base, headers=headers).status_code == 404
    assert (
        client.post(base, json={"portal": "outro", "username": "x", "password": SECRET}, headers=headers).status_code
        == 404
    )
    assert client.patch(f"{base}/{fake}", json={"username": "y"}, headers=headers).status_code == 404
    assert client.delete(f"{base}/{fake}", headers=headers).status_code == 404
    assert client.post(f"{base}/{fake}/reveal", headers=headers).status_code == 404
    assert db_session.query(ProjectPortalCredential).filter(ProjectPortalCredential.project_id == other.id).count() == 0


def test_logical_delete_wipes_password_and_hides_row(db_session, client):
    project = _own_project(db_session)
    cred_id = client.post(
        f"/api/projects/{project.id}/credentials",
        json={"portal": "dgeg_login_geral", "username": "del-user", "password": SECRET},
        headers=_headers(PM),
    ).json()["id"]
    assert client.delete(f"/api/projects/{project.id}/credentials/{cred_id}", headers=_headers(PM)).status_code == 204

    row = db_session.get(ProjectPortalCredential, cred_id)
    assert row is not None
    assert row.deleted_at is not None
    assert row.password_encrypted is None
    assert client.post(f"/api/projects/{project.id}/credentials/{cred_id}/reveal", headers=_headers(PM)).status_code == 404
    assert client.delete(f"/api/projects/{project.id}/credentials/{cred_id}", headers=_headers(PM)).status_code == 404


def test_chefe_can_manage_and_reveal(db_session, client):
    project = _own_project(db_session)
    cred_id = client.post(
        f"/api/projects/{project.id}/credentials",
        json={"portal": "mastervantagem", "username": "chefe-user", "password": SECRET},
        headers=_headers(CHEFE),
    ).json()["id"]
    resp = client.post(f"/api/projects/{project.id}/credentials/{cred_id}/reveal", headers=_headers(CHEFE))
    assert resp.status_code == 200
    assert resp.json()["password"] == SECRET
