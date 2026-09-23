# Op_PM

Plataforma de gestão de operações, projetos, visitas, materiais e custos — em construção.

Este repositório é **público**. Nunca deve conter dados reais de clientes, moradas,
emails, tokens, `.env`, `.secrets`, backups ou exports de produção — ver `.gitignore`
e `docs/DECISIONS.md`. Todos os dados de exemplo neste repositório (fixtures, seed de
desenvolvimento) são sintéticos.

## Demonstração rápida (dados sintéticos)

Para ver a aplicação a funcionar em poucos minutos, sem Entra ID,
PostgreSQL nem credenciais:

```bash
docker compose -f docker-compose.demo.yml up --build
```

Abrir **http://localhost:8080** e escolher um utilizador de demonstração
(ex.: Chefe de Operações). Sem Docker: `python scripts/demo_local.py` e
abrir **http://localhost:5173**. Guia completo — pré-requisitos,
utilizadores e papéis, guião de demonstração, reposição de dados,
testes, diferenças entre demo/staging/produção e limitações:
[`docs/MVP_DEMO.md`](docs/MVP_DEMO.md).

| Utilizador de demonstração | Papel |
|---|---|
| `chefe.sintetico@example.invalid` | Chefe de Operações (vê e gere toda a operação) |
| `pm.um.sintetico@example.invalid` | Project Manager (só os seus projetos) |
| `admin.sintetico@example.invalid` | Administrador (todas as permissões) |
| `comercial.sintetico@example.invalid` | Comercial (consulta) |
| `financeiro.sintetico@example.invalid` | Financeiro (consulta) |

O modo demonstração só funciona com `APP_ENV=local`: em staging/produção
a aplicação recusa-se a arrancar com `DEMO_MODE=true`, o seed sintético é
recusado e o login de desenvolvimento nunca é aceite (D-051).

## Estado atual

**Fase 0 concluída** (fundação técnica + revisão de hardening), **Fase 1
concluída + revisão de hardening** (autenticação real, CRUD de projetos com
permissões por campo, resolução de migração reforçada, login MSAL real no
frontend), **fecho
técnico da Fase 1 para staging/produção concluído** (configuração obrigatória e
completa, separação real do login de desenvolvimento, provisionamento
administrativo de utilizadores, allowlist de PM revista, repetição segura de
promoção após rollback, ingestão controlada staging-only — ver `docs/DECISIONS.md`
D-032 a D-037), e **Fase 1.5 — MVP dashboard/workflow concluída**: página inicial
(`/`) com indicadores reais (projetos ativos, a começar em 30 dias, tarefas
atrasadas/pendentes esta semana, visitas técnicas e comissionamentos pendentes,
projetos sem PM/dados em falta, férias atuais/próximas, aniversários próximos,
trabalhos urgentes), entidade `Task` genérica (checklist padrão de 5 tarefas por
projeto + tarefas ad-hoc, máquina de estados, histórico), férias/ausências
(`Absence`), e o aviso persistente de fotos por colocar na Drive quando visita
técnica/comissionamento é concluído — ver `docs/DECISIONS.md` D-039 a D-047.
380 testes automatizados de backend a passar (+2 skipped) em SQLite (e em
PostgreSQL, ver abaixo) + 108 testes Vitest no frontend. Sem integrações
externas reais ligadas (Claude, Microsoft
Graph, ClickUp, Financial); sem migração de dados reais (os 295 projetos reais
continuam por migrar); sem envio de email ou criação de eventos reais; sem
pedidos de material ou biblioteca documental. Ver
`docs/PLAN.md` para o roadmap completo, `docs/STAGING_CHECKLIST.md`/
`docs/GO_LIVE_CHECKLIST.md` para os procedimentos de deployment, e
`docs/DATA_MIGRATION_RUNBOOK.md` para a migração real dos 295 projetos.

