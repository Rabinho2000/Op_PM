"""Os `.env.example` têm de refletir `app/config.py`: toda a variável
documentada existe (sem deriva de nomes, p.ex. `GRAPH_CLIENT_SECRET` vs.
`GRAPH_CLIENT_SECRET_FILE`), toda a variável de `Settings` está documentada,
e o exemplo de desenvolvimento carrega tal como está (valores vazios incluídos)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.config import Settings

BACKEND = Path(__file__).resolve().parents[1]
EXAMPLES = [BACKEND / ".env.example", BACKEND / ".env.staging.example"]
# Lida diretamente por `app/logging_setup.py`, não por `Settings`.
NON_SETTINGS_VARIABLES = {"LOG_LEVEL"}
KNOWN = {field.alias for field in Settings.model_fields.values() if field.alias}


def _documented(path: Path) -> set[str]:
    pattern = re.compile(r"^#?\s*([A-Z][A-Z0-9_]+)=", re.MULTILINE)
    return set(pattern.findall(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_every_documented_variable_exists_in_settings(path):
    unknown = _documented(path) - KNOWN - NON_SETTINGS_VARIABLES
    assert not unknown, f"{path.name} documenta variáveis que o código não lê: {sorted(unknown)}"


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_every_settings_variable_is_documented(path):
    # Só do código para o exemplo: ENTRA_MOCK_* é exclusivo de local/test.
    missing = KNOWN - _documented(path) - {"ENTRA_MOCK_PUBLIC_KEY_FILE"}
    assert not missing, f"{path.name} não documenta: {sorted(missing)}"


def test_dev_example_loads_as_is(monkeypatch):
    for name in KNOWN:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_ENV", "local")
    settings = Settings(_env_file=BACKEND / ".env.example")
    assert settings.app_env == "local"
    assert settings.api_docs_enabled is None
    assert settings.entra_jit_link_by_email is None
