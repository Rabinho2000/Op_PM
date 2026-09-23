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
import uuid

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from app.audit.log import record_project_change
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
)
from app.services.project_data import upsert_communication_data, upsert_installation_data, upsert_licensing_data

LEGACY_SOURCE_SYSTEM = "legacy_excel_licensing"

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
        raise LicensingImportError(
            f"Nenhuma linha reconhecida em '{SHEET1_NAME}' nem '{DADOS_GERAIS_NAME}' — confirme o ficheiro."
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

    communication_fields = {
        k: v
        for k, v in {
            "gsm_m2m_number": dados_gerais.get("m2m_number"),
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
    — nunca por `Project_number` isolado (existem duplicados no legado)."""
    external = (
        db.query(ProjectExternalId)
        .filter(
            ProjectExternalId.source_system == LEGACY_SOURCE_SYSTEM,
            ProjectExternalId.external_id == internal_reference,
        )
        .one_or_none()
    )
    if external is None:
        return None
    return db.get(Project, external.project_id)


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
        existing = db.get(Project, record.target_project_id) if record.target_project_id else None
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
        upsert_communication_data(
            db,
            project_id=project.id,
            changes=mapped["communication"],
            changed_by_person_id=applied_by_person_id,
            source="import_licensing",
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
    reverted = 0

    project_entries = (
        db.query(ProjectHistory)
        .filter(ProjectHistory.source == "import_licensing", ProjectHistory.note == note_marker)
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
        .filter(ProjectDataHistory.source == "import_licensing", ProjectDataHistory.note == note_marker)
        .all()
    )
    for entry in data_entries:
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