Pontos-chave: a aplicação recusa-se a arrancar em `staging`/`production` com
configuração de desenvolvimento (ver secção "Segurança" abaixo); a migração nunca
escreve diretamente em `projects` — passa sempre por ingestão em staging, reconciliação
de PM, revisão de conflitos (com o alvo de uma ligação manual validado contra os
candidatos detetados — D-030), e promoção explícita e reversível
(`app/migration/staging.py`); valores monetários usam `Numeric`/`Decimal`, nunca
`Float`; tokens Microsoft Entra ID são validados a sério (`oid` obrigatório,
assinatura, issuer, audience, tenant, `scp`, `nbf`, validade —
`app/security/entra_auth.py`, D-024/D-029); edição de projeto por um PM é limitada a
uma lista explícita de campos, aplicada no servidor (D-028); o frontend já faz login
real via MSAL (Authorization Code + PKCE), pendente só de um tenant/app registration
reais para ter credenciais (ver `docs/OPEN_QUESTIONS.md`, pergunta 1, e D-031).

**Preparação para staging (D-049):** `docs/STAGING_RUNBOOK.md` (novo) e
`backend/.env.staging.example`/`frontend/.env.staging.example` (novos)
cobrem o procedimento completo. `app.cli.ingest_staging` ganhou
`--dry-run`/`--only-ids`/`--limit` para testar um piloto de 5 a 10
projetos reais antes dos 295; `app.migration.seed_dev` recusa-se agora a
correr fora de `local`/`test`.

**Bootstrap de utilizadores e containers de staging (D-050):**
`python -m app.cli.provision_staging` cria/atualiza, de forma idempotente
e auditada, o catálogo de papéis/permissões e os `Person`/`User`/
`UserRole` reais a partir de um ficheiro JSON externo ao repositório —
ver [`docs/STAGING_BOOTSTRAP.md`](docs/STAGING_BOOTSTRAP.md) para o
procedimento passo-a-passo (não exige conhecimento de código).
`backend/Dockerfile`, `frontend/Dockerfile` e
`docker-compose.staging.example.yml` (novos) tornam o arranque de
staging repetível por containers, com migrações sempre separadas do
arranque da app — não decidem nem criam nenhum alojamento/recurso cloud.
Continua pendente: tenant Entra ID real, domínio e alojamento de staging
(ver `docs/STAGING_RUNBOOK.md` secção 16 para a lista objetiva).

**MVP de demonstração (D-051):** interface nova (sidebar, painel com
resumo visual da semana e aviso de fotografias, projetos com filtros por
estado/PM/datas, tarefas em lista e Kanban, calendário de férias e
aniversários), sempre alimentada pela API e limitada pelas permissões do
servidor (`editable_fields`, `can_manage_tasks`, `can_edit`,
`can_cancel`); arranque num comando com `docker-compose.demo.yml` ou
`scripts/demo_local.py`; seed de demonstração só em `APP_ENV=local`
(`python -m app.cli.demo setup|reset`). Ver [`docs/MVP_DEMO.md`](docs/MVP_DEMO.md).

