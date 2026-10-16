"""Ligação e schema da base privada de preços de materiais.

Esta base é deliberadamente independente da base operacional: não importa
``app.db.Base`` nem cria chaves estrangeiras para as tabelas principais. O
schema é atualizado por um mini-migrador local (``schema_version``), porque os
preços não fazem parte das migrações Alembic públicas.
"""
from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Generator
from pathlib import Path
from typing import Any

from fastapi import Request
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    create_engine,
    event,
    false,
    insert,
    select,
    text,
    true,
)
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import get_settings


_ALLOWED_DOMAINS = "'cabo', 'terminal', 'aparelho', 'quadro', 'inventario'"
_ALLOWED_SOURCE_KINDS = "'compra', 'catalogo', 'orcamento'"


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class PricesBase(DeclarativeBase):
    """Base declarativa exclusiva da BD privada."""


class SchemaVersion(PricesBase):
    __tablename__ = "schema_version"

    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )


class PriceSource(PricesBase):
    __tablename__ = "price_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )

    __table_args__ = (
        CheckConstraint(f"kind IN ({_ALLOWED_SOURCE_KINDS})", name="ck_price_sources_kind"),
    )


class MaterialPrice(PricesBase):
    __tablename__ = "material_prices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    domain: Mapped[str] = mapped_column(String(16), nullable=False)
    ref: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(String(512), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    unit_price: Mapped[Any] = mapped_column(Numeric(14, 4), nullable=False)
    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("price_sources.id", ondelete="RESTRICT"), nullable=False
    )
    price_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    attrs_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    estimated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    item_sku: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )

    __table_args__ = (
        CheckConstraint(f"domain IN ({_ALLOWED_DOMAINS})", name="ck_material_prices_domain"),
        CheckConstraint("unit_price >= 0", name="ck_material_prices_unit_price_nonnegative"),
        Index("ix_material_prices_domain_ref_date", "domain", "ref", "price_date"),
    )


class PriceImportBatch(PricesBase):
    __tablename__ = "price_import_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    source_file_sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    loaded_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
    rows_inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rows_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    actor: Mapped[str] = mapped_column(String(128), nullable=False, default="cli", server_default="cli")


class CatalogDataset(PricesBase):
    __tablename__ = "catalog_datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[str] = mapped_column(String(128), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    loaded_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())

    __table_args__ = (
        CheckConstraint("name IN ('breakers', 'indus', 'hager')", name="ck_catalog_datasets_name"),
        Index(
            "uq_catalog_datasets_current_name",
            "name",
            unique=True,
            sqlite_where=(is_current.is_(True)),
            postgresql_where=(is_current.is_(True)),
        ),
        Index("ix_catalog_datasets_name_loaded_at", "name", "loaded_at"),
    )


# Aliases with explicit names used by callers that prefer the table-oriented
# vocabulary from the plan.
MaterialPriceRow = MaterialPrice
PriceSourceRow = PriceSource
PriceImportBatchRow = PriceImportBatch
CatalogDatasetRow = CatalogDataset


def _make_prices_engine(url: str | None = None) -> Engine:
    """Create an engine for the private URL without touching the main DB."""
    database_url = url or get_settings().prices_database_url
    connect_args: dict[str, Any] = {}
    is_sqlite = database_url.startswith("sqlite")
    if is_sqlite:
        connect_args.update({"check_same_thread": False, "timeout": 30.0})
        if ":memory:" not in database_url:
            raw_path = database_url.split("///", 1)[-1].split("?", 1)[0]
            Path(raw_path).expanduser().parent.mkdir(parents=True, exist_ok=True)

    new_engine = create_engine(database_url, connect_args=connect_args, future=True)
    if is_sqlite:

        @event.listens_for(new_engine, "connect")
        def _sqlite_transaction_setup(dbapi_connection, _connection_record):
            dbapi_connection.isolation_level = None
            dbapi_connection.execute("PRAGMA foreign_keys=ON")
            if ":memory:" not in database_url:
                dbapi_connection.execute("PRAGMA journal_mode=WAL")
                dbapi_connection.execute("PRAGMA synchronous=NORMAL")
                dbapi_connection.execute(f"PRAGMA busy_timeout={int(connect_args['timeout'] * 1000)}")

        @event.listens_for(new_engine, "begin")
        def _sqlite_begin(connection):
            if connection.get_execution_options().get("sqlite_read_only"):
                connection.exec_driver_sql("BEGIN")
            else:
                connection.exec_driver_sql("BEGIN IMMEDIATE")

    return new_engine


# The public globals mirror app.db while remaining completely separate from it.
prices_engine = _make_prices_engine()
PriceSessionLocal = sessionmaker(bind=prices_engine, autoflush=False, autocommit=False, future=True)
engine = prices_engine
SessionLocal = PriceSessionLocal


_CURRENT_SCHEMA_VERSION = 1


def upgrade_prices_schema(bind: Engine | Connection | None = None) -> None:
    """Apply all private-schema steps idempotently.

    A single row in ``schema_version`` records the applied version.  ``create_all``
    is intentionally used only for the first version's idempotent DDL; future
    changes should be added as explicit numbered steps here, never to Alembic.
    """
    target = bind or prices_engine
    if isinstance(target, Engine):
        with target.begin() as connection:
            _upgrade_prices_schema_connection(connection)
    else:
        _upgrade_prices_schema_connection(target)


def _upgrade_prices_schema_connection(connection: Connection) -> None:
    SchemaVersion.__table__.create(connection, checkfirst=True)
    current = connection.execute(select(SchemaVersion.version).order_by(SchemaVersion.version.desc())).scalar_one_or_none()
    if current is not None and current > _CURRENT_SCHEMA_VERSION:
        raise RuntimeError(
            f"schema da BD de preços ({current}) é mais recente do que o suportado ({_CURRENT_SCHEMA_VERSION})."
        )
    PricesBase.metadata.create_all(connection, checkfirst=True)
    if current is None:
        connection.execute(insert(SchemaVersion).values(version=_CURRENT_SCHEMA_VERSION, applied_at=_utc_now()))


def configure_prices_database(url: str) -> Engine:
    """Replace the process-local private engine, primarily for isolated tests."""
    global prices_engine, PriceSessionLocal, engine, SessionLocal
    old_engine = prices_engine
    prices_engine = _make_prices_engine(url)
    PriceSessionLocal = sessionmaker(bind=prices_engine, autoflush=False, autocommit=False, future=True)
    engine = prices_engine
    SessionLocal = PriceSessionLocal
    if old_engine is not prices_engine:
        old_engine.dispose()
    return prices_engine


def open_prices_session(*, read_only: bool = False):
    """Open a private session after ensuring the mini-schema exists."""
    upgrade_prices_schema()
    db = PriceSessionLocal()
    if read_only and prices_engine.dialect.name == "sqlite":
        db.connection(execution_options={"sqlite_read_only": True})
    return db


def get_prices_db(request: Request) -> Generator[Any, None, None]:
    """FastAPI dependency for callers that want a private session directly."""
    db = open_prices_session(read_only=request.method in {"GET", "HEAD", "OPTIONS"})
    try:
        yield db
    finally:
        db.close()


# Explicit aliases keep integrations readable and make the mini-migrator easy
# to discover without exposing the main app's engine by accident.
ensure_prices_schema = upgrade_prices_schema
migrate_prices_database = upgrade_prices_schema
get_prices_engine = lambda: prices_engine
