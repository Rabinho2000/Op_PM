# Checklist de staging — Op_PM

> Esta checklist é o registo de sign-off (o que já foi feito e
> verificado); os comandos exatos para cada passo estão em
> `docs/STAGING_RUNBOOK.md` (runbook operacional completo, incluindo o
> piloto de 5 a 10 projetos reais antes dos 295 — secção 13). Não cobre a
> migração completa dos 295 projetos reais — ver
> `docs/DATA_MIGRATION_RUNBOOK.md` — nem a passagem a produção — ver
> `docs/GO_LIVE_CHECKLIST.md`. Sempre que este documento pedir uma
> decisão que a organização ainda não tomou, a caixa fica por marcar e
> aponta para `docs/OPEN_QUESTIONS.md` — nunca inventar a resposta para
> poder marcar a caixa.
>
> Alojamento (cloud vs. on-premises) não está decidido — ver
> `docs/OPEN_QUESTIONS.md`, secção "Podem ser decididas mais tarde",
> "Plano de deployment" em `docs/PLAN.md`. Este documento assume só que
> `staging` corre a mesma imagem/código do backend e do frontend que
> `local`, com uma base de dados PostgreSQL própria, distinta da de
> `production` (nunca partilhada — ver `docs/DATA_MIGRATION_RUNBOOK.md`
> para como os dados migrados chegam depois a produção).

## 1. Pré-requisitos

- [ ] Alguém com direitos de administrador no tenant Microsoft Entra ID
      da organização (para criar app registrations e conceder consentimento).
- [ ] Um servidor/serviço PostgreSQL 14+ dedicado a staging, acessível ao
      backend, **nunca partilhado com produção**.
- [ ] Um domínio/URL onde o frontend de staging vai ficar acessível (para
      os redirect URIs da app registration SPA).
- [ ] Acesso direto ao servidor/base de dados de staging para quem vai
      correr os comandos administrativos (`app/cli/provision_entra_user.py`,
      `app/cli/ingest_staging.py`) — nunca através de um endpoint HTTP,
      por desenho (ver `docs/DECISIONS.md` D-034/D-037).

## 2. App registrations Microsoft Entra ID

Duas app registrations distintas — nunca uma só (a SPA nunca deve ter
client secret; a API nunca deve ser pública):

### 2.1 App registration da API (backend)

- [ ] Criar a app registration (ex.: `Op_PM API — staging`).
- [ ] Em **Expose an API**, definir o Application ID URI (`api://<client-id-da-api>`
      ou um URI customizado) e adicionar um scope delegado:
  - Nome do scope: **`access_as_user`** (nome exato — o backend valida
    contra `ENTRA_REQUIRED_SCOPE`, que deve corresponder a este scope; ver
    `app/security/entra_auth.py:_validate_delegated_token`).
  - "Who can consent": Admins and users (ou só Admins, conforme a política
    da organização — `DECISÃO NECESSÁRIA`, não assumida aqui).
- [ ] Anotar o **Application (client) ID** desta app registration →
      `ENTRA_CLIENT_ID` do backend.
- [ ] Anotar o **Directory (tenant) ID** → `ENTRA_TENANT_ID`.
- [ ] **Nunca** gerar um client secret para uso pelo frontend — esta API
      só valida tokens recebidos (Resource Server), nunca inicia um fluxo
      OAuth como client confidencial nesta fase.

### 2.2 App registration da SPA (frontend)

- [ ] Criar a app registration (ex.: `Op_PM Frontend — staging`), tipo
      **Single-page application (SPA)** — nunca "Web" nem "Public client",
      para o MSAL.js usar Authorization Code + PKCE corretamente (ver
      `frontend/src/auth/msal.ts`).
- [ ] Em **Authentication → Single-page application → Redirect URIs**,
      adicionar o(s) URL(s) reais de staging, ex.:
      `https://staging.op-pm.exemplo.pt` (sem caminho — o MSAL trata o
      resto). **Nunca** usar `http://` nem um domínio de outro ambiente.
  - [ ] Confirmar também o "Logout URL" (`postLogoutRedirectUri`) — por
        omissão, `<redirect_uri>/login` (ver `msal.ts`).
