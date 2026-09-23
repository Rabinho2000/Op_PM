"""Importação de notas iniciais: JSON válido, HTML com JSON embutido,
ficheiro inválido, duplicado, versão desconhecida, campos em falta,
projeto existente, conflito, resolução, auditoria, dados sensíveis nunca
importados. Ver app/services/imports_notes.py e app/api/routes_imports.py.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.models.imports import FieldImportBatch
from app.models.project import Project
from app.models.project_data import ProjectDataHistory, ProjectInstallationData

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _headers(email: str) -> dict:
    return {"X-Dev-User-Email": email}


def _json_fixture_bytes() -> bytes:
    return (FIXTURES_DIR / "synthetic_notas_iniciais.json").read_bytes()


def _html_fixture_bytes() -> bytes:
    return (FIXTURES_DIR / "synthetic_notas_iniciais.html").read_bytes()


def test_unauthenticated_request_is_rejected(api_client):
    resp = api_client.post(
        "/api/imports/notes/preview", files={"file": ("teste.json", _json_fixture_bytes(), "application/json")}
    )
    assert resp.status_code == 401


def test_pm_cannot_import_notes(api_client):
    resp = api_client.post(
        "/api/imports/notes/preview",
        files={"file": ("teste.json", _json_fixture_bytes(), "application/json")},
        headers=_headers("pm.um.sintetico@example.invalid"),
    )
    assert resp.status_code == 403


def test_preview_json_creates_new_project_candidate(api_client):
    resp = api_client.post(
        "/api/imports/notes/preview",
        files={"file": ("notas-teste.json", _json_fixture_bytes(), "application/json")},
        headers=_headers("comercial.sintetico@example.invalid"),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["form_version"] == "12"
    assert body["status"] == "pending_confirmation"
    assert len(body["records"]) == 1
    record = body["records"][0]
    assert record["is_new_project"] is True
    assert record["mapped_fields"]["project"]["client_name"] == "Cliente Sintético das Notas Iniciais"
    assert record["conflicts"] == []


def test_preview_html_with_embedded_json_works(api_client):
    resp = api_client.post(
        "/api/imports/notes/preview",
        files={"file": ("notas-iniciais-v11.html", _html_fixture_bytes(), "text/html")},
        headers=_headers("comercial.sintetico@example.invalid"),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # Nome do ficheiro diz "v11", mas o conteúdo interno é v12 — a versão
    # usada é sempre a do payload, nunca a do nome do ficheiro.
    assert body["form_version"] == "12"
    assert body["records"][0]["mapped_fields"]["project"]["client_name"] == "Cliente Sintético do HTML de Notas"


def test_original_document_is_preserved_and_retrievable(db_session, api_client):
    """O documento original submetido (não só o JSON já extraído) tem de
    ficar guardado e recuperável tal como foi carregado — auditoria exige
    conseguir voltar à fonte, não só ao resultado normalizado."""
    headers = _headers("comercial.sintetico@example.invalid")
    html_bytes = _html_fixture_bytes()
    resp_preview = api_client.post(
        "/api/imports/notes/preview",
        files={"file": ("notas-iniciais-v11.html", html_bytes, "text/html")},
        headers=headers,
    )
    assert resp_preview.status_code == 201, resp_preview.text
    batch_id = resp_preview.json()["id"]

    batch = db_session.get(FieldImportBatch, batch_id)
    assert batch.raw_document_text == html_bytes.decode("utf-8")

    resp_document = api_client.get(f"/api/imports/{batch_id}/document", headers=headers)
    assert resp_document.status_code == 200, resp_document.text
    document = resp_document.json()
    assert document["filename"] == "notas-iniciais-v11.html"
    assert document["content"] == html_bytes.decode("utf-8")
    assert "<script" in document["content"] and "notas-iniciais-data" in document["content"]


def test_html_without_embedded_script_is_rejected(api_client):
    html = b"<html><body><h1>Sem dados estruturados</h1></body></html>"
    resp = api_client.post(
        "/api/imports/notes/preview",
        files={"file": ("vazio.html", html, "text/html")},
        headers=_headers("comercial.sintetico@example.invalid"),
    )
    assert resp.status_code == 400
    assert "notas-iniciais-data" in resp.json()["detail"]


def test_invalid_json_is_rejected(api_client):
    resp = api_client.post(
        "/api/imports/notes/preview",
        files={"file": ("invalido.json", b"{ isto nao e json valido ", "application/json")},
        headers=_headers("comercial.sintetico@example.invalid"),
    )
    assert resp.status_code == 400


def test_unsupported_extension_is_rejected(api_client):
    resp = api_client.post(
        "/api/imports/notes/preview",
        files={"file": ("dados.txt", b"qualquer coisa", "text/plain")},
        headers=_headers("comercial.sintetico@example.invalid"),
    )
    assert resp.status_code == 400


def test_unknown_form_version_is_rejected(api_client):
    payload = json.loads(_json_fixture_bytes())
    payload["formVersion"] = "7"
    resp = api_client.post(
        "/api/imports/notes/preview",
        files={"file": ("notas.json", json.dumps(payload).encode("utf-8"), "application/json")},
        headers=_headers("comercial.sintetico@example.invalid"),
    )
    assert resp.status_code == 400
    assert "não é compatível" in resp.json()["detail"]


def test_missing_minimum_fields_is_rejected(api_client):
    payload = {"formVersion": "12", "cliente": "Só o nome, sem mais nada"}
    resp = api_client.post(
        "/api/imports/notes/preview",
        files={"file": ("notas.json", json.dumps(payload).encode("utf-8"), "application/json")},
        headers=_headers("comercial.sintetico@example.invalid"),
    )
    assert resp.status_code == 400


def test_duplicate_file_preview_is_idempotent_then_rejected_after_applied(db_session, api_client):
    headers = _headers("comercial.sintetico@example.invalid")
    content = _json_fixture_bytes()

    resp1 = api_client.post(
        "/api/imports/notes/preview", files={"file": ("notas.json", content, "application/json")}, headers=headers
    )
    assert resp1.status_code == 201
    batch_id = resp1.json()["id"]

    # Reimportar o MESMO ficheiro (mesmo hash) antes de aplicar devolve o
    # lote já existente — idempotente, nunca duplica o registo de staging.
    resp2 = api_client.post(
        "/api/imports/notes/preview", files={"file": ("notas-outra-vez.json", content, "application/json")}, headers=headers
    )
    assert resp2.status_code == 201
    assert resp2.json()["id"] == batch_id

    apply_resp = api_client.post(
        "/api/imports/notes/apply",
        json={"batch_id": batch_id, "confirm": True},
        headers=headers,
    )
    assert apply_resp.status_code == 200, apply_resp.text

    resp3 = api_client.post(
        "/api/imports/notes/preview", files={"file": ("notas-terceira.json", content, "application/json")}, headers=headers
    )
    assert resp3.status_code == 409
    assert "já foi importado" in resp3.json()["detail"]


def test_apply_creates_project_and_installation_data(db_session, api_client):
    headers = _headers("comercial.sintetico@example.invalid")
    resp_preview = api_client.post(
        "/api/imports/notes/preview",
        files={"file": ("notas-apply.json", _json_fixture_bytes(), "application/json")},
        headers=headers,
    )
    batch_id = resp_preview.json()["id"]

    resp_apply = api_client.post(
        "/api/imports/notes/apply", json={"batch_id": batch_id, "confirm": True}, headers=headers
    )
    assert resp_apply.status_code == 200, resp_apply.text
    result = resp_apply.json()
    assert result["created_new_project"] is True

    project = db_session.get(Project, result["project_id"])
    assert project is not None
    assert project.client_email == "cliente.notas.sintetico@example.invalid"

    installation = (
        db_session.query(ProjectInstallationData)
        .filter(ProjectInstallationData.project_id == project.id)
        .one()
    )
    assert installation.panel_count == 18
    assert installation.contact_phone == "912000111"

    batch = db_session.get(FieldImportBatch, batch_id)
    assert batch.status == "applied"
    assert batch.applied_by_person_id is not None


def test_apply_requires_confirm_flag(db_session, api_client):
    headers = _headers("comercial.sintetico@example.invalid")
    resp_preview = api_client.post(
        "/api/imports/notes/preview",
        files={"file": ("notas-confirm.json", _json_fixture_bytes(), "application/json")},
        headers=headers,
    )
    batch_id = resp_preview.json()["id"]
    resp_apply = api_client.post("/api/imports/notes/apply", json={"batch_id": batch_id}, headers=headers)
    assert resp_apply.status_code == 400


def test_conflict_detected_and_resolution_required_before_apply(db_session, api_client):
    headers = _headers("comercial.sintetico@example.invalid")

    existing = Project(
        name="Projeto Sintético Já Existente para Conflito",
        client_email="cliente.notas.sintetico@example.invalid",
        power_kwp=1.0,
    )
    db_session.add(existing)
    db_session.commit()

    resp_preview = api_client.post(
        "/api/imports/notes/preview",
        files={"file": ("notas-conflito.json", _json_fixture_bytes(), "application/json")},
        headers=headers,
    )
    assert resp_preview.status_code == 201
    body = resp_preview.json()
    record = body["records"][0]
    assert record["is_new_project"] is False
    assert record["target_project_id"] == str(existing.id)
    assert len(record["conflicts"]) > 0
    power_conflict = next(c for c in record["conflicts"] if c["field_name"] == "power_kwp")
    assert power_conflict["resolution"] == "pending"

    batch_id = body["id"]
    resp_apply_blocked = api_client.post(
        "/api/imports/notes/apply", json={"batch_id": batch_id, "confirm": True}, headers=headers
    )
    assert resp_apply_blocked.status_code == 400
    assert "conflito" in resp_apply_blocked.json()["detail"].lower()

    for conflict in record["conflicts"]:
        resp_resolve = api_client.post(
            f"/api/imports/conflicts/{conflict['id']}/resolve",
            json={"resolution": "use_new"},
            headers=headers,
        )
        assert resp_resolve.status_code == 200
        assert resp_resolve.json()["resolved_by_person_id"] is not None

    resp_apply_ok = api_client.post(
        "/api/imports/notes/apply", json={"batch_id": batch_id, "confirm": True}, headers=headers
    )
    assert resp_apply_ok.status_code == 200, resp_apply_ok.text
    assert resp_apply_ok.json()["project_id"] == str(existing.id)
    assert resp_apply_ok.json()["created_new_project"] is False

    db_session.refresh(existing)
    assert existing.power_kwp == 8.28

    history = (
        db_session.query(ProjectDataHistory)
        .filter(ProjectDataHistory.project_id == existing.id)
        .filter(ProjectDataHistory.source == "import_notes")
        .all()
    )
    assert len(history) > 0


def test_keep_old_resolution_preserves_existing_value(db_session, api_client):
    headers = _headers("comercial.sintetico@example.invalid")
    existing = Project(
        name="Projeto Sintético Guardar Valor Antigo",
        client_email="cliente.notas.sintetico@example.invalid",
        power_kwp=1.0,
    )
    db_session.add(existing)
    db_session.commit()

    resp_preview = api_client.post(
        "/api/imports/notes/preview",
        files={"file": ("notas-keep-old.json", _json_fixture_bytes(), "application/json")},
        headers=headers,
    )
    body = resp_preview.json()
    record = body["records"][0]
    for conflict in record["conflicts"]:
        api_client.post(
            f"/api/imports/conflicts/{conflict['id']}/resolve",
            json={"resolution": "keep_old"},
            headers=headers,
        )

    resp_apply = api_client.post(
        "/api/imports/notes/apply", json={"batch_id": body["id"], "confirm": True}, headers=headers
    )
    assert resp_apply.status_code == 200, resp_apply.text

    db_session.refresh(existing)
    assert existing.power_kwp == 1.0  # valor antigo preservado


def test_sensitive_credential_fields_are_never_imported(db_session, api_client):
    """Mesmo que o payload contenha campos de credenciais (nunca deviam
    existir na origem, mas defendemo-nos de qualquer forma), o mapeamento
    nunca os traduz para nenhum campo modelado."""
    headers = _headers("comercial.sintetico@example.invalid")
    payload = json.loads(_json_fixture_bytes())
    payload["pin"] = "1234"
    payload["puk"] = "87654321"
    payload["password"] = "segredo-sintetico"
    payload["portalLogin"] = "utilizador-sintetico"

    resp_preview = api_client.post(
        "/api/imports/notes/preview",
        files={"file": ("notas-credenciais.json", json.dumps(payload).encode("utf-8"), "application/json")},
        headers=headers,
    )
    assert resp_preview.status_code == 201
    mapped = resp_preview.json()["records"][0]["mapped_fields"]
    serialized = json.dumps(mapped)
    for forbidden in ("1234", "87654321", "segredo-sintetico", "utilizador-sintetico"):
        assert forbidden not in serialized
