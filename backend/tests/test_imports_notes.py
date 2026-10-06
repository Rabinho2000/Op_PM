"""Importação de notas iniciais: JSON válido, HTML com JSON embutido,
ficheiro inválido, duplicado, versão desconhecida, campos em falta,
projeto existente, conflito, resolução, auditoria, dados sensíveis nunca
importados. Ver app/services/imports_notes.py e app/api/routes_imports.py.
"""
from __future__ import annotations

import asyncio
import json
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace

import app.services.imports_notes as imports_notes_service
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models.imports import (
    BATCH_STATUS_APPLIED,
    BATCH_STATUS_PENDING_CONFIRMATION,
    FieldImportBatch,
    FieldImportConflict,
    FieldImportRecord,
)
from app.models.project import Project
from app.models.project_data import ProjectDataHistory, ProjectInstallationData
from app.services.imports_notes import (
    DATA_URL_PLACEHOLDER,
    DOCUMENT_OMITTED_PLACEHOLDER,
    MAX_UPLOAD_BYTES,
    NotesImportError,
    _is_sensitive_label,
    _lock_pending_batch,
    _redact_text,
    _sanitize_payload,
    apply_notes_import,
    extract_payload,
    map_payload_to_fields,
    preview_notes_import,
    resolve_conflict,
    validate_payload,
)

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


def test_preview_rejects_filename_over_512_before_hashing(api_client, monkeypatch):
    monkeypatch.setattr(
        imports_notes_service,
        "compute_file_hash",
        lambda content: pytest.fail("o hash não deve ser calculado para um nome inválido"),
    )
    filename = f"{'a' * 513}.json"

    resp = api_client.post(
        "/api/imports/notes/preview",
        files={"file": (filename, _json_fixture_bytes(), "application/json")},
        headers=_headers("comercial.sintetico@example.invalid"),
    )

    assert resp.status_code == 400
    assert "512" in resp.json()["detail"]


@pytest.mark.parametrize("control", ["\x00", "\n", "\r", "\t", "\x7f", "\u200b", "\u202e"])
def test_preview_rejects_control_characters_in_filename_before_hashing(db_session, monkeypatch, control):
    monkeypatch.setattr(
        imports_notes_service,
        "compute_file_hash",
        lambda content: pytest.fail("o hash não deve ser calculado para um nome inválido"),
    )

    with pytest.raises(NotesImportError, match="caracteres de controlo"):
        preview_notes_import(
            db_session,
            filename=f"notas{control}.json",
            content=_json_fixture_bytes(),
            uploaded_by_person_id=None,
        )


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
    """A cópia textual sanitizada do documento submetido (não só o JSON já
    extraído) fica guardada para auditoria, sem data URLs ou credenciais."""
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
    stored_document = json.loads(batch.raw_document_text)
    assert stored_document == json.loads(batch.raw_payload_json)
    assert "<!doctype" not in batch.raw_document_text.lower()
    assert "<script" not in batch.raw_document_text.lower()
    assert "notas-iniciais-data" not in batch.raw_document_text

    resp_document = api_client.get(f"/api/imports/{batch_id}/document", headers=headers)
    assert resp_document.status_code == 200, resp_document.text
    document = resp_document.json()
    assert document["filename"] == "notas-iniciais-v11.html"
    assert document["content"] == batch.raw_document_text
    assert "<script" not in document["content"].lower()
    assert "<!doctype" not in document["content"].lower()


def test_html_without_embedded_script_is_rejected(api_client):
    html = b"<html><body><h1>Sem dados estruturados</h1></body></html>"
    resp = api_client.post(
        "/api/imports/notes/preview",
        files={"file": ("vazio.html", html, "text/html")},
        headers=_headers("comercial.sintetico@example.invalid"),
    )
    assert resp.status_code == 400
    assert "notas-iniciais-data" in resp.json()["detail"]


def test_legacy_html_export_is_detected_by_structured_fields_not_client_name():
    html = b"""
    <html><head><title>Exportacao antiga</title></head><body>
      <form>
        <label>Cliente</label><input name="cliente" value="Cliente Sintetico Antigo" />
        <input name="email" value="antigo@example.invalid" />
        <textarea name="morada">Rua Sintetica 1</textarea>
      </form>
    </body></html>
    """
    payload = extract_payload(filename="export-v99.html", content=html)
    assert payload["formVersion"] == "10"
    assert payload["cliente"] == "Cliente Sintetico Antigo"
    assert payload["email"] == "antigo@example.invalid"


def test_legacy_structural_dl_export_is_v10_and_preserves_unknown_pairs():
    html = (FIXTURES_DIR / "synthetic_notas_iniciais_v10_legacy.html").read_bytes()
    payload = extract_payload(filename="qualquer-nome.html", content=html)
    assert payload["formVersion"] == "10"
    assert payload["cliente"] == "Cliente Sintético Legado"
    assert payload["email"] == "legado@example.invalid"
    assert payload["telefone"] == "+351 910 000 000"
    assert payload["potenciaKwp"] == 12.5
    assert payload["paineis"] == {"descricao": "24 x 500 Wp"}
    assert payload["camposDesconhecidos"] == [
        {"label": "campo adicional", "value": "Valor adicional sintético"}
    ]


def test_legacy_v12_structural_sections_extract_all_supported_fields_without_data_urls():
    html = (FIXTURES_DIR / "synthetic_notas_iniciais_v12_structural.html").read_bytes()
    payload = extract_payload(filename="export-sem-marcador-de-cliente.html", content=html)

    assert payload["formVersion"] == "12"
    assert payload["cliente"] == "Cliente Sintético Estrutural V12"
    assert payload["contacto"] == "Contacto Sintético V12"
    assert payload["nif"] == "501234567"
    assert payload["distrito"] == "Porto"
    assert payload["concelho"] == "Matosinhos"
    assert payload["funcao"] == "Outra — Responsável técnico sintético"
    assert payload["telefone"] == "+351 910 111 222"
    assert payload["email"] == "v12.sintetico@example.invalid"
    assert payload["lat"] == 41.12345
    assert payload["lon"] == -8.54321
    assert payload["paineis"] == {"quantidade": 24, "potenciaWp": 500.0}
    assert payload["potenciaKwpCalculada"] == 12.0
    assert payload["potenciaKwpDeclarada"] == 12.5
    assert payload["potenciaKwp"] == 12.5
    assert payload["inversores"] == [
        {"modelo": "Inversor Sintético A 6 kW", "quantidade": 1},
        {"modelo": "Inversor Sintético B 6 kW", "quantidade": 1},
    ]
    assert payload["baterias"] == "Bateria Sintética 10 kWh"
    assert payload["backup"] is True
    assert payload["carregadoresVe"] == "2 carregadores VE sintéticos"
    assert payload["tipoInstalacao"] == "Autoconsumo com armazenamento"
    assert payload["controlador"] == "Controlador Sintético V12"
    assert payload["outroEquipamento"] == "Carregador VE sintético e bomba de calor"
    assert payload["injecao"] == "Autoconsumo com injeção na rede"
    assert payload["om"] == "A CONFIRMAR"
    assert payload["rgpd"] is True
    assert payload["upacExistente"] == "UPAC-SINT-001"
    assert payload["urgencia"] == "Urgente"
    assert payload["observacoes"] == "Observação estrutural sintética."
    assert payload["divergenciasHelioscope"] == "Diferença sintética de 0,2 kWp."
    assert payload["pressupostosProposta"] == "Pressupostos sintéticos de teste."
    assert payload["anexos"] == [
        {"nome": "planta-sintetica.pdf", "tipo": "application/pdf", "tamanho": 12345}
    ]
    assert payload["camposDesconhecidos"] == [
        {"label": "Campo futuro do formulário", "value": "Valor desconhecido sintético"}
    ]
    assert "data:application/pdf" not in json.dumps(payload, ensure_ascii=False)