- [ ] Em **API permissions**, adicionar uma permissão delegada apontando
      para o scope `access_as_user` da app registration da API (secção
      2.1) — **Add a permission → APIs my organization uses → (nome da
      API) → Delegated permissions → access_as_user**.
- [ ] **Conceder consentimento de administrador** para essa permissão
      (botão "Grant admin consent") — sem isto, o primeiro login de cada
      utilizador pede consentimento individual, o que pode falhar
      silenciosamente consoante a política do tenant.
- [ ] Anotar o **Application (client) ID** desta app registration →
      `VITE_ENTRA_CLIENT_ID` do frontend.
- [ ] `VITE_ENTRA_TENANT_ID` = mesmo tenant ID da secção 2.1.
- [ ] `VITE_ENTRA_API_SCOPE` = `api://<client-id-da-api>/access_as_user`
      (o Application ID URI definido em 2.1 + `/access_as_user`).

## 3. Variáveis de ambiente obrigatórias

Backend (`backend/.env` — nunca commitado; ver
`backend/.env.staging.example`, específico de staging, para a lista
completa comentada — `backend/.env.example` é a versão de local/dev). A
aplicação **recusa-se a arrancar** em
`APP_ENV=staging` se alguma destas faltar ou estiver incorreta (ver
`app/config.py:Settings._enforce_hardening_in_non_local_envs`,
`docs/DECISIONS.md` D-020/D-032):

- [ ] `APP_ENV=staging`
- [ ] `AUTH_ENABLED=true`
- [ ] `SECRET_KEY=` — valor aleatório real, gerado especificamente para
      staging (ex. `python -c "import secrets; print(secrets.token_urlsafe(48))"`),
      **nunca** o valor de `.env.example`, **nunca** reutilizado de
      `production`.
- [ ] `DATABASE_URL=postgresql+psycopg://...` apontando à base de dados de
      staging (secção 4).
- [ ] `ENTRA_VALIDATION_MODE=real`
- [ ] `ENTRA_TENANT_ID=` (secção 2.1)
- [ ] `ENTRA_CLIENT_ID=` (secção 2.1 — o da API, não o da SPA)
- [ ] `ENTRA_REQUIRED_SCOPE=access_as_user`
- [ ] `CORS_ALLOWED_ORIGINS=` — o(s) URL(s) reais do frontend de staging
      (secção 2.2), separados por vírgula se mais do que um. Nunca vazio,
      nunca `*`.
- [ ] `ENTRA_ISSUER`/`ENTRA_JWKS_URL`/`ENTRA_AUDIENCE` — deixar vazios
      (derivados automaticamente de `ENTRA_TENANT_ID`/`ENTRA_CLIENT_ID`)
      a menos que exista um motivo concreto para um override manual; se
      definir um, definir sempre os três juntos (nunca só um — bloqueado
      no arranque, D-032).
- [ ] Integrações externas (`GRAPH_ENABLED`, `CLICKUP_ENABLED`,
      `FINANCIAL_ENABLED`, `CLAUDE_ENABLED`) — manter todas `false` até
      cada uma ser explicitamente decidida e testada (Fases 6 a 9 do
      roadmap — ver `docs/PLAN.md`). Nada nesta checklist liga alguma
      destas.

Frontend (`frontend/.env.local` de build, ou variáveis injetadas no
processo de build de staging — ver `frontend/.env.staging.example`):

- [ ] `VITE_API_BASE_URL=` URL público do backend de staging.
- [ ] `VITE_ENTRA_CLIENT_ID`, `VITE_ENTRA_TENANT_ID`, `VITE_ENTRA_API_SCOPE`
      (secção 2.2).
- [ ] `VITE_ENTRA_REDIRECT_URI=` (se o URL de staging não for a raiz do
      domínio — ver `frontend/.env.example`).
- [ ] `VITE_ENABLE_DEV_LOGIN` — **não definir** (ou definir explicitamente
      `false`) num build de staging/produção: por omissão já fica
      desligado fora de `vite dev` (`devLoginEnabled`, D-033), mas deixar
      explícito evita qualquer dúvida ao rever a configuração de build.