**MVP de Operações (D-052 a D-057):** inventário da IdealMinde com
reservas/consumo/libertação/devolução por projeto (`/inventory` para o
stock central, tab **Inventário** no detalhe do projeto para as
necessidades e movimentos por projeto — livro de movimentos, nunca um
total editável, ver [`docs/INVENTORY_RULES.md`](docs/INVENTORY_RULES.md));
dados de instalação/licenciamento/comunicação por projeto (tabs "Dados da
instalação"/"Licenciamento" no detalhe do projeto,
`/api/projects/{id}/installation-data` etc., com histórico por campo);
mapa operacional (`/map`, Leaflet com lista funcional de recurso quando
não há provider de tiles configurado) e calendário de planeamento
(`/planning`, vistas de semana/mês/lista) — **backend e UI completos e
testados**; `Task.category` (workflow/field/material/documentation/
commercial/other) e um estado `attention` (green/yellow/red) por projeto,
derivado no servidor a partir de tarefas operacionais e inventário
(`GET /api/map/data`), com pins/lista/resumo coloridos por `attention` em
`/map` — **backend e UI completos e testados** (D-058), ver
[`docs/MAP_AND_PLANNING.md`](docs/MAP_AND_PLANNING.md);
permissões de tarefas revistas (PM vê tarefas de todos os projetos, mas
só cria/edita as suas — nunca reatribui); "Metas e indicadores" como
página única (`/performance`, nunca "Metas"/"Dashboards" separados, com
filtros por ano/período/PM e edição de metas), ver
[`docs/PERFORMANCE_METRICS.md`](docs/PERFORMANCE_METRICS.md); importador
de notas iniciais (arrastar HTML/JSON, preview, conflitos por campo,
confirmação, auditoria — `/projects/import`) e importador de
licenciamento via Excel (`python -m app.cli.import_licensing`,
`--dry-run`/`--apply`/`--rollback`, nunca via UI), ver
[`docs/DATA_IMPORTS.md`](docs/DATA_IMPORTS.md). 411 testes de backend
(+2 skipped) e 108 testes Vitest no frontend.

Documentação:

- [`docs/MVP_DEMO.md`](docs/MVP_DEMO.md) — **como levantar e apresentar a demonstração** (Docker ou manual, utilizadores sintéticos, limitações).
- [`docs/PLAN_OPERATIONS_MVP.md`](docs/PLAN_OPERATIONS_MVP.md) — arquitetura completa do MVP de Operações (inventário, dados de projeto, mapa, calendário, metas), o que ficou nesta fatia e o que fica para a seguinte.
- [`docs/INVENTORY_RULES.md`](docs/INVENTORY_RULES.md) — contrato exato de reserva/consumo/libertação/devolução de inventário.
- [`docs/MAP_AND_PLANNING.md`](docs/MAP_AND_PLANNING.md) — endpoints do mapa e do calendário de planeamento.
- [`docs/PERFORMANCE_METRICS.md`](docs/PERFORMANCE_METRICS.md) — cálculo de metas/progresso/indicadores históricos.
- [`docs/DATA_IMPORTS.md`](docs/DATA_IMPORTS.md) — importadores de notas iniciais e Excel de licenciamento, implementados e testados.
- [`docs/PRODUCT_SCOPE.md`](docs/PRODUCT_SCOPE.md) — escopo inicial do produto.
- [`docs/ARCHITECTURE_PROPOSAL.md`](docs/ARCHITECTURE_PROPOSAL.md) — arquitetura, modelo de dados, integrações.
- [`docs/PLAN.md`](docs/PLAN.md) — roadmap por fases, plano de migração, testes, segurança.
- [`docs/OPEN_QUESTIONS.md`](docs/OPEN_QUESTIONS.md) — perguntas bloqueantes/importantes.
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — decisões de arquitetura já tomadas e a sua justificação.
- [`docs/STAGING_RUNBOOK.md`](docs/STAGING_RUNBOOK.md) — runbook operacional completo de staging (App registrations Entra ID, PostgreSQL, migrações, os 5 utilizadores, health checks, backups/rollback, piloto de 5 a 10 projetos reais).
- [`docs/STAGING_BOOTSTRAP.md`](docs/STAGING_BOOTSTRAP.md) — procedimento passo-a-passo do bootstrap de utilizadores reais (`app.cli.provision_staging`, D-050), executável sem conhecimento de código.
- [`docs/STAGING_CHECKLIST.md`](docs/STAGING_CHECKLIST.md) — checklist de sign-off do primeiro deployment de staging (usa o runbook acima para os comandos exatos).
- [`docs/GO_LIVE_CHECKLIST.md`](docs/GO_LIVE_CHECKLIST.md) — checklist de passagem a produção.
- [`docs/DATA_MIGRATION_RUNBOOK.md`](docs/DATA_MIGRATION_RUNBOOK.md) — procedimento da migração real dos 295 projetos.

