"""Verificação explícita e visível do motor de base de dados realmente
ligado — sobretudo para o job `backend-postgres` do CI, que declara
`EXPECTED_DB_DIALECT=postgresql` precisamente para nunca poder passar
silenciosamente contra SQLite (ver docs/DECISIONS.md D-022).

O bloqueio "duro" já acontece em `conftest.py::_prepare_database` (via
`pytest.exit`, antes de qualquer teste correr) — este teste existe também
como um resultado nomeado e visível no relatório da suite, e como
documentação executável da garantia.
"""
from __future__ import annotations

import os

import pytest

from app.db import engine


def test_dialect_matches_expected_when_declared_by_the_caller():
    expected = os.environ.get("EXPECTED_DB_DIALECT")
    if not expected:
        pytest.skip(
            "EXPECTED_DB_DIALECT não definido pelo ambiente — nada a verificar aqui "
            "(uso local sem essa variável). Os jobs de CI definem-na sempre."
        )
    assert engine.dialect.name == expected, (
        f"esperava o motor {expected!r} mas a suite está ligada a {engine.dialect.name!r}"
    )


def test_postgres_ci_job_is_really_postgresql_not_a_silent_sqlite_fallback():
    """Redundante de propósito em relação ao teste acima: um nome de teste
    que descreve exatamente o risco que existe a evitar, para que apareça
    sem ambiguidade no relatório do job 'backend-postgres'."""
    if os.environ.get("EXPECTED_DB_DIALECT") != "postgresql":
        pytest.skip("Só relevante quando o chamador pede explicitamente EXPECTED_DB_DIALECT=postgresql.")
    assert engine.dialect.name == "postgresql"
    assert engine.dialect.name != "sqlite"
