"""Configuração tipada por ambiente.

Todos os valores sensíveis (segredos, tokens, chaves de API) vêm exclusivamente
de variáveis de ambiente / ficheiro `.env` local (nunca commitado — ver
`.gitignore`). Este módulo nunca deve conter um valor real; `.env.example`
documenta as chaves esperadas com valores vazios ou de exemplo óbvio.

Nesta fase (Fase 0), todas as integrações externas arrancam em modo mock por
omissão (`*_ENABLED=false`). Ligar uma integração real exige alterar
explicitamente a variável de ambiente correspondente — nunca é o
comportamento por omissão do código.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "staging", "production"]

# Valor de segredo que só é aceitável em 'local'/'test'. Mantido como
# constante nomeada (em vez de repetir a string) para que a validação de
# arranque (ver `Settings._enforce_hardening_in_non_local_envs`) e
# `.env.example` nunca divirjam silenciosamente.
DEFAULT_DEV_SECRET_KEY = "dev-only-insecure-secret-change-me"

# Ambientes onde a aplicação só arranca com configuração de produção real —
# nunca com o mecanismo de utilizador de desenvolvimento, segredo por
# omissão, ou SQLite. Ver docs/DECISIONS.md.
HARDENED_ENVIRONMENTS: frozenset[Environment] = frozenset({"staging", "production"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Aplicação ---
    app_env: Environment = Field(default="local", alias="APP_ENV")
    app_name: str = Field(default="Op_PM API", alias="APP_NAME")
    secret_key: str = Field(
        default=DEFAULT_DEV_SECRET_KEY,
        alias="SECRET_KEY",
        description="Nunca usar o valor por omissão fora de 'local'/'test'.",
    )

    # --- Base de dados ---
    # Produção/staging: PostgreSQL (fonte de verdade operacional única).
    # Local/test por omissão: SQLite em ficheiro, para arrancar sem serviços
    # externos. Ver docs/DECISIONS.md (D-0xx) para a justificação desta
    # escolha pragmática de Fase 0.
    database_url: str = Field(
        default="sqlite:///./data/op_pm_local.db",
        alias="DATABASE_URL",
    )

    # --- Autenticação (Microsoft Entra ID) ---
    entra_tenant_id: str = Field(default="", alias="ENTRA_TENANT_ID")
    entra_client_id: str = Field(default="", alias="ENTRA_CLIENT_ID")
    entra_client_secret: str = Field(default="", alias="ENTRA_CLIENT_SECRET")
    auth_enabled: bool = Field(
        default=False,
        alias="AUTH_ENABLED",
        description="Falso em Fase 0: sem Entra ID configurado, usa utilizador de desenvolvimento local.",
    )

    # --- Integrações: flags explícitas, todas falsas por omissão ---
    graph_enabled: bool = Field(default=False, alias="GRAPH_ENABLED")
    graph_tenant_id: str = Field(default="", alias="GRAPH_TENANT_ID")
    graph_client_id: str = Field(default="", alias="GRAPH_CLIENT_ID")
    graph_client_secret: str = Field(default="", alias="GRAPH_CLIENT_SECRET")
    # Pasta local onde o adapter de fallback grava rascunhos .eml/.ics
    # enquanto o Graph real não estiver configurado.
    graph_fallback_dir: str = Field(default="./data/outbox", alias="GRAPH_FALLBACK_DIR")

    clickup_enabled: bool = Field(default=False, alias="CLICKUP_ENABLED")
    clickup_token: str = Field(default="", alias="CLICKUP_TOKEN")
    clickup_list_id: str = Field(default="", alias="CLICKUP_LIST_ID")

    financial_enabled: bool = Field(default=False, alias="FINANCIAL_ENABLED")
    financial_mode: Literal["mock", "csv", "excel", "api"] = Field(
        default="mock", alias="FINANCIAL_MODE"
    )
    financial_csv_path: str = Field(default="", alias="FINANCIAL_CSV_PATH")
    financial_api_base_url: str = Field(default="", alias="FINANCIAL_API_BASE_URL")
    financial_api_key: str = Field(default="", alias="FINANCIAL_API_KEY")

    claude_enabled: bool = Field(default=False, alias="CLAUDE_ENABLED")
    claude_api_key: str = Field(default="", alias="CLAUDE_API_KEY")
    claude_model: str = Field(default="claude-sonnet-5", alias="CLAUDE_MODEL")

    @model_validator(mode="after")
    def _enforce_hardening_in_non_local_envs(self) -> "Settings":
        """Impede o arranque em staging/produção com configuração de
        desenvolvimento. Isto corre sempre que `Settings()` é construído —
        incluindo em `get_settings()`, chamado no import de `app.main` — por
        isso uma configuração insegura impede mesmo o processo de arrancar,
        não é só um aviso em runtime.

        Regra explícita (ver docs/DECISIONS.md): em 'staging'/'production',
        AUTH_ENABLED tem de ser verdadeiro, SECRET_KEY não pode ser o valor
        de desenvolvimento, e DATABASE_URL não pode ser SQLite. O mecanismo
        de utilizador de desenvolvimento (`X-Dev-User-Email` — ver
        `app/security/current_user.py`) tem uma segunda verificação
        independente, feita a cada pedido, para o mesmo efeito."""
        if self.app_env not in HARDENED_ENVIRONMENTS:
            return self

        problems: list[str] = []
        if not self.auth_enabled:
            problems.append("AUTH_ENABLED tem de ser 'true'")
        if self.secret_key == DEFAULT_DEV_SECRET_KEY:
            problems.append("SECRET_KEY não pode usar o valor de desenvolvimento por omissão")
        if self.database_url.startswith("sqlite"):
            problems.append("DATABASE_URL não pode ser SQLite")

        if problems:
            raise ValueError(
                f"Configuração insegura para APP_ENV={self.app_env!r}: "
                + "; ".join(problems)
                + ". Corrigir as variáveis de ambiente antes de arrancar."
            )
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def data_dir(self) -> Path:
        path = Path(self.graph_fallback_dir).parent
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache
def get_settings() -> Settings:
    return Settings()
