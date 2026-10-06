from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

import app.services.imports_notes as imports_notes_service
from app.api.routes_imports import _conflict_to_read, _staging_json_to_read
from app.models.imports import BATCH_STATUS_PENDING_CONFIRMATION, FieldImportBatch, FieldImportConflict, FieldImportRecord
from app.services.imports_notes import (
    DOCUMENT_OMITTED_PLACEHOLDER,
    NotesImportError,
    _sanitize_payload,
    _SensitiveValueMatcher,
    sanitize_document_for_read,
)


READ_OMITTED_PLACEHOLDER = "[dados omitidos por segurança]"


def _payload_with_sensitive_values(kind: str) -> tuple[dict, str]:
    payload: dict[str, object] = {
        "formVersion": "12",
        "cliente": "Cliente Sintético Cap",
        "potenciaKwp": 1.0,
    }
    if kind == "count":
        values = [f"SYNTHETIC_COUNT_CAP_{index:04d}" for index in range(imports_notes_service._MAX_SENSITIVE_VALUE_COUNT + 1)]
    elif kind == "bytes":
        values = [f"{index:04d}" + ("b" * (1024 - 4)) for index in range(513)]
    elif kind == "length":
        values = ["SYNTHETIC_LENGTH_CAP_" + ("l" * (imports_notes_service._MAX_SENSITIVE_VALUE_LENGTH - 20))]
    else:  # pragma: no cover - test helper misuse
        raise AssertionError(kind)

    for index, value in enumerate(values):
        payload[f"password{index}"] = value
    marker = values[-1]
    payload["publicDuplicate"] = marker
    return payload, marker


def _cap_payload_bytes(kind: str) -> tuple[bytes, str]:
    payload, marker = _payload_with_sensitive_values(kind)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), marker


def test_sensitive_collection_rejects_every_budget_overflow_without_secret_details():
    for kind in ("count", "bytes", "length"):
        payload, marker = _payload_with_sensitive_values(kind)

        with pytest.raises(NotesImportError) as error:
            _sanitize_payload(payload)

        message = str(error.value)
        assert marker not in message
        assert "2048" not in message
        assert "512" not in message
        assert "16384" not in message


def test_direct_matcher_rejects_overlong_value_instead_of_silently_skipping_it():
    with pytest.raises(NotesImportError):
        _SensitiveValueMatcher({"x" * (imports_notes_service._MAX_SENSITIVE_VALUE_LENGTH + 1)})


@pytest.mark.parametrize("kind", ("count", "bytes", "length"))
def test_exact_sensitive_value_budgets_are_accepted(kind):
    payload, _ = _payload_with_sensitive_values(kind)
    if kind == "count":
        for key in list(payload):
            if key.startswith("password2048"):
                payload.pop(key)
        payload.pop("publicDuplicate")
    elif kind == "bytes":
        payload.pop("password512")
        payload.pop("publicDuplicate")
    else:
        payload["password0"] = "l" * imports_notes_service._MAX_SENSITIVE_VALUE_LENGTH
        payload["publicDuplicate"] = "public value"

    sanitized = _sanitize_payload(payload)
    serialized = json.dumps(sanitized, ensure_ascii=False)
    assert "password" not in serialized.lower()


@pytest.mark.parametrize("kind", ("count", "bytes", "length"))
def test_staging_read_returns_omission_placeholder_for_budget_overflow(kind):
    raw, marker = _cap_payload_bytes(kind)

    sanitized = _staging_json_to_read(raw.decode("utf-8"), default={})

    assert sanitized == {READ_OMITTED_PLACEHOLDER: READ_OMITTED_PLACEHOLDER}
    assert marker not in json.dumps(sanitized, ensure_ascii=False)


@pytest.mark.parametrize("kind", ("count", "bytes", "length"))
def test_historical_document_read_omits_budget_overflow(kind):
    raw, marker = _cap_payload_bytes(kind)

    content = sanitize_document_for_read(filename="historical.json", raw_document_text=raw.decode("utf-8"))

    assert content == DOCUMENT_OMITTED_PLACEHOLDER
    assert marker not in content


