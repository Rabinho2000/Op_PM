"""Contratos HTTP da BD privada, usando apenas dados sintéticos."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path


def _headers(email: str) -> dict[str, str]:
    return {"X-Dev-User-Email": email}


def _seed_private_prices(path: Path):
    from app.prices_db import CatalogDataset, MaterialPrice, PriceSource, _make_prices_engine, upgrade_prices_schema
    from sqlalchemy.orm import sessionmaker

    engine = _make_prices_engine(f"sqlite:///{path.as_posix()}")
    upgrade_prices_schema(engine)
    session = sessionmaker(bind=engine, autoflush=False, future=True)()
    source = PriceSource(code="synthetic-api", name="Synthetic API source", kind="compra")
    session.add(source)
    session.flush()
    session.add(
        MaterialPrice(
            domain="cabo",
            ref="SYN-API-CABLE",
            description="Synthetic API cable",
            unit="m",
            unit_price=Decimal("2.5000"),
            source_id=source.id,
            price_date=date(2026, 3, 1),
            attrs_json=json.dumps(
                {
                    "material": "Cu",
                    "forma": "round",
                    "section_mm2": 10,
                    "supplier": "Synthetic API source",
                    "engine_row": ["Cu", "round", 10, 2.5, "2026-03-01", "SYN-API-CABLE", "Synthetic API cable", "Synthetic API source"],
                },
                ensure_ascii=False,
            ),
            estimated=False,
            is_active=True,
        )
    )
    session.add_all(
        [
            CatalogDataset(
                name="breakers",
                version="synthetic-v1",
                content_sha256="a" * 64,
                payload_json='{"synthetic": {"rows": []}}',
                is_current=True,
            ),
            CatalogDataset(
                name="indus",
                version="synthetic-v1",
                content_sha256="b" * 64,
                payload_json='{"SYN-BOARD": ["Synthetic board", 1, "2026-03-01"]}',
                is_current=True,
            ),
        ]
    )
    session.commit()
    session.close()
    return engine


def test_engine_data_etag_and_price_permissions(api_client, tmp_path: Path):
    import app.prices_db as prices_db

    private_engine = prices_db.configure_prices_database(str(f"sqlite:///{(tmp_path / 'private.db').as_posix()}"))
    _seed_private_prices(tmp_path / "private.db")
    try:
        engine_data = api_client.get(
            "/api/cable-design/engine-data",
            headers=_headers("pm.um.sintetico@example.invalid"),
        )
        assert engine_data.status_code == 200, engine_data.text
        assert engine_data.headers["cache-control"] == "private, no-store"
        assert engine_data.headers["etag"]
        body = engine_data.json()
        assert body["prices"][0][5] == "SYN-API-CABLE"
        assert body["breakers"]["synthetic"]["rows"] == []
        assert body["versions"] == {"breakers": "a" * 64, "indus": "b" * 64}

        not_modified = api_client.get(
            "/api/cable-design/engine-data",
            headers={
                **_headers("pm.um.sintetico@example.invalid"),
                "If-None-Match": engine_data.headers["etag"],
            },
        )
        assert not_modified.status_code == 304
        assert not_modified.content == b""

        visible = api_client.get(
            "/api/material-prices?domain=cabo&current=true",
            headers=_headers("chefe.sintetico@example.invalid"),
        )
        assert visible.status_code == 200, visible.text
        assert visible.json()[0]["ref"] == "SYN-API-CABLE"

        forbidden = api_client.get(
            "/api/material-prices",
            headers=_headers("pm.um.sintetico@example.invalid"),
        )
        assert forbidden.status_code == 403

        unauthenticated = api_client.get("/api/material-prices")
        assert unauthenticated.status_code == 401
    finally:
        private_engine.dispose()
