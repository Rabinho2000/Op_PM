# Runbook de staging — Op_PM

> Procedimento operacional, passo-a-passo, para levantar (e parar) o
> ambiente de `staging` pela primeira vez, incluindo o piloto de 5 a 10
> projetos reais antes da migração completa dos 295. Complementa
> `docs/STAGING_CHECKLIST.md` (a checklist de sign-off — usa este runbook
> como referência dos comandos exatos) e `docs/DATA_MIGRATION_RUNBOOK.md`
> (a migração completa dos 295 projetos, depois do piloto). Não cobre a
> passagem a produção — ver `docs/GO_LIVE_CHECKLIST.md`.
>
> **Nada aqui liga uma integração externa real** (Claude, Microsoft
> Graph, ClickUp, Financial) — ficam todas `*_ENABLED=false`, só
> documentadas como pontos de integração futuros (ver `docs/PLAN.md`).
> Este runbook também não decide alojamento (cloud vs. on-premises) —
> ver a lista de dados externos necessários na secção final.

## Índice

1. [Pré-requisitos](#1-pré-requisitos)
2. [Microsoft Entra ID — App registrations](#2-microsoft-entra-id--app-registrations)
3. [PostgreSQL](#3-postgresql)
4. [Configuração do backend](#4-configuração-do-backend)
5. [Migrações Alembic](#5-migrações-alembic)
6. [Configuração do frontend](#6-configuração-do-frontend)
7. [Arrancar o ambiente](#7-arrancar-o-ambiente)
8. [Health checks](#8-health-checks)
9. [Criação dos 5 utilizadores](#9-criação-dos-5-utilizadores)
10. [Logs](#10-logs)
11. [Backups e restauração](#11-backups-e-restauração)
12. [Testes de aceitação](#12-testes-de-aceitação)
13. [Piloto: 5 a 10 projetos reais antes dos 295](#13-piloto-5-a-10-projetos-reais-antes-dos-295)
14. [Procedimento de rollback](#14-procedimento-de-rollback)
15. [Parar o ambiente](#15-parar-o-ambiente)
16. [Dados externos ainda necessários](#16-dados-externos-ainda-necessários)

---

## 1. Pré-requisitos

- [ ] Acesso de administrador ao tenant Microsoft Entra ID da organização
      (para criar app registrations e conceder consentimento).
- [ ] Um servidor/serviço PostgreSQL 14+ dedicado a staging, **nunca
      partilhado com produção**, acessível a partir de onde o backend vai
      correr.
- [ ] Um domínio/URL onde o frontend de staging vai ficar acessível
      (necessário para os redirect URIs da secção 2).
- [ ] Acesso direto ao servidor/base de dados de staging para quem vai
      correr comandos administrativos (`app/cli/provision_entra_user.py`,
      `app/cli/ingest_staging.py`, `alembic`) — nunca através de um
      endpoint HTTP, por desenho (D-034/D-037).
- [ ] Python 3.12+ e Node.js 20+ disponíveis na máquina/imagem que vai
      correr o backend/frontend de staging.

Ver a secção 16 para a lista objetiva do que falta fornecer antes de
poder avançar.

## 2. Microsoft Entra ID — App registrations

Duas app registrations distintas — **nunca uma só** (a SPA nunca tem
client secret; a API nunca é pública):

### 2.1 App registration da API (backend) — "Resource Server"

1. **Azure Portal → Microsoft Entra ID → App registrations → New
   registration.**
   - Nome: por exemplo `Op_PM API — Staging`.
   - Supported account types: **Accounts in this organizational directory
     only** (single tenant) — a menos que a organização precise de
     multi-tenant, o que não é assumido aqui.
   - Redirect URI: deixar em branco (esta app registration nunca recebe
     um redirect — só valida tokens).
2. **Expose an API** (menu lateral):
   - Clicar **Set** ao lado de "Application ID URI" e aceitar o valor
     por omissão (`api://<client-id-desta-app>`), ou definir um URI
     customizado.
   - **Add a scope**:
     - Scope name: **`access_as_user`** (nome exato — o backend valida
       contra `ENTRA_REQUIRED_SCOPE`, que tem de corresponder a este
       scope; ver `app/security/entra_auth.py:_validate_delegated_token`).
     - Who can consent: "Admins and users", ou só "Admins" conforme a
       política da organização (`DECISÃO NECESSÁRIA` — ver secção 16).
     - Admin consent display name/description: texto livre (ex. "Aceder
       à API Op_PM em nome do utilizador").
     - State: **Enabled**.
3. Anotar (vai para `backend/.env`, secção 4):
   - **Application (client) ID** → `ENTRA_CLIENT_ID`.
   - **Directory (tenant) ID** → `ENTRA_TENANT_ID`.
4. **Nunca gerar um client secret** para esta app registration nesta
   fase — é só um Resource Server que valida tokens recebidos, nunca
   inicia um fluxo OAuth como client confidencial.

### 2.2 App registration da SPA (frontend)

1. **Azure Portal → Microsoft Entra ID → App registrations → New
   registration.**
   - Nome: por exemplo `Op_PM Frontend — Staging`.
   - Redirect URI: escolher **Single-page application (SPA)** como
     plataforma (nunca "Web" nem "Public client/native" — o MSAL.js
     precisa de SPA para Authorization Code + PKCE), e o URL real de
     staging, ex. `https://staging.op-pm.exemplo.pt` (sem caminho — o
     MSAL trata o resto).
2. **Authentication** (menu lateral), confirmar:
   - A plataforma SPA está listada com o redirect URI correto.
   - "Logout URL" (`postLogoutRedirectUri`) — por omissão,
     `<redirect_uri>/login` (ver `frontend/src/auth/msal.ts`); definir
     aqui se for diferente.
   - **Access tokens**/**ID tokens** (implicit grant): deixar **ambos
     desmarcados** — MSAL.js com Authorization Code + PKCE não precisa
     do fluxo implícito, e deixá-lo ligado é uma superfície
     desnecessária.
3. **API permissions** (menu lateral):
   - **Add a permission → APIs my organization uses** → procurar o nome
     da app registration da secção 2.1 → **Delegated permissions** →
     marcar `access_as_user` → **Add permissions**.
   - **Grant admin consent for <tenant>** (botão no topo da lista de
     permissões) — sem isto, o primeiro login de cada utilizador pede
     consentimento individual, que pode falhar silenciosamente consoante
     a política do tenant.
4. Anotar (vai para `frontend/.env.staging.example` → `.env`/variáveis
   de build, secção 6):
   - **Application (client) ID** desta app registration →
     `VITE_ENTRA_CLIENT_ID`.
   - Mesmo tenant ID da secção 2.1 → `VITE_ENTRA_TENANT_ID`.
   - `VITE_ENTRA_API_SCOPE` = `api://<client-id-da-api-2.1>/access_as_user`.

### 2.3 Ligar cada utilizador ao seu `entra_object_id`

Feito na secção 9, depois do backend estar a correr — nunca automático a
partir de um token (`app/cli/provision_entra_user.py`, D-034).

### 2.4 JIT linking (ligação automática por email)

**Fica desligado por omissão em staging** (`ENTRA_JIT_LINK_BY_EMAIL`
não definido → `resolved_entra_jit_link_by_email()` devolve `False` fora
de `local`/`test`, D-029). Não ativar `ENTRA_JIT_LINK_BY_EMAIL=true` em
staging sem uma decisão de negócio documentada em `docs/DECISIONS.md`
explicando porquê a ligação automática (sem confirmação manual via
`provision_entra_user.py`) é aceitável para este ambiente — nenhuma
decisão desse tipo foi tomada até agora.

## 3. PostgreSQL

- [ ] Criar a base de dados e um utilizador dedicados a staging (nunca o
      mesmo utilizador/credenciais de produção):
  ```sql
  CREATE ROLE op_pm_staging WITH LOGIN PASSWORD '<password-forte>';
  CREATE DATABASE op_pm_staging OWNER op_pm_staging;
  ```
- [ ] Confirmar a versão (14+) e que a rede permite ligação a partir de
      onde o backend vai correr:
  ```bash
  psql "postgresql://op_pm_staging:<password>@<host>:5432/op_pm_staging" -c "SELECT version();"
  ```
- [ ] Configurar backups automáticos **antes** de qualquer dado real
      entrar (ver secção 11) — nunca deixar para depois do piloto.

## 4. Configuração do backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Linux/Mac; Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-postgres.txt

cp .env.staging.example .env
# Editar .env: preencher SECRET_KEY, DATABASE_URL, ENTRA_TENANT_ID,
# ENTRA_CLIENT_ID, CORS_ALLOWED_ORIGINS com os valores reais das secções
# 2 e 3 — ver backend/.env.staging.example para a explicação de cada
# variável e o que a distingue de local/dev.
```

A aplicação **recusa-se a arrancar** com qualquer uma destas em falta ou
incorreta em `APP_ENV=staging` (`app/config.py:Settings._enforce_hardening_in_non_local_envs`,
`docs/DECISIONS.md` D-020/D-032) — isto é testado
(`tests/test_config_hardening.py`) e é o comportamento esperado, não um
bug: falhar cedo e alto é a proteção, nunca arrancar "quase seguro".

## 5. Migrações Alembic

```bash
cd backend
# DATABASE_URL já lido de .env (secção 4) via app/config.py
python -m alembic upgrade head
```

- [ ] Confirmar que corre sem erros e sem avisos de `head` múltiplo:
  ```bash
  python -m alembic heads   # tem de mostrar exatamente uma revisão
  python -m alembic current # confirma que ficou na revisão de topo
  ```
- [ ] **Nunca correr `python -m app.migration.seed_dev` em staging** —
      recusa-se sozinho a partir desta revisão
      (`app.migration.seed_dev.assert_seed_allowed_environment`,
      testado em `tests/test_seed_dev_staging_guard.py`): esse seed cria
      utilizadores/pessoas/projetos sintéticos (`*.invalid`), só para
      `local`/`test`. Staging arranca **sem nenhum dado de demonstração**
      — só o schema vazio até à secção 9 (utilizadores reais) e à secção
      13 (piloto de projetos reais).
- [ ] Se uma migração específica precisar de ser revertida:
  `python -m alembic downgrade -1` (ou para uma revisão nomeada) — cada
  migração já é testada em CI como `upgrade` → `downgrade` → `upgrade`,
  nunca pela primeira vez em staging.

## 6. Configuração do frontend

```bash
cd frontend
npm install
npm run lint    # tsc --noEmit — corre limpo antes de continuar
npm test        # Vitest — corre limpo antes de continuar

cp .env.staging.example .env.local
# Editar .env.local: VITE_API_BASE_URL, VITE_ENTRA_CLIENT_ID,
# VITE_ENTRA_TENANT_ID, VITE_ENTRA_API_SCOPE com os valores reais das
# secções 2 e 4 — VITE_ENABLE_DEV_LOGIN=false explícito.

npm run build   # gera frontend/dist/ — servir como estático (nginx,
                # storage estático, CDN — mecanismo concreto depende do
                # alojamento escolhido, ver secção 16)
```

Confirmar depois do build (inspecionar `dist/assets/*.js`, ou abrir a
app já servida e a consola do browser): nenhuma referência a
`X-Dev-User-Email` visível/ativa — `devLoginEnabled` (`src/auth/msal.ts`)
fica `false` num build de produção/staging real, mesmo que
`VITE_ENABLE_DEV_LOGIN` tivesse sido esquecido (D-033) — mas defini-lo
explicitamente evita qualquer dúvida ao rever a configuração.

## 7. Arrancar o ambiente

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Mecanismo exato de arranque (systemd, container, processo gerido por um
PaaS) depende do alojamento escolhido — `DECISÃO NECESSÁRIA`, ver secção
16. Sugestão mínima (`gunicorn` com workers Uvicorn, quando o alojamento
não gerir isto sozinho):

```bash
gunicorn app.main:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --workers 2
```

O frontend (`frontend/dist/`) é estático — servir com o mecanismo do
alojamento escolhido (nginx, storage estático + CDN, etc.).

## 8. Health checks

```bash
curl -s https://<dominio-do-backend-staging>/health | python -m json.tool
```

- [ ] `"status": "ok"`.
- [ ] `"app_env": "staging"`.
- [ ] `"database_dialect": "postgresql"` (nunca `"sqlite"` — se aparecer
      `sqlite` aqui, `DATABASE_URL` está errado ou não foi lido; parar e
      corrigir antes de continuar, nunca prosseguir "só para testar").
- [ ] `"integrations"` — todos `false` (`graph_enabled`,
      `clickup_enabled`, `financial_enabled`, `claude_enabled`).
- [ ] `GET /docs` (Swagger) acessível — confirma que a app está mesmo a
      responder, não só o processo a correr.
- [ ] Frontend: abrir `https://<dominio-do-frontend-staging>` — mostra o
      ecrã de login com "Entrar com Microsoft" **ativo** (não desativado
      — se aparecer desativado, `VITE_ENTRA_CLIENT_ID`/
      `VITE_ENTRA_TENANT_ID`/`VITE_ENTRA_API_SCOPE` não foram embutidos
      corretamente no build da secção 6) e **sem** a secção de
      desenvolvimento (login de dev não deve aparecer nesta build).

## 9. Criação dos 5 utilizadores

Ver `docs/DECISIONS.md` D-034 e `app/cli/provision_entra_user.py`. Este
comando **nunca cria** um `User`/`Person` — pressupõe que os registos já
existem na base de dados de staging.

### 9.1 Criar `Person`/`User`/`UserRole` (staging não tem seed automático)

Como `seed_dev.py` está bloqueado em staging (secção 5), os registos de
`Person`/`User`/`UserRole` e o catálogo de `Role`/`Permission`/
`RolePermission` (`app/security/catalog.py`) têm de existir antes de
provisionar alguém. Não existe ainda um script de seed dedicado a
staging neste repositório — `DECISÃO NECESSÁRIA` (ver secção 16): criar
manualmente via SQL/Python, usando `app/migration/seed_dev.py` só como
referência da **estrutura** dos registos (papéis, permissões), nunca
correndo esse ficheiro tal como está. Para cada uma das 5 pessoas reais
(Administrador, Chefe de Operações, Project Manager, Comercial,
Financeiro):

```python
# a partir de backend/, com DATABASE_URL já apontado a staging
from app.db import SessionLocal
from app.models.people import Person
from app.models.identity import User, UserRole, Role
from app.db import new_uuid

db = SessionLocal()
# códigos válidos (app/security/catalog.py): administrador,
# chefe_operacoes, project_manager, comercial, financeiro
role = db.query(Role).filter(Role.code == "project_manager").one()  # ou o papel correto
person = Person(id=new_uuid(), display_name="<Nome Real>", is_active=True)
db.add(person)
db.flush()
user = User(id=new_uuid(), person_id=person.id, email="<email-real>", is_active=True)
db.add(user)
db.flush()
db.add(UserRole(id=new_uuid(), user_id=user.id, role_id=role.id))
db.commit()
```

- [ ] Confirmar que `Role`/`Permission`/`RolePermission`
      (`app/security/catalog.py`) já existem na base de dados antes
      disto — se `alembic upgrade head` não os semeou, correr o
      equivalente de `seed_catalog()` de `seed_dev.py` isoladamente
      (é seguro correr independentemente do resto do seed — não cria
      pessoas/projetos fictícios, só o catálogo de papéis/permissões).

### 9.2 Ligar `entra_object_id`

Para cada um dos 5 utilizadores:

- [ ] Obter o **Object ID** da pessoa: **Azure Portal → Entra ID → Users
      → (utilizador) → Object ID** (não exige que a pessoa já tenha
      iniciado sessão).
- [ ] Correr, a partir do servidor de staging:
  ```bash
  python -m app.cli.provision_entra_user \
    --user-email <email-real> \
    --entra-object-id <object-id-do-azure-portal> \
    --actor-email <email-de-quem-executa> \
    --confirm
  ```
- [ ] Confirmar a saída `OK: ...` e o registo em `auth_audit_log`
      (evento `admin_provision_link`).
- [ ] Repetir para os 5 utilizadores. **Nunca** reutilizar o mesmo
      `entra_object_id` para duas pessoas — o comando recusa-se
      explicitamente (D-034).

## 10. Logs

- Backend (Uvicorn/Gunicorn): stdout/stderr do processo — redirecionar
  para o mecanismo de logging do alojamento escolhido (`journald`, o
  driver de logs do container, um serviço gerido). Nenhum log
  estruturado dedicado existe ainda neste repositório —
  `DECISÃO NECESSÁRIA` (ver secção 16) sobre agregação/retenção.
- Auditoria de aplicação (distinta de logs de processo, já implementada
  e persistente na base de dados, não em ficheiro):
  - `auth_audit_log` — eventos de autenticação/provisionamento
    (`admin_provision_link`, `jit_link_by_email` quando ativo).
  - `project_history` — toda a escrita relevante em `projects`, com
    autor, campo, valor antigo/novo, e fonte (`ui`, `import_legacy`,
    `migration_rollback`, `migration_retry`).
  - `ai_audit_log` — ações de IA (nenhuma ainda nesta fase, Claude
    desligado).
  ```sql
  -- consultar diretamente na base de dados de staging, sem endpoint
  -- HTTP dedicado nesta fase:
  SELECT * FROM auth_audit_log ORDER BY created_at DESC LIMIT 50;
  SELECT * FROM project_history ORDER BY changed_at DESC LIMIT 50;
  ```
- Retenção de logs/backups: `DECISÃO NECESSÁRIA` — ver
  `docs/OPEN_QUESTIONS.md` pergunta 15 e a secção 16 abaixo.

## 11. Backups e restauração

- [ ] Confirmar que o serviço PostgreSQL de staging tem backups
      automáticos configurados (diários, no mínimo) — mecanismo exato
      depende do alojamento (secção 16).
- [ ] Fazer um backup manual completo **antes** de qualquer passo da
      secção 12 (testes de aceitação) e, sobretudo, antes da secção 13
      (piloto):
  ```bash
  pg_dump "postgresql://op_pm_staging:<password>@<host>:5432/op_pm_staging" \
    --format=custom --file="op_pm_staging_$(date +%Y%m%d_%H%M%S).dump"
  ```
- [ ] Testar um restauro completo pelo menos uma vez antes de considerar
      staging pronto para uso real — para uma base de dados de
      verificação separada, nunca sobre a de staging em uso:
  ```bash
  createdb op_pm_staging_restore_test
  pg_restore --dbname=op_pm_staging_restore_test --clean --if-exists \
    op_pm_staging_20260101_120000.dump
  # depois: apontar DATABASE_URL para esta base de dados de teste,
  # arrancar o backend, confirmar /health e alguns dados batem certo,
  # e só depois apagar a base de dados de verificação.
  ```

## 12. Testes de aceitação

Repete `docs/STAGING_CHECKLIST.md` secção 7 em formato de comandos —
correr depois da secção 9 (utilizadores reais já ligados):

- [ ] **Health check** (secção 8) já feito.
- [ ] **Login real:** cada um dos 5 utilizadores abre o frontend, clica
      "Entrar com Microsoft", autentica-se, é redirecionado autenticado
      (nunca cai no mecanismo de desenvolvimento — que não aparece nesta
      build). `GET /me` devolve `user_id`/`email`/`roles`/`permissions`
      corretos.
- [ ] **Dashboard:** `/` mostra indicadores reais (mesmo com zero
      projetos antes da secção 13 — os contadores aparecem a zero, nunca
      erro).
- [ ] **Projetos/Tarefas/Férias/Aniversários:** páginas carregam sem
      erro (vazias antes da secção 13).
- [ ] **Permissões por perfil** (repetir para cada papel):
  ```bash
  # PM só vê os seus próprios projetos:
  curl -s https://<backend>/api/projects \
    -H "Authorization: Bearer <token-do-pm>" | python -m json.tool
  # Comercial tenta editar um projeto — espera 403:
  curl -s -o /dev/null -w "%{http_code}\n" -X PATCH https://<backend>/api/projects/<id> \
    -H "Authorization: Bearer <token-do-comercial>" -H "Content-Type: application/json" \
    -d '{"notes": "teste"}'
  # Financeiro tenta editar uma tarefa — espera 403:
  curl -s -o /dev/null -w "%{http_code}\n" -X PATCH https://<backend>/api/tasks/<id> \
    -H "Authorization: Bearer <token-do-financeiro>" -H "Content-Type: application/json" \
    -d '{"status": "in_progress"}'
  ```
- [ ] **Auditoria:** confirmar `auth_audit_log` só tem as entradas de
      `admin_provision_link` da secção 9 (nenhuma `jit_link_by_email` a
      menos que tenha sido ativado explicitamente — secção 2.4).
- [ ] **CORS:** um pedido do frontend de staging não é bloqueado; uma
      origem fora da lista é recusada:
  ```bash
  curl -s -o /dev/null -w "%{http_code}\n" https://<backend>/health \
    -H "Origin: https://um-dominio-nao-autorizado.exemplo"
  ```

## 13. Piloto: 5 a 10 projetos reais antes dos 295

**Nunca antes das secções 1 a 12 estarem completas.** O export real
nunca entra neste repositório Git — fica sempre num caminho local, fora
da árvore de trabalho (recomendado) ou coberto pelo `.gitignore`
(`backend/data/`, `backend/files/`); `app.cli.ingest_staging` recusa-se a
ler um ficheiro que o Git conseguiria apanhar (`git add -A`) e que não
esteja no `.gitignore`.

1. **Pré-visualizar sem escrever nada** (nem em staging):
   ```bash
   cd backend
   python -m app.cli.ingest_staging \
     --file /caminho/fora/do/repo/export_real.json \
     --only-ids <id1>,<id2>,<id3>,<id4>,<id5> \
     --dry-run
   ```
   Confirma as contagens (`projects_seen`, `distinct_pm_names`,
   `with_email`, `with_contact`, `with_coordinates`, `conflicts`) antes
   de decidir quais 5 a 10 IDs usar — repetir com `--only-ids` diferente
   até a amostra parecer representativa (pelo menos um projeto sem
   PM/email/coordenadas, se existir no export, para validar que campos
   em falta continuam bem tratados).
2. **Reconciliação de PM prévia** — seguir
   `docs/DATA_MIGRATION_RUNBOOK.md` secção 2, mas só para os PMs que
   aparecem nos IDs escolhidos.
3. **Ingerir a sério** (sem `--dry-run`), só o subconjunto:
   ```bash
   python -m app.cli.ingest_staging \
     --file /caminho/fora/do/repo/export_real.json \
     --only-ids <id1>,<id2>,<id3>,<id4>,<id5> \
     --actor-email <email-de-quem-executa>
   ```
4. **Rever a fila de conflitos e promover** — seguir
   `docs/DATA_MIGRATION_RUNBOOK.md` secções 4 e 5, exatamente igual à
   migração completa, só com menos registos.
5. **Validar o piloto** (`docs/DATA_MIGRATION_RUNBOOK.md` secção 6):
   amostragem manual de todos os projetos do piloto (não só 10 ao acaso,
   já que o piloto inteiro tem só 5 a 10) — confirmar campos, PM,
   histórico com `source='import_legacy'`.
6. **Testar o piloto na aplicação:** abrir cada projeto no frontend,
   confirmar que as tarefas padrão foram criadas
   (`ensure_default_tasks_for_project`), que o dashboard reflete os
   novos projetos, que as permissões por PM continuam corretas com dados
   reais.
7. **Rollback do piloto** (para repetir ou para confirmar que o
   procedimento funciona antes da migração completa) — reverter cada
   registo promovido do lote:
   ```bash
   # obter o import_batch_id impresso no passo 3, depois:
   curl -s "https://<backend>/api/migration/import-batches/<batch-id>/records?status=promoted" \
     -H "Authorization: Bearer <token-admin-ou-chefe>" | python -m json.tool
   # para cada registo promovido:
   curl -s -X POST "https://<backend>/api/migration/staging-records/<record-id>/rollback" \
     -H "Authorization: Bearer <token-admin-ou-chefe>" -H "Content-Type: application/json" \
     -d '{"reason": "rollback do piloto de staging"}'
   ```
   Confirmar depois: os projetos criados pelo piloto deixam de aparecer
   em `GET /api/projects` (ficam `is_active=false`, nunca apagados —
   `docs/DECISIONS.md`, `rollback_promotion`); os que já existiam e só
   foram atualizados voltam aos valores anteriores, com nova entrada em
   `project_history` (`source='migration_rollback'`).
8. **Só depois de o piloto (ingestão → promoção → validação →
   rollback de teste, ou promoção final aceite) correr sem surpresas**,
   avançar para `docs/DATA_MIGRATION_RUNBOOK.md` com o export completo
   dos 295 projetos.

## 14. Procedimento de rollback

- Rollback de uma promoção de projeto (piloto ou migração completa): ver
  secção 13, passo 7 — sempre por `staging-record`, nunca em bloco.
- Rollback de uma migração Alembic: ver secção 5.
- Rollback de um deployment de backend/frontend (código): reverter para
  a imagem/build anterior conhecida-boa — mecanismo exato depende do
  alojamento (secção 16).
- Se um utilizador foi provisionado com `entra_object_id` incorreto: não
  há um comando de "desligar" nesta fase (D-034, deliberado) — corrigir
  diretamente na base de dados (`UPDATE users SET entra_object_id = NULL
  WHERE id = ...`) e registar a correção manualmente.
- Se os dados ficarem num estado inconsistente que os passos acima não
  resolvam: restaurar o backup da secção 11.

## 15. Parar o ambiente

- [ ] Backend: parar o processo Uvicorn/Gunicorn (`Ctrl+C` em primeiro
      plano; `systemctl stop <serviço>` ou o equivalente do alojamento
      escolhido para um processo gerido).
- [ ] Frontend: se servido por um processo próprio (não um CDN/storage
      estático), parar da mesma forma; um CDN/storage estático não
      precisa de ser "parado", só deixar de apontar DNS/routing para lá
      se for para desativar o acesso.
- [ ] **Nunca apagar a base de dados PostgreSQL de staging só para
      "parar"** — parar o ambiente de aplicação não implica destruir
      dados; só apagar a base de dados deliberadamente, com um backup
      confirmado (secção 11) e por decisão explícita de recomeçar do
      zero.
- [ ] Se for para ficar parado por um período longo: confirmar que os
      backups automáticos da secção 11 continuam a correr (ou pausar
      deliberadamente, dependendo do custo do alojamento) — decisão do
      responsável pelo ambiente, não assumida aqui.
- [ ] Registar a paragem (motivo, data, quem) fora deste repositório —
      ex. na mesma folha de acompanhamento usada para a migração
      (`docs/DATA_MIGRATION_RUNBOOK.md`).

## 16. Dados externos ainda necessários

Lista objetiva do que precisa de ser fornecido por alguém fora deste
repositório antes (ou durante) de seguir este runbook — nada disto foi
inventado nem assumido nas secções acima:

1. **Acesso de administrador ao tenant Microsoft Entra ID** da
   organização, para criar as duas app registrations da secção 2.
2. **Domínio(s) reais** onde o frontend e o backend de staging vão ficar
   acessíveis (necessários para os redirect URIs da secção 2.2 e para
   `CORS_ALLOWED_ORIGINS`/`VITE_API_BASE_URL`).
3. **Decisão de alojamento** (cloud vs. on-premises, fornecedor
   concreto) — condiciona o mecanismo exato de arranque (secção 7),
   logs (secção 10) e backups automáticos (secção 11). Sem isto, as
   secções 7/10/11 só podem ficar com os comandos genéricos já dados,
   nunca instruções específicas de um fornecedor.
4. **Servidor/serviço PostgreSQL 14+** dedicado a staging (pode
   depender da decisão nº 3).
5. **Nomes reais dos 5 utilizadores** (Administrador, Chefe de
   Operações, PM, Comercial, Financeiro) e os respetivos emails do
   tenant, para a secção 9.
6. **Export real do sistema legado** (`files/atribuicoes.json` ou
   equivalente) — só necessário para a secção 13 (piloto), guardado
   sempre fora deste repositório Git.
7. **Decisão de negócio** sobre "who can consent" no scope
   `access_as_user` (secção 2.1) — Admins apenas, ou Admins e
   utilizadores.
8. **Decisão de negócio** (se aplicável) sobre ativar
   `ENTRA_JIT_LINK_BY_EMAIL=true` em staging — por omissão fica
   desligado (secção 2.4); só mudar com justificação documentada.
9. **Política de retenção de logs/backups** (dias/meses) — condiciona a
   configuração concreta do serviço PostgreSQL/alojamento escolhido
   (secções 10/11).

Sem os itens 1 a 4, este runbook não pode ser executado além da secção
6 (build do frontend, que não depende de infraestrutura real). Sem o
item 6, a secção 13 (piloto) não pode começar.