@pytest.mark.parametrize(("upac_value", "expected"), [("Sim", True), ("Não", False)])
def test_structural_v12_upac_question_uses_documented_boolean_contract_through_apply(
    db_session, api_client, upac_value, expected
):
    content = (FIXTURES_DIR / "synthetic_notas_iniciais_v12_upac_boolean.html").read_bytes()
    if upac_value == "Não":
        content = content.replace(
            b"<dt>J\xc3\xa1 existe UPAC no local?</dt><dd>Sim</dd>",
            b"<dt>J\xc3\xa1 existe UPAC no local?</dt><dd>N\xc3\xa3o</dd>",
        )

    payload = extract_payload(filename="realistic-v12-structural.html", content=content)

    assert payload["upacExistente"] is expected
    assert payload["backup"] is False
    assert payload["rgpd"] is True
    assert payload["om"] == "Sem contrato de OeM sintético"
    assert validate_payload(payload) == "12"

    mapped = map_payload_to_fields(payload)
    assert "upac_number" not in mapped["licensing"]
    assert mapped["installation"]["has_backup"] is False

    headers = _headers("comercial.sintetico@example.invalid")
    preview = api_client.post(
        "/api/imports/notes/preview",
        files={"file": (f"upac-{upac_value}.html", content, "text/html")},
        headers=headers,
    )
    assert preview.status_code == 201, preview.text
    body = preview.json()
    record = body["records"][0]
    assert record["is_new_project"] is True
    assert record["candidate_projects"] == []
    assert record["conflicts"] == []

    applied = api_client.post(
        "/api/imports/notes/apply",
        json={"batch_id": body["id"], "confirm": True},
        headers=headers,
    )
    assert applied.status_code == 200, applied.text
    result = applied.json()
    assert result["created_new_project"] is True

    project = db_session.get(Project, result["project_id"])
    assert project is not None
    installation = (
        db_session.query(ProjectInstallationData)
        .filter(ProjectInstallationData.project_id == project.id)
        .one()
    )
    assert installation.has_backup is False
    assert installation.om_notes == "Sem contrato de OeM sintético"
    assert db_session.get(FieldImportBatch, body["id"]).status == BATCH_STATUS_APPLIED


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("upacExistente", True),
        ("upacExistente", "UPAC-SINT-001"),
        ("backup", True),
        ("backup", "Sim"),
        ("rgpd", False),
        ("rgpd", "Não"),
    ],
)
def test_documented_boolean_or_text_fields_keep_their_explicit_contract(field, value):
    payload = json.loads(_json_fixture_bytes())
    payload[field] = value

    assert validate_payload(payload) == "12"


def test_om_remains_text_only_when_boolean_or_text_fields_are_allowed():
    payload = json.loads(_json_fixture_bytes())
    payload["om"] = True

    with pytest.raises(NotesImportError, match="Campo 'om' inválido: esperado texto"):
        validate_payload(payload)


def test_long_free_form_urgency_is_preserved_in_sanitized_notes(db_session, api_client):
    payload = json.loads(_json_fixture_bytes())
    urgency = ("Urgencia sintetica livre com contexto operacional completo. " * 20)[:463]
    payload["urgencia"] = urgency
    payload["observacoes"] = "<p>Observacao sintetica</p><img src=\"data:image/png;base64,PRIVATE_SYNTHETIC_DATA\">"

    assert len(urgency) == 463
    headers = _headers("comercial.sintetico@example.invalid")
    preview = api_client.post(
        "/api/imports/notes/preview",
        files={"file": ("urgencia-livre-sintetica.json", json.dumps(payload).encode("utf-8"), "application/json")},
        headers=headers,
    )

    assert preview.status_code == 201, preview.text
    body = preview.json()
    notes = body["records"][0]["mapped_fields"]["installation"]["notes"]
    assert f"Urgência: {urgency}" in notes
    assert "<p>" not in notes
    assert "<img" not in notes
    assert "data:" not in notes.lower()

    applied = api_client.post(
        "/api/imports/notes/apply",
        json={"batch_id": body["id"], "confirm": True},
        headers=headers,
    )
    assert applied.status_code == 200, applied.text
    project = db_session.get(Project, applied.json()["project_id"])
    installation = (
        db_session.query(ProjectInstallationData)
        .filter(ProjectInstallationData.project_id == project.id)
        .one()
    )
    assert f"Urgência: {urgency}" in installation.notes
    assert len(installation.notes) > len(urgency)
    assert "data:" not in installation.notes.lower()


def test_legacy_v12_structural_payload_maps_to_existing_schema_and_safe_notes():
    html = (FIXTURES_DIR / "synthetic_notas_iniciais_v12_structural.html").read_bytes()
    mapped = map_payload_to_fields(extract_payload(filename="export.html", content=html))

    assert mapped["project"]["client_name"] == "Cliente Sintético Estrutural V12"
    assert mapped["project"]["client_contact"] == "Contacto Sintético V12"
    assert mapped["installation"]["client_nif"] == "501234567"
    assert mapped["installation"]["district"] == "Porto"
    assert mapped["installation"]["municipality"] == "Matosinhos"
    assert mapped["project"]["role"] == "Outra — Responsável técnico sintético"
    assert mapped["project"]["lat"] == 41.12345
    assert mapped["project"]["lon"] == -8.54321
    assert mapped["project"]["power_kwp"] == 12.5
    assert mapped["project"]["power_raw"] == "12,5 kWp"
    assert mapped["project"]["equipment_notes"] == "Carregador VE sintético e bomba de calor"
    assert mapped["project"]["injection_notes"] == "Autoconsumo com injeção na rede"
    assert mapped["project"]["om_notes"] == "A CONFIRMAR"
    assert mapped["project"]["commercial_assumptions"] == "Pressupostos sintéticos de teste."
    assert mapped["installation"]["contact_person_name"] == "Contacto Sintético V12"
    assert mapped["installation"]["contact_person_role"] == "Outra — Responsável técnico sintético"
    assert mapped["installation"]["contact_phone"] == "351910111222"
    assert mapped["installation"]["panel_count"] == 24
    assert mapped["installation"]["panel_power_wp"] == 500.0
    assert json.loads(mapped["installation"]["inverters"]) == [
        {"modelo": "Inversor Sintético A 6 kW", "quantidade": 1},
        {"modelo": "Inversor Sintético B 6 kW", "quantidade": 1},
    ]
    assert mapped["installation"]["has_backup"] is True
    assert mapped["installation"]["ev_chargers"] == "2 carregadores VE sintéticos"
    assert mapped["installation"]["installation_type"] == "Autoconsumo com armazenamento"
    assert mapped["installation"]["injection_type"] == "Autoconsumo com injeção na rede"
    assert mapped["installation"]["om_notes"] == "A CONFIRMAR"
    assert mapped["licensing"]["upac_number"] == "UPAC-SINT-001"
    assert "RGPD: True" in mapped["installation"]["notes"]
    assert "Controlador: Controlador Sintético V12" in mapped["installation"]["notes"]
    assert "planta-sintetica.pdf" in mapped["installation"]["notes"]
    assert "Campo futuro do formulário" in mapped["installation"]["notes"]
    assert "data:application/pdf" not in mapped["installation"]["notes"]


