"""Importação das notas iniciais (`notas-iniciais-vNN.html`/`.json`) —
formulário usado pelo Comercial e pelo Sales Support. Ver
docs/DATA_IMPORTS.md para o desenho completo.

Regras de segurança inegociáveis:
- Nunca `eval`/`exec`/motor de JavaScript — HTML é lido como texto e o
  bloco `<script type="application/json" id="notas-iniciais-data">` é
  extraído com um parser HTML normal, nunca interpretado como código.
- Versão lida do conteúdo (`formVersion`), nunca do nome do ficheiro.
- Nunca escreve direto em `Project`/dados satélite — sempre
  preview (persistido em staging, `pending_confirmation`) → resolução de
  conflitos → `apply` explícito.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from html.parser import HTMLParser

from sqlalchemy.orm import Session

from app.audit.log import record_project_change
from app.models.imports import (
    BATCH_STATUS_APPLIED,
    BATCH_STATUS_PENDING_CONFIRMATION,
    CONFLICT_RESOLUTION_KEEP_OLD,
    CONFLICT_RESOLUTION_PENDING,
    CONFLICT_RESOLUTION_USE_NEW,
    RECORD_STATUS_APPLIED,
    SOURCE_TYPE_NOTES_HTML,
    SOURCE_TYPE_NOTES_JSON,
    FieldImportBatch,
    FieldImportConflict,
    FieldImportRecord,
)
from app.models.project import Project
from app.models.project_data import ProjectInstallationData, ProjectLicensingData
from app.services.project_data import upsert_installation_data, upsert_licensing_data

# Versões do formulário aceites — "v11" no nome do ficheiro pode conter
# conteúdo já na versão 12 (o nome do ficheiro nunca é a fonte de
# verdade); qualquer versão fora desta lista é rejeitada explicitamente.
COMPATIBLE_FORM_VERSIONS: frozenset[str] = frozenset({"11", "12"})

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".html", ".htm", ".json"})

SCRIPT_TAG_ID = "notas-iniciais-data"


class NotesImportError(ValueError):
    """Erro de negócio conhecido — mensagem sempre segura para mostrar."""


class DuplicateImportError(NotesImportError):
    pass


class _NotesScriptExtractor(HTMLParser):
    """Extrai só o texto de dentro de
    `<script type="application/json" id="notas-iniciais-data">` — nunca
    interpreta HTML/JS como código, só percorre a árvore de tags."""

    def __init__(self) -> None:
        super().__init__()
        self._capturing = False
        self.captured: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script":
            return
        attr_map = dict(attrs)
        if attr_map.get("id") == SCRIPT_TAG_ID:
            self._capturing = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script":
            self._capturing = False

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self.captured = (self.captured or "") + data


def compute_file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def extract_payload(*, filename: str, content: bytes) -> dict:
    """Devolve o payload JSON normalizado a partir de um `.json` solto ou
    de um `.html` com o bloco `<script id="notas-iniciais-data">`.
    Nunca executa o conteúdo — só extrai texto e faz `json.loads`."""
    lower_name = filename.lower()
    if lower_name.endswith(".json"):
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise NotesImportError("Ficheiro JSON com encoding inválido (esperado UTF-8).") from exc
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise NotesImportError(f"JSON inválido: {exc}") from exc

    if lower_name.endswith(".html") or lower_name.endswith(".htm"):
        try:
            html_text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise NotesImportError("Ficheiro HTML com encoding inválido (esperado UTF-8).") from exc
        extractor = _NotesScriptExtractor()
        extractor.feed(html_text)
        if not extractor.captured or not extractor.captured.strip():
            raise NotesImportError(
                "Não foi encontrado o bloco de dados estruturados "
                f'(<script type="application/json" id="{SCRIPT_TAG_ID}">) no HTML. '
                "Confirme que o formulário foi exportado com a versão que inclui esse bloco, "
                "ou envie o JSON em separado."
            )
        try:
            return json.loads(extractor.captured)
        except json.JSONDecodeError as exc:
            raise NotesImportError(f"O bloco de dados estruturados não é JSON válido: {exc}") from exc

    raise NotesImportError(f"Extensão de ficheiro não suportada: {filename!r} (use .html, .htm ou .json).")


def validate_payload(payload: dict) -> str:
    """Valida o mínimo exigível e devolve a versão do formulário. Nunca
    confia no nome do ficheiro para a versão."""
    if not isinstance(payload, dict):
        raise NotesImportError("O payload extraído não é um objeto JSON.")

    form_version = str(payload.get("formVersion") or "").strip()
    if not form_version:
        raise NotesImportError("O payload não indica 'formVersion' — versão do formulário desconhecida.")
    if form_version not in COMPATIBLE_FORM_VERSIONS:
        raise NotesImportError(
            f"Versão do formulário {form_version!r} não é compatível com este importador "
            f"(versões aceites: {', '.join(sorted(COMPATIBLE_FORM_VERSIONS))})."
        )

    cliente = str(payload.get("cliente") or "").strip()
    has_technical_field = any(
        payload.get(k) for k in ("paineis", "potenciaKwp", "inversores", "baterias")
    )
    if not cliente or not has_technical_field:
        raise NotesImportError(
            "Dados insuficientes para importar: é preciso pelo menos o nome do cliente e um campo "
            "técnico (painéis, potência, inversores ou baterias). Preencha os campos em falta manualmente."
        )
    return form_version


def _normalize(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.strip().lower().split())
    return normalized or None


def map_payload_to_fields(payload: dict) -> dict:
    """Traduz o payload das notas iniciais para os campos de
    `Project`/`ProjectInstallationData`/`ProjectLicensingData`. Campos sem
    tabela própria nesta versão (urgência, RGPD, controlador, divergências
    do Helioscope, pressupostos da proposta, anexos) ficam dobrados em
    `installation.notes`, nunca perdidos."""
    paineis = payload.get("paineis") or {}
    extra_notes_parts = []
    for label, key in (
        ("Urgência", "urgencia"),
        ("RGPD", "rgpd"),
        ("Controlador", "controlador"),
        ("Divergências do Helioscope", "divergenciasHelioscope"),
        ("Pressupostos da proposta", "pressupostosProposta"),
    ):
        value = payload.get(key)
        if value not in (None, ""):
            extra_notes_parts.append(f"{label}: {value}")
    anexos = payload.get("anexos") or []
    if anexos:
        extra_notes_parts.append(f"Anexos: {', '.join(str(a) for a in anexos)}")
    observacoes = payload.get("observacoes")
    if observacoes:
        extra_notes_parts.append(str(observacoes))
    combined_notes = "\n".join(extra_notes_parts)

    project_fields = {
        "client_name": payload.get("cliente"),
        "client_contact": payload.get("contacto"),
        "client_email": payload.get("email"),
        "address": payload.get("morada"),
        "lat": payload.get("lat"),
        "lon": payload.get("lon"),
        "power_kwp": payload.get("potenciaKwp"),
    }
    installation_fields = {
        "client_nif": payload.get("nif"),
        "contact_person_name": payload.get("contacto"),
        "contact_person_role": payload.get("funcao"),
        "contact_email": payload.get("email"),
        "contact_phone": payload.get("telefone"),
        "address": payload.get("morada"),
        "district": payload.get("distrito"),
        "municipality": payload.get("concelho"),
        "power_kwp": payload.get("potenciaKwp"),
        "panel_count": paineis.get("quantidade"),
        "panel_power_wp": paineis.get("potenciaWp"),
        "inverters": payload.get("inversores"),
        "batteries": payload.get("baterias"),
        "has_backup": payload.get("backup"),
        "ev_chargers": payload.get("carregadoresVe"),
        "installation_type": payload.get("tipoInstalacao"),
        "injection_type": payload.get("injecao"),
        "om_notes": payload.get("om"),
        "notes": combined_notes,
    }
    licensing_fields = {}
    if payload.get("upacExistente"):
        licensing_fields["upac_number"] = payload.get("upacExistente")

    return {
        "project": {k: v for k, v in project_fields.items() if v not in (None, "")},
        "installation": {k: v for k, v in installation_fields.items() if v not in (None, "")},
        "licensing": {k: v for k, v in licensing_fields.items() if v not in (None, "")},
    }


def find_matching_projects(db: Session, mapped: dict) -> tuple[list[Project], str]:
    """Procura projeto existente por email, depois telefone, depois
    morada normalizada — nunca por nome (D-004). Devolve os candidatos e
    a estratégia usada."""
    email = mapped["project"].get("client_email")
    if email:
        matches = db.query(Project).filter(Project.client_email == email).all()
        if matches:
            return matches, "email"

    phone = mapped["installation"].get("contact_phone")
    if phone:
        matches = (
            db.query(Project)
            .join(ProjectInstallationData, ProjectInstallationData.project_id == Project.id)
            .filter(ProjectInstallationData.contact_phone == phone)
            .all()
        )
        if matches:
            return matches, "phone"

    address = mapped["project"].get("address")
    normalized_address = _normalize(address)
    if normalized_address:
        candidates = db.query(Project).filter(Project.address.isnot(None)).all()
        matches = [p for p in candidates if _normalize(p.address) == normalized_address]
        if matches:
            return matches, "address"

    return [], "none"


def preview_notes_import(
    db: Session, *, filename: str, content: bytes, uploaded_by_person_id: uuid.UUID | None
) -> FieldImportBatch:
    if len(content) > MAX_UPLOAD_BYTES:
        raise NotesImportError(f"Ficheiro demasiado grande (máximo {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")
    lower_name = filename.lower()
    if not any(lower_name.endswith(ext) for ext in ALLOWED_EXTENSIONS):
        raise NotesImportError(f"Extensão não permitida — use {', '.join(sorted(ALLOWED_EXTENSIONS))}.")

    file_hash = compute_file_hash(content)
    existing = db.query(FieldImportBatch).filter(FieldImportBatch.source_file_hash == file_hash).one_or_none()
    if existing is not None:
        if existing.status == BATCH_STATUS_APPLIED:
            raise DuplicateImportError(
                f"Este ficheiro já foi importado (lote {existing.id}, aplicado em {existing.applied_at})."
            )
        # Ainda não aplicado (pending_confirmation/rejected): devolve o
        # lote já existente em vez de duplicar — preview é idempotente
        # pelo hash do ficheiro.
        return existing

    payload = extract_payload(filename=filename, content=content)
    form_version = validate_payload(payload)
    mapped = map_payload_to_fields(payload)
    candidates, strategy = find_matching_projects(db, mapped)

    source_type = SOURCE_TYPE_NOTES_JSON if lower_name.endswith(".json") else SOURCE_TYPE_NOTES_HTML
    batch = FieldImportBatch(
        source_type=source_type,
        source_filename=filename,
        source_file_hash=file_hash,
        form_version=form_version,
        raw_payload_json=json.dumps(payload, ensure_ascii=False),
        status=BATCH_STATUS_PENDING_CONFIRMATION,
        started_by_person_id=uploaded_by_person_id,
    )
    db.add(batch)
    db.flush()

    is_new = len(candidates) == 0
    target_project = candidates[0] if len(candidates) == 1 else None
    record = FieldImportRecord(
        batch_id=batch.id,
        target_project_id=target_project.id if target_project else None,
        is_new_project=is_new,
        match_strategy="ambiguous" if len(candidates) > 1 else strategy,
        candidate_project_ids_json=json.dumps([str(p.id) for p in candidates]),
        mapped_fields_json=json.dumps(mapped, ensure_ascii=False),
    )
    db.add(record)
    db.flush()

    if target_project is not None:
        _create_conflicts_for_record(db, record=record, target_project=target_project, mapped=mapped)

    db.commit()
    db.refresh(batch)
    return batch


def _create_conflicts_for_record(
    db: Session, *, record: FieldImportRecord, target_project: Project, mapped: dict
) -> None:
    for field_name, new_value in mapped["project"].items():
        old_value = getattr(target_project, field_name, None)
        if old_value is not None and str(old_value) != str(new_value):
            db.add(
                FieldImportConflict(
                    record_id=record.id,
                    target_entity="project",
                    field_name=field_name,
                    old_value=str(old_value),
                    new_value=str(new_value),
                )
            )

    installation = (
        db.query(ProjectInstallationData).filter(ProjectInstallationData.project_id == target_project.id).one_or_none()
    )
    if installation is not None:
        for field_name, new_value in mapped["installation"].items():
            old_value = getattr(installation, field_name, None)
            if old_value is not None and str(old_value) != str(new_value):
                db.add(
                    FieldImportConflict(
                        record_id=record.id,
                        target_entity="installation",
                        field_name=field_name,
                        old_value=str(old_value),
                        new_value=str(new_value),
                    )
                )

    licensing = (
        db.query(ProjectLicensingData).filter(ProjectLicensingData.project_id == target_project.id).one_or_none()
    )
    if licensing is not None:
        for field_name, new_value in mapped["licensing"].items():
            old_value = getattr(licensing, field_name, None)
            if old_value is not None and str(old_value) != str(new_value):
                db.add(
                    FieldImportConflict(
                        record_id=record.id,
                        target_entity="licensing",
                        field_name=field_name,
                        old_value=str(old_value),
                        new_value=str(new_value),
                    )
                )


def resolve_conflict(
    db: Session, *, conflict: FieldImportConflict, resolution: str, resolved_by_person_id: uuid.UUID | None
) -> FieldImportConflict:
    if resolution not in (CONFLICT_RESOLUTION_USE_NEW, CONFLICT_RESOLUTION_KEEP_OLD):
        raise NotesImportError(f"Resolução inválida: {resolution!r}.")
    conflict.resolution = resolution
    conflict.resolved_by_person_id = resolved_by_person_id
    conflict.resolved_at = dt.datetime.now(dt.timezone.utc)
    db.commit()
    db.refresh(conflict)
    return conflict


def apply_notes_import(
    db: Session,
    *,
    batch: FieldImportBatch,
    target_project_id: uuid.UUID | None,
    applied_by_person_id: uuid.UUID | None,
) -> Project:
    """Escreve os dados em `Project`/dados satélite — só aqui, nunca no
    preview. Exige que todos os conflitos estejam resolvidos
    (`use_new`/`keep_old`), e que uma ambiguidade de candidatos tenha sido
    desfeita com um `target_project_id` explícito."""
    if batch.status != BATCH_STATUS_PENDING_CONFIRMATION:
        raise NotesImportError(f"Lote já processado (estado atual: {batch.status!r}).")

    record = batch.records[0] if batch.records else None
    if record is None:
        raise NotesImportError("Lote sem registo — nada para aplicar.")

    pending = [c for c in record.conflicts if c.resolution == CONFLICT_RESOLUTION_PENDING]
    if pending:
        raise NotesImportError(
            f"Existem {len(pending)} conflito(s) por resolver — resolva-os antes de aplicar."
        )

    if record.match_strategy == "ambiguous" and target_project_id is None:
        raise NotesImportError(
            "Vários projetos correspondem a estes dados — indique target_project_id explicitamente."
        )

    mapped = json.loads(record.mapped_fields_json)
    project: Project
    if record.is_new_project and target_project_id is None:
        project = Project(name=mapped["project"].get("client_name") or "Projeto sem nome (importação)")
        for field_name, value in mapped["project"].items():
            setattr(project, field_name, value)
        db.add(project)
        db.flush()
    else:
        resolved_id = target_project_id or record.target_project_id
        project = db.get(Project, resolved_id)
        if project is None:
            raise NotesImportError("Projeto alvo não encontrado.")
        conflict_fields = {c.field_name: c.resolution for c in record.conflicts if c.target_entity == "project"}
        for field_name, new_value in mapped["project"].items():
            resolution = conflict_fields.get(field_name)
            if resolution == CONFLICT_RESOLUTION_KEEP_OLD:
                continue
            old_value = getattr(project, field_name)
            if str(old_value) == str(new_value):
                continue
            record_project_change(
                db,
                project_id=project.id,
                field_name=field_name,
                old_value=str(old_value) if old_value is not None else None,
                new_value=str(new_value) if new_value is not None else None,
                source="import_notes",
                changed_by_person_id=applied_by_person_id,
                note=f"Importação de notas iniciais (lote {batch.id}).",
            )
            setattr(project, field_name, new_value)

    db.flush()

    installation_changes = dict(mapped["installation"])
    installation_conflicts = {c.field_name: c.resolution for c in record.conflicts if c.target_entity == "installation"}
    for field_name, resolution in installation_conflicts.items():
        if resolution == CONFLICT_RESOLUTION_KEEP_OLD:
            installation_changes.pop(field_name, None)
    if installation_changes:
        upsert_installation_data(
            db,
            project_id=project.id,
            changes=installation_changes,
            changed_by_person_id=applied_by_person_id,
            source="import_notes",
        )

    licensing_changes = dict(mapped["licensing"])
    licensing_conflicts = {c.field_name: c.resolution for c in record.conflicts if c.target_entity == "licensing"}
    for field_name, resolution in licensing_conflicts.items():
        if resolution == CONFLICT_RESOLUTION_KEEP_OLD:
            licensing_changes.pop(field_name, None)
    if licensing_changes:
        upsert_licensing_data(
            db,
            project_id=project.id,
            changes=licensing_changes,
            changed_by_person_id=applied_by_person_id,
            source="import_notes",
        )

    record.status = RECORD_STATUS_APPLIED
    record.promoted_project_id = project.id
    batch.status = BATCH_STATUS_APPLIED
    batch.applied_by_person_id = applied_by_person_id
    batch.applied_at = dt.datetime.now(dt.timezone.utc)
    db.commit()
    db.refresh(project)
    return project
