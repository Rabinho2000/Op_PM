# Imagem de staging/produção do backend Op_PM (D-050). Multi-stage: a
# etapa 'builder' instala dependências (incl. o driver PostgreSQL,
# sempre necessário fora de local/test -- ver docs/DECISIONS.md) num
# virtualenv isolado; a etapa final copia só esse virtualenv + o código
# da app, sem cache do pip nem ferramentas de build.
#
# Deliberadamente NÃO corre `alembic upgrade head` nem qualquer seed no
# arranque (CMD) -- migrações são sempre um passo administrativo
# separado e explícito (ver docker-compose.staging.example.yml, serviço
# `backend-migrate`, e docs/STAGING_RUNBOOK.md secção 5): acoplar
# migrações ao arranque do container esconderia falhas de migração
# atrás de um restart automático do orquestrador, e um `alembic
# downgrade` nunca deve poder correr sozinho no arranque de um
# container qualquer.
#
# A app recusa-se a arrancar com configuração insegura em
# APP_ENV=staging/production (app/config.py,
# Settings._enforce_hardening_in_non_local_envs) -- isto continua a ser
# a barreira real; a imagem em si não assume nenhum valor de ambiente.

FROM python:3.12-slim AS builder
WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt requirements-postgres.txt ./
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt -r requirements-postgres.txt


FROM python:3.12-slim AS runtime
WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --home-dir /app app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

RUN mkdir -p /app/data && chown -R app:app /app
USER app

EXPOSE 8000

# Sem curl na imagem de propósito (superfície menor) -- usa a stdlib
# para confirmar que /health responde 200.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1

# 2 workers Uvicorn é um ponto de partida razoável para 5 utilizadores
# ativos (ver docs/STAGING_RUNBOOK.md secção 7); ajustar conforme a
# carga real observada. Sem --reload (nunca em staging/produção).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
