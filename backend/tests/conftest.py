"""Configuração partilhada dos testes.

Regra de ouro (corrigida numa revisão de hardening — ver docs/DECISIONS.md
D-022): este ficheiro NUNCA sobrescreve um `DATABASE_URL` já definido no
ambiente. Isso permite ao CI (ou a um dev local) apontar a suite para
PostgreSQL — o job `backend-postgres` do GitHub Actions depende disto para
não passar silenciosamente contra SQLite. Só quando `DATABASE_URL` está
por definir é que criamos e geríamos um ficheiro SQLite temporário, como
conveniência de desenvolvimento local (ver `backend/.env.example`).

`app/db.py` constrói o `engine` uma única vez, no momento do import, a
partir de `Settings().database_url` — por isso estas variáveis de ambiente
têm de estar definidas ANTES de qualquer módulo `app.*` ser importado.
Nenhum teste aqui toca em dados reais: a base é recriada de raiz e semeada
só com os dados sintéticos de `app/migration/seed_dev.py`.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

if "DATABASE_URL" not in os.environ:
    # Nenhum DATABASE_URL fornecido pelo ambiente (chamador) — usa um
    # SQLite temporário próprio, recriado a cada arranque da suite.
    _TEST_DB_PATH = Path(tempfile.gettempdir()) / "op_pm_test.db"
    if _TEST_DB_PATH.exists():
        _TEST_DB_PATH.unlink()
    os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH.as_posix()}"
# else: DATABASE_URL já está definido (ex.: o job backend-postgres do CI,
# ou um dev a testar manualmente contra PostgreSQL) — respeitado tal como
# está, nunca sobreposto.

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("GRAPH_FALLBACK_DIR", str(Path(tempfile.gettempdir()) / "op_pm_test_outbox"))

from sqlalchemy import event  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.migration.seed_dev import run_seed  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _prepare_database():
    # Verificação explícita e obrigatória (ver docs/DECISIONS.md D-022):
    # quando o chamador declara EXPECTED_DB_DIALECT (o CI declara-o nos
    # dois jobs de backend), a suite recusa-se a continuar se o dialect
    # real ligado não corresponder — nunca falha silenciosamente para
    # SQLite. `pytest.exit` aborta a sessão inteira antes de qualquer
    # teste correr, garantindo que o job de CI fica vermelho, não verde
    # com testes "passados" contra o motor errado.
    expected_dialect = os.environ.get("EXPECTED_DB_DIALECT")
    if expected_dialect and engine.dialect.name != expected_dialect:
        pytest.exit(
            f"EXPECTED_DB_DIALECT={expected_dialect!r} mas o motor realmente ligado "
            f"é {engine.dialect.name!r} (DATABASE_URL={os.environ.get('DATABASE_URL')!r}). "
            "A suite recusa-se a continuar — isto existe especificamente para impedir "
            "que o job 'backend-postgres' do CI passe silenciosamente contra SQLite.",
            returncode=1,
        )
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
