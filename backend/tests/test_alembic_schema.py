"""Integridade da cadeia Alembic e drift entre migrações e modelos.

A suite usa `Base.metadata.create_all` (ver conftest.py), por isso nada
garantia que `alembic upgrade head` produz o mesmo esquema que os modelos
descrevem — e é o Alembic que cria a BD de produção. Estes testes fecham essa
lacuna (secção 4 de docs/ANALISE_OP_PM.md):

- um só head (um merge esquecido deixa `upgrade head` ambíguo);
- `alembic upgrade head` numa BD SQLite vazia seguido de
  `compare_metadata` contra `Base.metadata` não pode encontrar diferenças.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

import app.models  # noqa: F401  — regista todas as tabelas em Base.metadata
from app.db import Base

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _script_directory() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini")))


def test_alembic_has_a_single_head():
    heads = _script_directory().get_heads()
    assert len(heads) == 1, f"a cadeia Alembic tem {len(heads)} heads ({sorted(heads)}) — falta uma migração de merge"


def test_alembic_chain_is_linear_from_a_single_base():
    script = _script_directory()
    # `walk_revisions` falha se alguma `down_revision` apontar para uma
    # revisão inexistente; uma base única garante que não há ramos soltos.
    revisions = list(script.walk_revisions())
    assert revisions, "nenhuma revisão encontrada"
    assert len(script.get_bases()) == 1
    ids = [rev.revision for rev in revisions]
    assert len(ids) == len(set(ids))
    versions = [p for p in (BACKEND_DIR / "alembic" / "versions").glob("*.py") if not p.name.startswith("_")]
    assert len(versions) == len(revisions), "há ficheiros em alembic/versions fora da cadeia"


@pytest.fixture(scope="module")
def migrated_sqlite_url(tmp_path_factory) -> str:
    database_path = tmp_path_factory.mktemp("alembic-drift") / "migrated.db"
    url = f"sqlite:///{database_path.as_posix()}"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.update({"APP_ENV": "test", "DATABASE_URL": url})
    environment.pop("EXPECTED_DB_DIALECT", None)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return url


def _include_object(obj, name, type_, reflected, compare_to) -> bool:
    """Ignora as tabelas `*_provisioning`: são tabelas de contabilidade das
    migrações de permissões (registam as linhas que a migração criou, para o
    `downgrade` só remover essas). Existem de propósito só na BD migrada e não
    têm modelo."""
    if type_ == "table" and reflected and compare_to is None and name.endswith("_provisioning"):
        return False
    return True


def _format_diff(diff) -> str:
    return "\n".join(f"  {entry!r}" for entry in diff)


def test_alembic_head_matches_models_no_drift(migrated_sqlite_url):
    # `compare_server_default` fica desligado de propósito: as migrações põem
    # `server_default` em ~15 colunas NOT NULL (relatórios, memberships, ...)
    # que os modelos só preenchem com `default=` do lado Python. É uma
    # divergência conhecida, sem efeito em runtime (a app envia sempre o
    # valor); alinhá-la é trabalho à parte. Tipos e nulidade são comparados.
    engine = create_engine(migrated_sqlite_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={"compare_type": True, "compare_server_default": False, "include_object": _include_object},
            )
            diff = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()
    assert not diff, "Drift entre `alembic upgrade head` e os modelos:\n" + _format_diff(diff)