def test_legacy_structural_dl_export_can_be_previewed(api_client):
    resp = api_client.post(
        "/api/imports/notes/preview",
        files={
            "file": (
                "export-v10.html",
                (FIXTURES_DIR / "synthetic_notas_iniciais_v10_legacy.html").read_bytes(),
                "text/html",
            )
        },
        headers=_headers("comercial.sintetico@example.invalid"),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["form_version"] == "10"
    assert body["records"][0]["mapped_fields"]["project"]["client_name"] == "Cliente Sintético Legado"
    assert body["records"][0]["mapped_fields"]["installation"]["contact_phone"] == "351910000000"
    assert "Valor adicional sintético" in body["records"][0]["mapped_fields"]["installation"]["notes"]


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


def test_staging_and_document_redact_nested_data_urls_and_credentials(db_session, api_client):
    payload = json.loads(_json_fixture_bytes())
    payload["cliente"] = "Cliente Sintético Sanitização"
    payload["nested"] = {
        "thumbnail": "data:image/png;base64,AAAASECRET",
        "apiToken": "nested-token-sintetico",
    }
    payload["password"] = "password-sintetico"
    payload["camposDesconhecidos"] = [
        {"label": "Portal password", "value": "legacy-secret-sintetico"},
        {"label": "Campo seguro", "value": "valor seguro sintético"},
    ]
    payload["observacoes"] = "Nota pública com password-sintetico e legacy-secret-sintetico."
    content = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    response = api_client.post(
        "/api/imports/notes/preview",
        files={"file": ("notas-sanitizacao.json", content, "application/json")},
        headers=_headers("comercial.sintetico@example.invalid"),
    )
    assert response.status_code == 201, response.text
    batch_id = response.json()["id"]
    batch = db_session.get(FieldImportBatch, batch_id)
    mapped = response.json()["records"][0]["mapped_fields"]
    document = api_client.get(
        f"/api/imports/{batch_id}/document", headers=_headers("comercial.sintetico@example.invalid")
    )

    persisted_and_exposed = "\n".join(
        [batch.raw_payload_json, batch.raw_document_text, json.dumps(mapped, ensure_ascii=False), document.text]
    )
    for forbidden in (
        "data:image/png;base64,AAAASECRET",
        "nested-token-sintetico",
        "password-sintetico",
        "legacy-secret-sintetico",
        "apiToken",
        "password",
    ):
        assert forbidden.lower() not in persisted_and_exposed.lower()
    assert "[valor sensível omitido]" in persisted_and_exposed
    assert "valor seguro sintético" in persisted_and_exposed
    assert "data:" not in persisted_and_exposed.lower()
    assert "legacy-secret-sintetico" not in batch.raw_document_text
    assert "Campo seguro" in batch.raw_payload_json


def test_html_staging_redacts_data_urls_and_credentials_before_persistence(db_session, api_client):
    payload = json.loads(_json_fixture_bytes())
    payload["cliente"] = "Cliente Sintético HTML Sanitização"
    payload["preview"] = "data:,HTMLSECRET"
    payload["portalLogin"] = "login-html-sintetico"
    payload["password"] = "password-html-sintetico"
    html = (
        '<html><body><p>Estrutura pública sintética</p>'
        '<input name="password" value="outside-only-314159">'
        '<script type="application/json" id="notas-iniciais-data">'
        + json.dumps(payload, ensure_ascii=False)
        + "</script></body></html>"
    ).encode("utf-8")

    response = api_client.post(
        "/api/imports/notes/preview",
        files={"file": ("notas-html-sanitizacao.html", html, "text/html")},
        headers=_headers("comercial.sintetico@example.invalid"),
    )
    assert response.status_code == 201, response.text
    batch = db_session.get(FieldImportBatch, response.json()["id"])
    document = api_client.get(
        f"/api/imports/{response.json()['id']}/document",
        headers=_headers("comercial.sintetico@example.invalid"),
    )
    persisted = "\n".join([batch.raw_payload_json, batch.raw_document_text, document.text])
    for forbidden in (
        "data:,HTMLSECRET",
        "HTMLSECRET",
        "login-html-sintetico",
        "password-html-sintetico",
        "outside-only-314159",
        "password",
    ):
        assert forbidden.lower() not in persisted.lower()
    assert "Estrutura pública sintética" not in batch.raw_document_text
    assert json.loads(batch.raw_document_text)["cliente"] == "Cliente Sintético HTML Sanitização"
    assert "data:" not in persisted.lower()


def test_parser_decodes_unicode_and_html_entities_before_redacting_nested_sensitive_data(db_session, api_client):
    payload = json.loads(_json_fixture_bytes())
    payload["safeMarkup"] = "<b>conteúdo público</b>"
    payload["preview"] = "data&#x3a;image/svg+xml&#x3b;base64&#x2c;PHN2Zy1zZWNyZXQ="
    payload["nested"] = {
        "label": "&#x70;assword",
        "value": "entity-secret-sintetico",
        "markup": "<img src=x onerror=alert(1)>",
    }
    payload["password"] = "unicode-secret-sintetico"
    # Keep the JSON escape in the submitted bytes; json.loads must decode the
    # label before recursive sanitization sees it.
    encoded = json.dumps(payload, ensure_ascii=False).replace('"password"', '"\\u0070assword"')
    response = api_client.post(
        "/api/imports/notes/preview",
        files={"file": ("notas-escapes.json", encoded.encode("utf-8"), "application/json")},
        headers=_headers("comercial.sintetico@example.invalid"),
    )
    assert response.status_code == 201, response.text
    batch = db_session.get(FieldImportBatch, response.json()["id"])
    document = api_client.get(
        f"/api/imports/{response.json()['id']}/document",
        headers=_headers("comercial.sintetico@example.invalid"),
    )
    persisted = "\n".join([batch.raw_payload_json, batch.raw_document_text, document.text])
    for forbidden in (
        "entity-secret-sintetico",
        "data:image/svg+xml",
        "PHN2Zy1zZWNyZXQ",
        "password",
        "<img",
        "onerror",
    ):
        assert forbidden.lower() not in persisted.lower()
    assert "conteúdo público" in persisted
    assert "[valor sensível omitido]" in persisted


def test_near_limit_adversarial_html_is_processed_within_practical_bound(api_client):
    import time

    payload = {"formVersion": "12", "cliente": "Cliente Sintético de Performance", "potenciaKwp": 1.0}
    adversarial_tail = "<textarea name=\"password\">" + ("</textareaX" * 82_000)
    html = (
        '<script type="application/json" id="notas-iniciais-data">'
        + json.dumps(payload)
        + "</script>"
        + adversarial_tail
    ).encode("utf-8")
    assert len(html) > 900_000
    started = time.perf_counter()
    response = api_client.post(
        "/api/imports/notes/preview",
        files={"file": ("notas-adversarial.html", html, "text/html")},
        headers=_headers("comercial.sintetico@example.invalid"),
    )
    elapsed = time.perf_counter() - started
    assert response.status_code == 201, response.text
    assert elapsed < 3.0, f"structured HTML import took {elapsed:.3f}s"


def test_over_limit_integer_is_a_bad_request_not_an_internal_error(api_client):
    oversized_integer = b"9" * 5000
    content = (
        b'{"formVersion":"12","cliente":"Cliente Sintetico Inteiro",'
        b'"potenciaKwp":' + oversized_integer + b"}"
    )
    response = api_client.post(
        "/api/imports/notes/preview",
        files={"file": ("notas-inteiro-demasiado-grande.json", content, "application/json")},
        headers=_headers("comercial.sintetico@example.invalid"),
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"]


def test_conflict_can_be_re_resolved_before_apply_but_is_immutable_after_apply(db_session, api_client):
    headers = _headers("comercial.sintetico@example.invalid")
    existing = Project(
        name="Projeto Sintético Re-resolução",
        client_email="cliente.notas.sintetico@example.invalid",
        power_kwp=1.0,
    )
    db_session.add(existing)
    db_session.commit()
    preview = api_client.post(
        "/api/imports/notes/preview",
        files={"file": ("notas-reresolucao.json", _json_fixture_bytes(), "application/json")},
        headers=headers,
    )
    assert preview.status_code == 201, preview.text
    body = preview.json()
    conflict = next(c for c in body["records"][0]["conflicts"] if c["field_name"] == "power_kwp")
    conflict_url = f"/api/imports/conflicts/{conflict['id']}/resolve"

    first_resolution = api_client.post(conflict_url, json={"resolution": "use_new"}, headers=headers)
    assert first_resolution.status_code == 200, first_resolution.text
    second_resolution = api_client.post(conflict_url, json={"resolution": "keep_old"}, headers=headers)
    assert second_resolution.status_code == 200, second_resolution.text
    assert second_resolution.json()["resolution"] == "keep_old"
    for other_conflict in body["records"][0]["conflicts"]:
        if other_conflict["id"] == str(conflict["id"]):
            continue
        resolved = api_client.post(
            f"/api/imports/conflicts/{other_conflict['id']}/resolve",
            json={"resolution": "keep_old"},
            headers=headers,
        )
        assert resolved.status_code == 200, resolved.text

    applied = api_client.post(
        "/api/imports/notes/apply",
        json={"batch_id": body["id"], "confirm": True},
        headers=headers,
    )
    assert applied.status_code == 200, applied.text
    db_session.refresh(existing)
    assert existing.power_kwp == 1.0

    immutable = api_client.post(conflict_url, json={"resolution": "use_new"}, headers=headers)
    assert immutable.status_code == 400, immutable.text
    db_session.refresh(existing)
    assert existing.power_kwp == 1.0


def test_ambiguous_target_requires_target_specific_conflicts_before_apply(db_session, api_client):
    headers = _headers("comercial.sintetico@example.invalid")
    first = Project(
        name="Projeto Sintético Ambíguo A",
        client_email="cliente.notas.sintetico@example.invalid",
        power_kwp=1.0,
    )
    second = Project(
        name="Projeto Sintético Ambíguo B",
        client_email="cliente.notas.sintetico@example.invalid",
        power_kwp=2.0,
    )
    db_session.add_all([first, second])
    db_session.commit()

    preview = api_client.post(
        "/api/imports/notes/preview",
        files={"file": ("notas-ambigua.json", _json_fixture_bytes(), "application/json")},
        headers=headers,
    )
    assert preview.status_code == 201, preview.text
    batch_id = preview.json()["id"]
    record = preview.json()["records"][0]
    assert record["match_strategy"] == "ambiguous"
    assert record["target_project_id"] is None
    assert record["conflicts"] == []

    first_apply = api_client.post(
        "/api/imports/notes/apply",
        json={"batch_id": batch_id, "target_project_id": str(second.id), "confirm": True},
        headers=headers,
    )
    assert first_apply.status_code == 400, first_apply.text
    assert "conflito" in first_apply.json()["detail"].lower()

    db_session.refresh(first)
    db_session.refresh(second)
    assert first.power_kwp == 1.0
    assert second.power_kwp == 2.0

    selected = api_client.get(f"/api/imports/{batch_id}", headers=headers)
    selected_record = selected.json()["records"][0]
    assert selected_record["target_project_id"] == str(second.id)
    assert selected_record["conflicts"]
    power_conflict = next(c for c in selected_record["conflicts"] if c["field_name"] == "power_kwp")
    assert power_conflict["old_value"] == "2.0"
    assert power_conflict["resolution"] == "pending"

    for conflict in selected_record["conflicts"]:
        resolved = api_client.post(
            f"/api/imports/conflicts/{conflict['id']}/resolve",
            json={"resolution": "use_new"},
            headers=headers,
        )
        assert resolved.status_code == 200, resolved.text

    final_apply = api_client.post(
        "/api/imports/notes/apply",
        json={"batch_id": batch_id, "target_project_id": str(second.id), "confirm": True},
        headers=headers,
    )
    assert final_apply.status_code == 200, final_apply.text
    db_session.refresh(first)
    db_session.refresh(second)
    assert first.power_kwp == 1.0
    assert second.power_kwp == 8.28


def test_malformed_email_object_is_rejected_as_bad_request(api_client):
    payload = json.loads(_json_fixture_bytes())
    payload["email"] = {"address": "email-object@example.invalid"}
    response = api_client.post(
        "/api/imports/notes/preview",
        files={"file": ("notas-email-tipo-invalido.json", json.dumps(payload).encode("utf-8"), "application/json")},
        headers=_headers("comercial.sintetico@example.invalid"),
    )
    assert response.status_code == 400, response.text
    assert "email" in response.json()["detail"].lower()


@pytest.mark.parametrize(
    ("name", "mutate"),
    [
        ("latitude_out_of_range", lambda payload: payload.update(lat=91.0)),
        ("non_finite_nested_number", lambda payload: payload.update(nested={"reading": float("nan")})),
        ("fractional_panel_count", lambda payload: payload["paineis"].update(quantidade=1.5)),
        ("wrong_inverters_shape", lambda payload: payload.update(inversores={"modelo": "não é uma lista"})),
        ("wrong_attachments_shape", lambda payload: payload.update(anexos={"nome": "não é uma lista"})),
        ("overlong_client_name", lambda payload: payload.update(cliente="x" * 257)),
    ],
)
def test_malformed_values_and_shapes_are_rejected_as_bad_request(api_client, name, mutate):
    payload = json.loads(_json_fixture_bytes())
    mutate(payload)
    response = api_client.post(
        "/api/imports/notes/preview",
        files={"file": (f"notas-invalida-{name}.json", json.dumps(payload).encode("utf-8"), "application/json")},
        headers=_headers("comercial.sintetico@example.invalid"),
    )
    assert response.status_code == 400, response.text


def test_entity_redaction_reaches_a_bounded_fixed_point_before_classification():
    encoded_data_url = "data&amp;#x3a;image/svg+xml&amp;#x3b;base64&amp;#x2c;SECRET"
    encoded_label = "pa&amp;#x73;s&amp;#x77;ord"
    over_budget_colon = "&#x3a;"
    for _ in range(9):
        over_budget_colon = over_budget_colon.replace("&", "&amp;")

    redacted = _redact_text(encoded_data_url)
    over_budget_redacted = _redact_text(f"data{over_budget_colon}SECRET")

    assert DATA_URL_PLACEHOLDER in redacted
    assert "SECRET" not in redacted
    assert "SECRET" not in over_budget_redacted
    assert _is_sensitive_label(encoded_label)
    over_budget_label = "&#x70;assword"
    for _ in range(9):
        over_budget_label = over_budget_label.replace("&", "&amp;")
    assert _is_sensitive_label(over_budget_label)


@pytest.mark.parametrize(
    "label",
    [
        "passwd",
        "pass",
        "secret_key",
        "access_token",
        "recovery-code",
        "otp",
    ],
)
def test_common_credential_aliases_are_sensitive_labels(label):
    assert _is_sensitive_label(label)


def test_document_read_sanitizes_legacy_raw_html_and_never_returns_markup(db_session, api_client):
    batch = FieldImportBatch(
        source_type="notes_html",
        source_filename="legacy-export.html",
        source_file_hash="legacy-read-html-hash",
        form_version="12",
        raw_payload_json="{}",
        raw_document_text=(
            '<!doctype html><script type="application/json" id="notas-iniciais-data">'
            '{"formVersion":"12","cliente":"Cliente legado sintético",'
            '"potenciaKwp":1.0,"password":"legacy-secret-sintético",'
            '"preview":"data:text/plain;base64,SECRET"}'
            "</script>"
        ),
        status=BATCH_STATUS_PENDING_CONFIRMATION,
    )
    db_session.add(batch)
    db_session.commit()

    response = api_client.get(
        f"/api/imports/{batch.id}/document",
        headers=_headers("comercial.sintetico@example.invalid"),
    )

    assert response.status_code == 200, response.text
    content = response.json()["content"]
    assert content == (
        '{"[campo sensível omitido]":"[valor sensível omitido]",'
        '"cliente":"Cliente legado sintético","formVersion":"12",'
        '"potenciaKwp":1.0,"preview":"[data-url omitido]"}'
    )
    assert "<" not in content
    assert "legacy-secret-sintético" not in content
    assert "data:text" not in content


def test_document_read_returns_omitted_placeholder_when_legacy_document_cannot_be_parsed(db_session, api_client):
    batch = FieldImportBatch(
        source_type="notes_json",
        source_filename="legacy-export.json",
        source_file_hash="legacy-read-invalid-hash",
        form_version=None,
        raw_payload_json="{}",
        raw_document_text='{"unterminated":',
        status=BATCH_STATUS_PENDING_CONFIRMATION,
    )
    db_session.add(batch)
    db_session.commit()

    response = api_client.get(
        f"/api/imports/{batch.id}/document",
        headers=_headers("comercial.sintetico@example.invalid"),
    )

    assert response.status_code == 200, response.text
    assert response.json()["content"] == DOCUMENT_OMITTED_PLACEHOLDER
    assert "unterminated" not in response.text


def test_upload_is_read_with_a_bounded_extra_byte_and_rejected_before_processing(api_client, monkeypatch):
    from app.api import routes_imports

    calls: list[int] = []

    class FakeUpload:
        filename = "too-large.json"

        async def read(self, size: int = -1) -> bytes:
            calls.append(size)
            return b"x" * (MAX_UPLOAD_BYTES + 1)

    monkeypatch.setattr(routes_imports, "_require_import_notes", lambda ctx: None)
    monkeypatch.setattr(
        routes_imports,
        "preview_notes_import",
        lambda *args, **kwargs: pytest.fail("oversized upload reached importer"),
    )

    with pytest.raises(routes_imports.HTTPException) as error:
        asyncio.run(
            routes_imports.preview_notes_endpoint(
                file=FakeUpload(), db=SimpleNamespace(), ctx=SimpleNamespace(person_id=None)
            )
        )

    assert error.value.status_code == 400
    assert calls == [MAX_UPLOAD_BYTES + 1]


def test_apply_blocks_null_preview_fields_until_explicitly_resolved(db_session, api_client):
    headers = _headers("comercial.sintetico@example.invalid")
    existing = Project(
        name="Projeto Sintético Sem Potência",
        client_email="cliente.notas.sintetico@example.invalid",
        power_kwp=None,
    )
    db_session.add(existing)
    db_session.commit()

    preview = api_client.post(
        "/api/imports/notes/preview",
        files={"file": ("notas-null-at-preview.json", _json_fixture_bytes(), "application/json")},
        headers=headers,
    )
    assert preview.status_code == 201, preview.text
    record = preview.json()["records"][0]
    power_conflict = next(conflict for conflict in record["conflicts"] if conflict["field_name"] == "power_kwp")
    assert power_conflict["old_value"] is None
    assert power_conflict["resolution"] == "pending"

    blocked = api_client.post(
        "/api/imports/notes/apply",
        json={"batch_id": preview.json()["id"], "confirm": True},
        headers=headers,
    )

    assert blocked.status_code == 400, blocked.text
    db_session.refresh(existing)
    assert existing.power_kwp is None


def test_apply_resets_stale_conflict_to_current_value_and_aborts(db_session, api_client):
    headers = _headers("comercial.sintetico@example.invalid")
    existing = Project(
        name="Projeto Sintético Estado Alterado",
        client_email="cliente.notas.sintetico@example.invalid",
        power_kwp=1.0,
    )
    db_session.add(existing)
    db_session.commit()

    preview = api_client.post(
        "/api/imports/notes/preview",
        files={"file": ("notas-stale-conflict.json", _json_fixture_bytes(), "application/json")},
        headers=headers,
    )
    assert preview.status_code == 201, preview.text
    batch_id = preview.json()["id"]
    conflicts = preview.json()["records"][0]["conflicts"]
    for conflict in conflicts:
        resolved = api_client.post(
            f"/api/imports/conflicts/{conflict['id']}/resolve",
            json={"resolution": "use_new"},
            headers=headers,
        )
        assert resolved.status_code == 200, resolved.text

    existing.power_kwp = 2.0
    db_session.commit()

    blocked = api_client.post(
        "/api/imports/notes/apply",
        json={"batch_id": batch_id, "confirm": True},
        headers=headers,
    )

    assert blocked.status_code == 400, blocked.text
    db_session.refresh(existing)
    assert existing.power_kwp == 2.0
    refreshed = api_client.get(f"/api/imports/{batch_id}", headers=headers)
    power_conflict = next(
        conflict
        for conflict in refreshed.json()["records"][0]["conflicts"]
        if conflict["field_name"] == "power_kwp" and conflict["target_entity"] == "project"
    )
    assert power_conflict["old_value"] == "2.0"
    assert power_conflict["resolution"] == "pending"


def test_apply_generates_new_conflict_when_unconflicted_field_changes_after_preview(db_session, api_client):
    headers = _headers("comercial.sintetico@example.invalid")
    existing = Project(
        name="Projeto Sintético Divergência Nova",
        client_name="Cliente Sintético das Notas Iniciais",
        client_email="cliente.notas.sintetico@example.invalid",
        power_kwp=8.28,
    )
    db_session.add(existing)
    db_session.commit()

    preview = api_client.post(
        "/api/imports/notes/preview",
        files={"file": ("notas-new-divergence.json", _json_fixture_bytes(), "application/json")},
        headers=headers,
    )
    assert preview.status_code == 201, preview.text
    batch_id = preview.json()["id"]
    assert not any(
        conflict["field_name"] == "client_name" for conflict in preview.json()["records"][0]["conflicts"]
    )

    existing.client_name = "Cliente Sintético Alterado Depois"
    db_session.commit()
    blocked = api_client.post(
        "/api/imports/notes/apply",
        json={"batch_id": batch_id, "confirm": True},
        headers=headers,
    )

    assert blocked.status_code == 400, blocked.text
    db_session.refresh(existing)
    assert existing.client_name == "Cliente Sintético Alterado Depois"
    refreshed = api_client.get(f"/api/imports/{batch_id}", headers=headers)
    client_name_conflict = next(
        conflict
        for conflict in refreshed.json()["records"][0]["conflicts"]
        if conflict["field_name"] == "client_name"
    )
    assert client_name_conflict["old_value"] == "Cliente Sintético Alterado Depois"
    assert client_name_conflict["resolution"] == "pending"


def test_concurrent_same_hash_previews_return_one_idempotent_batch(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'preview-race.db').as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(bind=engine)
    barrier = threading.Barrier(2, timeout=10)

    class BarrierSession(Session):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._first_flush = True

        def flush(self, *args, **kwargs):
            if self._first_flush:
                self._first_flush = False
                barrier.wait()
            return super().flush(*args, **kwargs)

    factory = sessionmaker(bind=engine, class_=BarrierSession, future=True)
    payload = '{"formVersion":"12","cliente":"Cliente Sintético Race","potenciaKwp":1.0}'.encode()
    returned_ids: list[str] = []
    errors: list[BaseException] = []

    def worker():
        db = factory()
        try:
            batch = preview_notes_import(
                db,
                filename="notas-race.json",
                content=payload,
                uploaded_by_person_id=None,
            )
            db.commit()
            returned_ids.append(str(batch.id))
        except Exception as exc:  # assertion below reports unexpected worker failures
            errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert len(returned_ids) == 2
    assert returned_ids[0] == returned_ids[1]
    with Session(engine) as db:
        assert db.query(FieldImportBatch).count() == 1


def test_apply_wins_batch_lock_and_late_resolution_cannot_change_applied_batch(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'resolve-apply-race.db').as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, future=True)
    setup = factory()
    project = Project(
        name="Projeto Sintético Concorrência",
        client_name="Cliente Sintético Antigo",
        client_email="race@example.invalid",
    )
    setup.add(project)
    setup.flush()
    batch = FieldImportBatch(
        source_type="notes_json",
        source_filename="race.json",
        source_file_hash="resolve-apply-race-hash",
        form_version="12",
        raw_payload_json="{}",
        raw_document_text="{}",
        status=BATCH_STATUS_PENDING_CONFIRMATION,
    )
    setup.add(batch)
    setup.flush()
    record = FieldImportRecord(
        batch_id=batch.id,
        target_project_id=project.id,
        is_new_project=False,
        match_strategy="email",
        candidate_project_ids_json=json.dumps([str(project.id)]),
        mapped_fields_json=json.dumps(
            {"project": {"client_name": "Cliente Sintético Novo"}, "installation": {}, "licensing": {}}
        ),
    )
    setup.add(record)
    setup.flush()
    conflict = FieldImportConflict(
        record_id=record.id,
        target_entity="project",
        field_name="client_name",
        old_value="Cliente Sintético Antigo",
        new_value="Cliente Sintético Novo",
        resolution="use_new",
    )
    setup.add(conflict)
    setup.commit()
    batch_id = batch.id
    conflict_id = conflict.id
    project_id = project.id
    setup.close()

    original_lock = imports_notes_service._lock_pending_batch
    apply_locked = threading.Event()
    resolve_entered = threading.Event()
    release_apply = threading.Event()

    def controlled_lock(db, locked_batch_id):
        if threading.current_thread().name == "resolve":
            resolve_entered.set()
        locked = original_lock(db, locked_batch_id)
        if threading.current_thread().name == "apply":
            apply_locked.set()
            assert release_apply.wait(timeout=10)
        return locked

    monkeypatch.setattr(imports_notes_service, "_lock_pending_batch", controlled_lock)
    results: dict[str, object] = {}

    def apply_worker():
        db = factory()
        try:
            results["apply"] = apply_notes_import(
                db,
                batch=db.get(FieldImportBatch, batch_id),
                target_project_id=project_id,
                applied_by_person_id=None,
            )
            db.commit()
        except Exception as exc:
            results["apply_error"] = exc
        finally:
            db.close()

    def resolve_worker():
        db = factory()
        try:
            conflict_row = db.get(FieldImportConflict, conflict_id)
            results["resolve"] = resolve_conflict(
                db,
                conflict=conflict_row,
                resolution="keep_old",
                resolved_by_person_id=None,
            )
            db.commit()
        except Exception as exc:
            results["resolve_error"] = exc
        finally:
            db.close()

    apply_thread = threading.Thread(target=apply_worker, name="apply")
    resolve_thread = threading.Thread(target=resolve_worker, name="resolve")
    apply_thread.start()
    assert apply_locked.wait(timeout=10), repr(results)
    resolve_thread.start()
    assert resolve_entered.wait(timeout=10)
    release_apply.set()
    apply_thread.join(timeout=15)
    resolve_thread.join(timeout=15)

    assert not apply_thread.is_alive()
    assert not resolve_thread.is_alive()
    assert "apply_error" not in results
    assert isinstance(results.get("resolve_error"), imports_notes_service.NotesImportError)
    with Session(engine) as db:
        persisted_batch = db.get(FieldImportBatch, batch_id)
        persisted_conflict = db.get(FieldImportConflict, conflict_id)
        persisted_project = db.get(Project, project_id)
        assert persisted_batch.status == BATCH_STATUS_APPLIED
        assert persisted_conflict.resolution == "use_new"
        assert persisted_project.client_name == "Cliente Sintético Novo"


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("portal&#x4c;ogin", True),
        ("pass&#x77;ord2", True),
        ("api<span>Key</span>_9", True),
        ("<span>pass</span><strong>word</strong>", True),
        ("access&#x20;token99", True),
        ("compass bearing", False),
        ("passenger count", False),
        ("tokenizer version", False),
    ],
)
def test_sensitive_labels_are_canonicalized_before_classification(label, expected):
    assert _is_sensitive_label(label) is expected