## 4. Base de dados PostgreSQL

- [ ] Criar a base de dados e o utilizador dedicados a staging (nunca o
      mesmo utilizador/credenciais de produção).
- [ ] Confirmar a versão do PostgreSQL (14+) e que a rede permite ligação
      do backend (`DATABASE_URL`).
- [ ] Aplicar as migrações: `python -m alembic upgrade head` a partir de
      `backend/`, com `DATABASE_URL` já apontado à base de dados de
      staging.
- [ ] **Nunca correr `app/migration/seed_dev.py` em staging** — recusa-se
      sozinho a partir de `run_seed()`/`assert_seed_allowed_environment`
      (testado em `tests/test_seed_dev_staging_guard.py`), não é só
      disciplina manual. Esse seed cria utilizadores/pessoas/projetos
      sintéticos (`*.invalid`), pensados só para `local`/`test`. Staging
      usa dados reais (pessoas/utilizadores reais desde o início — secção
      5; projetos, só via `docs/STAGING_RUNBOOK.md` secção 13 — piloto —
      e depois `docs/DATA_MIGRATION_RUNBOOK.md`).
  - Isto implica criar manualmente (ou por um script de seed específico de
    staging, ainda por escrever) os `Role`/`Permission`/`RolePermission`
    de `app/security/catalog.py` e as `Person`/`User` reais (secção 5) —
    `seed_dev.py` pode servir de referência de estrutura, nunca ser
    corrido tal como está.
- [ ] Configurar backups automáticos (ver secção 6) antes de qualquer
      dado real entrar nesta base de dados.

## 5. Provisionamento dos 5 utilizadores

Ver `docs/DECISIONS.md` D-034 e `app/cli/provision_entra_user.py`. Nunca
cria um `User`/`Person` a partir daqui — pressupõe que os registos
`Person`/`User` já existem na base de dados de staging (criados
manualmente ou por um script de seed de staging, ver secção 4).

Para cada um dos 5 utilizadores ativos (papéis: Administrador, Chefe de
Operações, Project Manager, Comercial, Financeiro — ver
`app/security/catalog.py`):

- [ ] Confirmar que a pessoa já iniciou sessão pelo menos uma vez no
      Microsoft 365 da organização (para existir um `oid` real a ligar) —
      ou obter o **Object ID** diretamente no Azure Portal
      (**Entra ID → Users → (utilizador) → Object ID**), sem exigir login
      prévio.
- [ ] Confirmar que existe um `User` ativo com o email correto já na base
      de dados de staging, com o papel (`UserRole`) correto atribuído.
- [ ] Correr, a partir do servidor de staging:
  ```bash
  python -m app.cli.provision_entra_user \
    --user-email <email-real> \
    --entra-object-id <object-id-do-azure-portal> \
    --actor-email <email-de-quem-executa> \
    --confirm
  ```
- [ ] Confirmar a saída `OK: ...` e o registo em auditoria (`auth_audit_log`,
      evento `admin_provision_link` — consultável diretamente na base de
      dados; sem endpoint de leitura dedicado nesta fase).
- [ ] Repetir para os 5 utilizadores. **Nunca** reutilizar o mesmo
      `entra_object_id` para duas pessoas — o comando recusa-se
      explicitamente, e a coluna tem UNIQUE na base de dados como barreira
      final (D-034).

## 6. Backups e restauração

- [ ] Confirmar que o serviço PostgreSQL de staging tem backups
      automáticos configurados (diários, no mínimo) — mecanismo exato
      depende do alojamento escolhido (`DECISÃO NECESSÁRIA`, ver
      `docs/OPEN_QUESTIONS.md`).
- [ ] Fazer um backup manual completo **antes** de qualquer passo da
      secção 7 (testes) e, sobretudo, antes de `docs/DATA_MIGRATION_RUNBOOK.md`.
- [ ] Testar um restauro completo (não só confirmar que o backup "existe"
      — restaurar para uma base de dados de verificação e confirmar que
      a aplicação arranca e os dados batem certo) pelo menos uma vez antes
      de considerar staging pronto para uso real.

