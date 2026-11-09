"""Importação do Excel de licenciamento (`SIM card Numbers Projects.xlsx`)
— ver docs/DATA_IMPORTS.md. Nunca lê/escreve o ficheiro original no
repositório (só fixtures sintéticas). Leitura só (`read_only=True`),
nunca escreve no ficheiro de origem.

Reaproveita os mesmos modelos genéricos de staging da importação de
notas iniciais (`FieldImportBatch`/`FieldImportRecord`/
`FieldImportConflict`, `source_type='licensing_excel'`) — o desenho de
staging→conflitos→confirmação é o mesmo, só a extração de dados muda.

Segurança: allowlist explícita de colunas aceites por folha — uma coluna
não reconhecida é sempre ignorada e reportada, nunca importada "por
precaução". Additionally, qualquer coluna cujo cabeçalho contenha uma
palavra de credencial (`FORBIDDEN_HEADER_KEYWORDS`) é sempre ignorada,
mesmo que por engano tivesse sido adicionada à allowlist — defesa em
profundidade.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import io
import json
import re
import unicodedata
import uuid

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

from app.audit.log import record_project_change
from app.config import Settings, get_settings
from app.models.imports import (
    BATCH_STATUS_APPLIED,
    BATCH_STATUS_PENDING_CONFIRMATION,
    RECORD_STATUS_APPLIED,
    SOURCE_TYPE_LICENSING_EXCEL,
    FieldImportBatch,
    FieldImportConflict,
    FieldImportRecord,
    SurplusContract,
)
from app.models.project import Project, ProjectExternalId, ProjectHistory
from app.models.project_data import (
    ProjectCommunicationData,
    ProjectDataHistory,
    ProjectInstallationData,
    ProjectLicensingData,
    ProjectPortalCredential,
    ProjectSimCard,
    ProjectSurplusContract,
)
from app.security.secret_box import SecretBoxDecryptError, SecretBoxUnavailable, decrypt_secret, encrypt_secret
from app.services.project_data import (
    ENTITY_TYPE_CREDENTIAL,
    ENTITY_TYPE_SIM,
    ENTITY_TYPE_SURPLUS,
    PASSWORD_HISTORY_MARKER,
    SECRET_HISTORY_MARKER,
    create_sim_card,
    update_sim_card,
    upsert_communication_data,
    upsert_installation_data,
    upsert_licensing_data,
)

LEGACY_SOURCE_SYSTEM = "legacy_excel_licensing"
SIM_NOMENCLATURE_SOURCE_SYSTEM = "solcor_nomenclatura_xlsx"
_SIM_PROJECT_NUMBER_PREFIX = re.compile(r"^\s*(\d+)_")
SIM_SAFE_ONLY_VERSION = "sim-safe-only-v1"

# entity_type (ProjectDataHistory) -> modelo — usado pelo rollback para
# saber em que tabela reaplicar o valor anterior.
_ENTITY_MODEL_BY_TYPE = {
    "installation": ProjectInstallationData,
    "licensing": ProjectLicensingData,
    "communication": ProjectCommunicationData,
}

SHEET1_NAME = "Sheet1"
DADOS_GERAIS_NAME = "Dados gerais"
SURPLUS_SHEET_NAME = "Venda do excedente"

FORBIDDEN_HEADER_KEYWORDS: frozenset[str] = frozenset(
    {"pin", "puk", "password", "senha", "login", "username", "utilizador", "token", "credencial", "credential"}
)

# Allowlist por folha: cabeçalho normalizado (minúsculas, sem espaços a
# mais) -> chave interna. Uma coluna fora desta lista é sempre ignorada.
SHEET1_COLUMNS: dict[str, str] = {
    "project_number": "project_number",
    "project_name": "project_name",
    "client_name": "client_name",
    "nif": "nif",
    "type": "type",
    "internal_reference": "internal_reference",
    "date": "date",
    "adress": "address",
    "address": "address",
    "location": "location",
    "panel_count": "panel_count",
    "panel_power_wp": "panel_power_wp",
    "power_kwp": "power_kwp",
    "installation_type": "installation_type",
    "injection": "injection",
    "batteries": "batteries",
    "chargers": "chargers",
    "vendedor": "vendedor",
    "om": "om",
    "estado": "estado",
    "contacts": "contacts",
    "notes": "notes",
    "contracted_month_year": "contracted_month_year",
}

DADOS_GERAIS_COLUMNS: dict[str, str] = {
    "internal_reference": "internal_reference",
    "m2m_number": "m2m_number",
    "operator": "operator",
    "upac_number": "upac_number",
    "registration": "registration",
    "cadastro": "cadastro",
    "licensing_status": "licensing_status",
    "inspecting_entity": "inspecting_entity",
    "inspection_date": "inspection_date",
    "certificate_date": "certificate_date",
    "email": "email",
    "power_kwp": "power_kwp",
    "modules": "modules",
    "inverters": "inverters",
    "installer": "installer",
    "production_kwh": "production_kwh",
    "location": "location",
    "contract": "contract",
    "contact": "contact",
    "comments": "comments",
}

SURPLUS_COLUMNS: dict[str, str] = {
    "internal_reference": "internal_reference",
    "commercializer": "commercializer",
    "contract_type": "contract_type",
    "status": "status",
    "sent_date": "sent_date",
    "signed_date": "signed_date",
    "duration": "duration",
    "start_date": "start_date",
    "end_date": "end_date",
    "notes": "notes",
}


class LicensingImportError(ValueError):
    pass


class DuplicateLicensingImportError(LicensingImportError):
    pass


def compute_file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _normalize_header(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split()).replace(" ", "_")


def _read_sheet_rows(ws, allowed_columns: dict[str, str]) -> tuple[list[dict], list[str]]:
    rows_iter = ws.iter_rows(values_only=True)
    try:
        header_row = next(rows_iter)
    except StopIteration:
        return [], []

    column_index: dict[int, str] = {}
    ignored_columns: list[str] = []
    for idx, raw_header in enumerate(header_row):
        if raw_header is None:
            continue
        normalized = _normalize_header(raw_header)
        if any(keyword in normalized for keyword in FORBIDDEN_HEADER_KEYWORDS):
            ignored_columns.append(str(raw_header))
            continue
        field_name = allowed_columns.get(normalized)
        if field_name is None:
            ignored_columns.append(str(raw_header))
            continue
        column_index[idx] = field_name

    rows: list[dict] = []
    for raw_row in rows_iter:
        if raw_row is None or all(v is None for v in raw_row):
            continue
        row: dict = {}
        for idx, field_name in column_index.items():
            if idx < len(raw_row) and raw_row[idx] not in (None, ""):
                value = raw_row[idx]
                if isinstance(value, dt.datetime):
                    value = value.date()
                row[field_name] = value
        if row:
            rows.append(row)
    return rows, ignored_columns


@dataclasses.dataclass
class ParsedWorkbook:
    project_rows: list[dict]
    surplus_rows: list[dict]
    ignored_columns: dict[str, list[str]]


def parse_workbook(content: bytes) -> ParsedWorkbook:
    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - openpyxl raises several exception types for bad files
        raise LicensingImportError(f"Não foi possível ler o ficheiro Excel: {exc}") from exc

    ignored: dict[str, list[str]] = {}
    sheet1_rows: list[dict] = []
    dados_gerais_rows: list[dict] = []
    surplus_rows: list[dict] = []

    if SHEET1_NAME in wb.sheetnames:
        sheet1_rows, ignored[SHEET1_NAME] = _read_sheet_rows(wb[SHEET1_NAME], SHEET1_COLUMNS)
    if DADOS_GERAIS_NAME in wb.sheetnames:
        dados_gerais_rows, ignored[DADOS_GERAIS_NAME] = _read_sheet_rows(wb[DADOS_GERAIS_NAME], DADOS_GERAIS_COLUMNS)
    if SURPLUS_SHEET_NAME in wb.sheetnames:
        surplus_rows, ignored[SURPLUS_SHEET_NAME] = _read_sheet_rows(wb[SURPLUS_SHEET_NAME], SURPLUS_COLUMNS)

    if not sheet1_rows and not dados_gerais_rows:
        # Chegar aqui pelo CLI significa que `detect_layout` também não viu o cabeçalho SIM: a
        # mensagem tem de dizer isso, senão um ficheiro SIM com o cabeçalho deslocado parece
        # um problema do layout legado.
        raise LicensingImportError(
            "Layout do ficheiro não reconhecido: nenhuma linha reconhecida em "
            f"'{SHEET1_NAME}' nem '{DADOS_GERAIS_NAME}' (layout legado) e o cabeçalho do layout SIM "
            f"não bate (esperado na linha {SIM_HEADER_ROW} de '{DADOS_GERAIS_NAME}') — confirme o ficheiro."
        )

    by_ref: dict[str, dict] = {}
    for row in sheet1_rows:
        ref = str(row.get("internal_reference") or "").strip()
        if not ref:
            continue  # sem Internal_reference, a linha não pode ser ligada com confiança — ignorada, reportada via contagem
        by_ref.setdefault(ref, {})["sheet1"] = row
    for row in dados_gerais_rows:
        ref = str(row.get("internal_reference") or "").strip()
        if not ref:
            continue
        by_ref.setdefault(ref, {})["dados_gerais"] = row

    project_rows = [{"internal_reference": ref, **parts} for ref, parts in by_ref.items()]
    return ParsedWorkbook(project_rows=project_rows, surplus_rows=surplus_rows, ignored_columns=ignored)


def _map_project_fields(parts: dict) -> dict:
    sheet1 = parts.get("sheet1", {})
    dados_gerais = parts.get("dados_gerais", {})

    project_fields = {
        k: v
        for k, v in {
            "name": sheet1.get("project_name"),
            "client_name": sheet1.get("client_name"),
            "address": sheet1.get("address"),
            "start_date": sheet1.get("date") if isinstance(sheet1.get("date"), dt.date) else None,
            "power_kwp": sheet1.get("power_kwp") or dados_gerais.get("power_kwp"),
            "client_contact": sheet1.get("contacts") or dados_gerais.get("contact"),
        }.items()
        if v not in (None, "")
    }

    notes_parts = []
    for label, value in (
        ("Vendedor", sheet1.get("vendedor")),
        ("Estado (legado Excel)", sheet1.get("estado")),
        ("Contratação", sheet1.get("contracted_month_year")),
        ("Notas", sheet1.get("notes")),
    ):
        if value not in (None, ""):
            notes_parts.append(f"{label}: {value}")

    installation_fields = {
        k: v
        for k, v in {
            "client_nif": sheet1.get("nif"),
            "installation_type": sheet1.get("type") or sheet1.get("installation_type"),
            "address": sheet1.get("address") or dados_gerais.get("location"),
            "district": dados_gerais.get("location"),
            "panel_count": sheet1.get("panel_count") or dados_gerais.get("modules"),
            "panel_power_wp": sheet1.get("panel_power_wp"),
            "power_kwp": sheet1.get("power_kwp") or dados_gerais.get("power_kwp"),
            "injection_type": sheet1.get("injection"),
            "batteries": sheet1.get("batteries"),
            "ev_chargers": sheet1.get("chargers"),
            "om_notes": sheet1.get("om"),
            "contact_email": dados_gerais.get("email"),
            "inverters": dados_gerais.get("inverters"),
            "notes": "\n".join(notes_parts) if notes_parts else None,
        }.items()
        if v not in (None, "")
    }

    licensing_fields = {
        k: v
        for k, v in {
            "upac_number": dados_gerais.get("upac_number"),
            "cadastro_number": dados_gerais.get("cadastro"),
            "licensing_status": dados_gerais.get("licensing_status") or dados_gerais.get("registration"),
            "inspecting_entity": dados_gerais.get("inspecting_entity"),
            "inspection_date": dados_gerais.get("inspection_date")
            if isinstance(dados_gerais.get("inspection_date"), dt.date)
            else None,
            "certificate_date": dados_gerais.get("certificate_date")
            if isinstance(dados_gerais.get("certificate_date"), dt.date)
            else None,
            "installer": dados_gerais.get("installer"),
            "annual_production_kwh": dados_gerais.get("production_kwh"),
            "comments": "; ".join(
                str(v) for v in (dados_gerais.get("contract"), dados_gerais.get("comments")) if v not in (None, "")
            )
            or None,
        }.items()
        if v not in (None, "")
    }

    # Cartão SIM (lista em `project_sim_cards`): só nº e operador. PIN/PUK
    # nunca são lidos (ver FORBIDDEN_HEADER_KEYWORDS).
    communication_fields = {
        k: v
        for k, v in {
            "phone_number": dados_gerais.get("m2m_number"),
            "operator": dados_gerais.get("operator"),
        }.items()
        if v not in (None, "")
    }

    return {
        "project": project_fields,
        "installation": installation_fields,
        "licensing": licensing_fields,
        "communication": communication_fields,
    }


def find_project_by_external_reference(db: Session, internal_reference: str) -> Project | None:
    """Corresponde sempre por `Internal_reference` via `ProjectExternalId`
    — nunca por `Project_number` isolado (existem duplicados no legado).
    Projetos removidos logicamente não são alvos de importação."""
    return (
        db.query(Project)
        .join(ProjectExternalId, ProjectExternalId.project_id == Project.id)
        .filter(
            ProjectExternalId.source_system == LEGACY_SOURCE_SYSTEM,
            ProjectExternalId.external_id == internal_reference,
            Project.deleted_at.is_(None),
        )
        .one_or_none()
    )


def _external_reference_points_to_deleted_project(db: Session, internal_reference: str) -> bool:
    return (
        db.query(Project.id)
        .join(ProjectExternalId, ProjectExternalId.project_id == Project.id)
        .filter(
            ProjectExternalId.source_system == LEGACY_SOURCE_SYSTEM,
            ProjectExternalId.external_id == internal_reference,
            Project.deleted_at.is_not(None),
        )
        .first()
        is not None
    )


def _reject_deleted_licensing_targets(db: Session, references) -> None:
    if any(_external_reference_points_to_deleted_project(db, reference) for reference in references):
        raise LicensingImportError(
            "A importação contém uma referência associada a um projeto apagado; nada foi aplicado."
        )


_DATE_FIELDS_BY_SECTION: dict[str, tuple[str, ...]] = {
    "project": ("start_date",),
    "licensing": ("inspection_date", "certificate_date"),
}


def _reparse_dates_after_json_roundtrip(mapped: dict) -> dict:
    """`FieldImportRecord.mapped_fields_json` guarda `date` como texto ISO
    (`json.dumps(..., default=str)`) — ao reler (`_finalize_licensing_batch`,
    possivelmente numa chamada posterior depois de resolver conflitos),
    os campos de data têm de voltar a `datetime.date`, senão o SQLAlchemy
    rejeita a escrita (`SQLite Date type only accepts Python date
    objects`)."""
    for section, fields in _DATE_FIELDS_BY_SECTION.items():
        section_dict = mapped.get(section)
        if not section_dict:
            continue
        for field_name in fields:
            value = section_dict.get(field_name)
            if isinstance(value, str):
                try:
                    section_dict[field_name] = dt.date.fromisoformat(value)
                except ValueError:
                    section_dict.pop(field_name, None)
    return mapped


def _diff_conflicts(existing_obj, mapped_fields: dict) -> list[tuple[str, object, object]]:
    conflicts = []
    for field_name, new_value in mapped_fields.items():
        old_value = getattr(existing_obj, field_name, None)
        if old_value not in (None, "") and str(old_value) != str(new_value):
            conflicts.append((field_name, old_value, new_value))
    return conflicts


@dataclasses.dataclass
class LicensingImportSummary:
    batch_id: uuid.UUID | None
    total_projects: int
    new_projects: int
    existing_projects: int
    total_conflicts: int
    surplus_contracts_linked: int
    surplus_contracts_unlinked: int
    ignored_columns: dict[str, list[str]]


def dry_run_licensing_import(db: Session, *, content: bytes) -> LicensingImportSummary:
    """Só leitura — nunca escreve nada na base de dados."""
    parsed = parse_workbook(content)
    _reject_deleted_licensing_targets(
        db, (row["internal_reference"] for row in parsed.project_rows)
    )
    new_count = 0
    existing_count = 0
    conflict_count = 0
    for row in parsed.project_rows:
        mapped = _map_project_fields(row)
        existing = find_project_by_external_reference(db, row["internal_reference"])
        if existing is None:
            new_count += 1
        else:
            existing_count += 1
            conflict_count += len(_diff_conflicts(existing, mapped["project"]))

    linked = 0
    unlinked = 0
    known_refs = {row["internal_reference"] for row in parsed.project_rows}
    for surplus_row in parsed.surplus_rows:
        ref = str(surplus_row.get("internal_reference") or "").strip()
        if ref and (ref in known_refs or find_project_by_external_reference(db, ref) is not None):
            linked += 1
        else:
            unlinked += 1

    return LicensingImportSummary(
        batch_id=None,
        total_projects=len(parsed.project_rows),
        new_projects=new_count,
        existing_projects=existing_count,
        total_conflicts=conflict_count,
        surplus_contracts_linked=linked,
        surplus_contracts_unlinked=unlinked,
        ignored_columns=parsed.ignored_columns,
    )


def apply_licensing_import(
    db: Session, *, filename: str, content: bytes, applied_by_person_id: uuid.UUID | None
) -> LicensingImportSummary:
    """Persiste o lote (staging) e aplica de imediato os registos sem
    conflitos; registos com conflitos ficam por resolver via
    `POST /api/imports/conflicts/{id}/resolve`. Chamar `--apply` outra vez
    com o MESMO ficheiro (mesmo hash) nunca duplica o lote — resume-o,
    aplicando os registos cujos conflitos entretanto foram resolvidos
    (idempotente, mesmo princípio da importação de notas)."""
    file_hash = compute_file_hash(content)
    existing_batch = db.query(FieldImportBatch).filter(FieldImportBatch.source_file_hash == file_hash).one_or_none()
    if existing_batch is not None:
        if existing_batch.status == BATCH_STATUS_APPLIED:
            raise DuplicateLicensingImportError(
                f"Este ficheiro já foi importado (lote {existing_batch.id}, aplicado em {existing_batch.applied_at})."
            )
        return _finalize_licensing_batch(db, batch=existing_batch, applied_by_person_id=applied_by_person_id)

    parsed = parse_workbook(content)
    _reject_deleted_licensing_targets(
        db, (row["internal_reference"] for row in parsed.project_rows)
    )

    batch = FieldImportBatch(
        source_type=SOURCE_TYPE_LICENSING_EXCEL,
        source_filename=filename,
        source_file_hash=file_hash,
        raw_payload_json=json.dumps({"ignored_columns": parsed.ignored_columns}, ensure_ascii=False),
        status=BATCH_STATUS_PENDING_CONFIRMATION,
        started_by_person_id=applied_by_person_id,
    )
    db.add(batch)
    db.flush()

    for row in parsed.project_rows:
        mapped = _map_project_fields(row)
        existing = find_project_by_external_reference(db, row["internal_reference"])

        record = FieldImportRecord(
            batch_id=batch.id,
            target_project_id=existing.id if existing else None,
            is_new_project=existing is None,
            match_strategy="internal_reference" if existing else "none",
            mapped_fields_json=json.dumps(
                {**mapped, "internal_reference": row["internal_reference"]}, ensure_ascii=False, default=str
            ),
        )
        db.add(record)
        db.flush()

        conflicts = _diff_conflicts(existing, mapped["project"]) if existing else []
        for field_name, old_value, new_value in conflicts:
            db.add(
                FieldImportConflict(
                    record_id=record.id,
                    target_entity="project",
                    field_name=field_name,
                    old_value=str(old_value),
                    new_value=str(new_value),
                )
            )

    for surplus_row in parsed.surplus_rows:
        ref = str(surplus_row.get("internal_reference") or "").strip()
        target_project = find_project_by_external_reference(db, ref) if ref else None
        db.add(
            SurplusContract(
                project_id=target_project.id if target_project else None,
                internal_reference_raw=ref or None,
                commercializer=surplus_row.get("commercializer"),
                contract_type=surplus_row.get("contract_type"),
                status=surplus_row.get("status"),
                sent_date=surplus_row.get("sent_date") if isinstance(surplus_row.get("sent_date"), dt.date) else None,
                signed_date=surplus_row.get("signed_date")
                if isinstance(surplus_row.get("signed_date"), dt.date)
                else None,
                duration=str(surplus_row.get("duration")) if surplus_row.get("duration") is not None else None,
                start_date=surplus_row.get("start_date")
                if isinstance(surplus_row.get("start_date"), dt.date)
                else None,
                end_date=surplus_row.get("end_date") if isinstance(surplus_row.get("end_date"), dt.date) else None,
                notes=str(surplus_row.get("notes") or ""),
                import_batch_id=batch.id,
            )
        )

    db.commit()
    return _finalize_licensing_batch(db, batch=batch, applied_by_person_id=applied_by_person_id)


def _finalize_licensing_batch(
    db: Session, *, batch: FieldImportBatch, applied_by_person_id: uuid.UUID | None
) -> LicensingImportSummary:
    """Aplica todos os registos do lote cujos conflitos já estão todos
    resolvidos; deixa por resolver os restantes. Chamável tantas vezes
    quantas forem necessárias (idempotente) — cada registo só é aplicado
    uma vez (`record.status == RECORD_STATUS_APPLIED` protege-o)."""
    applied_now = 0
    still_pending = 0
    for record in batch.records:
        if record.status == RECORD_STATUS_APPLIED:
            continue
        pending_conflicts = [c for c in record.conflicts if c.resolution == "pending"]
        if pending_conflicts:
            still_pending += 1
            continue

        mapped = _reparse_dates_after_json_roundtrip(json.loads(record.mapped_fields_json))
        internal_reference = mapped.get("internal_reference", "")
        existing = None
        if record.target_project_id is not None:
            project_query = (
                db.query(Project)
                .populate_existing()
                .filter(Project.id == record.target_project_id, Project.deleted_at.is_(None))
            )
            if db.get_bind().dialect.name == "postgresql":
                project_query = project_query.with_for_update()
            existing = project_query.one_or_none()
            if existing is None:
                for contract in (
                    db.query(SurplusContract)
                    .filter(
                        SurplusContract.import_batch_id == batch.id,
                        SurplusContract.internal_reference_raw == internal_reference,
                        SurplusContract.project_id == record.target_project_id,
                    )
                    .all()
                ):
                    contract.project_id = None
                still_pending += 1
                continue
        elif _external_reference_points_to_deleted_project(db, internal_reference):
            still_pending += 1
            continue
        project = _write_project_record(
            db,
            existing=existing,
            internal_reference=internal_reference,
            mapped=mapped,
            applied_by_person_id=applied_by_person_id,
            batch_id=batch.id,
        )
        record.status = RECORD_STATUS_APPLIED
        record.target_project_id = project.id
        record.promoted_project_id = project.id
        applied_now += 1

        # Liga agora as vendas de excedente deste lote que apontavam para
        # este `internal_reference` mas ainda não tinham projeto (porque
        # o projeto era novo, criado só agora).
        for contract in (
            db.query(SurplusContract)
            .filter(SurplusContract.import_batch_id == batch.id, SurplusContract.project_id.is_(None))
            .all()
        ):
            if contract.internal_reference_raw == internal_reference:
                contract.project_id = project.id

    total_records = len(batch.records)
    applied_total = sum(1 for r in batch.records if r.status == RECORD_STATUS_APPLIED)
    all_applied = applied_total == total_records
    batch.status = BATCH_STATUS_APPLIED if all_applied else BATCH_STATUS_PENDING_CONFIRMATION
    if all_applied:
        batch.applied_by_person_id = applied_by_person_id
        batch.applied_at = dt.datetime.now(dt.timezone.utc)
        _record_rollback_guards(db, batch=batch)
    db.commit()

    surplus_contracts = db.query(SurplusContract).filter(SurplusContract.import_batch_id == batch.id).all()
    linked = sum(1 for c in surplus_contracts if c.project_id is not None)
    unlinked = sum(1 for c in surplus_contracts if c.project_id is None)

    ignored_columns: dict[str, list[str]] = {}
    try:
        ignored_columns = json.loads(batch.raw_payload_json or "{}").get("ignored_columns", {})
    except (ValueError, TypeError):
        pass

    return LicensingImportSummary(
        batch_id=batch.id,
        total_projects=total_records,
        new_projects=applied_now,
        existing_projects=still_pending,
        total_conflicts=still_pending,
        surplus_contracts_linked=linked,
        surplus_contracts_unlinked=unlinked,
        ignored_columns=ignored_columns,
    )


def _batch_note(batch_id: uuid.UUID) -> str:
    return f"Importação do Excel de licenciamento (lote {batch_id})."


_ROLLBACK_GUARD_FIELD = "__rollback_guard__"
_ROLLBACK_REFUSED_MESSAGE = (
    "Rollback recusado: foram detetadas alterações posteriores ao lote; nenhum campo foi revertido."
)


def _rollback_snapshot_digest(instance) -> str:
    """Hash do estado persistido do registo; tokens cifrados entram só no digest."""
    snapshot = {
        column.name: getattr(instance, column.name)
        for column in instance.__table__.columns
        if column.name not in ("created_at", "updated_at")
    }
    encoded = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _record_rollback_guards(db: Session, *, batch: FieldImportBatch) -> None:
    """Regista snapshots opacos append-only dos alvos tocados pelo lote."""
    # SessionLocal tem autoflush=False. Persistir (na transação atual) os
    # históricos recém-criados antes de os consultar, para não omitir alvos
    # cujo histórico ainda está pendente, como um excedente acabado de criar.
    db.flush()
    note_marker = _batch_note(batch.id)
    project_ids = {
        entry.project_id
        for entry in db.query(ProjectHistory).filter(
            ProjectHistory.source == "import_licensing", ProjectHistory.note == note_marker
        )
        if entry.field_name != _ROLLBACK_GUARD_FIELD
    }
    project_ids.update(
        record.promoted_project_id
        for record in batch.records
        if record.is_new_project and record.promoted_project_id is not None
    )

    for project_id in project_ids:
        project = db.get(Project, project_id)
        if project is None:
            raise LicensingImportError("Não foi possível registar a proteção do lote.")
        db.add(
            ProjectHistory(
                project_id=project.id,
                field_name=_ROLLBACK_GUARD_FIELD,
                old_value=None,
                new_value=_rollback_snapshot_digest(project),
                source="import_licensing",
                note=note_marker,
                changed_at=dt.datetime.now(dt.timezone.utc),
            )
        )

    data_entries = db.query(ProjectDataHistory).filter(
        ProjectDataHistory.source == "import_licensing", ProjectDataHistory.note == note_marker
    ).all()
    targets: dict[tuple[str, uuid.UUID, uuid.UUID], object] = {}
    for entry in data_entries:
        if entry.field_name == _ROLLBACK_GUARD_FIELD:
            continue
        if entry.entity_type in _SIM_CREATED_MODELS:
            model_cls = _SIM_CREATED_MODELS[entry.entity_type]
            instance = db.get(model_cls, entry.record_id) if entry.record_id is not None else None
        else:
            model_cls = _ENTITY_MODEL_BY_TYPE.get(entry.entity_type)
            instance = (
                db.query(model_cls).filter(model_cls.project_id == entry.project_id).one_or_none()
                if model_cls is not None
                else None
            )
        if instance is None:
            raise LicensingImportError("Não foi possível registar a proteção do lote.")
        targets[(entry.entity_type, entry.project_id, instance.id)] = instance

    for (entity_type, project_id, record_id), instance in targets.items():
        db.add(
            ProjectDataHistory(
                project_id=project_id,
                entity_type=entity_type,
                record_id=record_id,
                field_name=_ROLLBACK_GUARD_FIELD,
                old_value=None,
                new_value=_rollback_snapshot_digest(instance),
                source="import_licensing",
                note=note_marker,
                changed_at=dt.datetime.now(dt.timezone.utc),
            )
        )


def _guard_key(entity_type: str, project_id: uuid.UUID, record_id: uuid.UUID | None):
    if entity_type in _SIM_CREATED_MODELS:
        return entity_type, project_id, record_id
    return entity_type, project_id, None


def _utc_datetime(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def _has_audit_after_guard(db: Session, *, guard, batch_note: str, project_history: bool) -> bool:
    cutoff = _utc_datetime(guard.changed_at).replace(microsecond=0)
    if project_history:
        entries = db.query(ProjectHistory).filter(ProjectHistory.project_id == guard.project_id).all()
    else:
        entries = db.query(ProjectDataHistory).filter(
            ProjectDataHistory.project_id == guard.project_id,
            ProjectDataHistory.entity_type == guard.entity_type,
        ).all()

    for entry in entries:
        if entry.note == batch_note or entry.field_name == _ROLLBACK_GUARD_FIELD:
            continue
        if entry.field_name in ("secrets_revealed", "password_revealed"):
            continue
        if not project_history:
            if guard.entity_type in _SIM_CREATED_MODELS and entry.record_id != guard.record_id:
                continue
            if guard.entity_type in _ENTITY_MODEL_BY_TYPE and entry.record_id not in (None, guard.record_id):
                continue
        if _utc_datetime(entry.changed_at) >= cutoff:
            return True
    return False


def _preflight_licensing_rollback(db: Session, *, batch: FieldImportBatch, note_marker: str) -> bool:
    project_entries = db.query(ProjectHistory).filter(
        ProjectHistory.source == "import_licensing", ProjectHistory.note == note_marker
    ).all()
    project_guards = {
        entry.project_id: entry
        for entry in project_entries
        if entry.field_name == _ROLLBACK_GUARD_FIELD
    }
    guarded_projects = set(project_guards)
    for guard in project_guards.values():
        project = db.get(Project, guard.project_id)
        if project is None:
            return False
        if (
            _rollback_snapshot_digest(project) != guard.new_value
            or _has_audit_after_guard(db, guard=guard, batch_note=note_marker, project_history=True)
        ):
            return False
    for record in batch.records:
        if record.is_new_project and record.promoted_project_id is not None:
            if record.promoted_project_id not in guarded_projects:
                return False
    for entry in project_entries:
        if entry.field_name == _ROLLBACK_GUARD_FIELD or entry.project_id in guarded_projects:
            continue
        project = db.get(Project, entry.project_id)
        if project is None or str(getattr(project, entry.field_name, None)) != str(entry.new_value):
            return False

    data_entries = db.query(ProjectDataHistory).filter(
        ProjectDataHistory.source == "import_licensing", ProjectDataHistory.note == note_marker
    ).all()
    data_guards = {
        _guard_key(entry.entity_type, entry.project_id, entry.record_id): entry
        for entry in data_entries
        if entry.field_name == _ROLLBACK_GUARD_FIELD
    }
    for key, guard in data_guards.items():
        if guard.entity_type in _SIM_CREATED_MODELS:
            model_cls = _SIM_CREATED_MODELS[guard.entity_type]
            instance = db.get(model_cls, guard.record_id)
        else:
            model_cls = _ENTITY_MODEL_BY_TYPE.get(guard.entity_type)
            instance = (
                db.query(model_cls).filter(model_cls.project_id == guard.project_id).one_or_none()
                if model_cls is not None
                else None
            )
        if instance is None:
            return False
        if (
            _rollback_snapshot_digest(instance) != guard.new_value
            or _has_audit_after_guard(db, guard=guard, batch_note=note_marker, project_history=False)
        ):
            return False

    for entry in data_entries:
        if entry.field_name == _ROLLBACK_GUARD_FIELD:
            continue
        key = _guard_key(entry.entity_type, entry.project_id, entry.record_id)
        if key in data_guards:
            continue
        if entry.entity_type in _SIM_CREATED_MODELS:
            if entry.field_name == "created" or entry.record_id is None:
                return False
            model_cls = _SIM_CREATED_MODELS[entry.entity_type]
            instance = db.get(model_cls, entry.record_id)
        else:
            model_cls = _ENTITY_MODEL_BY_TYPE.get(entry.entity_type)
            instance = (
                db.query(model_cls).filter(model_cls.project_id == entry.project_id).one_or_none()
                if model_cls is not None
                else None
            )
        if instance is None:
            return False
        column = _FILLED_FIELD_COLUMNS.get(entry.field_name, entry.field_name)
        current_value = getattr(instance, column, None)
        if column.endswith("_encrypted"):
            expected_present = entry.new_value in (SECRET_HISTORY_MARKER, PASSWORD_HISTORY_MARKER)
            if (current_value is not None) != expected_present:
                return False
        elif str(current_value) != str(entry.new_value):
            return False
    return True


def _revert_value_for_column(model_cls, field_name: str, old_value: str | None):
    """`old_value=None` normalmente significa "o campo nunca tinha sido
    preenchido antes" — mas algumas colunas de texto (`notes`/`comments`)
    são `NOT NULL` com omissão `""`, nunca `NULL` de facto. Reverter para
    `None` nesses casos violava a restrição da base de dados; a omissão
    correta da coluna é o valor certo a repor."""
    if old_value is not None:
        return old_value
    column = model_cls.__table__.columns.get(field_name)
    if column is not None and not column.nullable and column.default is not None:
        return column.default.arg
    return None


def _upsert_import_sim_card(
    db: Session,
    *,
    project_id: uuid.UUID,
    values: dict,
    changed_by_person_id: uuid.UUID | None,
    note: str,
) -> None:
    """SIM de comunicações importado: idempotente pelo nº (não cria duplicados ao
    correr de novo). Sem nº, não cria linha — só o operador não chega para um SIM."""
    phone = values.get("phone_number")
    if phone is None:
        return
    existing = (
        db.query(ProjectSimCard)
        .filter(
            ProjectSimCard.project_id == project_id,
            ProjectSimCard.phone_number == str(phone),
            ProjectSimCard.deleted_at.is_(None),
        )
        .one_or_none()
    )
    if existing is None:
        create_sim_card(
            db,
            project_id=project_id,
            values={"purpose": "comunicacoes", "phone_number": str(phone), "operator": values.get("operator")},
            encrypted_pin=None,
            encrypted_puk=None,
            changed_by_person_id=changed_by_person_id,
        )
    elif values.get("operator") and existing.operator != values["operator"] and existing.operator is None:
        update_sim_card(
            db,
            sim=existing,
            changes={"operator": values["operator"]},
            secret_changes={},
            changed_by_person_id=changed_by_person_id,
        )


def _write_project_record(
    db: Session,
    *,
    existing: Project | None,
    internal_reference: str,
    mapped: dict,
    applied_by_person_id: uuid.UUID | None,
    batch_id: uuid.UUID,
) -> Project:
    note = _batch_note(batch_id)
    if existing is None:
        project = Project(name=mapped["project"].get("name") or f"Projeto importado ({internal_reference})")
        for field_name, value in mapped["project"].items():
            setattr(project, field_name, value)
        db.add(project)
        db.flush()
        db.add(
            ProjectExternalId(
                project_id=project.id, source_system=LEGACY_SOURCE_SYSTEM, external_id=internal_reference
            )
        )
    else:
        # Só chega aqui sem conflitos por resolver — ou o campo estava
        # vazio (preenche e regista histórico) ou já tinha o mesmo valor
        # (nada a fazer). Um valor existente divergente do novo já ficou
        # retido em FieldImportConflict antes de chegar aqui.
        project = existing
        for field_name, new_value in mapped["project"].items():
            old_value = getattr(project, field_name)
            if str(old_value) == str(new_value):
                continue
            record_project_change(
                db,
                project_id=project.id,
                field_name=field_name,
                old_value=str(old_value) if old_value is not None else None,
                new_value=str(new_value),
                source="import_licensing",
                changed_by_person_id=applied_by_person_id,
                note=note,
            )
            setattr(project, field_name, new_value)

    db.flush()
    if mapped["installation"]:
        upsert_installation_data(
            db,
            project_id=project.id,
            changes=mapped["installation"],
            changed_by_person_id=applied_by_person_id,
            source="import_licensing",
            note=note,
        )
    if mapped["licensing"]:
        upsert_licensing_data(
            db,
            project_id=project.id,
            changes=mapped["licensing"],
            changed_by_person_id=applied_by_person_id,
            source="import_licensing",
            note=note,
        )
    if mapped["communication"]:
        _upsert_import_sim_card(
            db,
            project_id=project.id,
            values=mapped["communication"],
            changed_by_person_id=applied_by_person_id,
            note=note,
        )
    return project


def rollback_licensing_batch(db: Session, *, batch: FieldImportBatch) -> int:
    """Reverte um lote aplicado: reaplica o valor anterior de cada campo
    alterado (a partir de `ProjectHistory`/`ProjectDataHistory` com
    `source='import_licensing'` e nota a referir este lote), remove os
    `SurplusContract` criados por ele, e marca o lote como `rejected`.
    Nunca apaga histórico — só acrescenta entradas que revertem os
    valores, mesmo princípio de `rollback_promotion` (D-017).

    Limitação conhecida: a correlação com o lote é feita por igualdade de
    texto na nota (`note == '<mensagem com o batch id>'`), não por chave
    estrangeira — mais simples do que alargar `ProjectHistory`/
    `ProjectDataHistory` (tabelas partilhadas por vários caminhos de
    escrita) só para este caso."""
    if batch.status != BATCH_STATUS_APPLIED:
        raise LicensingImportError(f"Só é possível reverter um lote aplicado (estado atual: {batch.status!r}).")

    note_marker = _batch_note(batch.id)
    if not _preflight_licensing_rollback(db, batch=batch, note_marker=note_marker):
        raise LicensingImportError(_ROLLBACK_REFUSED_MESSAGE)
    reverted = 0

    project_entries = (
        db.query(ProjectHistory)
        .filter(
            ProjectHistory.source == "import_licensing",
            ProjectHistory.note == note_marker,
            ProjectHistory.field_name != _ROLLBACK_GUARD_FIELD,
        )
        .all()
    )
    for entry in project_entries:
        project = db.get(Project, entry.project_id)
        if project is None:
            continue
        current_value = getattr(project, entry.field_name)
        if str(current_value) == str(entry.old_value):
            continue
        revert_value = _revert_value_for_column(Project, entry.field_name, entry.old_value)
        record_project_change(
            db,
            project_id=project.id,
            field_name=entry.field_name,
            old_value=str(current_value) if current_value is not None else None,
            new_value=str(revert_value) if revert_value is not None else None,
            source="import_licensing",
            note=f"Rollback do lote {batch.id}.",
        )
        setattr(project, entry.field_name, revert_value)
        reverted += 1

    data_entries = (
        db.query(ProjectDataHistory)
        .filter(
            ProjectDataHistory.source == "import_licensing",
            ProjectDataHistory.note == note_marker,
            ProjectDataHistory.field_name != _ROLLBACK_GUARD_FIELD,
        )
        .all()
    )
    for entry in data_entries:
        if entry.entity_type in _SIM_CREATED_MODELS:
            if entry.field_name == "created":
                reverted += _soft_delete_created_record(db, entry, batch)
            else:
                reverted += _clear_filled_record_field(db, entry, batch)
            continue
        model_cls = _ENTITY_MODEL_BY_TYPE.get(entry.entity_type)
        if model_cls is None:
            continue
        instance = db.query(model_cls).filter(model_cls.project_id == entry.project_id).one_or_none()
        if instance is None:
            continue
        current_value = getattr(instance, entry.field_name, None)
        if str(current_value) == str(entry.old_value):
            continue
        revert_value = _revert_value_for_column(model_cls, entry.field_name, entry.old_value)
        db.add(
            ProjectDataHistory(
                project_id=entry.project_id,
                entity_type=entry.entity_type,
                field_name=entry.field_name,
                old_value=str(current_value) if current_value is not None else None,
                new_value=str(revert_value) if revert_value is not None else None,
                source="import_licensing",
                note=f"Rollback do lote {batch.id}.",
            )
        )
        setattr(instance, entry.field_name, revert_value)
        reverted += 1

    # Projetos criados de novo por este lote não têm histórico de campo
    # "anterior" para reverter (nunca existiram antes) — inativa-os, mesmo
    # princípio de `rollback_promotion` para a migração de projetos
    # legados (D-017): nunca `DELETE`, só `is_active=False`, sempre
    # auditado.
    for record in batch.records:
        if not record.is_new_project or record.promoted_project_id is None:
            continue
        project = db.get(Project, record.promoted_project_id)
        if project is None or not project.is_active:
            continue
        record_project_change(
            db,
            project_id=project.id,
            field_name="is_active",
            old_value=str(project.is_active),
            new_value=str(False),
            source="import_licensing",
            note=f"Rollback do lote {batch.id}.",
        )
        project.is_active = False
        reverted += 1

    db.query(SurplusContract).filter(SurplusContract.import_batch_id == batch.id).delete()

    batch.status = "rejected"
    db.commit()
    return reverted


# ===========================================================================
# Layout "SIM card Numbers Projects" (docs/DATA_IMPORTS.md, secção 2b).
# Folha "Dados gerais": cabeçalho na linha 8, dados a partir da linha 9,
# colunas POSICIONAIS (0-based no mapeamento). Folha "Venda do excedente":
# cabeçalho na linha 1, ligação ao projeto por nome normalizado.
# Coexiste com o layout legado acima — `detect_layout` escolhe.
# Relatórios: só nomes de campo, números de linha/coluna e contagens. Nunca
# valores de PIN/PUK/password, usernames ou emails.
# ===========================================================================

SIM_LAYOUT_NAME = "sim_v1"
SIM_LAYOUT_LEGACY = "legacy"
SIM_HEADER_ROW = 8
SIM_FIRST_DATA_ROW = 9
SIM_SURPLUS_HEADER_ROW = 1
SIM_PORTAL = "dgeg_login_geral"
SIM_BLANK_TOKENS = frozenset({"-", "–", "por confirmar"})
SIM_BLOCK_NAMES = ("sim_1", "sim_2", "credencial_login_geral", "licenciamento", "excedente")

# coluna 0-based -> palavras que têm de existir no cabeçalho normalizado.
_SIM_HEADER_CHECKS: dict[int, tuple[str, ...]] = {
    3: ("numero",),
    4: ("card",),
    5: ("pin",),
    6: ("puk",),
    8: ("numero",),
    9: ("barras",),
    10: ("pin",),
    11: ("puk",),
    13: ("login",),
    14: ("password",),
    15: ("upac", "registo"),
    16: ("data", "registo"),
    17: ("upac", "cadastro"),
    18: ("data", "cadastro"),
    19: ("pedido",),
    20: ("entidade",),
    21: ("inspe",),
    22: ("certificado",),
    23: ("mail",),
}
# Rótulos confirmados na folha SIM real: aliases exatos e apenas nestas posições.
_SIM_HEADER_ALIASES: dict[int, frozenset[str]] = {
    4: frozenset({"cod. barras"}),
    13: frozenset({"username"}),
    22: frozenset({"data cetificado"}),
}
_SIM_SIGNATURE_COLS = (3, 4, 13, 14)
_SIM_MAPPED_COLS = frozenset({0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23})

_SURPLUS_HEADER_MAP: dict[str, str] = {
    "project": "project_name",
    "comercializador": "commercializer",
    "tipo de contrato": "contract_type",
    "envio do contrato": "contract_sent_date",
    "ass. do contrato": "signed_received_date",
    "envio p/ comercializador": "sent_to_commercializer_date",
    "situacao": "status",
    "duracao (mes)": "duration_months",
    "data inicio": "start_date",
    "data final": "end_date",
    "observacao": "notes",
}
_SURPLUS_REQUIRED = ("project_name", "commercializer", "start_date")
_SURPLUS_FIELD_KEYS = (
    "commercializer",
    "contract_type",
    "contract_sent_date",
    "signed_received_date",
    "sent_to_commercializer_date",
    "status",
    "duration_months",
    "start_date",
    "end_date",
)
_SIM_CREATED_MODELS = {
    ENTITY_TYPE_SIM: ProjectSimCard,
    ENTITY_TYPE_CREDENTIAL: ProjectPortalCredential,
    ENTITY_TYPE_SURPLUS: ProjectSurplusContract,
}
_DATE_EXACT = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_DATE_SEARCH = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def _strip_accents_lower(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.lower().split())


def _name_key(value: object) -> str:
    """Correspondência exata normalizada de nomes de projeto (sem acentos,
    minúsculas, espaços colapsados)."""
    return _strip_accents_lower(value)


def _header_has(value: object, keywords: tuple[str, ...]) -> bool:
    text = _strip_accents_lower(value)
    return all(keyword in text for keyword in keywords)


def _sim_header_matches(idx: int, value: object) -> bool:
    return (
        _header_has(value, _SIM_HEADER_CHECKS[idx])
        or _strip_accents_lower(value) in _SIM_HEADER_ALIASES.get(idx, ())
    )


def _cell(row: tuple, idx: int):
    return row[idx] if idx < len(row) else None


def _sim_clean(value):
    if value is None:
        return None
    if isinstance(value, str):
        text = " ".join(value.split())
        if not text or text.lower() in SIM_BLANK_TOKENS:
            return None
        return text
    return value


def _sim_text(value) -> str | None:
    value = _sim_clean(value)
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _sim_identifier(value) -> tuple[str | None, str | None]:
    """Nº de telefone / ICCID. Número numérico grande perde precisão no Excel."""
    value = _sim_clean(value)
    if value is None:
        return None, None
    if isinstance(value, bool):
        return None, "valor inválido"
    if isinstance(value, float):
        if abs(value) >= 1e14:
            return None, "número com 15+ dígitos guardado como valor numérico (perda de precisão) — gravar como texto"
        if value.is_integer():
            return str(int(value)), None
        return None, "valor numérico inválido"
    if isinstance(value, int):
        if abs(value) >= 10**14:
            return None, "número com 15+ dígitos guardado como valor numérico (perda de precisão) — gravar como texto"
        return str(value), None
    if isinstance(value, str):
        return value.replace(" ", ""), None
    return None, "tipo de célula inesperado"


def _sim_secret(value) -> tuple[str | None, str | None]:
    """PIN/PUK/password. Devolve (valor, aviso). Nunca devolve o valor em mensagens."""
    value = _sim_clean(value)
    if value is None:
        return None, None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, (int, float)):
        return str(value), "valor guardado como número no Excel — confirmar zeros à esquerda"
    if isinstance(value, (dt.datetime, dt.date)):
        return None, "tipo de célula inesperado"
    return str(value), None


def _sim_date(value) -> tuple[dt.date | None, str | None]:
    value = _sim_clean(value)
    if value is None:
        return None, None
    if isinstance(value, dt.datetime):
        return value.date(), None
    if isinstance(value, dt.date):
        return value, None
    if isinstance(value, str):
        match = _DATE_EXACT.match(value)
        if match:
            try:
                return dt.date(int(match.group(3)), int(match.group(2)), int(match.group(1))), None
            except ValueError:
                return None, "data inválida"
    return None, "data não reconhecida (esperado dd/mm/aaaa)"


def _sim_certificate(value) -> tuple[str | None, dt.date | None, str | None]:
    """'definitivo' (data ou texto 'Cert. dd/mm/aaaa'), 'provisorio' (texto sem
    data) ou erro."""
    value = _sim_clean(value)
    if value is None:
        return None, None, None
    if isinstance(value, dt.datetime):
        return "definitivo", value.date(), None
    if isinstance(value, dt.date):
        return "definitivo", value, None
    if isinstance(value, str):
        low = value.lower()
        if "provis" in low:
            return "provisorio", None, None
        match = _DATE_SEARCH.search(value)
        if "cert" in low and match:
            try:
                return "definitivo", dt.date(int(match.group(3)), int(match.group(2)), int(match.group(1))), None
            except ValueError:
                return None, None, "data do certificado inválida"
    return None, None, "certificado sem data reconhecida (esperado 'Cert. dd/mm/aaaa' ou 'Certificado provisório')"


def _sim_int(value) -> tuple[int | None, str | None]:
    value = _sim_clean(value)
    if value is None:
        return None, None
    if isinstance(value, bool):
        return None, "número de meses inválido"
    if isinstance(value, int):
        return value, None
    if isinstance(value, float) and value.is_integer():
        return int(value), None
    if isinstance(value, str):
        match = re.match(r"\s*(\d+)", value)
        if match:
            return int(match.group(1)), None
    return None, "número de meses inválido"


def _open_workbook(content: bytes):
    try:
        return load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - openpyxl levanta vários tipos para ficheiros inválidos
        raise LicensingImportError(f"Não foi possível ler o ficheiro Excel: {exc}") from exc


def _sheet_row(ws, row_number: int) -> tuple:
    for idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if idx == row_number:
            return tuple(row)
        if idx > row_number:
            break
    return ()


def detect_layout(content: bytes) -> str:
    """`sim_v1` se o cabeçalho da linha 8 de 'Dados gerais' tiver as colunas
    de SIM/login; senão, o layout legado. Não valida o layout SIM (isso é
    feito em `parse_sim_layout`, com erro claro)."""
    wb = _open_workbook(content)
    try:
        if DADOS_GERAIS_NAME not in wb.sheetnames:
            return SIM_LAYOUT_LEGACY
        header = _sheet_row(wb[DADOS_GERAIS_NAME], SIM_HEADER_ROW)
        hits = sum(1 for idx in _SIM_SIGNATURE_COLS if _sim_header_matches(idx, _cell(header, idx)))
        # 2 ou mais sinais => é o layout SIM (a validação estrita depois dá o
        # erro claro se alguma coluna não bater); 0-1 => legado.
        return SIM_LAYOUT_NAME if hits >= 2 else SIM_LAYOUT_LEGACY
    finally:
        wb.close()


def _validate_sim_headers(header: tuple) -> None:
    bad = [
        get_column_letter(idx + 1)
        for idx in _SIM_HEADER_CHECKS
        if not _sim_header_matches(idx, _cell(header, idx))
    ]
    if bad:
        raise LicensingImportError(
            "Layout SIM não reconhecido: folha 'Dados gerais', cabeçalho na linha 8 — colunas "
            f"{', '.join(bad)} não batem com o mapeamento. Confirme o ficheiro (nada foi lido nem gravado)."
        )


def _surplus_columns(header: tuple) -> dict[str, int]:
    found: dict[str, int] = {}
    for idx, raw in enumerate(header):
        key = _SURPLUS_HEADER_MAP.get(_strip_accents_lower(raw))
        if key and key not in found:
            found[key] = idx
    missing = [key for key in _SURPLUS_REQUIRED if key not in found]
    if missing:
        raise LicensingImportError(
            "Layout SIM: folha 'Venda do excedente' — cabeçalho da linha 1 não reconhecido "
            "(esperado PROJECT, Comercializador, Data Inicio)."
        )
    return found


@dataclasses.dataclass
class SimRow:
    row_number: int
    project_number: str | None
    sims: list
    credential: dict | None
    licensing: dict


@dataclasses.dataclass
class SimLayoutParsed:
    rows: list
    surplus: list
    invalid: list
    warnings: list
    field_issues: list
    ignored_columns: list
    has_surplus_sheet: bool


def _sim_issue_location(idx: int) -> tuple[str, str]:
    """Mapeia uma coluna SIM para bloco/campo, sem expor o conteúdo da célula."""
    fields = {
        0: ("ligacao_projeto", "numero_projeto"),
        2: ("sim_1", "operator"),
        3: ("sim_1", "phone_number"),
        4: ("sim_1", "iccid"),
        5: ("sim_1", "pin"),
        6: ("sim_1", "puk"),
        7: ("sim_2", "operator"),
        8: ("sim_2", "phone_number"),
        9: ("sim_2", "iccid"),
        10: ("sim_2", "pin"),
        11: ("sim_2", "puk"),
        13: ("credencial_login_geral", "username"),
        14: ("credencial_login_geral", "password"),
        15: ("licenciamento", "upac_number"),
        16: ("licenciamento", "upac_registration_date"),
        17: ("licenciamento", "cadastro_number"),
        18: ("licenciamento", "registration_date"),
        19: ("licenciamento", "certification_request_date"),
        20: ("licenciamento", "inspecting_entity"),
        21: ("licenciamento", "inspection_date"),
        22: ("licenciamento", "certificate_date"),
        23: ("credencial_login_geral", "email"),
    }
    return fields.get(idx, ("desconhecido", f"coluna_{get_column_letter(idx + 1).lower()}"))


def _parse_sim_row(row_number: int, raw: tuple, invalid: list, warnings: list, field_issues: list) -> SimRow:
    def bad(idx: int, reason: str) -> None:
        invalid.append({"linha": row_number, "coluna": get_column_letter(idx + 1), "motivo": reason})
        block, field_name = _sim_issue_location(idx)
        field_issues.append(
            {"folha": DADOS_GERAIS_NAME, "linha": row_number, "bloco": block, "campo": field_name, "motivo": reason}
        )

    def warn(idx: int, text: str) -> None:
        warnings.append({"linha": row_number, "coluna": get_column_letter(idx + 1), "aviso": text})
        block, field_name = _sim_issue_location(idx)
        field_issues.append(
            {"folha": DADOS_GERAIS_NAME, "linha": row_number, "bloco": block, "campo": field_name, "motivo": text}
        )

    def c(idx: int):
        return _cell(raw, idx)

    project_number = None
    if _sim_clean(c(0)) is None:
        bad(0, "nº de projeto em falta")
    else:
        project_number = _sim_text(c(0))

    sims: list[dict] = []
    for block, first in (("sim_1", 2), ("sim_2", 7)):
        operator = _sim_text(c(first))
        phone, err_phone = _sim_identifier(c(first + 1))
        iccid, err_iccid = _sim_identifier(c(first + 2))
        if err_phone:
            bad(first + 1, err_phone)
        if err_iccid:
            bad(first + 2, err_iccid)
        pin, warn_pin = _sim_secret(c(first + 3))
        puk, warn_puk = _sim_secret(c(first + 4))
        if warn_pin:
            warn(first + 3, warn_pin)
        if warn_puk:
            warn(first + 4, warn_puk)
        if phone is None and iccid is None:
            if not (err_phone or err_iccid) and any(v is not None for v in (operator, pin, puk)):
                bad(first + 1, "sem nº de telefone nem nº de cartão — bloco SIM ignorado")
            continue
        sims.append(
            {
                "block": block,
                "purpose": "comunicacoes" if block == "sim_1" else "dados_moveis",
                "operator": operator,
                "phone_number": phone,
                "iccid": iccid,
                "pin": pin,
                "puk": puk,
            }
        )

    username = _sim_text(c(13))
    password, warn_pw = _sim_secret(c(14))
    if warn_pw:
        warn(14, warn_pw)
    email = _sim_text(c(23))
    credential = None
    if username is None:
        if password is not None or email is not None:
            bad(13, "login em falta (existe password ou email)")
    else:
        credential = {"username": username, "password": password, "email": email}

    licensing: dict = {}

    def take(field_name: str, idx: int, value, err: str | None) -> None:
        if err:
            bad(idx, err)
        elif value is not None:
            licensing[field_name] = value

    take("upac_number", 15, _sim_text(c(15)), None)
    value, err = _sim_date(c(16))
    take("upac_registration_date", 16, value, err)
    take("cadastro_number", 17, _sim_text(c(17)), None)
    value, err = _sim_date(c(18))
    take("registration_date", 18, value, err)
    value, err = _sim_date(c(19))
    take("certification_request_date", 19, value, err)
    take("inspecting_entity", 20, _sim_text(c(20)), None)
    value, err = _sim_date(c(21))
    take("inspection_date", 21, value, err)
    kind, value, err = _sim_certificate(c(22))
    if err:
        bad(22, err)
    elif kind == "definitivo":
        licensing["certificate_date"] = value
    elif kind == "provisorio":
        warn(22, "certificado provisório sem data — campo deixado vazio")

    return SimRow(row_number, project_number, sims, credential, licensing)


def _parse_sim_dados_gerais(ws, invalid: list, warnings: list, field_issues: list) -> tuple[list, set]:
    rows: list[SimRow] = []
    ignored: set[int] = set()
    for row_number, raw in enumerate(ws.iter_rows(values_only=True), start=1):
        if row_number < SIM_FIRST_DATA_ROW:
            continue
        raw = tuple(raw)
        for idx, value in enumerate(raw):
            if idx not in _SIM_MAPPED_COLS and _sim_clean(value) is not None:
                ignored.add(idx)
        if all(_sim_clean(_cell(raw, idx)) is None for idx in _SIM_MAPPED_COLS):
            continue
        rows.append(_parse_sim_row(row_number, raw, invalid, warnings, field_issues))
    return rows, ignored


def _parse_sim_surplus(ws, invalid: list, field_issues: list) -> list[dict]:
    cols = _surplus_columns(_sheet_row(ws, SIM_SURPLUS_HEADER_ROW))
    result: list[dict] = []
    for row_number, raw in enumerate(ws.iter_rows(values_only=True), start=1):
        if row_number <= SIM_SURPLUS_HEADER_ROW:
            continue
        raw = tuple(raw)
        if all(_sim_clean(_cell(raw, idx)) is None for idx in cols.values()):
            continue

        def bad(key: str, reason: str) -> None:
            invalid.append({"linha": row_number, "coluna": get_column_letter(cols[key] + 1), "motivo": reason})
            field_issues.append(
                {
                    "folha": SURPLUS_SHEET_NAME,
                    "linha": row_number,
                    "bloco": "excedente",
                    "campo": key,
                    "motivo": reason,
                }
            )

        valid = True
        name_key = _name_key(_sim_text(_cell(raw, cols["project_name"])) or "")
        if not name_key:
            bad("project_name", "nome do projeto em falta")
            valid = False

        entry: dict = {
            "linha": row_number,
            "name_key": name_key,
            "commercializer": _sim_text(_cell(raw, cols["commercializer"])),
            "contract_type": None,
            "status": None,
            "duration_months": None,
            "notes": None,
        }
        for key in ("contract_type", "status", "notes"):
            if key in cols:
                entry[key] = _sim_text(_cell(raw, cols[key]))
        for key in ("contract_sent_date", "signed_received_date", "sent_to_commercializer_date", "start_date", "end_date"):
            entry[key] = None
            if key in cols:
                value, err = _sim_date(_cell(raw, cols[key]))
                if err:
                    bad(key, err)
                    valid = False
                entry[key] = value
        if "duration_months" in cols:
            value, err = _sim_int(_cell(raw, cols["duration_months"]))
            if err:
                bad("duration_months", err)
                valid = False
            entry["duration_months"] = value
        entry["valid"] = valid
        result.append(entry)
    return result


def parse_sim_layout(content: bytes) -> SimLayoutParsed:
    """Só leitura. Valida cabeçalhos antes de tocar em dados; falha com erro claro."""
    wb = _open_workbook(content)
    try:
        if DADOS_GERAIS_NAME not in wb.sheetnames:
            raise LicensingImportError("Layout SIM: folha 'Dados gerais' em falta.")
        ws = wb[DADOS_GERAIS_NAME]
        _validate_sim_headers(_sheet_row(ws, SIM_HEADER_ROW))

        invalid: list[dict] = []
        warnings: list[dict] = []
        field_issues: list[dict] = []
        rows, ignored = _parse_sim_dados_gerais(ws, invalid, warnings, field_issues)

        if SHEET1_NAME in wb.sheetnames:
            warnings.append({"aviso": "folha 'Sheet1' ignorada no layout SIM"})

        has_surplus = SURPLUS_SHEET_NAME in wb.sheetnames
        surplus: list[dict] = []
        if has_surplus:
            surplus = _parse_sim_surplus(wb[SURPLUS_SHEET_NAME], invalid, field_issues)
        else:
            warnings.append({"aviso": "folha 'Venda do excedente' não encontrada — excedente não importado"})

        if not rows and not surplus:
            # Sem nada para importar não se cria um lote "aplicado" vazio (gastaria o hash do ficheiro).
            raise LicensingImportError(
                f"Layout SIM: nenhuma linha de dados encontrada em '{DADOS_GERAIS_NAME}' (a partir da linha "
                f"{SIM_FIRST_DATA_ROW}) nem em '{SURPLUS_SHEET_NAME}' — confirme o ficheiro."
            )

        by_number: dict[str, list[int]] = {}
        for row in rows:
            if row.project_number is not None:
                by_number.setdefault(row.project_number, []).append(row.row_number)
        for number, linhas in sorted(by_number.items()):
            if len(linhas) > 1:
                warnings.append({"linhas": linhas, "aviso": "nº de projeto repetido no ficheiro"})

        return SimLayoutParsed(
            rows=rows,
            surplus=surplus,
            invalid=invalid,
            warnings=warnings,
            field_issues=field_issues,
            ignored_columns=[get_column_letter(idx + 1) for idx in sorted(ignored)],
            has_surplus_sheet=has_surplus,
        )
    finally:
        wb.close()


@dataclasses.dataclass
class SimImportReport:
    mode: str
    batch_id: uuid.UUID | None = None
    already_imported: bool = False
    previously_imported_batch_id: uuid.UUID | None = None
    projects_found: int = 0
    projects_not_found: list = dataclasses.field(default_factory=list)
    projects_ambiguous: dict[str, int] = dataclasses.field(default_factory=dict)
    counts: dict = dataclasses.field(default_factory=lambda: {block: {} for block in SIM_BLOCK_NAMES})
    invalid: list = dataclasses.field(default_factory=list)
    conflicts: list = dataclasses.field(default_factory=list)
    warnings: list = dataclasses.field(default_factory=list)
    safe_only: bool = False
    safe_exclusions: list = dataclasses.field(default_factory=list)
    surplus_unlinked: list = dataclasses.field(default_factory=list)
    ignored_columns: list = dataclasses.field(default_factory=list)

    def to_dict(self) -> dict:
        """Sem segredos: nomes de campo, números de linha/coluna, contagens."""
        return {
            "modo": self.mode,
            "safe_only": self.safe_only,
            "layout": SIM_LAYOUT_NAME,
            "lote": str(self.batch_id) if self.batch_id else None,
            "ja_importado": self.already_imported,
            "lote_anterior_com_mesmo_ficheiro": str(self.previously_imported_batch_id)
            if self.previously_imported_batch_id
            else None,
            "projetos_encontrados": self.projects_found,
            "projetos_nao_encontrados": sorted(set(self.projects_not_found)),
            "projetos_ambiguos": [
                {"numero": number, "quantidade": count}
                for number, count in sorted(self.projects_ambiguous.items())
            ],
            "contagens": {block: dict(sorted(counter.items())) for block, counter in self.counts.items()},
            "linhas_invalidas": self.invalid,
            "conflitos": self.conflicts,
            "avisos": self.warnings,
            "exclusoes_safe_only": self.safe_exclusions,
            "excedente_por_ligar": self.surplus_unlinked,
            "colunas_ignoradas": self.ignored_columns,
        }


def _bump(report: SimImportReport, block: str, key: str, n: int = 1) -> None:
    counter = report.counts[block]
    counter[key] = counter.get(key, 0) + n


def _plan_field(existing_value, new_value) -> str:
    if new_value is None:
        return "none"
    if existing_value in (None, ""):
        return "fill"
    return "same" if str(existing_value) == str(new_value) else "conflict"


def _secret_compare(settings: Settings, token: str | None, value: str | None) -> str:
    """Compara sem expor: 'none' (nada a importar), 'fill' (vazio na plataforma),
    'same', ou 'conflict' (diferente, ou não comparável sem chave)."""
    if value is None:
        return "none"
    if token is None:
        return "fill"
    try:
        current = decrypt_secret(settings, token)
    except (SecretBoxUnavailable, SecretBoxDecryptError):
        return "conflict"
    return "same" if current == value else "conflict"


def _tally(report: SimImportReport, block: str, row_number: int, states: dict[str, str]) -> list[str]:
    fills: list[str] = []
    for field_name, state in states.items():
        if state == "fill":
            fills.append(field_name)
        elif state == "conflict":
            report.conflicts.append({"linha": row_number, "bloco": block, "campo": field_name})
            _bump(report, block, "conflitos")
    return fills


def _has_conflict(states: dict[str, str]) -> bool:
    return any(state == "conflict" for state in states.values())


def _require_secret_key(settings: Settings) -> None:
    try:
        encrypt_secret(settings, "verificação-de-chave")
    except SecretBoxUnavailable:
        raise LicensingImportError(
            "Há PIN/PUK/passwords a importar e a cifra não está configurada (OPPM_SECRETS_KEY_FILE). "
            "Nada foi gravado."
        ) from None


def _import_history(
    db: Session,
    *,
    project_id: uuid.UUID,
    entity_type: str,
    record_id: uuid.UUID,
    field_name: str,
    old_value: str | None,
    new_value: str | None,
    actor_id: uuid.UUID | None,
    note: str,
) -> None:
    db.add(
        ProjectDataHistory(
            project_id=project_id,
            entity_type=entity_type,
            record_id=record_id,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            changed_by_person_id=actor_id,
            source="import_licensing",
            note=note,
        )
    )


def _projects_by_name(db: Session) -> dict[str, list[Project]]:
    result: dict[str, list[Project]] = {}
    for project in (
        db.query(Project)
        .filter(Project.is_active.is_(True), Project.deleted_at.is_(None))
        .all()
    ):
        key = _name_key(project.name)
        if key:
            result.setdefault(key, []).append(project)
    return result


@dataclasses.dataclass(frozen=True)
class SimProjectResolver:
    """Mapas de ligação materializados uma vez para cada execução do layout SIM."""

    nomenclature_numbers: frozenset[str]
    nomenclature_projects: dict[str, dict[uuid.UUID, Project]]
    legacy_projects: dict[str, dict[uuid.UUID, Project]]

    def resolve(self, number: str) -> tuple[Project | None, int]:
        # A presença de qualquer nomenclatura deste número bloqueia o fallback,
        # incluindo quando todas as entradas são inativas ou há ambiguidade.
        candidates = (
            self.nomenclature_projects.get(number, {})
            if number in self.nomenclature_numbers
            else self.legacy_projects.get(number, {})
        )
        if len(candidates) == 1:
            return next(iter(candidates.values())), 0
        return None, len(candidates)


def _load_sim_project_resolver(db: Session) -> SimProjectResolver:
    """Carrega nomenclatura e ids legados num SELECT, deduplicados por project_id."""
    nomenclature_numbers: set[str] = set()
    nomenclature_projects: dict[str, dict[uuid.UUID, Project]] = {}
    legacy_projects: dict[str, dict[uuid.UUID, Project]] = {}
    external_ids = (
        db.query(ProjectExternalId, Project)
        .join(Project, Project.id == ProjectExternalId.project_id)
        .filter(
            ProjectExternalId.source_system.in_(
                (SIM_NOMENCLATURE_SOURCE_SYSTEM, LEGACY_SOURCE_SYSTEM)
            )
        )
        .all()
    )
    for external, project in external_ids:
        if external.source_system == SIM_NOMENCLATURE_SOURCE_SYSTEM:
            match = _SIM_PROJECT_NUMBER_PREFIX.match(str(external.external_id or ""))
            if match is None:
                continue
            number = match.group(1)
            nomenclature_numbers.add(number)
            if project.is_active and project.deleted_at is None:
                nomenclature_projects.setdefault(number, {})[project.id] = project
        elif project.is_active and project.deleted_at is None:
            legacy_projects.setdefault(str(external.external_id), {})[project.id] = project
    return SimProjectResolver(
        nomenclature_numbers=frozenset(nomenclature_numbers),
        nomenclature_projects=nomenclature_projects,
        legacy_projects=legacy_projects,
    )


def _find_existing_sim(db: Session, *, project_id: uuid.UUID, sim: dict) -> ProjectSimCard | None:
    """SIM ativo do projeto que corresponde ao do Excel: primeiro pelo ICCID; senão pelo nº de
    telefone, que também identifica o cartão — apanha o SIM criado na plataforma só com o número
    (o Excel traz-lhe o ICCID) e o inverso (o Excel só traz o número). Sem isto o importador
    duplicava SIMs já registados. Um ICCID diferente para o mesmo nº fica como conflito."""
    query = db.query(ProjectSimCard).filter(
        ProjectSimCard.project_id == project_id, ProjectSimCard.deleted_at.is_(None)
    )
    if sim["iccid"]:
        found = query.filter(ProjectSimCard.iccid == sim["iccid"]).order_by(ProjectSimCard.created_at).first()
        if found is not None:
            return found
    if sim["phone_number"]:
        return (
            query.filter(ProjectSimCard.phone_number == sim["phone_number"]).order_by(ProjectSimCard.created_at).first()
        )
    return None


def _sim_action(db, *, project, row, sim, settings, write, note, actor_id, report, planned) -> None:
    block = sim["block"]
    if sim["iccid"]:
        key = ("iccid", project.id, sim["iccid"])
    else:
        key = ("phone", project.id, sim["purpose"], sim["phone_number"])
    existing = _find_existing_sim(db, project_id=project.id, sim=sim)
    if key in planned:
        _bump(report, block, "duplicado_no_ficheiro")
        return
    planned.add(key)

    if existing is None:
        _bump(report, block, "criados")
        if write:
            _create_sim(db, project_id=project.id, sim=sim, settings=settings, note=note, actor_id=actor_id)
        return

    states = {
        "operator": _plan_field(existing.operator, sim["operator"]),
        "phone_number": _plan_field(existing.phone_number, sim["phone_number"]),
        "iccid": _plan_field(existing.iccid, sim["iccid"]),
        "pin": _secret_compare(settings, existing.pin_encrypted, sim["pin"]),
        "puk": _secret_compare(settings, existing.puk_encrypted, sim["puk"]),
    }
    fills = _tally(report, block, row.row_number, states)
    if fills:
        _bump(report, block, "preenchidos")
        if write:
            for field_name in fills:
                if field_name in ("pin", "puk"):
                    setattr(existing, f"{field_name}_encrypted", encrypt_secret(settings, sim[field_name]))
                    _import_history(
                        db,
                        project_id=project.id,
                        entity_type=ENTITY_TYPE_SIM,
                        record_id=existing.id,
                        field_name=field_name,
                        old_value=None,
                        new_value=SECRET_HISTORY_MARKER,
                        actor_id=actor_id,
                        note=note,
                    )
                else:
                    setattr(existing, field_name, sim[field_name])
                    _import_history(
                        db,
                        project_id=project.id,
                        entity_type=ENTITY_TYPE_SIM,
                        record_id=existing.id,
                        field_name=field_name,
                        old_value=None,
                        new_value=sim[field_name],
                        actor_id=actor_id,
                        note=note,
                    )
            db.flush()
    elif not _has_conflict(states):
        _bump(report, block, "ja_existentes")


def _create_sim(db, *, project_id, sim, settings, note, actor_id) -> None:
    pin_token = encrypt_secret(settings, sim["pin"]) if sim["pin"] is not None else None
    puk_token = encrypt_secret(settings, sim["puk"]) if sim["puk"] is not None else None
    row = ProjectSimCard(
        project_id=project_id,
        purpose=sim["purpose"],
        operator=sim["operator"],
        phone_number=sim["phone_number"],
        iccid=sim["iccid"],
        notes="",
        pin_encrypted=pin_token,
        puk_encrypted=puk_token,
    )
    db.add(row)
    db.flush()
    _import_history(
        db,
        project_id=project_id,
        entity_type=ENTITY_TYPE_SIM,
        record_id=row.id,
        field_name="created",
        old_value=None,
        new_value=sim["purpose"],
        actor_id=actor_id,
        note=note,
    )
    if pin_token is not None or puk_token is not None:
        _import_history(
            db,
            project_id=project_id,
            entity_type=ENTITY_TYPE_SIM,
            record_id=row.id,
            field_name="secrets",
            old_value=None,
            new_value=SECRET_HISTORY_MARKER,
            actor_id=actor_id,
            note=note,
        )


def _credential_action(db, *, project, row, cred, settings, write, note, actor_id, report, planned, planned_dgeg) -> None:
    block = "credencial_login_geral"
    username = cred["username"]
    key = ("cred", project.id, username)
    if key in planned:
        _bump(report, block, "duplicado_no_ficheiro")
        return
    planned.add(key)

    dgeg = (
        db.query(ProjectPortalCredential)
        .filter(
            ProjectPortalCredential.project_id == project.id,
            ProjectPortalCredential.portal == SIM_PORTAL,
            ProjectPortalCredential.deleted_at.is_(None),
        )
        .all()
    )
    known = {c.username for c in dgeg} | planned_dgeg.get(project.id, set())
    if known and username not in known:
        report.conflicts.append({"linha": row.row_number, "bloco": block, "campo": "username"})
        _bump(report, block, "conflitos")
        return

    same = [c for c in dgeg if c.username == username]
    if not same:
        _bump(report, block, "criados")
        planned_dgeg.setdefault(project.id, set()).add(username)
        if write:
            password_token = encrypt_secret(settings, cred["password"]) if cred["password"] is not None else None
            credential = ProjectPortalCredential(
                project_id=project.id,
                portal=SIM_PORTAL,
                username=username,
                email=cred["email"],
                password_encrypted=password_token,
            )
            db.add(credential)
            db.flush()
            _import_history(
                db,
                project_id=project.id,
                entity_type=ENTITY_TYPE_CREDENTIAL,
                record_id=credential.id,
                field_name="created",
                old_value=None,
                new_value=SIM_PORTAL,
                actor_id=actor_id,
                note=note,
            )
            if password_token is not None:
                _import_history(
                    db,
                    project_id=project.id,
                    entity_type=ENTITY_TYPE_CREDENTIAL,
                    record_id=credential.id,
                    field_name="password",
                    old_value=None,
                    new_value=PASSWORD_HISTORY_MARKER,
                    actor_id=actor_id,
                    note=note,
                )
        return

    current = same[0]
    states = {
        "email": _plan_field(current.email, cred["email"]),
        "password": _secret_compare(settings, current.password_encrypted, cred["password"]),
    }
    fills = _tally(report, block, row.row_number, states)
    if fills:
        _bump(report, block, "preenchidos")
        if write:
            if "email" in fills:
                current.email = cred["email"]
                _import_history(
                    db,
                    project_id=project.id,
                    entity_type=ENTITY_TYPE_CREDENTIAL,
                    record_id=current.id,
                    field_name="email",
                    old_value=None,
                    new_value=cred["email"],
                    actor_id=actor_id,
                    note=note,
                )
            if "password" in fills:
                current.password_encrypted = encrypt_secret(settings, cred["password"])
                _import_history(
                    db,
                    project_id=project.id,
                    entity_type=ENTITY_TYPE_CREDENTIAL,
                    record_id=current.id,
                    field_name="password",
                    old_value=None,
                    new_value=PASSWORD_HISTORY_MARKER,
                    actor_id=actor_id,
                    note=note,
                )
            db.flush()
    elif not _has_conflict(states):
        _bump(report, block, "ja_existentes")


def _licensing_action(db, *, project, row, write, note, actor_id, report) -> None:
    block = "licenciamento"
    existing = db.query(ProjectLicensingData).filter(ProjectLicensingData.project_id == project.id).one_or_none()
    states = {
        field_name: _plan_field(getattr(existing, field_name, None) if existing is not None else None, value)
        for field_name, value in row.licensing.items()
    }
    fills = _tally(report, block, row.row_number, states)
    changes = {field_name: row.licensing[field_name] for field_name in fills}
    if changes:
        _bump(report, block, "criados" if existing is None else "preenchidos")
        if write:
            upsert_licensing_data(
                db,
                project_id=project.id,
                changes=changes,
                changed_by_person_id=actor_id,
                source="import_licensing",
                note=note,
                commit=False,
            )
    elif not _has_conflict(states):
        _bump(report, block, "ja_existentes")


def _surplus_action(db, *, srow, projects_by_name, write, note, actor_id, report, planned) -> None:
    block = "excedente"
    candidates = projects_by_name.get(srow["name_key"], []) if srow["name_key"] else []
    if not candidates:
        report.surplus_unlinked.append({"linha": srow["linha"], "motivo": "sem projeto com nome igual (normalizado)"})
        _bump(report, block, "por_ligar")
        return
    if len(candidates) > 1:
        report.surplus_unlinked.append({"linha": srow["linha"], "motivo": "nome ambíguo: mais de um projeto"})
        _bump(report, block, "por_ligar")
        return
    project = candidates[0]
    key = (project.id, srow["commercializer"], srow["start_date"])
    if key in planned:
        _bump(report, block, "duplicado_no_ficheiro")
        return
    planned.add(key)

    existing = [
        c
        for c in db.query(ProjectSurplusContract)
        .filter(ProjectSurplusContract.project_id == project.id, ProjectSurplusContract.deleted_at.is_(None))
        .all()
        if c.commercializer == srow["commercializer"] and c.start_date == srow["start_date"]
    ]
    if existing:
        _bump(report, block, "ja_existentes")
        return
    _bump(report, block, "criados")
    if not write:
        return
    contract = ProjectSurplusContract(
        project_id=project.id,
        notes=srow["notes"] or "",
        **{field_name: srow[field_name] for field_name in _SURPLUS_FIELD_KEYS},
    )
    db.add(contract)
    db.flush()
    _import_history(
        db,
        project_id=project.id,
        entity_type=ENTITY_TYPE_SURPLUS,
        record_id=contract.id,
        field_name="created",
        old_value=None,
        new_value=srow["commercializer"],
        actor_id=actor_id,
        note=note,
    )


def _current_sim_target(db: Session, project_id: uuid.UUID, *, lock: bool = False) -> Project | None:
    query = (
        db.query(Project)
        .populate_existing()
        .filter(Project.id == project_id, Project.is_active.is_(True), Project.deleted_at.is_(None))
    )
    if lock and db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    return query.one_or_none()


def _run_sim_rows(
    db, *, parsed: SimLayoutParsed, resolver: SimProjectResolver, settings, write, note, actor_id, report
) -> None:
    planned_sims: set = set()
    planned_creds: set = set()
    planned_dgeg: dict = {}
    planned_surplus: set = set()
    found_projects: set = set()

    for row in parsed.rows:
        if row.project_number is None:
            continue
        project, ambiguous_count = resolver.resolve(row.project_number)
        if ambiguous_count > 1:
            report.projects_ambiguous[row.project_number] = ambiguous_count
            continue
        if project is None:
            report.projects_not_found.append(row.project_number)
            continue
        project = _current_sim_target(db, project.id, lock=write)
        if project is None:
            report.projects_not_found.append(row.project_number)
            continue
        found_projects.add(project.id)
        for sim in row.sims:
            _sim_action(
                db,
                project=project,
                row=row,
                sim=sim,
                settings=settings,
                write=write,
                note=note,
                actor_id=actor_id,
                report=report,
                planned=planned_sims,
            )
        if row.credential:
            _credential_action(
                db,
                project=project,
                row=row,
                cred=row.credential,
                settings=settings,
                write=write,
                note=note,
                actor_id=actor_id,
                report=report,
                planned=planned_creds,
                planned_dgeg=planned_dgeg,
            )
        if row.licensing:
            _licensing_action(db, project=project, row=row, write=write, note=note, actor_id=actor_id, report=report)
    report.projects_found = len(found_projects)

    projects_by_name = _projects_by_name(db)
    for srow in parsed.surplus:
        if not srow["valid"]:
            continue
        _surplus_action(
            db,
            srow=srow,
            projects_by_name=projects_by_name,
            write=write,
            note=note,
            actor_id=actor_id,
            report=report,
            planned=planned_surplus,
        )


def _needs_secret_key(db: Session, parsed: SimLayoutParsed, resolver: SimProjectResolver) -> bool:
    for row in parsed.rows:
        if row.project_number is None:
            continue
        project, ambiguous_count = resolver.resolve(row.project_number)
        if project is None or ambiguous_count > 1:
            continue
        if _current_sim_target(db, project.id) is None:
            continue
        if any(sim["pin"] is not None or sim["puk"] is not None for sim in row.sims):
            return True
        if row.credential and row.credential["password"] is not None:
            return True
    return False


def _apply_safe_only_filter(parsed: SimLayoutParsed) -> list[dict]:
    """Retira apenas os campos sinalizados; exclusões nunca incluem valores do Excel."""
    exclusions = [
        {
            "folha": issue["folha"],
            "linha": issue["linha"],
            "bloco": issue["bloco"],
            "campo": issue["campo"],
            "motivo": issue["motivo"],
        }
        for issue in parsed.field_issues
    ]
    rows_by_sheet_line = {(DADOS_GERAIS_NAME, row.row_number): row for row in parsed.rows}
    surplus_by_sheet_line = {(SURPLUS_SHEET_NAME, row["linha"]): row for row in parsed.surplus}
    issues_by_sheet_line: dict[tuple[str, int], list[dict]] = {}

    for issue in parsed.field_issues:
        location = (issue["folha"], issue["linha"])
        if issue["folha"] == SURPLUS_SHEET_NAME:
            srow = surplus_by_sheet_line.get(location)
            if srow is not None:
                field_name = issue["campo"]
                if field_name == "project_name":
                    srow["name_key"] = None
                elif field_name in srow:
                    srow[field_name] = None
            continue
        if issue["folha"] == DADOS_GERAIS_NAME:
            issues_by_sheet_line.setdefault(location, []).append(issue)

    for location, issues in issues_by_sheet_line.items():
        row = rows_by_sheet_line.get(location)
        if row is None:
            continue
        for issue in issues:
            block, field_name = issue["bloco"], issue["campo"]
            if block == "ligacao_projeto":
                # Sem chave inequívoca, nenhum bloco da linha pode ser aplicado.
                row.project_number = None
                row.sims = []
                row.credential = None
                row.licensing = {}
            elif block in ("sim_1", "sim_2"):
                sim = next((item for item in row.sims if item["block"] == block), None)
                if sim is not None and field_name in sim:
                    sim[field_name] = None
            elif block == "credencial_login_geral" and row.credential is not None:
                if field_name == "username":
                    row.credential = None
                elif field_name in row.credential:
                    row.credential[field_name] = None
            elif block == "licenciamento":
                row.licensing.pop(field_name, None)

    for srow in parsed.surplus:
        # O nome é o único valor obrigatório por linha no parser normal. Datas
        # (incluindo Data Inicio) podem ficar vazias; safe-only não deve tornar
        # inválidas linhas que o modo normal aceita só por recalcular aqui.
        srow["valid"] = bool(srow["name_key"])
    return sorted(exclusions, key=lambda item: (item["linha"], item["bloco"], item["campo"], item["motivo"]))


def _sim_identity_hash(content: bytes, safe_only: bool) -> tuple[str, str]:
    original_hash = compute_file_hash(content)
    if not safe_only:
        return original_hash, original_hash
    identity = hashlib.sha256(f"{SIM_SAFE_ONLY_VERSION}:{original_hash}".encode("ascii")).hexdigest()
    return identity, original_hash


def _new_sim_report(mode: str, parsed: SimLayoutParsed, *, safe_only: bool = False) -> SimImportReport:
    report = SimImportReport(mode=mode)
    report.invalid = list(parsed.invalid)
    report.warnings = list(parsed.warnings)
    report.ignored_columns = list(parsed.ignored_columns)
    report.safe_only = safe_only
    if safe_only:
        report.safe_exclusions = _apply_safe_only_filter(parsed)
    return report


def dry_run_sim_import(
    db: Session, *, content: bytes, settings: Settings, safe_only: bool = False
) -> SimImportReport:
    """Só leitura — nunca escreve (nem lote, nem cifra)."""
    parsed = parse_sim_layout(content)
    report = _new_sim_report("dry-run", parsed, safe_only=safe_only)
    file_hash, _original_hash = _sim_identity_hash(content, safe_only)
    previous = db.query(FieldImportBatch).filter(FieldImportBatch.source_file_hash == file_hash).one_or_none()
    if previous is not None and previous.status == BATCH_STATUS_APPLIED:
        report.previously_imported_batch_id = previous.id
    resolver = _load_sim_project_resolver(db)
    _run_sim_rows(
        db, parsed=parsed, resolver=resolver, settings=settings, write=False, note="", actor_id=None, report=report
    )
    return report


def apply_sim_import(
    db: Session, *, filename: str, content: bytes, settings: Settings, applied_by_person_id: uuid.UUID | None,
    safe_only: bool = False,
) -> SimImportReport:
    """Idempotente por hash e modo; safe-only deixa campos duvidosos pendentes."""
    file_hash, original_hash = _sim_identity_hash(content, safe_only)
    previous = db.query(FieldImportBatch).filter(FieldImportBatch.source_file_hash == file_hash).one_or_none()
    if previous is not None:
        if previous.status == BATCH_STATUS_APPLIED:
            report = SimImportReport(
                mode="apply", already_imported=True, batch_id=previous.id, safe_only=safe_only
            )
            if safe_only:
                report = _new_sim_report("apply", parse_sim_layout(content), safe_only=True)
                report.already_imported = True
                report.batch_id = previous.id
            return report
        raise LicensingImportError(
            f"Este ficheiro já tem um lote no estado '{previous.status}' — use um ficheiro novo."
        )

    parsed = parse_sim_layout(content)
    report = _new_sim_report("apply", parsed, safe_only=safe_only)
    resolver = _load_sim_project_resolver(db)
    if _needs_secret_key(db, parsed, resolver):
        _require_secret_key(settings)

    batch = FieldImportBatch(
        source_type=SOURCE_TYPE_LICENSING_EXCEL,
        source_filename=filename,
        source_file_hash=file_hash,
        raw_payload_json=json.dumps(
            {
                "layout": SIM_LAYOUT_NAME,
                "ignored_columns": parsed.ignored_columns,
                **({"safe_only": SIM_SAFE_ONLY_VERSION, "original_file_hash": original_hash} if safe_only else {}),
            },
            ensure_ascii=False,
        ),
        status=BATCH_STATUS_APPLIED,
        started_by_person_id=applied_by_person_id,
        applied_by_person_id=applied_by_person_id,
        applied_at=dt.datetime.now(dt.timezone.utc),
    )
    db.add(batch)
    db.flush()

    report.batch_id = batch.id
    note = _batch_note(batch.id)
    _run_sim_rows(
        db,
        parsed=parsed,
        resolver=resolver,
        settings=settings,
        write=True,
        note=note,
        actor_id=applied_by_person_id,
        report=report,
    )
    _record_rollback_guards(db, batch=batch)
    db.commit()
    return report


def _soft_delete_created_record(db: Session, entry: ProjectDataHistory, batch: FieldImportBatch) -> int:
    """Rollback de um registo criado pelo lote (SIM, credencial, excedente):
    remoção lógica + segredos apagados, histórico acrescentado (nunca apagado)."""
    if entry.field_name != "created" or entry.record_id is None:
        return 0
    model_cls = _SIM_CREATED_MODELS[entry.entity_type]
    instance = db.get(model_cls, entry.record_id)
    if instance is None or instance.deleted_at is not None:
        return 0
    instance.deleted_at = dt.datetime.now(dt.timezone.utc)
    for column in ("pin_encrypted", "puk_encrypted", "password_encrypted"):
        if hasattr(instance, column):
            setattr(instance, column, None)
    db.add(
        ProjectDataHistory(
            project_id=entry.project_id,
            entity_type=entry.entity_type,
            record_id=entry.record_id,
            field_name="deleted",
            old_value=None,
            new_value=None,
            source="import_licensing",
            note=f"Rollback do lote {batch.id}.",
        )
    )
    return 1


_FILLED_FIELD_COLUMNS: dict[str, str] = {
    "operator": "operator",
    "phone_number": "phone_number",
    "iccid": "iccid",
    "pin": "pin_encrypted",
    "puk": "puk_encrypted",
    "email": "email",
    "password": "password_encrypted",
}


def _clear_filled_record_field(db: Session, entry: ProjectDataHistory, batch: FieldImportBatch) -> int:
    """Rollback de um campo PREENCHIDO (estava vazio, o lote pôs valor). Repõe
    vazio. Entradas de contexto (`created`, `secrets`) não mexem em nada aqui."""
    column = _FILLED_FIELD_COLUMNS.get(entry.field_name)
    if column is None:
        return 0
    model_cls = _SIM_CREATED_MODELS[entry.entity_type]
    instance = db.get(model_cls, entry.record_id) if entry.record_id else None
    if instance is None or getattr(instance, column, None) is None:
        return 0
    setattr(instance, column, None)
    db.add(
        ProjectDataHistory(
            project_id=entry.project_id,
            entity_type=entry.entity_type,
            record_id=entry.record_id,
            field_name=entry.field_name,
            old_value=SECRET_HISTORY_MARKER if column.endswith("_encrypted") else None,
            new_value=None,
            source="import_licensing",
            note=f"Rollback do lote {batch.id}.",
        )
    )
    return 1
