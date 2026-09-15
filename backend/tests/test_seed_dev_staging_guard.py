"""Seed sintético nunca corre em staging/produção (docs/STAGING_RUNBOOK.md).

Testa `assert_seed_allowed_environment` diretamente — o mesmo padrão de
`tests/test_ingest_staging_cli.py` para `assert_staging_only_environment`.
Não chama `run_seed()` com APP_ENV real de staging/produção aqui (exigiria
mexer na configuração global partilhada pelos outros testes); a barreira
em si é o que se testa, e `run_seed()` só a invoca no primeiro passo.
"""
from __future__ import annotations

import pytest

from app.migration.seed_dev import SeedNotAllowedError, assert_seed_allowed_environment


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_assert_seed_allowed_environment_rejects_hardened_envs(app_env):
    with pytest.raises(SeedNotAllowedError, match="seed sintético recusado"):
        assert_seed_allowed_environment(app_env)


@pytest.mark.parametrize("app_env", ["local", "test"])
def test_assert_seed_allowed_environment_allows_local_and_test(app_env):
    assert_seed_allowed_environment(app_env)  # não levanta
