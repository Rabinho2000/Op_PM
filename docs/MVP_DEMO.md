# MVP de demonstração — Op_PM

> Guia para levantar a demonstração da Op_PM **sem conhecer o código**.
> Tudo o que aparece na demonstração é **sintético** (nomes, clientes,
> emails `*.invalid`, moradas). Não é preciso Microsoft Entra ID,
> PostgreSQL, alojamento, nem nenhuma credencial externa.
> Decisão técnica: `docs/DECISIONS.md` D-051.

## Índice

1. [O que se pode demonstrar](#1-o-que-se-pode-demonstrar)
2. [Pré-requisitos](#2-pré-requisitos)
3. [Arranque com Docker (recomendado)](#3-arranque-com-docker-recomendado)
4. [Arranque manual (sem Docker)](#4-arranque-manual-sem-docker)
5. [URLs](#5-urls)
6. [Utilizadores de demonstração](#6-utilizadores-de-demonstração)
7. [Guião sugerido para a demonstração](#7-guião-sugerido-para-a-demonstração)
8. [Reiniciar os dados](#8-reiniciar-os-dados)
9. [Testes e verificações](#9-testes-e-verificações)
10. [Build de produção](#10-build-de-produção)
11. [Demo local vs. staging vs. produção](#11-demo-local-vs-staging-vs-produção)
12. [Limitações atuais](#12-limitações-atuais)
13. [Integrações ainda não ativadas](#13-integrações-ainda-não-ativadas)
14. [Resolução de problemas](#14-resolução-de-problemas)

---

## 1. O que se pode demonstrar

| Área | O que mostra |
|---|---|
| **Painel** | Projetos ativos, a começar em 30 dias, tarefas atrasadas, tarefas desta semana, tarefas urgentes, visitas técnicas e comissionamentos pendentes, projetos sem PM, projetos com dados incompletos, aviso de fotografias por colocar, resumo visual da semana, férias atuais/próximas e aniversários. Todos os números vêm do servidor (`GET /api/dashboard/summary`). |
| **Projetos** | Pesquisa por projeto/cliente, filtros por estado, PM, datas e situação; estado, progresso, próxima tarefa, prazo, tarefas atrasadas, avisos de dados em falta e de fotografias. Detalhe com resumo, tarefas, histórico e dados do cliente; edição só dos campos que o perfil pode alterar. |
| **Tarefas** | Vista de lista e vista Kanban (arrastar cartões ou usar o seletor), filtros por projeto, responsável, prioridade e atraso, criação de tarefas, destaque de urgentes/atrasadas e confirmação visual ao concluir. |
| **Férias e aniversários** | Calendário mensal, quem está ausente hoje, próximas ausências, aniversários, registo e cancelamento — sempre dentro das permissões do perfil. |
| **Permissões** | Entrar com perfis diferentes mostra vistas diferentes (o PM só vê os seus projetos; o Comercial só consulta). |

## 2. Pré-requisitos

**Opção A — Docker (recomendado):**

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows/macOS) ou Docker Engine + plugin Compose v2 (Linux).
- Git (para clonar o repositório).
- Portas livres nesta máquina: **8080** (aplicação) e **8000** (API).

**Opção B — sem Docker:**

- Python **3.12** ou superior (`python --version`).
- Node.js **20** ou superior, com npm (`node --version`).
- Git.
- Portas livres: **5173** (aplicação) e **8000** (API).

Ligação à internet só é necessária na primeira vez, para descarregar
dependências/imagens.

## 3. Arranque com Docker (recomendado)

```bash
git clone https://github.com/Rabinho2000/Op_PM.git
cd Op_PM
docker compose -f docker-compose.demo.yml up --build
```

A primeira execução demora alguns minutos (construção das imagens). O
arranque faz, por esta ordem:

1. `demo-setup` — aplica as migrações da base de dados e carrega os dados
   sintéticos (só aceita `APP_ENV=local`) e termina. No registo aparece:
   `Demonstração Op_PM pronta … Aplicação: http://localhost:8080`.
2. `backend` — arranca a API (SQLite num volume Docker próprio).
3. `frontend` — arranca quando a API responde.

Abrir **http://localhost:8080** e escolher um utilizador de demonstração.

Parar: `Ctrl+C` (ou, noutro terminal, `docker compose -f docker-compose.demo.yml down`).
Os dados mantêm-se entre arranques (volume `op_pm_demo_data`).

> As portas ficam acessíveis apenas nesta máquina (`127.0.0.1`). Para
> mostrar noutro dispositivo da rede, altere `127.0.0.1:8080:80` para
> `8080:80` em `docker-compose.demo.yml` — só em redes de confiança.

## 4. Arranque manual (sem Docker)

### Opção rápida — um comando (Windows, Linux e macOS)

Na raiz do repositório:

```bash
python scripts/demo_local.py
```

(Em Linux/macOS pode ser `python3`.) O script cria `backend/.venv`,
instala as dependências, corre `npm install`, aplica migrações e dados
sintéticos numa base própria (`backend/data/op_pm_demo.db`) e arranca a
API e a aplicação. Abrir **http://localhost:5173**. Parar com `Ctrl+C`.

Opções: `--reset` (repõe os dados), `--install` (reinstala dependências),
`--backend-port`, `--frontend-port`.

### Opção passo-a-passo

Dois terminais, a partir da raiz do repositório.

**Terminal 1 — API:**

Windows (PowerShell):

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:APP_ENV="local"; $env:DEMO_MODE="true"; $env:AUTH_ENABLED="false"
$env:DATABASE_URL="sqlite:///./data/op_pm_demo.db"
python -m app.cli.demo setup
uvicorn app.main:app --port 8000
```

Linux/macOS:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export APP_ENV=local DEMO_MODE=true AUTH_ENABLED=false
export DATABASE_URL=sqlite:///./data/op_pm_demo.db
python -m app.cli.demo setup
uvicorn app.main:app --port 8000
```

**Terminal 2 — aplicação:**

```bash
cd frontend
npm install
npm run dev
```

Abrir **http://localhost:5173**. (Por omissão, `npm run dev` usa a API em
`http://localhost:8000` e ativa o login de demonstração.)

## 5. URLs

| O quê | Docker | Manual |
|---|---|---|
| Aplicação | http://localhost:8080 | http://localhost:5173 |
| API — estado | http://localhost:8080/health | http://localhost:8000/health |
| API — documentação (Swagger) | http://localhost:8080/docs | http://localhost:8000/docs |

## 6. Utilizadores de demonstração

No ecrã de entrada, secção **Modo demonstração (apenas local)**, basta
clicar no perfil. Não há passwords — este acesso só existe com o servidor
em `APP_ENV=local`/`test`.

| Utilizador | Papel | O que pode fazer |
|---|---|---|
| `chefe.sintetico@example.invalid` | Chefe de Operações | Vê toda a operação; edita qualquer projeto e tarefa; gere férias de todos; reconciliação de PM. **Melhor perfil para a demonstração.** |
| `pm.um.sintetico@example.invalid` | Project Manager | Vê só os seus projetos e as tarefas desses projetos (ou atribuídas a si); edita notas de acompanhamento e as suas tarefas; gere as próprias férias. |
| `admin.sintetico@example.invalid` | Administrador | Todas as permissões. |
| `comercial.sintetico@example.invalid` | Comercial | Consulta projetos e tarefas, sem editar; vê e gere só as próprias férias. |
| `financeiro.sintetico@example.invalid` | Financeiro | Consulta projetos e tarefas, sem editar; vê e gere só as próprias férias. |

Pessoas sem conta de login (aparecem como responsáveis/PM): `Técnica
Sintética Ana`, `Técnico Sintético Bruno` e três PM legados.

Os dados são gerados **relativamente ao dia de hoje** (fuso
Europe/Lisbon): há sempre tarefas atrasadas, tarefas nesta semana,
férias em curso e aniversários próximos, seja qual for o dia da
demonstração.

## 7. Guião sugerido para a demonstração

1. Entrar como **Chefe de Operações** → Painel: indicadores, aviso de
   fotografias, resumo da semana, férias e aniversários.
2. Abrir um projeto → separador **Percurso de obra**: fases, cronograma
   das 18 etapas, marcar uma subtarefa ou um contacto com o cliente e ver
   a alteração no **Histórico** (processo de exemplo; o oficial carrega-se
   à parte — `docs/WORKFLOW.md`).
3. Clicar num projeto do aviso de fotografias → detalhe → **Marcar como
   colocadas**: o aviso desaparece e o progresso sobe.
4. **Projetos** → filtrar por estado "Em curso" e por PM; pesquisar
   "Escola".
5. **Tarefas** → vista **Kanban** → arrastar uma tarefa para "Concluída"
   (confirmação visual); criar uma **Nova tarefa**.
6. **Férias e aniversários** → navegar no calendário; **Registar
   ausência**.
7. Sair e entrar como **Project Manager**: o painel e as listas mostram só
   os seus projetos; ao editar um projeto só aparecem notas.
8. Entrar como **Comercial**: sem botões de edição nem de criação.

## 8. Reiniciar os dados

Docker (apaga o volume e volta a criar tudo):

```bash
docker compose -f docker-compose.demo.yml down -v
docker compose -f docker-compose.demo.yml up --build
```

Sem Docker:

```bash
python scripts/demo_local.py --reset
```

ou, no terminal da API (com as variáveis da secção 4 definidas):

```bash
python -m app.cli.demo reset --yes
```

O comando recusa-se a correr com qualquer `APP_ENV` diferente de `local`.

## 9. Testes e verificações

```bash
# Backend (a partir de backend/, com o ambiente virtual ativo)
python -m pytest -q

# Migrações round-trip (numa base temporária)
DATABASE_URL=sqlite:///./data/roundtrip.db python -m alembic upgrade head
DATABASE_URL=sqlite:///./data/roundtrip.db python -m alembic downgrade base
DATABASE_URL=sqlite:///./data/roundtrip.db python -m alembic upgrade head

# Frontend (a partir de frontend/)
npm run lint      # verificação de tipos (tsc)
npm test          # Vitest
npm run build     # build de produção

# Docker (a partir da raiz)
docker compose -f docker-compose.demo.yml config --quiet
docker build -f frontend/Dockerfile.demo ./frontend
```

O CI (`.github/workflows/ci.yml`) corre tudo isto em cada PR, incluindo o
job `demo-smoke`, que arranca `docker-compose.demo.yml` e verifica a
aplicação, a API, os dados sintéticos e a idempotência do seed.

## 10. Build de produção

```bash
cd frontend
npm run build          # gera frontend/dist/ (VITE_ENABLE_DEV_LOGIN=false por omissão)
```

Imagens de staging/produção: `backend/Dockerfile` e `frontend/Dockerfile`
(este último fixa `VITE_ENABLE_DEV_LOGIN=false`) — ver
`docker-compose.staging.example.yml` e `docs/STAGING_RUNBOOK.md`. **Não
usar** `frontend/Dockerfile.demo` nem `docker-compose.demo.yml` fora da
demonstração local.

## 11. Demo local vs. staging vs. produção

| | Demo local | Staging | Produção |
|---|---|---|---|
| `APP_ENV` | `local` | `staging` | `production` |
| Dados | 100% sintéticos (seed) | Utilizadores reais (`app.cli.provision_staging`) + piloto de projetos reais | Dados reais migrados |
| Login | Utilizadores de demonstração (sem password) | Microsoft Entra ID (MSAL) | Microsoft Entra ID (MSAL) |
| Base de dados | SQLite | PostgreSQL dedicado | PostgreSQL dedicado |
| `DEMO_MODE` | `true` | **proibido** (a app não arranca) | **proibido** (a app não arranca) |
| Seed sintético | `app.cli.demo` | **recusado** | **recusado** |
| Login de desenvolvimento | Aceite | **recusado** (duas barreiras no backend) | **recusado** |
| Ficheiros | `docker-compose.demo.yml`, `frontend/Dockerfile.demo`, `scripts/demo_local.py` | `docker-compose.staging.example.yml`, `backend/Dockerfile`, `frontend/Dockerfile` | idem staging |

Barreiras que impedem o modo demo fora de `local` (independentes entre si):

1. `app/config.py` — em staging/produção a aplicação recusa-se a arrancar
   com `AUTH_ENABLED=false`, SQLite ou `DEMO_MODE=true`.
2. `app/security/current_user.py` — o cabeçalho de desenvolvimento só é
   aceite com `APP_ENV` `local`/`test`, verificado em cada pedido.
3. `app/cli/demo.py` / `app/migration/seed_demo.py` — só `APP_ENV=local`.
4. Frontend — o build de produção desliga o login de demonstração; o
   build demo só o mostra quando `/health` confirma `dev_login_available`.

## 12. Limitações atuais

- Dados exclusivamente sintéticos; os 295 projetos reais não estão
  migrados (ver `docs/DATA_MIGRATION_RUNBOOK.md`).
- Não há criação/arquivo de projetos pela interface (só edição).
- Férias sem fluxo de aprovação (ficam aprovadas ao registar — D-042).
- Aniversários: só dia/mês, visíveis a quem tem `absence.view_all` (ou o
  próprio).
- Os campos de data usam o formato do browser (ex.: `mm/dd/aaaa` num
  browser em inglês).
- Sem notificações por email, sem mapa, inventário, pedidos de material,
  biblioteca documental ou custos na interface.
- SQLite na demonstração (um processo, poucos utilizadores); staging e
  produção exigem PostgreSQL.
- Login Microsoft real implementado mas não configurado (sem tenant) —
  o botão aparece desativado com a explicação.

## 13. Integrações ainda não ativadas

| Integração | Estado na demonstração |
|---|---|
| Microsoft Entra ID (login real) | Implementado, não configurado — não é necessário. |
| Microsoft Graph (email/calendário) | Desligado (`GRAPH_ENABLED=false`); só rascunhos locais. |
| ClickUp | Desligado; fixture sintética. |
| Financial | Desligado; nenhum dado financeiro na interface. |
| Claude | Desligado; respostas `[MOCK]`, sem chamadas de rede. |

## 14. Resolução de problemas

| Sintoma | Solução |
|---|---|
| `port is already allocated` / porta ocupada | Fechar a aplicação que usa 8080/8000 (Docker) ou 5173/8000 (manual), ou mudar a porta em `docker-compose.demo.yml` / `--frontend-port`. |
| Ecrã de entrada sem utilizadores de demonstração e mensagem "Não foi possível contactar o servidor" | A API ainda não arrancou ou não está em `APP_ENV=local`. Ver os registos do `backend`. |
| "Este servidor não aceita o modo demonstração" | O backend está em staging/produção ou com `AUTH_ENABLED=true` — comportamento esperado. |
| Números do painel diferentes de outra demonstração | Os dados são relativos à data de hoje; para os repor, ver a secção 8. |
| `python` não encontrado (Windows) | Instalar Python 3.12+ a partir de python.org e marcar "Add python.exe to PATH". |
