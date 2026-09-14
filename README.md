# Op_PM

Plataforma de gestão de operações, projetos, visitas, materiais e custos — em construção.

Este repositório é **público**. Nunca deve conter dados reais de clientes, moradas,
emails, tokens, `.env`, `.secrets`, backups ou exports de produção — ver `.gitignore`
e `docs/DECISIONS.md`. Todos os dados de exemplo neste repositório (fixtures, seed de
desenvolvimento) são sintéticos.

## Estado atual

**Fase 0 — fundação técnica, com a revisão de hardening concluída**, implementada e
testada (56 testes automatizados). Sem integrações externas reais ligadas (Claude,
Microsoft Graph, ClickUp, Financial); sem migração de dados reais; sem envio de email ou
criação de eventos reais. Ver `docs/PLAN.md` para o roadmap completo.

Pontos-chave do hardening: a aplicação recusa-se a arrancar em `staging`/`production`
com configuração de desenvolvimento (ver secção "Segurança" abaixo); a migração nunca
escreve diretamente em `projects` — passa sempre por ingestão em staging, revisão de
conflitos, e promoção explícita e reversível (`app/migration/staging.py`); valores
monetários usam `Numeric`/`Decimal`, nunca `Float`.

Documentação:

- [`docs/PRODUCT_SCOPE.md`](docs/PRODUCT_SCOPE.md) — escopo inicial do produto.
- [`docs/ARCHITECTURE_PROPOSAL.md`](docs/ARCHITECTURE_PROPOSAL.md) — arquitetura, modelo de dados, integrações.
- [`docs/PLAN.md`](docs/PLAN.md) — roadmap por fases, plano de migração, testes, segurança.
- [`docs/OPEN_QUESTIONS.md`](docs/OPEN_QUESTIONS.md) — perguntas bloqueantes/importantes.
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — decisões de arquitetura já tomadas e a sua justificação.

## Estrutura

```text
backend/    API (FastAPI + SQLAlchemy + Alembic), adapters de integração, migração/staging
frontend/   Casca web mínima (React + Vite + TypeScript)
docs/       Documentação de arquitetura e planeamento
.github/    CI
```

## Backend — instalação e execução local

Requisitos: Python 3.12+ (testado com 3.12 e 3.14). Não precisa de Docker nem de
PostgreSQL para correr localmente — usa SQLite por omissão (ver
`backend/.env.example` e `docs/DECISIONS.md`).

```bash
cd backend
python -m venv .venv
# Windows (PowerShell): .venv\Scripts\Activate.ps1
# Windows (Git Bash):   source .venv/Scripts/activate
# Linux/Mac:            source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # ajustar se necessário; os valores por omissão já funcionam localmente

python -m alembic upgrade head      # cria o schema (SQLite local em ./data/)
python -m app.migration.seed_dev    # semeia dados sintéticos de desenvolvimento
python -m pytest -q                 # corre a suite de testes

uvicorn app.main:app --reload --port 8000
```

Com o servidor a correr: `http://localhost:8000/docs` (Swagger), `http://localhost:8000/health`.

`/me` e outros endpoints autenticados exigem o cabeçalho de desenvolvimento
`X-Dev-User-Email` (ver `app/security/current_user.py`) — por exemplo
`chefe.sintetico@example.invalid`, criado pelo seed. Isto é um mecanismo de
desenvolvimento explícito, não autenticação real; a integração com Microsoft Entra ID
fica para uma fase seguinte (`AUTH_ENABLED=true` levanta `NotImplementedError`
propositadamente enquanto isso não estiver feito).

### PostgreSQL real (opcional, para validar contra a base de dados-alvo)

```bash
docker compose up -d db     # a partir da raiz do repositório
pip install -r requirements-postgres.txt
DATABASE_URL="postgresql+psycopg://op_pm:op_pm_dev_only@localhost:5432/op_pm" \
  python -m alembic upgrade head
```

(`docker-compose.yml` não pôde ser validado no ambiente onde a Fase 0 foi construída,
por não ter Docker disponível — reveja antes da primeira utilização.)

## Frontend — instalação e execução local

Requisitos: Node.js 20+ (testado com Node 24).

```bash
cd frontend
npm install
cp .env.example .env.local   # ajustar se necessário
npm run dev                  # http://localhost:5173, espera o backend em :8000
npm run build                # valida TypeScript + gera build de produção
```

## Integrações — todas em modo mock/fallback nesta fase

Nenhuma integração externa real está ligada. Cada uma tem uma flag explícita
(`*_ENABLED`, omissão `false`) e uma implementação mock ou de fallback local:

| Integração | Flag | Comportamento em Fase 0 |
|---|---|---|
| Microsoft Graph (email/calendário) | `GRAPH_ENABLED` | Escreve rascunhos `.eml`/`.ics` localmente (`GRAPH_FALLBACK_DIR`); nunca envia nem publica nada real, mesmo com "aprovação". |
| ClickUp | `CLICKUP_ENABLED` | Lê tarefas de uma fixture sintética (`backend/fixtures/synthetic_clickup_tasks.json`). |
| Financial | `FINANCIAL_ENABLED` / `FINANCIAL_MODE` | `mock` (registo sintético) ou `csv` (lê um CSV local real — ver `backend/fixtures/synthetic_financial_costs.csv`); `api`/`excel` ainda não implementados. |
| Claude | `CLAUDE_ENABLED` | Devolve texto determinístico marcado `[MOCK]`, sem qualquer chamada de rede. |

Ativar qualquer uma destas para chamadas reais é trabalho de uma fase futura — ver
`docs/PLAN.md`. Tentar ativar a flag sem a implementação correspondente levanta
`NotImplementedError` de propósito, em vez de falhar silenciosamente para mock.

## Segurança

- Nenhum segredo real neste repositório — só ficheiros `.env.example`.
- Nenhum dado de produção — só fixtures sintéticas (ver `backend/fixtures/`).
- `.gitignore` bloqueia `.env`, `.secrets/`, `data/`, `files/`, backups e bases de
  dados locais.
- **A aplicação recusa-se a arrancar em `APP_ENV=staging`/`production`** se
  `AUTH_ENABLED=false`, `SECRET_KEY` for o valor de desenvolvimento, ou `DATABASE_URL`
  for SQLite — ver `app/config.py` e `docs/DECISIONS.md` D-020. O mecanismo de
  utilizador de desenvolvimento (`X-Dev-User-Email`) tem uma segunda verificação
  independente e só funciona em `local`/`test`.
- Nenhuma migração escreve diretamente em `projects` — passa sempre por ingestão em
  staging (`import_batches`/`staging_project_records`), revisão de conflitos, e
  promoção explícita, sempre com auditoria e rollback (`app/migration/staging.py`,
  docs/DECISIONS.md D-017).
- Valores monetários usam `Numeric`/`Decimal`, nunca `Float` (D-018).
- Antes de expor este backend fora de uma rede de confiança, correr uma revisão de
  segurança dedicada (ver `docs/PLAN.md`, secção de segurança).