def test_direct_conflict_read_omits_overlong_sensitive_conflict():
    marker = "SYNTHETIC_CONFLICT_LENGTH_CAP_" + (
        "c" * (imports_notes_service._MAX_SENSITIVE_VALUE_LENGTH - 29)
    )
    conflict = SimpleNamespace(
        id=uuid.uuid4(),
        target_entity="project",
        field_name="password",
        old_value=marker,
        new_value=marker,
        resolution="pending",
        resolved_by_person_id=None,
        resolved_at=None,
    )

    response = _conflict_to_read(conflict)

    assert response.field_name == READ_OMITTED_PLACEHOLDER
    assert response.old_value == READ_OMITTED_PLACEHOLDER
    assert response.new_value == READ_OMITTED_PLACEHOLDER
    assert marker not in response.model_dump_json()


@pytest.mark.parametrize("kind", ("count", "bytes", "length"))
def test_preview_rejects_budget_overflow_before_persistence(api_client, db_session, monkeypatch, kind):
    raw, marker = _cap_payload_bytes(kind)
    if kind == "length":
        monkeypatch.setattr(
            imports_notes_service,
            "_MAX_GENERIC_STRING_LENGTH",
            imports_notes_service._MAX_SENSITIVE_VALUE_LENGTH + 1,
        )

    response = api_client.post(
        "/api/imports/notes/preview",
        files={"file": (f"cap-{kind}.json", raw, "application/json")},
        headers={"X-Dev-User-Email": "comercial.sintetico@example.invalid"},
    )

    assert response.status_code == 400, response.text
    assert marker not in response.text
    assert "2048" not in response.text
    assert "512" not in response.text
    assert "16384" not in response.text
    assert db_session.query(FieldImportBatch).count() == 0


@pytest.mark.parametrize("kind", ("count", "bytes", "length"))
def test_historical_batch_conflict_and_document_endpoints_omit_affected_values(
    db_session, api_client, monkeypatch, kind
):
    raw, marker = _cap_payload_bytes(kind)
    if kind == "length":
        monkeypatch.setattr(
            imports_notes_service,
            "_MAX_GENERIC_STRING_LENGTH",
            imports_notes_service._MAX_SENSITIVE_VALUE_LENGTH + 1,
        )
    batch = FieldImportBatch(
        source_type="notes_json",
        source_filename=f"historical-cap-{kind}.json",
        source_file_hash=f"historical-cap-{kind}-hash",
        form_version="12",
        raw_payload_json=raw.decode("utf-8"),
        raw_document_text=raw.decode("utf-8"),
        status=BATCH_STATUS_PENDING_CONFIRMATION,
    )
    db_session.add(batch)
    db_session.flush()
    record = FieldImportRecord(
        batch_id=batch.id,
        is_new_project=True,
        match_strategy="none",
        candidate_project_ids_json="[]",
        mapped_fields_json=raw.decode("utf-8"),
    )
    db_session.add(record)
    db_session.flush()
    conflict = FieldImportConflict(
        record_id=record.id,
        target_entity="project",
        field_name="notes",
        old_value=marker,
        new_value=marker,
    )
    db_session.add(conflict)
    db_session.commit()

    headers = {"X-Dev-User-Email": "comercial.sintetico@example.invalid"}
    batch_response = api_client.get(f"/api/imports/{batch.id}", headers=headers)
    conflicts_response = api_client.get(f"/api/imports/{batch.id}/conflicts", headers=headers)
    document_response = api_client.get(f"/api/imports/{batch.id}/document", headers=headers)

    assert batch_response.status_code == 200, batch_response.text
    assert conflicts_response.status_code == 200, conflicts_response.text
    assert document_response.status_code == 200, document_response.text
    assert marker not in batch_response.text
    assert marker not in conflicts_response.text
    assert marker not in document_response.text
    assert READ_OMITTED_PLACEHOLDER in batch_response.text
    assert READ_OMITTED_PLACEHOLDER in conflicts_response.text
    assert document_response.json()["content"] == DOCUMENT_OMITTED_PLACEHOLDER

    # The cap failure must not turn a historical read into a persistence path.
    assert db_session.query(FieldImportBatch).count() == 1
    assert db_session.query(FieldImportRecord).count() == 1
    assert db_session.query(FieldImportConflict).count() == 1
