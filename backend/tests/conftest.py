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

from sqlalchemy import event  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.migration.seed_dev import run_seed  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _prepare_database():
    Base.metadata.create_all(bind=engine)
    run_seed()
    yield


@pytest.fixture()
def db_session():
    """Isola cada teste numa transação exterior que é sempre desfeita no
    fim — mesmo que o código testado chame `session.commit()` várias vezes,
    como `app/migration/staging.py` faz de propósito a cada etapa
    (ingestão, resolução, promoção, rollback). Sem isto, esses commits
    reais deixariam dados de um teste visíveis nos testes seguintes, porque
    todos partilham o mesmo ficheiro SQLite de teste (ver `_prepare_database`
    acima, que só corre uma vez por sessão).

    Padrão documentado do SQLAlchemy ("Joining a Session into an External
    Transaction"): liga a sessão a uma única `connection`, abre uma
    transação exterior + uma SAVEPOINT; quando o código testado faz
    `commit()`, só a SAVEPOINT termina — um listener reabre logo outra, para
    que haja sempre uma ativa. No fim do teste, `trans.rollback()` desfaz a
    transação exterior por completo, incluindo tudo o que foi "commitado"
    lá dentro.
    """
    connection = engine.connect()
    trans = connection.begin()
    session = SessionLocal(bind=connection)

    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess, transaction):
        nonlocal nested
        if not nested.is_active:
            nested = connection.begin_nested()

    try:
        yield session
    finally:
        session.close()
        if trans.is_active:
            trans.rollback()
        connection.close()
