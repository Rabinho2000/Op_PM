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
        description="Falso por omissão: usa o mecanismo de utilizador de desenvolvimento local.",
    )
    # 'real': valida contra o tenant Entra ID de verdade (JWKS via rede,
    # issuer/audience derivados de entra_tenant_id/entra_client_id).
    # 'mock': valida contra uma chave de teste local, sem rede — só para
    # testes automatizados; NUNCA aceitável em staging/produção (reforçado
    # por _enforce_hardening_in_non_local_envs abaixo). Ver
    # app/security/entra_auth.py e docs/DECISIONS.md D-024.
    entra_validation_mode: Literal["real", "mock"] = Field(default="real", alias="ENTRA_VALIDATION_MODE")
    # Normalmente derivados de entra_tenant_id/entra_client_id — só
    # preencher explicitamente para um cenário não-standard (ex. tenant
    # multi-audience, ou apontar para um emissor de testes).
    entra_issuer: str = Field(default="", alias="ENTRA_ISSUER")
    entra_jwks_url: str = Field(default="", alias="ENTRA_JWKS_URL")
    entra_audience: str = Field(default="", alias="ENTRA_AUDIENCE")
    # Escopo delegado exigido no claim 'scp' (ver docs/DECISIONS.md D-029)
    # — esta API só aceita tokens delegados (utilizador interativo via
    # Authorization Code + PKCE), nunca tokens só de aplicação (client
    # credentials, claim 'roles' sem 'scp'). Vazio: qualquer 'scp' não
    # vazio serve, mas um token sem 'scp' nenhum continua sempre recusado.
    entra_required_scope: str = Field(default="", alias="ENTRA_REQUIRED_SCOPE")
    # None = "não configurado explicitamente" -> ver
    # resolved_entra_jit_link_by_email(): True em local/test, False em
    # staging/produção, a menos que definido aqui de propósito (D-029).
    entra_jit_link_by_email: bool | None = Field(default=None, alias="ENTRA_JIT_LINK_BY_EMAIL")

    def resolved_entra_issuer(self) -> str:
        return self.entra_issuer or f"https://login.microsoftonline.com/{self.entra_tenant_id}/v2.0"

    def resolved_entra_jwks_url(self) -> str:
        return self.entra_jwks_url or (
            f"https://login.microsoftonline.com/{self.entra_tenant_id}/discovery/v2.0/keys"
        )

    def resolved_entra_audience(self) -> str:
        return self.entra_audience or self.entra_client_id

    def resolved_entra_jit_link_by_email(self) -> bool:
        if self.entra_jit_link_by_email is not None:
            return self.entra_jit_link_by_email
        return self.app_env not in HARDENED_ENVIRONMENTS

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

    # --- CORS (frontend a falar com esta API) ---
    # Em 'local'/'test', o servidor liberta sempre localhost em qualquer
    # porta (conveniência de desenvolvimento — `npm run dev` muda de porta
    # com frequência). Em 'staging'/'production' só as origens aqui
    # listadas (separadas por vírgula) são aceites — vazio por omissão,
    # tem de ser configurado explicitamente antes de expor a API.
    cors_allowed_origins: str = Field(default="", alias="CORS_ALLOWED_ORIGINS")

    def resolved_cors_origins(self) -> list[str]:
        explicit = [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]
        if self.app_env in ("local", "test"):
            return explicit or ["http://localhost:5173", "http://127.0.0.1:5173"]
        return explicit

    @model_validator(mode="after")
    def _enforce_hardening_in_non_local_envs(self) -> "Settings":
        """Impede o arranque em staging/produção com configuração de
        desenvolvimento ou incompleta. Isto corre sempre que `Settings()` é
        construído — incluindo em `get_settings()`, chamado no import de
        `app.main` — por isso uma configuração insegura impede mesmo o
        processo de arrancar, não é só um aviso em runtime.

        Regra explícita (ver docs/DECISIONS.md D-020/D-032): em
        'staging'/'production':
        - AUTH_ENABLED tem de ser verdadeiro;
        - SECRET_KEY não pode ser o valor de desenvolvimento nem vazio;
        - DATABASE_URL não pode ser SQLite (tem de ser PostgreSQL);
        - ENTRA_VALIDATION_MODE tem de ser 'real' — o validador de token
          'mock' (D-024) nunca pode ser alcançável fora de local/test, mesmo
          que alguém ligue AUTH_ENABLED sem querer dizer isso a sério;
        - ENTRA_TENANT_ID, ENTRA_CLIENT_ID e ENTRA_REQUIRED_SCOPE têm de
          estar preenchidos — sem eles não há tenant/scope a validar, e
          `resolved_entra_issuer()`/`resolved_entra_jwks_url()` apontariam
          para um URL inválido (D-032);
        - CORS_ALLOWED_ORIGINS não pode ficar vazio — vazio nestes ambientes
          significaria "nenhuma origem aceite" em runtime (ver
          `resolved_cors_origins`), o que quase de certeza não é a intenção
          de quem está a configurar isto, por isso falha já no arranque em
          vez de deixar a API silenciosamente inacessível a qualquer
          frontend (D-032);
        - se algum de ENTRA_ISSUER/ENTRA_JWKS_URL/ENTRA_AUDIENCE for
          definido explicitamente, os três têm de estar (um override
          parcial deixaria os campos não definidos a cair para o valor
          derivado de ENTRA_TENANT_ID/ENTRA_CLIENT_ID, uma mistura que quase
          nunca é a intenção de quem define um override manual — D-032).

        O mecanismo de utilizador de desenvolvimento (`X-Dev-User-Email` —
        ver `app/security/current_user.py`) tem uma segunda verificação
        independente, feita a cada pedido, para o mesmo efeito."""
        if self.app_env not in HARDENED_ENVIRONMENTS:
            return self

        problems: list[str] = []
        if not self.auth_enabled:
            problems.append("AUTH_ENABLED tem de ser 'true'")
        if self.secret_key == DEFAULT_DEV_SECRET_KEY or not self.secret_key.strip():
            problems.append("SECRET_KEY não pode usar o valor de desenvolvimento por omissão nem ficar vazio")
        if self.database_url.startswith("sqlite"):
            problems.append("DATABASE_URL não pode ser SQLite (tem de ser PostgreSQL)")
        if self.entra_validation_mode != "real":
            problems.append("ENTRA_VALIDATION_MODE tem de ser 'real' (nunca 'mock')")
        if not self.entra_tenant_id.strip():
            problems.append("ENTRA_TENANT_ID tem de estar preenchido")
        if not self.entra_client_id.strip():
            problems.append("ENTRA_CLIENT_ID tem de estar preenchido")
        if not self.entra_required_scope.strip():
            problems.append("ENTRA_REQUIRED_SCOPE tem de estar preenchido")
        if not self.cors_allowed_origins.strip():
            problems.append("CORS_ALLOWED_ORIGINS tem de ter pelo menos uma origem")

        explicit_entra_overrides = {
            "ENTRA_ISSUER": self.entra_issuer.strip(),
            "ENTRA_JWKS_URL": self.entra_jwks_url.strip(),
            "ENTRA_AUDIENCE": self.entra_audience.strip(),
        }
        if any(explicit_entra_overrides.values()) and not all(explicit_entra_overrides.values()):
            missing = [name for name, value in explicit_entra_overrides.items() if not value]
            problems.append(
                "ENTRA_ISSUER/ENTRA_JWKS_URL/ENTRA_AUDIENCE: se um for definido explicitamente "
                f"os três têm de ser — em falta: {', '.join(missing)}"
            )

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
