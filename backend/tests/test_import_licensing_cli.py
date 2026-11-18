"""Importação do Excel de licenciamento: Sheet1, Dados gerais, Venda do
excedente, Internal_reference como chave (nunca Project_number, que se
repete no ficheiro sintético de propósito), colunas de credenciais nunca
importadas, dry-run sem escrita, aplicação, conflitos, idempotência,
rollback. Ver app/services/imports_licensing.py e
app/cli/import_licensing.py.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from app.cli.import_licensing import main as cli_main
from app.models.imports import FieldImportBatch
from app.models.project import Project, ProjectExternalId
from app.models.project_data import ProjectCommunicationData, ProjectInstallationData, ProjectLicensingData
from app.services.imports_licensing import (
    DuplicateLicensingImportError,
    LicensingImportError,
    apply_licensing_import,
    dry_run_licensing_import,
    find_project_by_external_reference,
    parse_workbook,
)

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_licensing.xlsx"


def _content() -> bytes:
    return FIXTURE_PATH.read_bytes()


def test_fixture_exists():
    assert FIXTURE_PATH.exists(), "gere a fixture com: python fixtures/generate_synthetic_licensing_xlsx.py"


def test_parse_workbook_uses_internal_reference_not_project_number():
    parsed = parse_workbook(_content())
    refs = {row["internal_reference"] for row in parsed.project_rows}
    assert refs == {"REF-EXCEL-001", "REF-EXCEL-002"}
    # As duas linhas partilham Project_number=1001 — a chave usada é
    # sempre Internal_reference, nunca o número repetido.
    assert len(parsed.project_rows) == 2


def test_credential_columns_are_always_ignored():
    parsed = parse_workbook(_content())
    ignored = parsed.ignored_columns.get("Dados gerais", [])
    assert "PIN" in ignored
    assert "PUK" in ignored
    assert "Portal_password" in ignored
    assert "Portal_login" in ignored

    # E nunca aparecem como VALOR de nenhum campo mapeado (comparação
    # exata — não substring, que colidiria por acaso com outros números,
    # ex. "1234" é uma sub-sequência de "912345000").
    forbidden_values = {"1234", "87654321", "segredo-sintetico-a", "segredo-sintetico-b", "utilizador-sintetico-a", "utilizador-sintetico-b"}
    for row in parsed.project_rows:
        for section in ("sheet1", "dados_gerais"):
            for value in row.get(section, {}).values():
                assert str(value) not in forbidden_values


def test_dry_run_never_writes_to_database(db_session):
    before = db_session.query(Project).count()
    summary = dry_run_licensing_import(db_session, content=_content())
    db_session.rollback()
    after = db_session.query(Project).count()
    assert after == before
    assert summary.total_projects == 2
    assert summary.new_projects == 2
    assert summary.batch_id is None


def test_apply_creates_projects_with_installation_licensing_communication_data(db_session):
    summary = apply_licensing_import(db_session, filename="synthetic_licensing.xlsx", content=_content(), applied_by_person_id=None)
    assert summary.new_projects == 2
    assert summary.total_conflicts == 0

    project = find_project_by_external_reference(db_session, "REF-EXCEL-001")
    assert project is not None
    assert project.client_name == "Cliente Sintético Excel A"
    assert project.power_kwp == 9.0

    licensing = db_session.query(ProjectLicensingData).filter(ProjectLicensingData.project_id == project.id).one()
    assert licensing.upac_number == "UPAC-EXCEL-001"
    assert licensing.installer == "Instalador Sintético A"

    from app.models.project_data import ProjectSimCard

    sim = db_session.query(ProjectSimCard).filter(ProjectSimCard.project_id == project.id).one()
    assert sim.phone_number == "912345000"
    assert sim.pin_encrypted is None and sim.puk_encrypted is None

    external = (
        db_session.query(ProjectExternalId)
        .filter(ProjectExternalId.source_system == "legacy_excel_licensing", ProjectExternalId.project_id == project.id)
        .one()
    )
    assert external.external_id == "REF-EXCEL-001"


def test_surplus_contract_linked_and_unlinked(db_session):
    from app.models.imports import SurplusContract

    apply_licensing_import(db_session, filename="f.xlsx", content=_content(), applied_by_person_id=None)
    contracts = db_session.query(SurplusContract).all()
    assert len(contracts) == 2
    linked = [c for c in contracts if c.project_id is not None]
    unlinked = [c for c in contracts if c.project_id is None]
    assert len(linked) == 1
    assert linked[0].internal_reference_raw == "REF-EXCEL-001"
    assert len(unlinked) == 1
    assert unlinked[0].internal_reference_raw == "REF-EXCEL-999"


def test_duplicate_file_rejected_after_applied(db_session):
    apply_licensing_import(db_session, filename="f.xlsx", content=_content(), applied_by_person_id=None)
    with pytest.raises(DuplicateLicensingImportError):
        apply_licensing_import(db_session, filename="f-outra-vez.xlsx", content=_content(), applied_by_person_id=None)


def test_conflict_blocks_field_until_resolved(db_session):
    from app.services.imports_licensing import _finalize_licensing_batch

    existing = Project(name="Projeto Sintético Excel Já Existente", power_kwp=1.0)
    db_session.add(existing)
    db_session.commit()
    db_session.add(
        ProjectExternalId(project_id=existing.id, source_system="legacy_excel_licensing", external_id="REF-EXCEL-001")
    )
    db_session.commit()

    summary = apply_licensing_import(db_session, filename="f.xlsx", content=_content(), applied_by_person_id=None)
    assert summary.total_conflicts >= 1

    batch = db_session.get(FieldImportBatch, summary.batch_id)
    assert batch.status == "pending_confirmation"

    db_session.refresh(existing)
    assert existing.power_kwp == 1.0  # ainda não aplicado — conflito por resolver

    conflicted_record = next(r for r in batch.records if r.target_project_id == existing.id)
    for conflict in conflicted_record.conflicts:
        conflict.resolution = "use_new"
    db_session.commit()

    resumed = _finalize_licensing_batch(db_session, batch=batch, applied_by_person_id=None)
    assert resumed.total_conflicts == 0
    db_session.refresh(existing)
    assert existing.power_kwp == 9.0


def test_rollback_deactivates_newly_created_project(db_session):
    from app.services.imports_licensing import rollback_licensing_batch

    summary = apply_licensing_import(db_session, filename="f.xlsx", content=_content(), applied_by_person_id=None)
    project = find_project_by_external_reference(db_session, "REF-EXCEL-001")
    assert project.is_active is True

    batch = db_session.get(FieldImportBatch, summary.batch_id)
    rollback_licensing_batch(db_session, batch=batch)

    db_session.refresh(project)
    assert project.is_active is False
    db_session.refresh(batch)
    assert batch.status == "rejected"


def test_cli_dry_run_exits_zero_and_writes_nothing(db_session, capsys):
    exit_code = cli_main(["--file", str(FIXTURE_PATH), "--dry-run"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Dry-run" in out
    assert db_session.query(Project).filter(Project.name.like("%Excel%")).count() == 0


def test_legacy_licensing_preview_and_apply_refuse_deleted_external_reference(db_session):
    deleted = Project(
        name="Projeto Sintético Apagado Licenciamento",
        power_kwp=1.0,
        deleted_at=dt.datetime.now(dt.timezone.utc),
    )
    db_session.add(deleted)
    db_session.flush()
    db_session.add(
        ProjectExternalId(
            project_id=deleted.id,
            source_system="legacy_excel_licensing",
            external_id="REF-EXCEL-001",
        )
    )
    db_session.commit()
    project_count_before = db_session.query(Project).count()
    batch_count_before = db_session.query(FieldImportBatch).count()

    assert find_project_by_external_reference(db_session, "REF-EXCEL-001") is None
    with pytest.raises(LicensingImportError, match="apagado"):
        dry_run_licensing_import(db_session, content=_content())

    with pytest.raises(LicensingImportError, match="apagado"):
        apply_licensing_import(
            db_session,
            filename="deleted-licensing.xlsx",
            content=_content(),
            applied_by_person_id=None,
        )

    db_session.refresh(deleted)
    assert deleted.deleted_at is not None and deleted.power_kwp == 1.0
    assert db_session.query(Project).count() == project_count_before
    assert db_session.query(FieldImportBatch).count() == batch_count_before
    assert db_session.query(ProjectInstallationData).filter_by(project_id=deleted.id).count() == 0
    assert db_session.query(ProjectLicensingData).filter_by(project_id=deleted.id).count() == 0
    assert db_session.query(ProjectCommunicationData).filter_by(project_id=deleted.id).count() == 0


def test_pending_legacy_licensing_plan_does_not_apply_after_target_is_deleted_and_restores_cleanly(
    db_session,
):
    from app.models.project_data import ProjectDataHistory

    existing = Project(name="Projeto Sintético Apagar Depois", power_kwp=1.0)
    db_session.add(existing)
    db_session.flush()
    db_session.add(
        ProjectExternalId(
            project_id=existing.id,
            source_system="legacy_excel_licensing",
            external_id="REF-EXCEL-001",
        )
    )
    db_session.commit()

    summary = apply_licensing_import(
        db_session,
        filename="stale-licensing.xlsx",
        content=_content(),
        applied_by_person_id=None,
    )
    batch = db_session.get(FieldImportBatch, summary.batch_id)
    record = next(item for item in batch.records if item.target_project_id == existing.id)
    assert record.status != "applied"
    for conflict in record.conflicts:
        conflict.resolution = "use_new"
    db_session.commit()
    installation_before = db_session.query(ProjectInstallationData).filter_by(project_id=existing.id).count()
    licensing_before = db_session.query(ProjectLicensingData).filter_by(project_id=existing.id).count()
    communication_before = db_session.query(ProjectCommunicationData).filter_by(project_id=existing.id).count()
    history_before = db_session.query(ProjectDataHistory).filter_by(project_id=existing.id).count()

    existing.deleted_at = dt.datetime.now(dt.timezone.utc)
    db_session.commit()
    apply_licensing_import(
        db_session,
        filename="stale-licensing.xlsx",
        content=_content(),
        applied_by_person_id=None,
    )

    db_session.refresh(existing)
    assert existing.deleted_at is not None and existing.power_kwp == 1.0
    assert record.status != "applied"
    assert db_session.query(ProjectInstallationData).filter_by(project_id=existing.id).count() == installation_before
    assert db_session.query(ProjectLicensingData).filter_by(project_id=existing.id).count() == licensing_before
    assert db_session.query(ProjectCommunicationData).filter_by(project_id=existing.id).count() == communication_before
    assert db_session.query(ProjectDataHistory).filter_by(project_id=existing.id).count() == history_before

    existing.deleted_at = None
    db_session.commit()
    resumed = apply_licensing_import(
        db_session,
        filename="stale-licensing.xlsx",
        content=_content(),
        applied_by_person_id=None,
    )
    assert resumed.total_conflicts == 0
    db_session.refresh(existing)
    assert existing.power_kwp == 9.0