def test_recursive_metadata_scan_checks_every_label_alias_key():
    payload = {
        "safe": "texto público sintético",
        "metadata": {
            "label": "rótulo público",
            "fieldName": "<b>pass</b>word2",
            "name": "api<span>Key</span>9",
            "key": "token3",
            "value": "credential-secret-sintético",
        },
    }

    sanitized = _sanitize_payload(payload)
    serialized = json.dumps(sanitized, ensure_ascii=False)

    assert "credential-secret-sintético" not in serialized
    assert "password" not in serialized.lower()
    assert "apikey" not in serialized.lower()
    assert "texto público sintético" in serialized


def test_legacy_staging_json_is_sanitized_on_batch_conflict_and_document_reads(db_session, api_client):
    batch = FieldImportBatch(
        source_type="notes_json",
        source_filename="legacy-read.json",
        source_file_hash="legacy-read-all-fields-hash",
        form_version="12",
        raw_payload_json=json.dumps({"password": "raw-payload-secret", "safe": "<b>raw public</b>"}),
        raw_document_text=json.dumps(
            {
                "cliente": "<b>document public</b>",
                "api<span>Token</span>4": "document-secret",
                "preview": "data&#x3a;text/plain&#x2c;DOCUMENTSECRET",
            }
        ),
        status=BATCH_STATUS_PENDING_CONFIRMATION,
    )
    db_session.add(batch)
    db_session.flush()
    record = FieldImportRecord(
        batch_id=batch.id,
        is_new_project=True,
        match_strategy="none",
        candidate_project_ids_json="[]",
        mapped_fields_json=json.dumps(
            {
                "project": {
                    "client_name": "<i>mapped public</i>",
                    "password": "mapped-secret",
                },
                "installation": {},
                "licensing": {},
            }
        ),
    )
    db_session.add(record)
    db_session.flush()
    conflict = FieldImportConflict(
        record_id=record.id,
        target_entity="project",
        field_name="<span>pass</span>word2",
        old_value="old-conflict-secret",
        new_value="<script>new-conflict-secret</script>",
    )
    db_session.add(conflict)
    db_session.commit()

    batch_response = api_client.get(
        f"/api/imports/{batch.id}", headers=_headers("comercial.sintetico@example.invalid")
    )
    assert batch_response.status_code == 200, batch_response.text
    batch_text = batch_response.text
    assert "mapped-secret" not in batch_text
    assert "<i>" not in batch_text
    assert "password" not in batch_text.lower()

    conflict_response = api_client.get(
        f"/api/imports/{batch.id}/conflicts", headers=_headers("comercial.sintetico@example.invalid")
    )
    assert conflict_response.status_code == 200, conflict_response.text
    conflict_text = conflict_response.text
    assert "old-conflict-secret" not in conflict_text
    assert "new-conflict-secret" not in conflict_text
    assert "<script>" not in conflict_text
    assert "password" not in conflict_text.lower()

    document_response = api_client.get(
        f"/api/imports/{batch.id}/document", headers=_headers("comercial.sintetico@example.invalid")
    )
    assert document_response.status_code == 200, document_response.text
    document_text = document_response.text
    assert "document-secret" not in document_text
    assert "DOCUMENTSECRET" not in document_text
    assert "data:" not in document_text.lower()
    assert "<b>" not in document_text
    assert "document public" in document_text