## 7. Testes pós-deployment

- [ ] **`/health`** responde `200`, com `database_dialect` = `postgresql`
      e `app_env` = `staging`.
- [ ] **Teste de login real:** cada um dos 5 utilizadores consegue abrir o
      frontend de staging, clicar "Entrar com Microsoft", autenticar-se
      no tenant real, e ser redirecionado de volta autenticado (sem cair
      no mecanismo de desenvolvimento — que nem aparece, `devLoginEnabled`
      é `false` num build de produção/staging real). `GET /me` devolve o
      `user_id`/`email`/`roles`/`permissions` corretos para cada um.
- [ ] **Teste de permissões por perfil:** para cada papel, confirmar pelo
      menos um caso de acesso permitido e um caso de acesso negado
      (`403`), usando os endpoints já implementados:
  - PM: `GET /api/projects` só devolve os projetos onde é `pm_person_id`
    (`project.view_own`); tentar editar um campo administrativo (ex.
    `client_email`) devolve `403` (`app/security/project_fields.py`).
  - Chefe de Operações/Administrador: `GET /api/projects` devolve todos;
    conseguem editar campos administrativos.
  - Comercial: só leitura (`GET` funciona, qualquer `PATCH` devolve `403`).
  - Financeiro: mesma verificação de só-leitura sobre projetos.
  - Um utilizador sem permissão de migração (`migration.view`) recebe
    `403` em `GET /api/migration/import-batches`.
- [ ] **Teste de auditoria:** depois do teste de login, confirmar que
      nenhuma entrada indevida foi criada em `auth_audit_log` (só deve
      haver as entradas de `admin_provision_link` da secção 5 — o JIT
      linking por email está desligado por omissão em staging, D-029, por
      isso não deve haver `jit_link_by_email` a menos que alguém tenha
      definido `ENTRA_JIT_LINK_BY_EMAIL=true` explicitamente). Editar um
      projeto de teste e confirmar que `project_history` regista o autor,
      o campo, o valor antigo/novo, e a fonte `ui`.
- [ ] **CORS:** confirmar no browser (consola de rede) que um pedido do
      frontend de staging não é bloqueado por CORS, e que uma origem fora
      da lista (`CORS_ALLOWED_ORIGINS`) é recusada (testar com `curl -H
      "Origin: https://outro-dominio.exemplo"` ou equivalente).

## 8. Procedimento de rollback (deste deployment de staging)

- [ ] Se a validação da secção 7 falhar de forma não trivial: reverter o
      deployment do backend/frontend para a versão anterior conhecida-boa
      (nenhuma migração de dados reais foi feita ainda nesta checklist —
      só schema e utilizadores/pessoas reais, ver secção 4/5).
- [ ] Se uma migração Alembic específica for a causa: `python -m alembic
      downgrade -1` (ou para uma revisão nomeada) — testado em CI para
      cada migração (`upgrade` → `downgrade` → `upgrade`), nunca só em
      staging pela primeira vez.
- [ ] Se um utilizador foi provisionado incorretamente (`entra_object_id`
      errado): não há um comando de "desligar" nesta fase (D-034,
      deliberado) — corrigir diretamente na base de dados
      (`UPDATE users SET entra_object_id = NULL WHERE id = ...`) e
      registar a correção manualmente (não há auditoria automática para
      uma correção direta em SQL — anotar em `auth_audit_log` manualmente
      se for prático, ou num registo externo).
- [ ] Restaurar o backup da secção 6 se os dados ficarem num estado
      inconsistente que os passos acima não resolvam.

## 9. Critérios para considerar staging pronto

- [ ] Todas as caixas das secções 1 a 7 marcadas.
- [ ] Nenhum dado real de cliente entrou ainda (isso só acontece em
      `docs/DATA_MIGRATION_RUNBOOK.md`, com aprovação explícita própria).
- [ ] Nenhuma integração externa real ligada (`GRAPH_ENABLED`,
      `CLICKUP_ENABLED`, `FINANCIAL_ENABLED`, `CLAUDE_ENABLED` continuam
      `false`).
- [ ] Backup e restauro testados com sucesso (secção 6).
