"""Ligação à base de dados e tipos portáveis SQLite/PostgreSQL.

Produção e staging usam PostgreSQL (fonte de verdade operacional única —
ver docs/ARCHITECTURE_PROPOSAL.md). Local/test usam SQLite por omissão para
não depender de serviços externos nesta fase. Os modelos evitam tipos
específicos do PostgreSQL para que o mesmo schema/migração funcione em ambos
os motores; `GUID` abaixo é o único ponto de adaptação necessário.
"""
from __future__ import annotations

import uuid
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import CHAR, TypeDecorator

from app.config import get_settings


class GUID(TypeDecorator):
    """Identificador UUID portável: nativo em PostgreSQL, texto em SQLite."""

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import UUID as PG_UUID

            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return str(value)
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    pass


def _make_engine():
    settings = get_settings()
    url = settings.database_url
    connect_args = {}
    is_sqlite = url.startswith("sqlite")
    if is_sqlite:
        connect_args["check_same_thread"] = False
        # garante que a pasta ./data existe antes do SQLite tentar abrir o ficheiro
        if ":memory:" not in url:
            from pathlib import Path

            db_path = url.split("///")[-1]
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    new_engine = create_engine(url, connect_args=connect_args, future=True)

    if is_sqlite:
        # Recipe padrão do SQLAlchemy para SAVEPOINTs funcionarem
        # corretamente com o pysqlite: por omissão o pysqlite gere as suas
        # próprias transações de forma a interferir com begin_nested(). Só
        # tem efeito em SQLite — nunca em PostgreSQL. Usado por
        # tests/conftest.py para isolar cada teste numa transação que é
        # sempre desfeita no fim, mesmo que o código testado chame
        # `session.commit()` várias vezes (como app/migration/staging.py
        # faz de propósito).
        @event.listens_for(new_engine, "connect")
        def _sqlite_disable_pysqlite_transaction_control(dbapi_connection, connection_record):
            dbapi_connection.isolation_level = None

        @event.listens_for(new_engine, "begin")
        def _sqlite_emit_explicit_begin(conn):
            conn.exec_driver_sql("BEGIN")

    return new_engine


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
