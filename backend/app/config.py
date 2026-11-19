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
from typing import Literal, get_args

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

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


def _read_secret_file(variable: str, path: str) -> str:
    """Lê um segredo de um ficheiro. Falha com mensagem sem o conteúdo."""
    try:
        value = Path(path.strip()).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError(f"{variable}: não foi possível ler o ficheiro ({exc.strerror or type(exc).__name__})") from None
    if not value:
        raise ValueError(f"{variable}: o ficheiro está vazio")
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Aplicação ---
    # Obrigatório, sem valor por omissão (A7, fail-closed): um deploy que
    # esqueça (ou escreva mal) APP_ENV nunca pode cair em 'local', onde a
    # autenticação é substituída pelo cabeçalho X-Dev-User-Email. Quem
    # desenvolve define APP_ENV=local explicitamente (ver backend/.env.example).
    app_env: Environment = Field(alias="APP_ENV")
    app_name: str = Field(default="Op_PM API", alias="APP_NAME")
    secret_key: str = Field(
        default=DEFAULT_DEV_SECRET_KEY,
        alias="SECRET_KEY",
        description="Nunca usar o valor por omissão fora de 'local'/'test'.",
    )

    # Segredos por ficheiro (Docker/Compose secrets): caminho de um ficheiro
    # que contém o valor (uma linha; espaços/quebras de linha finais são
    # ignorados). Evita pôr o segredo em variáveis de ambiente (visíveis em
    # `docker inspect`). Se a variável direta E a variante _FILE estiverem
    # definidas, o arranque falha: nunca se escolhe uma em silêncio.
    secret_key_file: str = Field(default="", alias="SECRET_KEY_FILE")
    database_url_file: str = Field(default="", alias="DATABASE_URL_FILE")
    database_password_file: str = Field(
        default="",
        alias="DATABASE_PASSWORD_FILE",
        description="Password da BD por ficheiro; só se aplica se DATABASE_URL não trouxer password.",
    )

    # Modo demonstração (D-051): só informativo para o frontend (banner
    # "Dados sintéticos") e para o arranque demo (`app.cli.demo`). Nunca
    # aceite em staging/produção — ver _enforce_hardening_in_non_local_envs.
    demo_mode: bool = Field(default=False, alias="DEMO_MODE")
    # A instância pode ter dados reais de clientes. Exposta sempre em /health
    # (mesmo fora do modo demo) para o frontend mostrar o aviso de dados
    # reais; também fecha /docs por omissão (resolved_api_docs_enabled).
    demo_real_data: bool = Field(default=False, alias="DEMO_REAL_DATA")

    # --- Base de dados ---
    # Produção/staging: PostgreSQL (fonte de verdade operacional única).
    # Local/test por omissão: SQLite em ficheiro, para arrancar sem serviços
    # externos. Ver docs/DECISIONS.md (D-0xx) para a justificação desta
    # escolha pragmática de Fase 0.
    database_url: str = Field(
        default="sqlite:///./data/op_pm_local.db",
        alias="DATABASE_URL",
    )

    # Ferramenta embebida de dimensionamento: ficheiro privado opcional,
    # servido apenas pelo endpoint protegido por `cable_design.view_costs`.
    cable_tool_file: Path | None = Field(default=None, alias="CABLE_TOOL_FILE")
    # Fotografias principais de projetos. O volume /app/data já existe em produção;
    # o subdiretório é privado e pode ser redirecionado em testes via env.
    project_photo_dir: Path = Field(default=Path("/app/data/project_photos"), alias="PROJECT_PHOTO_DIR")
    # Pasta privada de fotografias e documentos do catálogo de inventário.
    inventory_file_dir: Path = Field(default=Path("/app/data/inventory"), alias="INVENTORY_FILE_DIR")

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

    @field_validator("cable_tool_file", mode="before")
    @classmethod
    def _empty_cable_tool_file_is_none(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value

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
    graph_client_secret_file: str = Field(default="", alias="GRAPH_CLIENT_SECRET_FILE")
    # Pasta local onde o adapter de fallback grava rascunhos .eml/.ics
    # enquanto o Graph real não estiver configurado.
    graph_fallback_dir: str = Field(default="./data/outbox", alias="GRAPH_FALLBACK_DIR")

    # --- Scheduler do relatório semanal (app/cli/client_reports.py) ---
    # Utilizador de serviço com client_report.manage e âmbito global
    # (project.view_all ou project.edit_all). Vazio: usa o primeiro utilizador
    # ativo que cumpra esses requisitos e regista um aviso no log.
    client_report_scheduler_email: str = Field(default="", alias="CLIENT_REPORT_SCHEDULER_EMAIL")
    # Ficheiro de heartbeat lido pelo healthcheck do scheduler. Vazio:
    # <pasta de dados>/client_report_scheduler.heartbeat.
    client_report_scheduler_heartbeat_file: str = Field(default="", alias="CLIENT_REPORT_SCHEDULER_HEARTBEAT_FILE")

    # --- Documentação interativa da API (/docs, /redoc, /openapi.json) ---
    # Vazio: só em 'local'/'test' sem dados reais (DEMO_REAL_DATA=false).
    api_docs_enabled: bool | None = Field(default=None, alias="API_DOCS_ENABLED")

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

    # --- Cifra das credenciais de portais por projeto (ver docs/PLANO_LICENCIAMENTO_SIM.md) ---
    # Caminho de ficheiro com a chave Fernet (uma linha). Nunca um valor
    # inline. Vazio: gravar/revelar uma password falha fechado (503).
    oppm_secrets_key_file: str = Field(default="", alias="OPPM_SECRETS_KEY_FILE")

    # --- Mapa operacional (ver docs/MAP_AND_PLANNING.md) ---
    # Sem provider configurado, GET /api/map/data continua a devolver os
    # dados (projetos/fornecedores/recolhas/pendências) — o frontend mostra
    # um aviso claro em vez de tiles, e a lista de locais como alternativa;
    # nunca dependemos de um serviço externo para o resto da app funcionar.
    map_provider_enabled: bool = Field(default=False, alias="MAP_PROVIDER_ENABLED")
    map_tile_url: str = Field(default="", alias="MAP_TILE_URL")
    map_tile_attribution: str = Field(default="", alias="MAP_TILE_ATTRIBUTION")

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
    def _load_secrets_from_files(self) -> Settings:
        """Resolve SECRET_KEY_FILE, DATABASE_URL_FILE e DATABASE_PASSWORD_FILE.

        Declarado ANTES de `_enforce_hardening_in_non_local_envs` (os
        validadores 'after' correm pela ordem de declaração), para que a
        validação de arranque veja sempre os valores finais. As mensagens de
        erro referem só nomes de variáveis e caminhos, nunca o conteúdo."""
        if self.secret_key_file.strip():
            if "secret_key" in self.model_fields_set:
                raise ValueError("SECRET_KEY e SECRET_KEY_FILE estão ambos definidos; use só um")
            self.secret_key = _read_secret_file("SECRET_KEY_FILE", self.secret_key_file)
        if self.database_url_file.strip():
            if "database_url" in self.model_fields_set:
                raise ValueError("DATABASE_URL e DATABASE_URL_FILE estão ambos definidos; use só um")
            self.database_url = _read_secret_file("DATABASE_URL_FILE", self.database_url_file)
        if self.database_password_file.strip():
            password = _read_secret_file("DATABASE_PASSWORD_FILE", self.database_password_file)
            url = make_url(self.database_url)
            if url.password:
                raise ValueError(
                    "DATABASE_PASSWORD_FILE não se aplica: o DATABASE_URL já traz uma password"
                )
            if url.get_backend_name() == "sqlite":
                raise ValueError("DATABASE_PASSWORD_FILE não se aplica a uma base SQLite")
            self.database_url = url.set(password=password).render_as_string(hide_password=False)
        return self

    @model_validator(mode="after")
    def _reject_integrations_without_implementation(self) -> Settings:
        """Recusa as flags de integrações que ainda não têm implementação real.

        `CLICKUP_ENABLED`, `FINANCIAL_ENABLED` e `CLAUDE_ENABLED` não ligam a
        nada: ligá-las não teria efeito, mas `/health` passaria a anunciar a
        integração como ativa. Falhar no arranque é mais seguro do que aceitar
        a flag em silêncio. (A integração ClickUp real está adiada, não
        cancelada — ver docs/ANALISE_OP_PM.md, "Mock vs. real".)"""
        pending = {
            "CLICKUP_ENABLED": self.clickup_enabled,
            "FINANCIAL_ENABLED": self.financial_enabled,
            "CLAUDE_ENABLED": self.claude_enabled,
        }
        enabled = [name for name, value in pending.items() if value]
        if enabled:
            raise ValueError(
                f"{', '.join(enabled)}: a integração real ainda não está implementada, "
                "por isso a flag tem de ficar 'false'"
            )
        return self

    @model_validator(mode="after")
    def _enforce_hardening_in_non_local_envs(self) -> Settings:
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
        - DEMO_MODE não pode estar ligado — a demonstração com dados
          sintéticos só existe em 'local' (D-051);
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
        if self.demo_mode:
            problems.append("DEMO_MODE tem de ser 'false' (o modo demonstração só existe em local)")

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

    def resolved_api_docs_enabled(self) -> bool:
        if self.api_docs_enabled is not None:
            return self.api_docs_enabled
        return self.app_env in ("local", "test") and not self.demo_real_data

    def resolved_scheduler_heartbeat_file(self) -> Path:
        if self.client_report_scheduler_heartbeat_file:
            return Path(self.client_report_scheduler_heartbeat_file)
        return Path(self.graph_fallback_dir).parent / "client_report_scheduler.heartbeat"


class ConfigurationError(RuntimeError):
    """Configuração em falta ou inválida que impede a aplicação (ou uma CLI)
    de arrancar. A mensagem diz o que corrigir — nunca inclui valores de
    variáveis, para não imprimir segredos por engano."""


_APP_ENV_HELP = (
    "APP_ENV não está definido (ou tem um valor inválido). Não há valor por omissão de propósito: "
    "um deploy mal configurado não pode arrancar sem autenticação. Definir APP_ENV como um de "
    f"{', '.join(repr(e) for e in get_args(Environment))} — 'local' para desenvolvimento "
    "(ver backend/.env.example), 'test' para a suite de testes, 'staging'/'production' em deploys reais."
)


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        # Só o problema de APP_ENV é traduzido: os restantes (hardening em
        # staging/produção, etc.) já trazem uma mensagem própria e clara.
        if any(error["loc"] and error["loc"][0] in ("APP_ENV", "app_env") for error in exc.errors()):
            raise ConfigurationError(_APP_ENV_HELP) from None
        raise
