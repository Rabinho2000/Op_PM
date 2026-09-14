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

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "staging", "production"]


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
        default="dev-only-insecure-secret-change-me",
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
