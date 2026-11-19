# Imagem do frontend Op_PM -- UM só Dockerfile para staging, produção e
# demonstração (antes eram Dockerfile, Dockerfile.demo e Dockerfile.tailscale).
# Multi-stage: 'build' compila o bundle estático com Node; 'runtime' serve-o
# com nginx, SEM root -- a imagem final não tem Node/npm nem código-fonte,
# só frontend/dist/.
#
# O que muda entre variantes é só configuração (--build-arg):
#
#   NGINX_CONF   docker/nginx.conf         estático, API noutra origem (staging;
#                                          omissão)
#                docker/nginx.proxy.conf   estático + proxy de /api, /me, /health
#                                          para o serviço `backend` (produção
#                                          Tailscale e demonstração)
#   VITE_*       embutidas no bundle NO MOMENTO DO BUILD (Vite/import.meta.env,
#                nunca lidas em runtime pelo browser) -- por isso têm de ser
#                passadas como `--build-arg` (ver docker-compose.*.yml e
#                docs/STAGING_RUNBOOK.md secção 6), nunca definidas só no
#                container em execução, onde não teriam qualquer efeito.
#
# Exemplos:
#   staging     docker build --build-arg VITE_API_BASE_URL=https://<backend> \
#                 --build-arg VITE_ENTRA_CLIENT_ID=... (etc.) frontend
#   produção    docker build --build-arg NGINX_CONF=docker/nginx.proxy.conf \
#                 --build-arg VITE_API_BASE_URL=/ --build-arg VITE_ENTRA_...=... \
#                 --build-arg VITE_REAL_DATA_INSTANCE=true frontend
#   demonstração (docker-compose.demo.yml)
#               --build-arg NGINX_CONF=docker/nginx.proxy.conf \
#                 --build-arg VITE_API_BASE_URL=/ --build-arg VITE_ENABLE_DEV_LOGIN=true
#
# VITE_ENABLE_DEV_LOGIN é 'false' por omissão e o build RECUSA 'true' quando há
# um VITE_ENTRA_CLIENT_ID: o login de desenvolvimento (X-Dev-User-Email) só
# existe na demonstração (sem Entra) e nunca deve poder chegar a uma imagem
# real, mesmo que alguém o passe por engano (o backend também o recusa fora
# de local/test -- app/config.py + app/security/current_user.py).
#
# A CSP (docker/security-csp.conf) é copiada para a imagem; se VITE_API_BASE_URL
# for um URL absoluto, a sua origem entra no `connect-src`.

# node:22-slim — digest do índice multi-arquitetura; o Dependabot (docker) atualiza tag e digest.
FROM node:22-slim@sha256:e9f565d32859f0cbfb52125eafe8be39390f24dac302dc3cdf566e8ba3ab21ee AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY tsconfig.json vite.config.ts index.html ./
COPY src ./src
COPY public ./public

ARG VITE_API_BASE_URL=/
ARG VITE_ENTRA_CLIENT_ID=
ARG VITE_ENTRA_TENANT_ID=
ARG VITE_ENTRA_API_SCOPE=
ARG VITE_ENTRA_REDIRECT_URI=
ARG VITE_REAL_DATA_INSTANCE=false
ARG VITE_ENABLE_DEV_LOGIN=false
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_ENTRA_CLIENT_ID=${VITE_ENTRA_CLIENT_ID} \
    VITE_ENTRA_TENANT_ID=${VITE_ENTRA_TENANT_ID} \
    VITE_ENTRA_API_SCOPE=${VITE_ENTRA_API_SCOPE} \
    VITE_ENTRA_REDIRECT_URI=${VITE_ENTRA_REDIRECT_URI} \
    VITE_REAL_DATA_INSTANCE=${VITE_REAL_DATA_INSTANCE} \
    VITE_ENABLE_DEV_LOGIN=${VITE_ENABLE_DEV_LOGIN}

RUN if [ "$VITE_ENABLE_DEV_LOGIN" = "true" ] && [ -n "$VITE_ENTRA_CLIENT_ID" ]; then \
      echo "ERRO: VITE_ENABLE_DEV_LOGIN=true não é permitido com VITE_ENTRA_CLIENT_ID definido (só na demonstração, sem Entra)." >&2; \
      exit 1; \
    fi

RUN npm run build


# nginx:stable-alpine (1.30.7 a 2026-11-18; a 1.27 deixou de ter correções) — digest do índice multi-arquitetura; o Dependabot (docker) atualiza tag e digest.
# Corre como o utilizador `nginx` (uid 101), sem root, ao estilo de
# nginxinc/nginx-unprivileged (pid em /tmp, caches e configuração do utilizador),
# mas sobre a imagem oficial fixada (a nginx-unprivileged estava atrás: 1.30.6).
# A porta continua a ser a 80: o Docker já define
# net.ipv4.ip_unprivileged_port_start=0 nos containers (Docker >= 20.10).
FROM nginx:stable-alpine@sha256:9e596d26590907ed433eb53c83c4016038025d4e004b15922786ba85c8957264 AS runtime
ARG NGINX_CONF=docker/nginx.conf
# Redeclarado: os ARG não atravessam estágios. Só serve para o `connect-src`.
ARG VITE_API_BASE_URL=/

RUN set -eux; \
    sed -i -e '/^user /d' -e 's,^pid .*;,pid /tmp/nginx.pid;,' /etc/nginx/nginx.conf; \
    mkdir -p /etc/nginx/snippets; \
    chown -R nginx:nginx /var/cache/nginx /etc/nginx/conf.d /etc/nginx/snippets

COPY --from=build --chown=nginx:nginx /app/dist /usr/share/nginx/html
COPY --chown=nginx:nginx docker/security-base.conf docker/security-csp.conf docker/security-csp-frame.conf /etc/nginx/snippets/
COPY --chown=nginx:nginx ${NGINX_CONF} /etc/nginx/conf.d/default.conf

# A origem da API (se absoluta) passa a ser aceite pelo connect-src da CSP.
RUN set -eu; \
    origin="$(printf '%s' "$VITE_API_BASE_URL" | sed -nE 's#^(https?://[^/]+).*#\1#p')"; \
    sed -i "s#__CONNECT_EXTRA__#${origin}#" /etc/nginx/snippets/security-csp.conf; \
    ! grep -q __CONNECT_EXTRA__ /etc/nginx/snippets/security-csp.conf

USER nginx
EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD wget --quiet --spider http://127.0.0.1:80/ || exit 1
