# Imagem de staging/produção do frontend Op_PM (D-050). Multi-stage:
# 'build' compila o bundle estático com Node; 'runtime' serve-o com
# nginx -- a imagem final não tem Node/npm nem código-fonte, só
# frontend/dist/.
#
# As variáveis VITE_* ficam embutidas no bundle NO MOMENTO DO BUILD
# (Vite/import.meta.env, nunca lidas em runtime pelo browser) -- por
# isso têm de ser passadas como `--build-arg` (ver
# docker-compose.staging.example.yml e docs/STAGING_RUNBOOK.md secção
# 6), nunca definidas só no container em execução, onde não teriam
# qualquer efeito.
#
# VITE_ENABLE_DEV_LOGIN é sempre 'false' aqui, fixado no Dockerfile
# (nunca um ARG) -- o login de desenvolvimento (X-Dev-User-Email) nunca
# deve poder chegar a uma imagem construída por este Dockerfile, mesmo
# que alguém esqueça de o definir no processo de build (D-033 já
# desliga isto por omissão fora de `vite dev`/testes; isto é só mais uma
# barreira, redundante de propósito).

FROM node:20-slim AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY tsconfig.json vite.config.ts index.html ./
COPY src ./src

ARG VITE_API_BASE_URL
ARG VITE_ENTRA_CLIENT_ID
ARG VITE_ENTRA_TENANT_ID
ARG VITE_ENTRA_API_SCOPE
ARG VITE_ENTRA_REDIRECT_URI=
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_ENTRA_CLIENT_ID=${VITE_ENTRA_CLIENT_ID} \
    VITE_ENTRA_TENANT_ID=${VITE_ENTRA_TENANT_ID} \
    VITE_ENTRA_API_SCOPE=${VITE_ENTRA_API_SCOPE} \
    VITE_ENTRA_REDIRECT_URI=${VITE_ENTRA_REDIRECT_URI} \
    VITE_ENABLE_DEV_LOGIN=false

RUN npm run build


FROM nginx:1.27-alpine AS runtime
COPY --from=build /app/dist /usr/share/nginx/html
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD wget --quiet --spider http://127.0.0.1:80/ || exit 1
