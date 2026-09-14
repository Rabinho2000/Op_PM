"""Configuração partilhada dos testes.

Isola a base de dados de teste num ficheiro SQLite temporário, definido
ANTES de qualquer módulo `app.*` ser importado — `app/db.py` constrói o
`engine` uma única vez, no momento do import, a partir de
`Settings().database_url`. Nenhum teste aqui toca em dados reais: a base é
recriada de raiz e semeada só com os dados sintéticos de
`app/migration/seed_dev.py`.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TEST_DB_PATH = Path(tempfile.gettempdir()) / "op_pm_test.db"
if _TEST_DB_PATH.exists():
    _TEST_DB_PATH.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH.as_posix()}"
os.environ["APP_ENV"] = "test"
os.environ["GRAPH_FALLBACK_DIR"] = str(Path(tempfile.gettempdir()) / "op_pm_test_outbox")

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.migration.seed_dev import run_seed  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _prepare_database():
    Base.metadata.create_all(bind=engine)
    run_seed()
    yield


@pytest.fixture()
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