def _isolated_import_db(tmp_path, name):
    engine = create_engine(
        f"sqlite:///{(tmp_path / name).as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine, future=True)()


def test_preview_does_not_commit_unrelated_dirty_state(tmp_path):
    engine, db = _isolated_import_db(tmp_path, "preview-dirty.db")
    unrelated = Project(name="Projeto independente original")
    db.add(unrelated)
    db.commit()
    unrelated_id = unrelated.id
    unrelated.name = "Projeto independente pendente"

    payload = '{"formVersion":"12","cliente":"Cliente Preview Sintético","potenciaKwp":1.0}'.encode("utf-8")
    with pytest.raises(NotesImportError, match="alterações pendentes"):
        preview_notes_import(db, filename="preview-dirty.json", content=payload, uploaded_by_person_id=None)

    observer = Session(engine)
    assert observer.get(Project, unrelated_id).name == "Projeto independente original"
    observer.close()
    db.rollback()
    assert db.get(Project, unrelated_id).name == "Projeto independente original"
    db.close()


def test_apply_does_not_commit_unrelated_dirty_state_on_success(tmp_path):
    engine, db = _isolated_import_db(tmp_path, "apply-dirty.db")
    unrelated = Project(name="Projeto apply original")
    db.add(unrelated)
    db.commit()
    unrelated_id = unrelated.id
    payload = '{"formVersion":"12","cliente":"Cliente Apply Sintético","potenciaKwp":1.0}'.encode("utf-8")
    batch = preview_notes_import(db, filename="apply-dirty.json", content=payload, uploaded_by_person_id=None)
    db.commit()  # route boundary owns this commit in production

    unrelated.name = "Projeto apply pendente"
    with pytest.raises(NotesImportError, match="alterações pendentes"):
        apply_notes_import(db, batch=batch, target_project_id=None, applied_by_person_id=None)
    observer = Session(engine)
    assert observer.get(Project, unrelated_id).name == "Projeto apply original"
    observer.close()
    db.rollback()
    assert db.get(Project, unrelated_id).name == "Projeto apply original"
    db.close()


def test_apply_error_does_not_commit_unrelated_dirty_state(tmp_path):
    engine, db = _isolated_import_db(tmp_path, "apply-error-dirty.db")
    unrelated = Project(name="Projeto erro original")
    db.add(unrelated)
    db.commit()
    unrelated_id = unrelated.id
    payload = '{"formVersion":"12","cliente":"Cliente Erro Sintético","potenciaKwp":1.0}'.encode("utf-8")
    batch = preview_notes_import(db, filename="apply-error-dirty.json", content=payload, uploaded_by_person_id=None)
    db.commit()

    unrelated.name = "Projeto erro pendente"
    with pytest.raises(NotesImportError, match="alterações pendentes"):
        apply_notes_import(db, batch=batch, target_project_id=uuid.uuid4(), applied_by_person_id=None)

    observer = Session(engine)
    assert observer.get(Project, unrelated_id).name == "Projeto erro original"
    observer.close()
    db.rollback()
    assert db.get(Project, unrelated_id).name == "Projeto erro original"
    db.close()


def test_resolve_does_not_commit_unrelated_dirty_state(tmp_path):
    engine, db = _isolated_import_db(tmp_path, "resolve-dirty.db")
    existing = Project(
        name="Projeto resolve original",
        client_email="resolve-dirty@example.invalid",
        power_kwp=1.0,
    )
    unrelated = Project(name="Projeto resolve independente original")
    db.add_all([existing, unrelated])
    db.commit()
    unrelated_id = unrelated.id
    payload = json.loads(_json_fixture_bytes())
    payload["email"] = existing.client_email
    batch = preview_notes_import(
        db,
        filename="resolve-dirty.json",
        content=json.dumps(payload).encode("utf-8"),
        uploaded_by_person_id=None,
    )
    db.commit()
    conflict = db.query(FieldImportConflict).filter(FieldImportConflict.record_id == batch.records[0].id).first()
    assert conflict is not None

    unrelated.name = "Projeto resolve independente pendente"
    with pytest.raises(NotesImportError, match="alterações pendentes"):
        resolve_conflict(db, conflict=conflict, resolution="keep_old", resolved_by_person_id=None)

    observer = Session(engine)
    assert observer.get(Project, unrelated_id).name == "Projeto resolve independente original"
    observer.close()
    db.rollback()
    assert db.get(Project, unrelated_id).name == "Projeto resolve independente original"
    db.close()


def test_postgresql_lock_path_refreshes_a_preloaded_batch_from_database(tmp_path, monkeypatch):
    engine, db = _isolated_import_db(tmp_path, "stale-lock.db")
    batch = FieldImportBatch(
        source_type="notes_json",
        source_filename="stale.json",
        source_file_hash="stale-lock-hash",
        raw_payload_json="{}",
        raw_document_text="{}",
        status=BATCH_STATUS_PENDING_CONFIRMATION,
    )
    db.add(batch)
    db.commit()
    batch_id = batch.id
    preloaded = db.get(FieldImportBatch, batch_id)
    assert preloaded.status == BATCH_STATUS_PENDING_CONFIRMATION

    writer = Session(engine)
    writer_batch = writer.get(FieldImportBatch, batch_id)
    writer_batch.status = BATCH_STATUS_APPLIED
    writer.commit()
    writer.close()

    monkeypatch.setattr(engine.dialect, "name", "postgresql", raising=False)
    with pytest.raises(NotesImportError, match="applied"):
        _lock_pending_batch(db, batch_id)
    db.close()


def test_password_and_secret_input_types_are_omitted_from_legacy_payload():
    marker = "SYNTHETIC_INPUT_SECRET_DO_NOT_PRINT"
    for input_type in ("password", "secret"):
        html = f"""
        <form>
          <input name="cliente" value="Cliente Sintético Input" />
          <input name="potenciaKwp" value="1.0" />
          <input type="{input_type}" name="arbitrary-field" value="{marker}" />
        </form>
        """.encode("utf-8")

        payload = extract_payload(filename="legacy.html", content=html)

        assert marker not in json.dumps(payload, ensure_ascii=False)


def test_legacy_void_controls_finalize_without_xhtml_end_tags_and_never_execute_script():
    marker = "SYNTHETIC_JS_MUST_NOT_EXECUTE"
    html = f"""
    <!doctype html>
    <html><head><meta charset="utf-8"><title>Legado sintético</title></head>
    <body>
      <form>
        <label>Cliente</label><input name="cliente" value="Cliente Void Sintético">
        <input name="email" value="void@example.invalid">
        <input name="potenciaKwp" value="5.5">
        <input type="checkbox" name="rgpd" checked>
        <select name="tipoInstalacao"><option selected>Autoconsumo</option></select>
        <br><img src="data:image/png;base64,VOID_IMAGE_SECRET" alt="imagem">
        <input name="observacoes" value="Campo depois de voids">
      </form>
      <script>window.{marker} = true;</script>
    </body></html>
    """.encode("utf-8")

    payload = extract_payload(filename="legado-sem-xhtml.html", content=html)

    assert payload["cliente"] == "Cliente Void Sintético"
    assert payload["email"] == "void@example.invalid"
    assert payload["potenciaKwp"] == 5.5
    assert payload["rgpd"] is True
    assert payload["tipoInstalacao"] == "Autoconsumo"
    assert payload["observacoes"] == "Campo depois de voids"
    serialized = json.dumps(payload, ensure_ascii=False)
    assert marker not in serialized
    assert "VOID_IMAGE_SECRET" not in serialized


def test_sensitive_sanitization_rejects_6003_fields_without_silent_secret_drops():
    import time

    field_count = 6003
    sensitive_count = 3000
    payload = {
        "formVersion": "12",
        "cliente": "Cliente Sintético Performance",
        "potenciaKwp": 1.0,
    }
    payload.update(
        {
            f"secretField{i}": f"SYNTHETIC_SECRET_{i:04d}_DO_NOT_LEAK"
            for i in range(sensitive_count)
        }
    )
    payload.update(
        {
            f"publicField{i}": f"texto público {i:04d} " + ("x" * 950)
            for i in range(field_count - len(payload))
        }
    )
    assert len(payload) == field_count
    assert len(json.dumps(payload, ensure_ascii=False)) > 3_000_000

    started = time.perf_counter()
    with pytest.raises(NotesImportError) as error:
        _sanitize_payload(payload)
    elapsed = time.perf_counter() - started

    assert elapsed < 8.0, f"sanitization took {elapsed:.3f}s for {field_count} fields"
    assert "2048" not in str(error.value)
    assert "512" not in str(error.value)
    assert "16384" not in str(error.value)
    assert "SYNTHETIC_SECRET_" not in str(error.value)


def test_recursive_metadata_classification_covers_all_label_aliases_and_value_forms():
    aliases = (
        "label",
        "field",
        "fieldName",
        "name",
        "key",
        "fieldLabel",
        "labelName",
        "property",
        "attribute",
        "caption",
        "title",
        "data-field",
        "dataName",
    )
    marker = "SYNTHETIC_METADATA_SECRET_DO_NOT_PRINT"

    for alias in aliases:
        payload = {
            "public": "texto público sintético",
            "metadata": {alias: "<b>password</b>", "attributeValue": marker},
        }

        sanitized = _sanitize_payload(payload)
        serialized = json.dumps(sanitized, ensure_ascii=False)

        assert marker not in serialized
        assert "password" not in serialized.lower()
        assert "texto público sintético" in serialized


@pytest.mark.parametrize(
    "value",
    [
        "data:\ntext/plain,\nSYNTHETIC_DATA_URL_SECRET_DO_NOT_PRINT",
        "data:\ttext/plain;\tbase64,\r\nSYNTHETIC_DATA_URL_SECRET_DO_NOT_PRINT",
        "prefix data:text/plain,\x00\nSYNTHETIC_DATA_URL_SECRET_DO_NOT_PRINT",
    ],
)
def test_data_url_redaction_canonicalizes_whitespace_and_controls(value):
    redacted = _redact_text(value)

    assert "SYNTHETIC_DATA_URL_SECRET_DO_NOT_PRINT" not in redacted
    assert DATA_URL_PLACEHOLDER in redacted


def test_api_read_models_redact_filename_raw_payload_mapped_conflict_and_document_variants(db_session, api_client):
    marker = "SYNTHETIC_READ_MODEL_SECRET_DO_NOT_PRINT"
    batch = FieldImportBatch(
        source_type="notes_json",
        source_filename=f"export-password={marker}.json",
        source_file_hash="read-model-all-fields-hash",
        form_version="12",
        raw_payload_json=json.dumps({"public": f"password={marker}"}),
        raw_document_text=json.dumps(
            {
                "public": f"<b>password={marker}</b>",
                "data": f"data:\ntext/plain,\n{marker}",
            }
        ),
        status=BATCH_STATUS_PENDING_CONFIRMATION,
    )
    db_session.add(batch)
    db_session.flush()
    record = FieldImportRecord(
        batch_id=batch.id,
        is_new_project=True,
        match_strategy="none",
        candidate_project_ids_json="[]",
        mapped_fields_json=json.dumps(
            {"project": {"notes": f"<i>password={marker}</i>"}, "installation": {}, "licensing": {}}
        ),
    )
    db_session.add(record)
    db_session.flush()
    db_session.add(
        FieldImportConflict(
            record_id=record.id,
            target_entity="project",
            field_name="notes",
            old_value=f"password={marker}",
            new_value=f"data:\ttext/plain,\t{marker}",
        )
    )
    db_session.commit()

    from app.api.routes_imports import _staging_json_to_read

    raw_read = _staging_json_to_read(batch.raw_payload_json, default={})
    assert marker not in json.dumps(raw_read, ensure_ascii=False)

    response = api_client.get(
        f"/api/imports/{batch.id}", headers=_headers("comercial.sintetico@example.invalid")
    )
    assert response.status_code == 200, response.text
    assert marker not in response.text
    assert "<i>" not in response.text
    assert "data:" not in response.text.lower()

    conflict_response = api_client.get(
        f"/api/imports/{batch.id}/conflicts", headers=_headers("comercial.sintetico@example.invalid")
    )
    assert conflict_response.status_code == 200, conflict_response.text
    assert marker not in conflict_response.text
    assert "data:" not in conflict_response.text.lower()

    document_response = api_client.get(
        f"/api/imports/{batch.id}/document", headers=_headers("comercial.sintetico@example.invalid")
    )
    assert document_response.status_code == 200, document_response.text
    assert marker not in document_response.text
    assert "<b>" not in document_response.text
    assert "data:" not in document_response.text.lower()


def test_ambiguous_target_route_commits_pending_selection_without_project_mutation(tmp_path, monkeypatch):
    engine, db = _isolated_import_db(tmp_path, "ambiguous-route-commit.db")
    first = Project(name="Projeto Ambíguo Route A", client_email="ambiguous-route@example.invalid", power_kwp=1.0)
    second = Project(name="Projeto Ambíguo Route B", client_email="ambiguous-route@example.invalid", power_kwp=2.0)
    db.add_all([first, second])
    db.commit()
    batch = preview_notes_import(
        db,
        filename="ambiguous-route.json",
        content=b'{"formVersion":"12","cliente":"Cliente Route","email":"ambiguous-route@example.invalid","potenciaKwp":8.0}',
        uploaded_by_person_id=None,
    )
    db.commit()

    from app.api import routes_imports
    from app.schemas.imports import ApplyImportRequest
    from fastapi import HTTPException

    monkeypatch.setattr(routes_imports, "_require_import_notes", lambda ctx: None)
    with pytest.raises(HTTPException) as error:
        routes_imports.apply_notes_endpoint(
            body=ApplyImportRequest(batch_id=batch.id, target_project_id=second.id, confirm=True),
            db=db,
            ctx=SimpleNamespace(person_id=None),
        )
    assert error.value.status_code == 400

    with Session(engine) as observer:
        persisted_record = observer.query(FieldImportRecord).filter(FieldImportRecord.batch_id == batch.id).one()
        assert persisted_record.target_project_id == second.id
        assert observer.query(FieldImportConflict).filter(FieldImportConflict.record_id == persisted_record.id).count() > 0
        assert observer.get(Project, first.id).power_kwp == 1.0
        assert observer.get(Project, second.id).power_kwp == 2.0
    db.close()


def test_stale_conflict_route_commits_refreshed_pending_state(tmp_path, monkeypatch):
    engine, db = _isolated_import_db(tmp_path, "stale-route-commit.db")
    existing = Project(
        name="Projeto Stale Route",
        client_email="stale-route@example.invalid",
        power_kwp=1.0,
    )
    db.add(existing)
    db.commit()
    payload = b'{"formVersion":"12","cliente":"Cliente Stale Route","email":"stale-route@example.invalid","potenciaKwp":8.0}'
    batch = preview_notes_import(db, filename="stale-route.json", content=payload, uploaded_by_person_id=None)
    db.commit()
    for conflict in db.query(FieldImportConflict).filter(FieldImportConflict.record_id == batch.records[0].id):
        conflict.resolution = "use_new"
    db.commit()
    existing.power_kwp = 2.0
    db.commit()

    from app.api import routes_imports
    from app.schemas.imports import ApplyImportRequest
    from fastapi import HTTPException

    monkeypatch.setattr(routes_imports, "_require_import_notes", lambda ctx: None)
    with pytest.raises(HTTPException) as error:
        routes_imports.apply_notes_endpoint(
            body=ApplyImportRequest(batch_id=batch.id, target_project_id=existing.id, confirm=True),
            db=db,
            ctx=SimpleNamespace(person_id=None),
        )
    assert error.value.status_code == 400

    with Session(engine) as observer:
        power_conflict = (
            observer.query(FieldImportConflict)
            .join(FieldImportRecord)
            .filter(FieldImportRecord.batch_id == batch.id, FieldImportConflict.field_name == "power_kwp")
            .filter(FieldImportConflict.target_entity == "project")
            .first()
        )
        assert power_conflict is not None
        assert power_conflict.old_value == "2.0"
        assert power_conflict.resolution == "pending"
        assert observer.get(Project, existing.id).power_kwp == 2.0
    db.close()


def test_import_service_rejects_dirty_new_and_deleted_state_without_flushing_or_rollback(tmp_path):
    engine, db = _isolated_import_db(tmp_path, "clean-session-precondition.db")
    dirty = Project(name="Projeto dirty original")
    deleted = Project(name="Projeto deleted original")
    db.add_all([dirty, deleted])
    db.commit()
    dirty_id = dirty.id
    deleted_id = deleted.id
    dirty.name = "Projeto dirty pendente"
    pending_new = Project(name="Projeto novo pendente")
    db.add(pending_new)
    db.delete(deleted)

    with pytest.raises(NotesImportError, match="alterações pendentes"):
        preview_notes_import(
            db,
            filename="clean-session-precondition.json",
            content=b'{"formVersion":"12","cliente":"Cliente Clean","potenciaKwp":1.0}',
            uploaded_by_person_id=None,
        )

    assert dirty in db.dirty
    assert pending_new in db.new
    assert deleted in db.deleted
    with Session(engine) as observer:
        assert observer.get(Project, dirty_id).name == "Projeto dirty original"
        assert observer.get(Project, deleted_id) is not None
        assert observer.query(FieldImportBatch).count() == 0
    db.close()


def test_v11_multiple_contact_people_are_mapped_first_is_primary_rest_in_notes():
    html = (FIXTURES_DIR / "synthetic_notas_iniciais_v11_contactos.html").read_bytes()
    payload = extract_payload(filename="export.html", content=html)

    assert payload["formVersion"] == "11"
    assert payload["contacto"] == "Contacto Sintético Um"
    assert payload["funcao"] == "Gerente / administrador"
    assert payload["telefone"] == "910000001"
    assert payload["email"] == "Um.Sintetico@Example.invalid"
    assert payload["contactos"] == [
        {
            "nome": "Contacto Sintético Um",
            "funcao": "Gerente / administrador",
            "telefone": "910000001",
            "email": "Um.Sintetico@Example.invalid",
        },
        {"nome": "Contacto Sintético Dois", "funcao": "Responsável de manutenção", "telefone": "910000002"},
        {"nome": "Contacto Sintético Três", "email": "tres.sintetico@example.invalid"},
    ]
    # Já não fica como campo desconhecido.
    labels = [item["label"] for item in payload.get("camposDesconhecidos", [])]
    assert not any("contacto" in label.lower() for label in labels)
    validate_payload(payload)

    mapped = map_payload_to_fields(payload)
    assert mapped["project"]["client_contact"] == "Contacto Sintético Um"
    assert mapped["project"]["client_email"] == "um.sintetico@example.invalid"
    assert mapped["installation"]["contact_person_name"] == "Contacto Sintético Um"
    assert mapped["installation"]["contact_person_role"] == "Gerente / administrador"
    assert mapped["installation"]["contact_phone"]
    notes = mapped["installation"]["notes"]
    assert "Contactos adicionais" in notes
    assert "Contacto Sintético Dois" in notes and "910000002" in notes
    assert "Contacto Sintético Três" in notes and "tres.sintetico@example.invalid" in notes
    assert "Contacto Sintético Um" not in notes


def test_contactos_payload_is_validated_as_hostile_input():
    base = {"formVersion": "11", "cliente": "Cliente Sintético", "baterias": "Sem baterias"}
    for bad in ("texto", [1], [{"nome": 5}], [{"nome": "x" * 300}], [{"nome": "ok", "telefone": "9" * 80}]):
        with pytest.raises(NotesImportError):
            validate_payload({**base, "contactos": bad})
    validate_payload({**base, "contactos": [{"nome": "Ok", "telefone": "910000000"}]})


def _contacts_html(blocks: str, tail: str = "") -> bytes:
    return (
        '<!DOCTYPE html><html><body><header><h1>Notas Iniciais — Cliente Sintético</h1></header>'
        '<section><div class="f"><dt>Nome do cliente</dt><dd>Cliente Sintético</dd></div>'
        f'<div class="f"><dt>Pessoas de contacto no local</dt><dd><div class="cts">{blocks}</div></dd></div>{tail}</section>'
        '<section><div class="f"><dt>Baterias</dt><dd>Sem baterias</dd></div></section>'
        "<footer>Formulário de notas iniciais v11</footer></body></html>"
    ).encode()


def test_unclosed_contact_block_does_not_leak_text_into_other_fields():
    html = _contacts_html('<div class="ct"><b>Contacto Sintético</b> <span class="fn">· Gerente')
    payload = extract_payload(filename="x.html", content=html)
    # O bloco por fechar acaba nos fechos externos: só guarda o que leu dentro
    # dele, nunca texto de campos seguintes, e o resto do documento é lido.
    assert payload["contactos"] == [{"nome": "Contacto Sintético"}]
    assert payload["baterias"] == "Sem baterias"
    assert "Sem baterias" not in str(payload["contactos"])


def test_unclosed_contact_block_at_dt_boundary_is_reset():
    html = _contacts_html(
        '<div class="ct"><b>Por Fechar',
        tail='<div class="f"><dt>Urgência</dt><dd>nenhuma</dd></div>',
    )
    payload = extract_payload(filename="x.html", content=html)
    assert "Urgência" not in str(payload.get("contactos", ""))
    assert payload["urgencia"] == "nenhuma"
    assert payload["baterias"] == "Sem baterias"


def test_additional_contact_with_same_name_as_primary_is_kept_in_notes():
    html = _contacts_html(
        '<div class="ct"><b>Pessoa Repetida</b><div class="via"><a href="tel:910000001">1</a></div></div>'
        '<div class="ct"><b>Pessoa Repetida</b><div class="via"><a href="tel:910000002">2</a></div></div>'
    )
    mapped = map_payload_to_fields(extract_payload(filename="x.html", content=html))
    assert "Contactos adicionais: Pessoa Repetida (910000002)" in mapped["installation"]["notes"]
    assert "910000001" not in mapped["installation"]["notes"]


def test_nested_contact_blocks_are_not_merged():
    html = _contacts_html(
        '<div class="ct"><b>Exterior</b><div class="ct"><b>Interior</b>'
        '<a href="tel:910000009">x</a></div></div>'
        '<div class="ct"><b>Normal</b><a href="tel:910000003">y</a></div>'
    )
    payload = extract_payload(filename="x.html", content=html)
    assert [c["nome"] for c in payload["contactos"]] == ["Normal"]
    assert "910000009" not in str(payload["contactos"])


def test_tel_uri_parameters_are_not_part_of_phone_number():
    for href in ("tel:%2B351910000001?ext=42", "tel:+351910000001;ext=42", "tel:+351910000001#frag"):
        html = _contacts_html(f'<div class="ct"><b>Sintético</b><a href="{href}">t</a></div>')
        payload = extract_payload(filename="x.html", content=html)
        assert payload["contactos"][0]["telefone"] == "+351910000001", href


def test_contact_people_limit_is_enforced_while_parsing():
    blocks = "".join(f'<div class="ct"><b>Pessoa {i}</b></div>' for i in range(55))
    payload = extract_payload(filename="x.html", content=_contacts_html(blocks))
    assert len(payload["contactos"]) == 50
    assert payload["contactos"][-1]["nome"] == "Pessoa 49"
    validate_payload(payload)


def test_json_payload_with_only_contactos_maps_first_person_as_primary():
    payload = {
        "formVersion": "11",
        "cliente": "Cliente Sintético",
        "baterias": "Sem baterias",
        "contactos": [
            {"nome": "Principal API", "funcao": "Gerente", "telefone": "910000100", "email": "Principal@Example.invalid"},
            {"nome": "Adicional API", "telefone": "910000101"},
        ],
    }
    validate_payload(payload)
    mapped = map_payload_to_fields(payload)
    assert mapped["project"]["client_contact"] == "Principal API"
    assert mapped["project"]["client_email"] == "principal@example.invalid"
    assert mapped["installation"]["contact_person_name"] == "Principal API"
    assert mapped["installation"]["contact_person_role"] == "Gerente"
    assert mapped["installation"]["contact_phone"]
    assert "Contactos adicionais: Adicional API (910000101)" in mapped["installation"]["notes"]
    assert "Principal API" not in mapped["installation"]["notes"]


def test_explicit_top_level_contact_fields_win_over_contactos_list():
    payload = {
        "formVersion": "11",
        "cliente": "Cliente Sintético",
        "baterias": "Sem baterias",
        "contacto": "Explícito",
        "contactos": [{"nome": "Lista Um"}],
    }
    mapped = map_payload_to_fields(payload)
    assert mapped["project"]["client_contact"] == "Explícito"
