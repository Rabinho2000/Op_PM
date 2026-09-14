import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Garante que `app` é importável quando o alembic corre a partir de
# qualquer diretório de trabalho.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: E402  — regista todas as tabelas em Base.metadata
from app.config import get_settings  # noqa: E402
from app.db import Base  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# A URL real vem sempre de Settings (variável de ambiente DATABASE_URL),
# nunca do valor estático em alembic.ini — evita divergência entre o que a
# app usa e o que as migrações veem.
config.set_main_option("sqlalchemy.url", get_settings().database_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # `app.db.GUID` é um TypeDecorator próprio; sem isto o autogenerate
            # emite `app.db.GUID()` no ficheiro de migração sem o importar.
            # Mesmo assim, confirma sempre o import no topo do ficheiro gerado
            # antes de correr `alembic upgrade` — ver docs/DECISIONS.md.
            user_module_prefix="app.db.",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
