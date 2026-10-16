"""Testes sintéticos da BD privada de preços."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.orm import sessionmaker


def test_private_prices_schema_and_current_price_are_file_scoped(tmp_path):
    from app.prices_db import (
        MaterialPrice,
        PriceSource,
        _make_prices_engine,
        upgrade_prices_schema,
    )
    from app.services.material_prices import list_material_prices

    engine = _make_prices_engine(f"sqlite:///{(tmp_path / 'prices.db').as_posix()}")
    upgrade_prices_schema(engine)
    Session = sessionmaker(bind=engine, autoflush=False, future=True)
    db = Session()
    try:
        source = PriceSource(code="synthetic-source", name="Synthetic source", kind="compra")
        db.add(source)
        db.flush()
        db.add_all(
            [
                MaterialPrice(
                    domain="cabo",
                    ref="SYN-CABLE-1",
                    description="Synthetic cable old",
                    unit="m",
                    unit_price=Decimal("1.2300"),
                    source_id=source.id,
                    price_date=date(2026, 1, 1),
                    attrs_json="{}",
                    estimated=False,
                    is_active=True,
                ),
                MaterialPrice(
                    domain="cabo",
                    ref="SYN-CABLE-1",
                    description="Synthetic cable current",
                    unit="m",
                    unit_price=Decimal("1.4500"),
                    source_id=source.id,
                    price_date=date(2026, 2, 1),
                    attrs_json="{}",
                    estimated=False,
                    is_active=True,
                ),
            ]
        )
        db.commit()
        rows = list_material_prices(db, current=True)
        assert len(rows) == 1
        assert rows[0]["ref"] == "SYN-CABLE-1"
        assert rows[0]["unit_price"] == Decimal("1.4500")
    finally:
        db.close()
        engine.dispose()

    assert set(inspect(engine).get_table_names()) >= {
        "schema_version",
        "price_sources",
        "material_prices",
        "price_import_batches",
        "catalog_datasets",
    }


def test_indus_parser_reads_literal_without_executing_javascript(tmp_path: Path):
    from app.cli.load_material_prices import parse_indus_source

    path = tmp_path / "rt-indus.js"
    path.write_text(
        "const INDUS={'SYN-BOARD':['Synthetic board',12.3456,'2026-03-01']};\n"
        "globalThis.__should_not_run = true;\n",
        encoding="utf-8",
    )

    parsed = parse_indus_source(path)

    assert parsed == {"SYN-BOARD": ["Synthetic board", 12.3456, "2026-03-01"]}
    assert not hasattr(__builtins__, "__should_not_run")


def test_loader_dry_run_apply_and_same_hash_are_idempotent(tmp_path: Path):
    from app.cli.load_material_prices import load_directory
    from app.prices_db import CatalogDataset, MaterialPrice, PriceImportBatch, _make_prices_engine, upgrade_prices_schema

    source = tmp_path / "input"
    source.mkdir()
    (source / "prices.json").write_text(
        '[\n'
        '  ["Cu", "round", 6, 1.25, "2026-01-01", "SYN-CABLE", "Synthetic cable", "Synthetic supplier"],\n'
        '  ["Cu", "round", 6, 1.50, "2026-02-01", "SYN-CABLE", "Synthetic cable", "Synthetic supplier"],\n'
        '  ["Cu", "term", 6, 0.35, "2026-02-01", "SYN-TERM", "Synthetic terminal", "Synthetic supplier"]\n'
        ']',
        encoding="utf-8",
    )
    (source / "brk.json").write_text('{"synthetic": {"rows": [{"rating": "SYN"}]}}', encoding="utf-8")
    (source / "hager.json").write_text('{"SYN-HAGER": ["Synthetic hager", 2.5]}', encoding="utf-8")
    (source / "rt-indus.js").write_text(
        "const INDUS={'SYN-BOARD':['Synthetic quadro',10.00,'2026-02-02'],"
        "'SYN-DEVICE':['Synthetic aparelho',4.00,'2026-02-02']};",
        encoding="utf-8",
    )

    engine = _make_prices_engine(f"sqlite:///{(tmp_path / 'prices.db').as_posix()}")
    upgrade_prices_schema(engine)
    Session = sessionmaker(bind=engine, autoflush=False, future=True)
    db = Session()
    try:
        preview = load_directory(source, dry_run=True, db=db)
        assert preview["inserted"] == 0
        assert preview["prices"]["cabo"] == 2
        assert preview["prices"]["terminal"] == 1
        assert preview["prices"]["aparelho"] == 1
        assert preview["prices"]["quadro"] == 1
        assert db.query(MaterialPrice).count() == 0

        applied = load_directory(source, db=db)
        assert applied["inserted"] == 8
        assert db.query(MaterialPrice).count() == 5
        assert db.query(CatalogDataset).count() == 3
        assert db.query(PriceImportBatch).count() == 4

        repeated = load_directory(source, db=db)
        assert repeated["inserted"] == 0
        assert repeated["already_loaded"] == 4
        assert repeated["skipped"] == 8
        assert db.query(MaterialPrice).count() == 5
    finally:
        db.close()
        engine.dispose()


def test_loader_fails_closed_for_missing_or_malformed_input(tmp_path: Path):
    from app.cli.load_material_prices import MaterialPricesLoadError, parse_directory

    source = tmp_path / "input"
    source.mkdir()
    with pytest.raises(MaterialPricesLoadError):
        parse_directory(source)
    for name in ("prices.json", "brk.json", "hager.json", "rt-indus.js"):
        path = source / name
        if name == "prices.json":
            path.write_text("{}", encoding="utf-8")
        elif name.endswith(".json"):
            path.write_text("{}", encoding="utf-8")
        else:
            path.write_text("const INDUS = nope;", encoding="utf-8")
    with pytest.raises(MaterialPricesLoadError):
        parse_directory(source)