## Estrutura

```text
backend/    API (FastAPI + SQLAlchemy + Alembic), adapters de integração, migração/staging
frontend/   Aplicação web (React + Vite + TypeScript, sem biblioteca de UI externa)
scripts/    demo_local.py — arranque da demonstração sem Docker
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

Para a demonstração com mais dados sintéticos (só `APP_ENV=local`):
`python -m app.cli.demo setup` (migrações + seed, idempotente) ou
`python -m app.cli.demo reset --yes` (apaga e volta a criar) — ver
`docs/MVP_DEMO.md`.

Endpoints principais da Fase 1.5 (ver `docs/PLAN.md`):
`GET /api/dashboard/summary` (indicadores do painel inicial, já filtrados pela
visibilidade do utilizador), `/api/tasks` (CRUD + histórico), `/api/absences`
(férias/ausências).

Endpoints do MVP de Operações (ver `docs/PLAN_OPERATIONS_MVP.md`):
`/api/inventory/*` e `/api/projects/{id}/inventory/*` (livro de
movimentos, reservas/consumo/libertação/devolução, necessidades de
material — [`docs/INVENTORY_RULES.md`](docs/INVENTORY_RULES.md)),
`/api/projects/{id}/installation-data|licensing-data|communication-data`
(+ `/data-history`), `/api/map/data`, `/api/suppliers`,
`/api/pickup-points`, `/api/projects/{id}/issues`, `/api/planning/*`
(calendário ligado a tarefas — [`docs/MAP_AND_PLANNING.md`](docs/MAP_AND_PLANNING.md)),
`/api/performance/summary` e `/api/performance/goals`
([`docs/PERFORMANCE_METRICS.md`](docs/PERFORMANCE_METRICS.md)).

Por omissão (`AUTH_ENABLED=false`), `/me` e outros endpoints autenticados exigem o
cabeçalho de desenvolvimento `X-Dev-User-Email` (ver `app/security/current_user.py`) —
por exemplo `chefe.sintetico@example.invalid`, criado pelo seed. Isto é um mecanismo de
desenvolvimento explícito, só disponível em `local`/`test`, nunca autenticação real.

Para testar a validação real de token Microsoft Entra ID sem um tenant de verdade,
defina `AUTH_ENABLED=true` e `ENTRA_VALIDATION_MODE=mock` (só válido em `local`/`test` —
ver `docs/DECISIONS.md` D-024) e envie `Authorization: Bearer <token>`, assinado com
`app.security.entra_auth.issue_mock_token(...)`. Com um tenant real disponível, deixe
`ENTRA_VALIDATION_MODE=real` (omissão) e defina `ENTRA_TENANT_ID`/`ENTRA_CLIENT_ID`.

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
npm run lint                 # tsc --noEmit
npm test                     # Vitest (vitest run) — login de desenvolvimento (D-033) + suite de UI (D-046)
npm run build                # valida TypeScript + gera build de produção
```

Com o backend também a correr (`uvicorn` — ver acima), abrir
`http://localhost:5173`: ecrã de login com duas opções claramente separadas —
"Entrar com Microsoft" (MSAL real, Authorization Code + PKCE — ver
`src/auth/msal.ts` e `docs/DECISIONS.md` D-031; aparece desativado sem
`VITE_ENTRA_CLIENT_ID`/`VITE_ENTRA_TENANT_ID`/`VITE_ENTRA_API_SCOPE` configurados) e
o mecanismo de desenvolvimento (`X-Dev-User-Email`, só em `vite dev`/testes por
omissão) — depois:

- **Painel** (`/`, página inicial): indicadores reais do dashboard, aviso de
  fotografias pendentes e resumo visual da semana (tudo calculado no servidor).
- **Projetos** (`/projects`, `/projects/:id`): pesquisa e filtros por estado/PM/
  datas/situação; estado, progresso, próxima tarefa, prazo, tarefas atrasadas,
  avisos de dados em falta e de fotos; detalhe em separadores (resumo, dados
  da instalação, licenciamento/comunicação, tarefas, inventário, histórico,
  cliente) com edição limitada aos campos que o servidor permite. "Novo
  projeto — importar notas" (`/projects/import`) carrega o HTML/JSON do
  formulário de notas iniciais, mostra preview e conflitos por campo, e só cria/
  atualiza o projeto após confirmação explícita — ver `docs/DATA_IMPORTS.md`.
- **Tarefas** (`/tasks`): vista de lista e Kanban, filtros por projeto/
  responsável/prioridade/atraso/estado, criação e transição de estado com
  confirmação visual. PM vê tarefas de todos os projetos, mas só cria/edita
  as suas (nunca reatribui) — ver `docs/DECISIONS.md` D-052.
- **Inventário** (`/inventory`): stock central da IdealMinde
  (físico/reservado/disponível/mínimo), alertas de stock baixo, registo de
  entradas/ajustes (`inventory.manage_central`); reservar/consumir/libertar/
  devolver material por projeto está na tab "Inventário" do detalhe do
  projeto — ver `docs/INVENTORY_RULES.md`.
- **Mapa** (`/map`): instalações, fornecedores, pontos de recolha e
  pendências — mapa visual (Leaflet) quando há um provider de tiles
  configurado, ou lista funcional sempre que não há; seleção múltipla + link
  de rota externa, sem otimização automática — ver `docs/MAP_AND_PLANNING.md`.
- **Planeamento** (`/planning`): calendário de visitas/comissionamentos —
  vistas de semana/mês/lista, filtros todos/meus/por PM/por projeto/por
  responsável, aviso (não bloqueante) de sobreposição de horário — sempre
  local, sem Outlook/Graph — ver `docs/MAP_AND_PLANNING.md`.
- **Metas e indicadores** (`/performance`): metas por período/PM com
  progresso calculado no servidor, edição de metas, portefólio por estado,
  indicadores anuais — ver `docs/PERFORMANCE_METRICS.md`.
- **Férias e aniversários** (`/vacations`): calendário mensal, ausentes hoje,
  próximas ausências, aniversários, registo e cancelamento conforme permissões.
- **Reconciliação de PM** (`/reconciliation`): fila de reconciliação da migração.
- **Estado do sistema** (`/status`): diagnóstico técnico (saúde do backend,
  integrações ativas, utilizador atual) — antiga página inicial da Fase 1.

Validado manualmente ponta-a-ponta nesta fase — ver `docs/DECISIONS.md` D-027/D-031,
D-039 a D-047 (Fase 1.5), D-052 a D-056 (MVP de Operações, fatia 1) e D-057
(fatia 2 — importadores implementados, UI de mapa/planeamento, tab de
inventário por projeto). D-058 (`Task.category`/`attention` do mapa,
incluindo a UI de `/map`) validado manualmente contra o seed real — ver
secção acima e `docs/DECISIONS.md`.

Login Microsoft real requer uma app registration SPA (Authorization Code + PKCE, sem
client secret) e uma app registration de API expondo o âmbito `access_as_user` — ver
`frontend/.env.example` e `docs/OPEN_QUESTIONS.md`, pergunta 1.

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
  `AUTH_ENABLED=false`, `SECRET_KEY` for o valor de desenvolvimento (ou vazio),
  `DATABASE_URL` for SQLite, `ENTRA_VALIDATION_MODE` não for `real`,
  `ENTRA_TENANT_ID`/`ENTRA_CLIENT_ID`/`ENTRA_REQUIRED_SCOPE` não estiverem
  preenchidos, `CORS_ALLOWED_ORIGINS` ficar vazio, ou um override de
  issuer/JWKS/audience ficar parcial — ver `app/config.py` e `docs/DECISIONS.md`
  D-020/D-024/D-032. O mecanismo de utilizador de desenvolvimento
  (`X-Dev-User-Email`) tem uma segunda verificação independente e só funciona em
  `local`/`test` — nem é consultado quando `AUTH_ENABLED=true`. No frontend, o
  equivalente (`devLoginEnabled`, `src/auth/msal.ts`) fica desligado por omissão num
  build de produção, ligado só em `vite dev`/testes — e nunca lê/escreve
  `localStorage` fora disso, mesmo com um valor antigo já guardado (D-033).
- Tokens Microsoft Entra ID são validados a sério: `oid` obrigatório (nunca `sub`
  como identidade persistente), assinatura RS256 (JWKS do tenant, cliente cacheado no
  processo), issuer, audience, tenant (`tid`, quando configurado), `scp` (só tokens
  delegados) e validade temporal (`exp`/`nbf`) — `app/security/entra_auth.py`, D-024
  e D-029. O modo `mock` (chave de teste local, sem rede) nunca é alcançável fora de
  `local`/`test`. Ligação automática de um `User` existente por email (JIT linking) é
  configurável e desligada por omissão fora de `local`/`test`, e sempre auditada em
  `auth_audit_log` quando acontece (D-029).
- No frontend, o login real usa MSAL com Authorization Code + PKCE; o token enviado à
  API é sempre um access token dedicado ao âmbito da API, nunca o ID token
  (`src/auth/msal.ts`, D-031).
- **Provisionamento de utilizadores Entra ID nunca é automático a partir de um
  token** — `app/cli/provision_entra_user.py` é o único caminho para ligar
  `User.entra_object_id` em staging/produção: comando administrativo controlado
  (nunca um endpoint HTTP), só liga a um `User` já existente e ativo, nunca cria
  nem reatribui, sempre auditado em `auth_audit_log` (D-034). JIT linking por
  email continua desligado por omissão fora de `local`/`test` (D-029).
  `app/cli/provision_staging.py` (D-050, mesmo desenho — comando
  administrativo controlado, nunca um endpoint HTTP) cria/atualiza os
  `Person`/`User`/`UserRole` reais a partir de um ficheiro JSON externo
  ao repositório, de forma idempotente e auditada, nunca guarda password
  nem cria projetos — ver `docs/STAGING_BOOTSTRAP.md`.
- Edição de um projeto por um PM (`project.edit_own_progress`) está limitada a uma
  lista explícita de campos, validada sempre no servidor independentemente do
  frontend — nunca `name`, `client_email`, `pm_person_id`, `is_active` e outros campos
  administrativos sem `project.edit_all` (`app/security/project_fields.py`, D-028).
  Potência, coordenadas, datas legadas e `commercial_assumptions` ficam também
  administrativos até confirmação de negócio (D-035, `docs/OPEN_QUESTIONS.md`
  pergunta 5-B).
- Nenhuma migração escreve diretamente em `projects` — passa sempre por ingestão em
  staging (`import_batches`/`staging_project_records`, só via
  `app/cli/ingest_staging.py`, comando controlado com modo staging-only — D-037),
  revisão de conflitos, e promoção explícita, sempre com auditoria e rollback
  (`app/migration/staging.py`, docs/DECISIONS.md D-017). Ligar manualmente um
  registo em conflito a um projeto fora dos candidatos detetados automaticamente
  exige a permissão `migration.link_arbitrary_project` e uma nota obrigatória
  (D-030). Repetir a promoção depois de um rollback nunca duplica o projeto
  (`retry_promotion_after_rollback`, D-036).
- Valores monetários usam `Numeric`/`Decimal`, nunca `Float` (D-018).
- Antes de expor este backend fora de uma rede de confiança, correr uma revisão de
  segurança dedicada (ver `docs/PLAN.md`, secção de segurança, e
  `docs/GO_LIVE_CHECKLIST.md`).
