"""`secret_box` (Fernet): chave mal formada, chave errada e o comportamento HTTP
das rotas de credenciais de portais e de cartões SIM perante cada falha.

Contrato verificado (ver app/security/secret_box.py e as rotas):
- sem chave, ficheiro ilegível ou chave mal formada -> `SecretBoxUnavailable`
  -> 503 (falha fechada, nada é gravado nem devolvido);
- dados cifrados com outra chave -> `SecretBoxDecryptError` -> 500 com mensagem
  fixa que não inclui o valor cifrado nem o claro.

Chaves Fernet geradas em tmp_path — nunca ficheiros de chave reais.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.config import Settings
from app.models.project import Project
from app.security.secret_box import (
    SecretBoxDecryptError,
    SecretBoxUnavailable,
    decrypt_secret,
    encrypt_secret,
)

PM = "pm.um.sintetico@example.invalid"
SECRET = "Pw-Segredo-box-unico-5521"


def _write_key(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def _settings(key_file: Path | str) -> Settings:
    return Settings(app_env="test", auth_enabled=False, oppm_secrets_key_file=str(key_file))


def _good_key_file(tmp_path: Path, name: str = "good.key") -> Path:
    return _write_key(tmp_path / name, Fernet.generate_key().decode("ascii") + "\n")


# --- unidade ---------------------------------------------------------------


def test_roundtrip_with_valid_key(tmp_path):
    settings = _settings(_good_key_file(tmp_path))
    token = encrypt_secret(settings, SECRET)
    assert SECRET not in token
    assert decrypt_secret(settings, token) == SECRET


@pytest.mark.parametrize(
    "content",
    [
        "isto-nao-e-uma-chave-fernet",  # base64 inválido / comprimento errado
        "",  # ficheiro vazio
        "a" * 43,  # comprimento certo mas sem o padding/alfabeto de uma chave Fernet de 32 bytes
        Fernet.generate_key().decode("ascii")[:-4],  # chave truncada
    ],
    ids=["texto-livre", "vazio", "comprimento-quase-certo", "truncada"],
)
def test_malformed_key_raises_unavailable(tmp_path, content):
    settings = _settings(_write_key(tmp_path / "bad.key", content))
    with pytest.raises(SecretBoxUnavailable):
        encrypt_secret(settings, SECRET)
    with pytest.raises(SecretBoxUnavailable):
        decrypt_secret(settings, "gAAAAA-qualquer-token")


def test_unavailable_message_never_includes_key_material(tmp_path):
    bad = "chave-mal-formada-que-nao-pode-vazar"
    settings = _settings(_write_key(tmp_path / "bad.key", bad))
    with pytest.raises(SecretBoxUnavailable) as exc_info:
        encrypt_secret(settings, SECRET)
    assert bad not in str(exc_info.value)


def test_missing_or_unreadable_key_file_raises_unavailable(tmp_path):
    for value in ("", "   ", tmp_path / "inexistente.key", tmp_path):  # a última é um diretório
        with pytest.raises(SecretBoxUnavailable):
            encrypt_secret(_settings(value), SECRET)


def test_data_encrypted_with_another_key_raises_decrypt_error(tmp_path):
    key_a = _settings(_good_key_file(tmp_path, "a.key"))
    key_b = _settings(_good_key_file(tmp_path, "b.key"))
    token = encrypt_secret(key_a, SECRET)
    with pytest.raises(SecretBoxDecryptError) as exc_info:
        decrypt_secret(key_b, token)
    # Mensagem fixa: nem o valor cifrado nem o claro.
    assert SECRET not in str(exc_info.value) and token not in str(exc_info.value)


def test_corrupted_ciphertext_raises_decrypt_error(tmp_path):
    settings = _settings(_good_key_file(tmp_path))
    token = encrypt_secret(settings, SECRET)
    corrupted = token[:-6] + ("AAAAAA" if not token.endswith("AAAAAA") else "BBBBBB")
    with pytest.raises(SecretBoxDecryptError):
        decrypt_secret(settings, corrupted)


def test_rotated_key_cannot_read_old_data_until_old_key_is_restored(tmp_path):
    """Sem rotação suportada: trocar a chave torna o histórico ilegível (erro
    tratado, não corrupção) e repor a chave antiga volta a decifrá-lo."""
    key_path = tmp_path / "rot.key"
    _write_key(key_path, Fernet.generate_key().decode("ascii"))
    old_key_text = key_path.read_text(encoding="utf-8")
    token = encrypt_secret(_settings(key_path), SECRET)

    _write_key(key_path, Fernet.generate_key().decode("ascii"))
    with pytest.raises(SecretBoxDecryptError):
        decrypt_secret(_settings(key_path), token)

    _write_key(key_path, old_key_text)
    assert decrypt_secret(_settings(key_path), token) == SECRET


# --- HTTP: credenciais de portais -----------------------------------------------


def _project(db) -> Project:
    return db.query(Project).filter(Project.name == "Instalação Sintética de Demonstração").one()


def _h() -> dict:
    return {"X-Dev-User-Email": PM}


def test_credentials_reveal_with_wrong_key_is_500_with_fixed_message(db_session, make_api_client, tmp_path):
    project = _project(db_session)
    client_a = make_api_client(_settings(_good_key_file(tmp_path, "a.key")))
    created = client_a.post(
        f"/api/projects/{project.id}/credentials",
        json={"portal": "dgeg_login_geral", "username": "box-user", "password": SECRET},
        headers=_h(),
    )
    assert created.status_code in (200, 201), created.text
    cred_id = created.json()["id"]

    client_b = make_api_client(_settings(_good_key_file(tmp_path, "b.key")))
    resp = client_b.post(f"/api/projects/{project.id}/credentials/{cred_id}/reveal", headers=_h())
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Não foi possível decifrar a credencial."
    assert SECRET not in resp.text


def test_credentials_with_malformed_key_fail_closed_503(db_session, make_api_client, tmp_path):
    project = _project(db_session)
    client = make_api_client(_settings(_write_key(tmp_path / "bad.key", "chave-mal-formada")))
    resp = client.post(
        f"/api/projects/{project.id}/credentials",
        json={"portal": "dgeg_login_geral", "username": "box-user", "password": SECRET},
        headers=_h(),
    )
    assert resp.status_code == 503
    assert SECRET not in resp.text and "chave-mal-formada" not in resp.text


# --- HTTP: cartões SIM -------------------------------------------------------------


def _sim_body(**extra) -> dict:
    body = {"purpose": "comunicacoes", "operator": "Operador Sintético", "phone_number": "910000077", "iccid": "ICCID-BOX-1"}
    body.update(extra)
    return body


def test_sim_reveal_with_wrong_key_is_500_with_fixed_message(db_session, make_api_client, tmp_path):
    project = _project(db_session)
    client_a = make_api_client(_settings(_good_key_file(tmp_path, "a.key")))
    created = client_a.post(
        f"/api/projects/{project.id}/sim-cards", json=_sim_body(pin="1234-box", puk="99887766"), headers=_h()
    )
    assert created.status_code == 201, created.text
    sim_id = created.json()["id"]

    client_b = make_api_client(_settings(_good_key_file(tmp_path, "b.key")))
    resp = client_b.post(f"/api/projects/{project.id}/sim-cards/{sim_id}/reveal", headers=_h())
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Não foi possível decifrar a credencial."
    assert "1234-box" not in resp.text and "99887766" not in resp.text


def test_sim_with_malformed_key_fail_closed_503(db_session, make_api_client, tmp_path):
    project = _project(db_session)
    client = make_api_client(_settings(_write_key(tmp_path / "bad.key", "chave-mal-formada")))
    resp = client.post(f"/api/projects/{project.id}/sim-cards", json=_sim_body(pin="1234-box"), headers=_h())
    assert resp.status_code == 503
    assert "1234-box" not in resp.text
