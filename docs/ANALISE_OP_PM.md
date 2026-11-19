# Análise de código Op_PM — estado, riscos e caminho para produção

> Data: 2026-11-18 · Âmbito: árvore de trabalho de `/opt/server/apps/Op_PM` (branch `main` + ~318 ficheiros de WIP por commitar, que é o que está publicado na instância Tailscale) e o PR draft `Rabinho2000/Op_PM#33` (Sales Support). Análise **só de leitura**: nenhum ficheiro de código foi alterado.
>
> Método: 3 agentes de mapeamento (backend, frontend, infra/scheduler) + 5 revisores especializados (code-reviewer, silent-failure-hunter, pr-test-analyzer, type-design-analyzer, comment-analyzer) + code-simplifier em modo identificação. Os achados de maior severidade foram re-verificados manualmente no código e contra a instância em execução (só pedidos GET).
>
> ⚠️ O repositório GitHub é **público**. Este documento não contém IDs de tenant, hostnames internos nem caminhos de segredos; manter assim se for commitado.

---

## 1. Resumo executivo

**Nota de maturidade: 6/10** — *código* 7,5/10, *operação/produção* 4/10.

O núcleo da aplicação é **surpreendentemente sólido**: ~139 k linhas, 241 rotas API todas autenticadas (exceto `/` e `/health`), âmbito de projeto aplicado no backend (404 fora de âmbito), validação Entra RS256 correta (iss, aud, scp, tid, oid), segredos cifrados com Fernet que falham fechados, uploads seguros contra path traversal e "magic number" falso, inventário e banco de horas com locks e idempotência, e **1 541 testes backend com 89 % de cobertura** (1 522 passam; 4 falhas são artefactos de execução fora do git, 1 é intermitente) + ~757 testes Vitest.

O que **não** está pronto é tudo o que rodeia o código:

- A instância com **dados reais de clientes corre em modo demo** (`APP_ENV=local`, `DEMO_MODE=true`, SQLite), o que desliga todo o hardening de arranque, ativa a ligação automática por email e volta a correr o seed sintético sobre a BD real a cada `docker compose up`.
- O **envio do relatório semanal ao cliente não funciona de forma fiável**: a janela de disparo é de 1 minuto exato e o loop corre de 5 em 5 minutos; um erro num projeto faz rollback dos envios anteriores (envios duplicados quando o Graph estiver ligado); e o pedido de token ao Graph está mal formado (JSON em vez de form-urlencoded).
- **Não há uma única chamada de logging** no backend. Falhas do scheduler, do Graph, do JWKS e do motor de cabos não deixam rasto.
- A produção corre a partir de **318 ficheiros por commitar**.
- **ClickUp e Kanban de Vendas são 100 % mock**: o adaptador ClickUp tem 50 linhas e nunca é chamado; o Kanban vive só no PR draft #33 como SPA isolada com dados fixos, e os endpoints `/api/sales-support/*` que espera não existem.

Em contagem: **2 Críticos, 10 Altos, 16 Médios, 12 Baixos**.

---

## 2. Arquitetura encontrada

```text
                         Microsoft Entra ID (tenant único)
                     ┌──────────────┴───────────────┐
         Auth Code + PKCE (SPA)            JWKS (RS256) / Graph client-credentials
                     │                              │
┌────────────────────▼─────────┐        ┌───────────▼──────────────────────────────┐
│ frontend (nginx 1.27, root)  │  /api  │ backend (FastAPI + SQLAlchemy 2 + Alembic)│
│ React 18 + Vite + MSAL       │ ─────► │ ~45 routers, 241 rotas, get_auth_context  │
│ Dockerfile.tailscale         │  /me   │ security/: entra_auth, current_user,      │
│ nginx.demo.conf (proxy,      │ /health│   permissions (papéis + âmbito), secret_box│
│   /docs e /openapi.json      │ /docs  │ services/: projects, inventory, time_bank,│
│   também encaminhados)       │        │   imports_notes/licensing, client_reports │
│ 127.0.0.1:18080 → Tailscale  │        │ adapters/: graph_mail (REAL, avariado),   │
│   Serve :8444 (tailnet)      │        │   clickup/claude/financial/graph (MOCK,   │
└──────────────────────────────┘        │   fábrica nunca chamada)                  │
                                        └──────┬──────────────────────┬────────────┘
                                               │                      │
          ┌────────────────────┐               │  mesmo ficheiro      │ /run/cable_tool (ro)
          │ scheduler          │───────────────┤  SQLite              │ motor de cabos privado
          │ cli.client_reports │  loop 300 s   │                      │ (servido ao browser,
          │ loop (sem health-  │               ▼                      │  executado via blob:)
          │ check, sem logs)   │      volume op-pm-tailscale_data
          └────────────────────┘      /app/data: op_pm_demo.db, material_prices.db,
          ┌────────────────────┐                 project_photos/, inventory/, outbox/
          │ demo-setup (one-   │──► alembic upgrade head + run_seed() + seed_demo_data()
          │ shot a cada `up`)  │    (sobre a BD com dados reais!)
          └────────────────────┘
                                       backup: timer de utilizador 4×/dia, só as 2 BDs,
                                       14 dias, mesmo host (fotos/documentos não)

Fora do main:  PR #33 (draft) sales-support/  — SPA Vite isolada, porta 5174,
               mock por omissão; espera GET /api/sales-support/board,
               POST /sync, POST /items/{clickup_task_id}/promote  → não existem.
```

**Fluxos principais**

| Fluxo | Estado | Pontos-chave |
|---|---|---|
| Login Entra | ✅ Real | MSAL `loginRedirect` + PKCE, tokens em `sessionStorage`; backend valida RS256/iss/aud/scp/tid/oid (`security/entra_auth.py:105-141`); utilizador resolvido por `oid`, com ligação "JIT" por email (`security/current_user.py:52-87`). |
| Papéis/permissões | ✅ Backend | 7 papéis (`security/catalog.py:9-25`); tabelas `roles/permissions/role_permissions` são a fonte de verdade; cada handler chama `get_auth_context` + `can_*`. Frontend só esconde menus/rotas. |
| Injeção de projetos | ✅ 4 vias, idempotentes | Manual (`POST /api/projects`, lock + nome único), export legado (`ProjectExternalId` com `uq_external_id_per_source`), notas HTML/JSON (hash SHA-256), Excel de licenciamento (hash + rollback). |
| Sincronização ClickUp | ❌ Mock | Só `clickup_status_mirror` (legado) e `MockClickUpAdapter` (29 linhas, só usado em testes). |
| Kanban de Apoio a Vendas | ❌ Mockup no PR #33 | Frontend isolado com `MOCK_ITEMS`; backend inexistente. O único Kanban no `main` é a vista de Tarefas (dados reais). |
| Relatório semanal ao cliente | ⚠️ Avariado | Scheduler + Graph `sendMail`; ver C2, A1–A5. |

**Variáveis de ambiente relevantes** (`backend/app/config.py`): `APP_ENV` (default `local`), `AUTH_ENABLED` (default `false`), `SECRET_KEY` (default de dev público), `DATABASE_URL` (default SQLite), `ENTRA_*` (tenant, client, audience, required scope, validation mode, JIT), `GRAPH_*` (+ `GRAPH_CLIENT_SECRET_FILE`), `CLICKUP_ENABLED/TOKEN/LIST_ID` (não usados), `FINANCIAL_*`, `CLAUDE_*`, `OPPM_SECRETS_KEY_FILE`, `CABLE_TOOL_FILE`, `PROJECT_PHOTO_DIR`, `INVENTORY_FILE_DIR`, `MAP_*`, `CORS_ALLOWED_ORIGINS`, `DEMO_MODE`, `DEMO_REAL_DATA`. Frontend (build-time): `VITE_API_BASE_URL`, `VITE_ENTRA_*`, `VITE_ENABLE_DEV_LOGIN`, `VITE_REAL_DATA_INSTANCE`.

---

## 3. Achados por severidade

Formato: **ID — título** · `ficheiro:linha` · problema → impacto → correção.

### 🔴 Crítico

**C1 — Instância com dados reais corre em modo demo, sem hardening, e volta a correr o seed sobre a BD real**
- `docker-compose.tailscale.yml:16-45` (serviço `demo-setup`, `APP_ENV: local`, `DEMO_MODE: "true"`, `DEMO_REAL_DATA: "true"`, SQLite); `backend/app/cli/demo.py:69-72`; `backend/app/migration/seed_demo.py:456`; `backend/app/migration/seed_dev.py:148-887`; `backend/app/config.py:130-133, 225-266`. Confirmado no `/health` em execução: `app_env=local`, `demo_mode=true`, `database_dialect=sqlite`.
- **Problema:** com `APP_ENV=local`, a validação de arranque de `_enforce_hardening_in_non_local_envs` não corre. Aceita o `SECRET_KEY` de desenvolvimento e SQLite. A ligação JIT por email fica ligada por omissão, e o login de desenvolvimento só fica bloqueado porque alguém se lembrou de pôr `AUTH_ENABLED=true`. Além disso, `demo-setup` corre `run_seed()` + `seed_demo_data()` em cada `up`. A idempotência depende de existir um projeto-marcador e de cada tabela não estar vazia: qualquer tabela real vazia (ausências, fornecedores, instaladores, metas, eventos, fases) recebe linhas sintéticas.
- **Impacto:** dados sintéticos misturados com dados de clientes. A segurança depende de uma única variável. Uma migração destrutiva corre automaticamente sem backup prévio.
- **Correção:**
  - Criar um perfil `APP_ENV=production` (ou `internal`) para esta instância.
  - Separar `migrate` (só `alembic upgrade head`, precedido de backup) do seed.
  - Remover o `demo-setup` deste compose.
  - Fixar `ENTRA_JIT_LINK_BY_EMAIL=false` depois de ligar todos os utilizadores.
  - Definir um `SECRET_KEY` real.
- **Estado (2026-11-18): preparado, cutover pendente.** `docker-compose.production.example.yml` (genérico) e um compose concreto fora do Git: `APP_ENV=production`, `DEMO_MODE=false`, segredos por ficheiro (`SECRET_KEY_FILE`, `DATABASE_PASSWORD_FILE`), `migrate` à parte (sem seed), PostgreSQL saudável antes do `migrate`. Ensaiado numa cópia; procedimento em `docs/RUNBOOK_CUTOVER_POSTGRES.md`. Falta correr o cutover e decidir a ligação dos utilizadores Entra sem `entra_object_id` (JIT desligado em production).

**C2 — O relatório semanal ao cliente quase nunca dispara e, quando disparar, pode ser enviado em duplicado**
- `backend/app/services/client_report_scheduler.py:32-35` (exige `hora == hh and minuto == mm`); `docker-compose.tailscale.yml:74` (`--interval 300`); `client_report_scheduler.py:39-47` (`db.rollback()` por projeto, `commit` único no fim).
- **Problema:** o loop acorda de 300 em 300 s (mais o tempo de processamento) e só apanha o minuto configurado cerca de 1 vez em cada 5 semanas. Quando o projeto N falha, o `rollback` apaga também as linhas `sent` dos projetos 1…N-1 e as expirações de `expire_pending_reviews`.
- **Impacto:** a maior parte dos relatórios nunca é gerada e nada o mostra. Com o Graph ligado, os emails já saídos ficam sem registo e são reenviados ao cliente.
- **Correção:**
  - Selecionar as configurações com `send_time` desta semana já ultrapassado e sem envio nesta semana ISO.
  - Fazer `commit` ou usar um savepoint por projeto.
  - Testar com um relógio simulado.

### 🟠 Alto

**A1 — Pedido de token ao Graph está mal formado**
- `backend/app/adapters/graph_mail.py:36-47`.
- **Problema:** o pedido envia `json.dumps(...)` com `Content-Type: application/json`, mas o endpoint `/oauth2/v2.0/token` exige `application/x-www-form-urlencoded`. O módulo tem 0 % de cobertura.
- **Impacto:** quando se ligar `GRAPH_ENABLED=true`, todos os envios falham com 400.
- **Correção:** usar `urllib.parse.urlencode(...)` com o cabeçalho de form e escrever testes com transporte falso. Codificar também o `from_email` no URL do `sendMail`.

**A2 — O envio para a pasta local `outbox` é registado como "enviado"**
- `backend/app/services/client_reports.py:600-616` e o badge em `frontend/src/components/ClientReport.tsx:462`.
- **Problema:** com o Graph desligado (o caso atual), grava-se um `.eml` em `/app/data/outbox` e a linha fica `status="sent"`. A nota semanal é limpa e a semana fica bloqueada para novo envio.
- **Impacto:** o PM vê um badge verde e julga que o cliente recebeu o relatório.
- **Correção:** criar o estado `outbox_local`, com um badge de aviso, sem limpar a nota e sem bloquear a semana.

**A3 — O scheduler usa uma identidade arbitrária, morre à primeira exceção e esconde erros**
- `backend/app/cli/client_reports.py:14-18` (o "sistema" é o primeiro utilizador ativo por ordem alfabética de email), `:31-42` (`while True` sem `try`) e `:39` (imprime `processados=N`, com exceções incluídas na contagem); `docker-compose.tailscale.yml:81-82` (healthcheck desativado).
- **Impacto:**
  - Se esse utilizador não tiver `client_report.manage` e `view_all`, todos os envios falham com 403/404 e o registo diz que foram processados.
  - Uma falha de BD provoca um ciclo de reinícios silencioso.
- **Correção:**
  - Criar um utilizador de serviço dedicado, com as permissões verificadas no arranque.
  - Envolver cada iteração em `try/except` com log e backoff.
  - Contar separadamente os envios bem-sucedidos, os que falharam e os ignorados.
  - Adicionar um heartbeat (ficheiro com timestamp) e um healthcheck que o leia.

**A4 — Não há envio idempotente: a corrida entre o scheduler e "Enviar agora" duplica emails**
- `backend/app/services/client_reports.py:646` (`_find_existing_send`: lê e depois insere), `:685-690` (`approve_send` sem lock); `backend/app/models/client_report.py:34` (o índice `project_id, iso_week` não é `UNIQUE`); `backend/app/api/routes_client_reports.py:93-94` (email enviado antes do `commit`).
- **Impacto:** o cliente pode receber o mesmo email externo duas vezes, e não há forma de o desfazer.
- **Correção:**
  - Índice único parcial em `(project_id, iso_week)` para os estados ativos.
  - `UPDATE … WHERE status='pending_review'` com verificação do `rowcount`.
  - Gravar `pending` e fazer `commit` antes de chamar o Graph, e atualizar o estado depois.

**A5 — A importação de notas contorna a allowlist de campos administrativos (D-028/D-035)**
- `backend/app/services/imports_notes.py:1693-1707, 2196-2212` (`setattr(project, …)`); `backend/app/api/routes_imports.py:52` (só exige `import.notes`). Verificado: no catálogo, o papel **Comercial** tem `import.notes` mas não tem `project.edit_all`.
- **Impacto:** um utilizador Comercial pode alterar `client_name`, `client_email`, `address`, `lat/lon`, `power_kwp` e `commercial_assumptions` de qualquer projeto existente, que é precisamente o que a D-035 restringiu.
- **Correção:**
  - Ao aplicar a um projeto existente, exigir `can_edit_project` e limitar os campos a `PM_EDITABLE_PROJECT_FIELDS` quando o utilizador não tem `edit_all`.
  - Para criar um projeto, exigir a mesma permissão que `create_project`.
  - Confirmar com o negócio. Verificar também o que está nas tabelas `role_permissions` reais, que podem diferir do catálogo.

**A6 — Não há logging no backend**
- Em todo o `backend/app` não existe nenhum `import logging` nem `logger`.
- **Impacto:** as falhas do scheduler, do Graph, do JWKS, do motor de cabos e das escritas em disco só aparecem como respostas HTTP ou linhas na BD. Não há diagnóstico possível em produção.
- **Correção:**
  - Usar `logging` estruturado (JSON) com `request_id`, configurado em `main.py` e nas CLIs.
  - Registar `logger.exception` em todos os `except` que convertem um erro numa resposta.
  - Enviar os logs para o `docker logs`, com rotação.

**A7 — Os defaults são inseguros: um deploy mal configurado arranca sem autenticação**
- `backend/app/config.py:28, 46-50, 65-68, 83-87`: `APP_ENV=local`, `AUTH_ENABLED=false`, `SECRET_KEY` público e SQLite por omissão.
- **Impacto:** se `APP_ENV` for omitido ou estiver mal escrito, a API aceita `X-Dev-User-Email` e qualquer pessoa pode fazer-se passar pelo administrador.
- **Correção:** por omissão, `APP_ENV=production`, e exigir `APP_ENV=local` de forma explícita para desenvolvimento. Em alternativa, recusar o arranque quando `APP_ENV` não está definido.
- **Estado (Fase 1, frente A):** ✅ resolvido pela alternativa: `APP_ENV` é obrigatório e a app, o Alembic e as CLIs recusam arrancar sem ele (`ConfigurationError`). Os outros defaults (`AUTH_ENABLED`, `SECRET_KEY`, SQLite) só são aceitáveis em `local`/`test`, que agora têm de ser pedidos de forma explícita.
- **Cutover (frente E):** o compose de produção fixa `APP_ENV=production` de forma explícita; a instância deixa de correr em `local` quando o cutover for feito.

**A8 — Produção em SQLite com dois processos a escrever, e locks que o SQLite ignora**
- `docker-compose.tailscale.yml:31, 51, 74` (o backend e o scheduler usam o mesmo ficheiro); `backend/app/services/safety_sheet.py:125-142` (`with_for_update()` sem efeito em SQLite; o comentário diz o contrário). Os testes de concorrência só correm em PostgreSQL.
- **Impacto:** erros `database is locked`, perda de escrita na primeira gravação da ficha de segurança, e garantias de concorrência validadas num motor que não é o de produção.
- **Correção:** migrar para PostgreSQL (o projeto já suporta e o CI já testa). Até lá, aplicar o padrão de "UPDATE vazio" que o inventário e o banco de horas já usam.
- **Estado (2026-11-18): preparado, cutover pendente.** CLI `app.cli.migrate_sqlite_to_postgres` (esquema por Alembic, cópia em lotes, checksums por tabela, `--dry-run`, deteção de linhas rejeitáveis). Ensaio sobre um backup real: 109 tabelas e 12 943 linhas copiadas em cerca de 2 s, contagens e checksums iguais, sem linhas rejeitadas. A suíte pytest contra PostgreSQL passou (1596 testes, 0 falhas) depois de corrigidos o `FOR UPDATE` com `joinedload` da ficha de segurança (dava 500 em PostgreSQL) e dois testes que só o PostgreSQL apanha. Falta o cutover real.

**A9 — Os backups não cobrem os ficheiros e ficam no mesmo host** — *parcialmente resolvido (Fase 1, 2026-11-18)*
- O script de utilizador do servidor (fora do repo) passou a guardar, por execução, a BD (`sqlite.backup` + `integrity_check`, como antes), um tar.gz com todos os ficheiros do volume (`project_photos/`, `inventory/`, `outbox/` e outros), um manifesto (tabelas/linhas e ficheiros/bytes por diretório) e o `sha256` de cada artefacto. Retenção de 14 dias para tudo, falha com código diferente de zero e marca `LAST_OK`. Há um script de ensaio de restauro (volume descartável + `alembic current` + contagens contra o manifesto) e o runbook em [`BACKUP_RESTORE.md`](BACKUP_RESTORE.md).
- **Em aberto:** continua a não haver cópia fora do servidor (decisão atual: só local) nem cifra dos backups; alerta ativo por falha; variante PostgreSQL do backup quando A8 for executado; ensaio trimestral.
- **Correção (resto):** cópia off-site cifrada e ensaio de restauro trimestral registado.

**A10 — A produção corre a partir de código por commitar**
- `git status` mostra 318 entradas (M e ??), incluindo 17 migrações Alembic novas e 13 routers novos. A branch local `snapshot/op-pm-production-2026-11-09` guarda uma cópia e não foi enviada ao GitHub. Isto está correto, porque contém IDs de tenant e o repo é público.
- **Impacto:** um `git checkout` ou `reset` apaga a produção. Não há revisão, não há CI sobre o que está deployado e não é possível reproduzir o build.
- **Correção:**
  - Partir o WIP em PRs por funcionalidade, já mapeados em `docs/PLANO_*.md`.
  - Pôr `docker-compose.tailscale.yml` em `.gitignore` ou num template sem IDs.
  - Fazer o deploy só a partir de um commit identificado.

### 🟡 Médio

| ID | Onde | Problema → Correção |
|---|---|---|
| M1 | `frontend/docker/nginx.demo.conf`, `backend/app/main.py:55` | `/docs` e `/openapi.json` estão acessíveis sem login no tailnet (confirmado: HTTP 200), o que expõe o mapa completo da API. → Usar `docs_url=None` fora de local, ou deixar de os encaminhar no nginx. |
| M2 | `frontend/docker/nginx*.conf`, `frontend/Dockerfile*` | Não há CSP, HSTS, X-Frame-Options nem `nosniff`, e falta `server_tokens off` (o nginx anuncia a versão 1.27.5). O nginx corre como root. O motor de cabos é executado através de um `<script src=blob:>` com acesso a toda a página, incluindo os tokens MSAL em `sessionStorage`. → Acrescentar os cabeçalhos, usar `nginxinc/nginx-unprivileged` e uma CSP com `blob:` restrito. Em alternativa, correr o motor num Web Worker ou num iframe isolado. **✅ Resolvido na Fase 2 (frente C, branch `fase2/cabos-csp`, sem push):** o motor corre num iframe `sandbox="allow-scripts"` sem `allow-same-origin` (`public/cable-engine-frame.html/.js`): origem opaca, sem `sessionStorage`/tokens MSAL nem DOM da página, com CSP própria (sem rede, `unsafe-eval` só ali). Um Web Worker foi tentado primeiro mas o motor real precisa de `Image`/`canvas`/`DOMParser` nas exportações. Protocolo de mensagens tipado e validado nos dois lados e fachada assíncrona na UI. CSP estrita no nginx (`script-src 'self'`, `connect-src` só a própria origem + Entra, `img-src` com os tiles do OpenStreetMap, `frame-ancestors 'none'`…; `style-src` mantém `'unsafe-inline'`, só estilos). nginx sem root (utilizador `nginx`, imagem oficial fixada por digest 1.30.7; a `nginx-unprivileged` estava atrás, em 1.30.6). Verificado num Chromium contra o build servido pelo nginx, com o motor real: cálculo, edição, separadores e todas as exportações (PDF, DOCX, DXF, SVG, PNG, orçamento, copiar tabela) funcionam. |
| M3 | `backend/app/security/entra_auth.py:122,138`; `current_user.py:109-117` | Uma falha de JWKS ou de rede chega ao utilizador como 401 "token inválido". O frontend mostra então "sessão expirada". O `PyJWKClient` não tem timeout. → Devolver 503 com log e definir um timeout explícito. **✅ Backend resolvido na Fase 1 (frente A):** timeout de 5 s no `PyJWKClient`, falha de ligação ou JWKS inutilizável → 503 com `logger.warning`; tokens inválidos continuam 401. O frontend não trata o 503 como sessão expirada. |
| M4 | `frontend/src/pages/ProjectDetail.tsx:790,793`; `CableDesignEditor.tsx:311,314-315,352-353`; `Vacations.tsx:328-332`; `InstallerAccessPages.tsx:120` | `.catch(() => [])`: um erro de rede ou um 403 aparece como "sem histórico", "sem tarefas", "sem revisões" ou "ninguém ausente". → Mostrar um estado de erro por secção, com botão para tentar de novo. |
| M5 | `backend/app/schemas/projects.py:119-135` | `ProjectUpdate` não tem os limites de `ProjectCreate` (lat/lon, `power_kwp`, `max_length`) e aceita `{"name": null}`, o que dá um 500 por violação de NOT NULL. → Usar tipos `Annotated` partilhados e rejeitar `None` nos campos obrigatórios. |
| M6 | `frontend/src/session/installerAccess.ts:17`; `components/Layout.tsx:57,60`; `backend/app/security/permissions.py:163` | Há drift de permissões: `inventory.manage`, `process.view_own`, `process.update_own` e o papel `admin` não existem no catálogo. Como as permissões são strings livres (`AuthContext.require(code: str)`, cerca de 185 chamadas), um erro de escrita nega o acesso em silêncio. → Criar `Perm(StrEnum)`, gerar o tipo TypeScript e escrever um teste que confirme que cada literal existe no catálogo. |
| M7 | `backend/app/models/project.py:109`; `models/inventory.py:240-311`; `models/time_bank.py:18-57` | Os vocabulários fechados (`lifecycle_status`, `movement_type`, `MaterialRequest.status`, `calculation_mode`, `kind`) e as quantidades não têm CHECK na BD. Como o stock é derivado por somas, uma linha inválida corrompe os saldos. → Uma migração com CHECKs gerados a partir das constantes Python; o modelo a seguir é `UserRequest`. |
| M8 | `backend/app/models/identity.py:65` | `User.email` é único mas distingue maiúsculas, enquanto a autenticação compara com `lower(email)`. `A@x` e `a@x` bloqueiam a ligação JIT sem dar erro. → Índice único em `lower(email)` e normalizar o email ao gravar. |
| M9 | `.github/workflows/ci.yml` | Não há ruff, mypy, `pip-audit`, `npm audit`, gitleaks, Trivy, Dependabot nem limiar de cobertura. Usa `npm install` em vez de `npm ci`. Não constrói o `Dockerfile.tailscale`, que é o que está em produção. As actions não estão fixadas por SHA e falta `permissions:`. | **Resolvido na Fase 1 (frente C, branch `fase1/ci-supply-chain`, sem push):** `permissions: contents: read`, `concurrency` por ref, actions fixadas por SHA, `npm ci`, build do `Dockerfile.tailscale`, ruff e mypy gradual (bloqueantes), limiar de cobertura de 85 % (medido: 89 %), `pip-audit`, `npm audit`, gitleaks (bloqueantes) e Trivy (informativo: 70 achados HIGH/CRITICAL corrigíveis no `nginx:1.27-alpine`), `actionlint` e Dependabot semanal.
| M10 | `backend/requirements.txt`; `backend/Dockerfile`; `frontend/Dockerfile*` | As dependências são intervalos sem lockfile e as imagens base são tags sem digest, por isso o build não é reproduzível. → Gerar um lock com `pip-compile`/`uv` e fixar as imagens por digest, com Dependabot. | **Resolvido na Fase 1 (frente C):** lock com hashes (`uv pip compile --generate-hashes`, Python 3.12) para `requirements.txt`, `requirements-postgres.txt` e `requirements-dev.txt`, instalado com `--require-hashes` no Dockerfile e no CI; imagens base dos quatro Dockerfiles fixadas por digest; Dependabot para pip, npm, docker e github-actions. O `nginx` subiu de 1.27 (sem correções) para `stable-alpine` 1.30.7, fixado por digest.
| M11 | `backend/app/adapters/__init__.py:1-13, 27-60`; `README.md:57-61, 310-324`; `backend/app/main.py:56-63`; `docs/API_CLIENT_REPORTS.md:3-5` | A documentação diz que "não há nenhuma integração real", mas o `graph_mail.py` é real e é chamado diretamente. As fábricas `get_*_adapter` são código morto e lançam `NotImplementedError` se alguém ligar `CLICKUP_ENABLED`. → Atualizar os textos e remover ou ligar a fábrica. |
| M12 | `backend/.env.example:48-52`; `.env.staging.example:72-76` | Documentam `GRAPH_CLIENT_SECRET`, mas o código lê `GRAPH_CLIENT_SECRET_FILE`. Faltam `OPPM_SECRETS_KEY_FILE`, `CABLE_TOOL_FILE`, `PROJECT_PHOTO_DIR` e `INVENTORY_FILE_DIR` nos exemplos e nos runbooks. |
| M13 | `backend/app/security/entra_auth.py:148-185` | A chave privada RSA de teste está no código da aplicação, e qualquer pessoa a pode ler (repo público). Se alguém ligar `ENTRA_VALIDATION_MODE=mock` em local, é possível forjar tokens. A config bloqueia isto fora de local/test. → Mover a chave para `tests/`. |
| M14 | `docker-compose.yml:19-22` | O Postgres de desenvolvimento fica publicado em `0.0.0.0:5432` com a password por omissão. → Usar `127.0.0.1:5432:5432`. |
| M15 | `backend/app/services/imports_licensing.py` (2 510 linhas), `imports_notes.py` (2 255), `frontend/src/api/client.ts` (2 907), `ProjectDetail.tsx` (1 550, 38 `useState`), `Inventory.tsx` (1 538, 61 `useState`), `ProjectLicensingPanel.tsx` (1 820) | Ficheiros grandes demais para rever com segurança. Ver a secção 5 (simplificação). |
| M16 | `frontend/src/App.tsx:181, 197-240` | A maioria das rotas usa só `StaffOnly`, que exclui instaladores mas não verifica permissões. `/projects/deleted` nem isso tem. O backend protege os dados, mas a UI pode mostrar ecrãs que depois só devolvem 403. → Guards por permissão, ou flags `can_*` calculadas pelo servidor. |

### 🟢 Baixo

| ID | Onde | Problema |
|---|---|---|
| B1 | `backend/app/api/routes_time_bank.py:356` | `year` com valor por omissão fixo em `2026`. A partir de 2027, os pedidos sem `year` devolvem dados errados. |
| B2 | `backend/app/services/user_requests.py:287` | Quando o autor responde, o pedido reabre sem verificar o limite `MAX_OPEN_REQUESTS_PER_AUTHOR`. |
| B3 | `backend/app/api/routes_health.py:26` vs `config.py:56-57` | `demo_real_data` é exposto sempre, ao contrário do que diz o comentário. Além disso, `/health` (sem auth) revela o ambiente, o motor da BD e as flags. |
| B4 | `backend/tests/test_import_licensing_sim.py` | Teste intermitente: o PIN fictício `7733` colide por acaso com o conteúdo cifrado (falhou 1 vez em 3). |
| B5 | `backend/tests/test_auth_entra.py:53` | "Assinatura inválida" usa HS256, por isso o teste falha pela lista de algoritmos e não pela verificação da assinatura. |
| B6 | `frontend/src/pages/cableBridge.ts:218` | `postMessage(..., "*")` numa ponte com iframe que não parece ser usada. Confirmar e remover se não for. **✅ Fase 2:** confirmado (só o próprio teste a importava); `cableBridge.ts` e o teste foram removidos. |
| B7 | `frontend/src/api/client.ts:168,176` | `fetch` sem timeout ou `AbortController`. |
| B8 | `.gitignore` | Faltam `*.key`, `*.pem`, `*.p12`, `*.pfx` e `secrets/`. |
| B9 | `backend/app/api/routes_inventory_visual.py:256-261` | O resumo ignora sem aviso os itens com categoria desconhecida, por isso o stock fica subavaliado. |
| B10 | `backend/app/api/routes_cable_tool.py:91-130` | Todas as falhas do motor dão o mesmo 503, sem log. Um manifesto inválido passa em silêncio para a versão baseada no hash. |
| B11 | `backend/app/models/project_payments.py:247-251` | O CHECK duplica o tuplo `PAYMENT_MILESTONES` à mão. `marked_at` guarda a "última alteração" e não a data de receção, e as alterações não ficam em histórico. |
| B12 | `README.md:56-57, 138-139, 247-248`; `docker-compose.yml:7-12` | Contagens de testes desatualizadas (719/238, quando são agora 1 541/~757), caminho de Windows no exemplo e nada sobre a instância Tailscale nem o scheduler. |

### Mock vs. real — o que falta para substituir

| Componente | Hoje | Para ficar real |
|---|---|---|
| **ClickUp** | `adapters/clickup/mock.py` (29 linhas), nunca chamado; `CLICKUP_TOKEN/LIST_ID` lidos mas não usados | 1. Cliente HTTP com token lido de ficheiro (não de variável de ambiente), timeout e retry com backoff exponencial sobre 429, respeitando os cabeçalhos `X-RateLimit-*` (a API do ClickUp limita por token e por minuto). 2. Mapeamento por **IDs de custom fields**, não por nomes. 3. Webhook para mudanças de estado + reconciliação periódica (job idempotente, com lock). 4. Testes com transporte falso. |
| **Kanban de Apoio a Vendas** | PR draft #33: SPA separada (`sales-support/`, porta 5174), `MOCK_ITEMS` em `src/api.ts`, `VITE_USE_MOCK` ligado por omissão | 1. Backend `services/sales_support.py` + `routes_sales_support.py`: `GET /board` (lê o ClickUp e cruza com `ProjectExternalId`), `POST /sync`, `POST /items/{id}/promote`. 2. Nova permissão `sales_support.promote` (migração Alembic, papéis Comercial e Chefe de Operações). 3. A promoção fica numa única transação: verificar que a task existe no ClickUp → `uq_external_id_per_source` impede duplicados (tratar `IntegrityError` como 409) → `Project` + `ProjectExternalId` + `ProjectHistory(source='clickup')`. 4. Integrar a SPA como rota de `frontend/src` (reaproveita MSAL, `client.ts` e o design system) em vez de uma app separada. |
| **Microsoft Graph (email)** | `graph_mail.py` real mas avariado (A1); o fallback para a pasta `outbox` aparece como "enviado" (A2) | Corrigir A1–A4, registar a app com `Mail.Send` limitada por *Application Access Policy* à caixa de envio, guardar o segredo em ficheiro (ou usar certificado), e escrever testes com transporte falso. |
| **Claude / Financeiro** | Mocks, fábrica nunca chamada | Fora do âmbito atual. Remover ou marcar como "Fase 0" para não confundir. |
| **Entra** | ✅ Real | Desligar o JIT, testar o validador real (ver secção 4) e devolver 503 em falhas do JWKS. |

---

## 4. Lacunas de testes

**Números:**
- Backend: 122 ficheiros, 1 541 testes e 89 % de cobertura de `app/`. 1 522 passam e 14 são ignorados (concorrência só em PostgreSQL). Das 5 falhas, 4 vêm de os testes terem corrido fora do git e 1 é o teste intermitente B4.
- Frontend: 93 ficheiros e cerca de 757 casos. Não foram corridos, porque o `npm install` escreveria no repositório.

| Crit. | Área | Cobertura | Teste em falta |
|---|---|---|---|
| 9 | Scheduler (`client_report_scheduler.py`, `cli/client_reports.py`) | 58 % / **0 %** | Um ciclo de 300 s não pode saltar a hora configurada. Uma falha a meio do ciclo não reverte os envios anteriores. Correr `run_due` em paralelo não deve gerar dois envios. Testar o contexto de sistema com as permissões certas e o comportamento do loop perante exceções. |
| 8 | `adapters/graph_mail.py` | **0 %** | Formato do pedido de token (form-urlencoded). Resposta sem `access_token`. Erros 4xx e 5xx devem dar `failed` e manter a nota. Segredo em falta. |
| 8 | `RealEntraTokenValidator` | ✅ Testado na Fase 1 (`tests/test_auth_entra_real_validator.py`) com um `PyJWKClient` falso, incluindo `alg: none`, HS256 com a chave pública, `tid` de outro tenant e JWKS indisponível (503) | Token RS256 assinado com outra chave. Token com `alg: none`. `kid` desconhecido. JWKS indisponível. Token mock rejeitado em modo real. `exp` ou `iat` em falta. |
| 7 | Autenticação em todas as rotas | ✅ `tests/test_routes_require_auth.py` (Fase 1). Falta a matriz papel × rota | Percorrer `app.routes`, exigir `get_current_user` na árvore de dependências (allowlist: `/` e `/health`) e confirmar que um GET sem cabeçalho recebe 401. Montar uma matriz papel × rota. `routes_installer_access.py` não tem nenhum teste de 403/404. |
| 7 | Modelos vs. migrações | ✅ `tests/test_alembic_schema.py` (Fase 1; head único + drift). `conftest` continua a usar `create_all` | Correr `alembic upgrade head` numa BD vazia e depois `compare_metadata`. Verificar que há um só head (hoje é `a6c8e0f2d4b1`). |
| 7 | Importação de notas vs. allowlist (A5) | Sem teste | Um Comercial aplica notas a um projeto existente: deve dar 403, ou os campos administrativos devem ser ignorados. |
| 6 | Banco de horas em SQLite | Concorrência só testada em PostgreSQL | Duas threads a gravar para a mesma pessoa: o saldo final tem de ficar consistente. Isto importa porque a produção é SQLite. |
| 6 | `secret_box` | ✅ `tests/test_secret_box.py` (Fase 1): chave mal formada e chave errada; a rotação de chave não existe, só está testado que a troca dá erro tratado | Chave mal formada. Dados cifrados com outra chave. Rotação de chave. |
| 5 | Frontend: MSAL e sessão | Só `client.dev-login.test.ts` | `acquireTokenSilent` → `InteractionRequiredAuthError` → redirecionamento. Um 401 limpa a sessão. Testes de `SessionContext` e `Login`. |
| 4 | ClickUp / Sales Support | Mock testado | Quando o adaptador for real: rate limit (429), idempotência da promoção e erro de custom field em falta. |

O CI corre o pytest em SQLite e em PostgreSQL 16, e no frontend `tsc`, `vitest` e o build. Faz também o build das imagens e um smoke test da demo. Não tem limiar de cobertura nem verificação de drift entre modelos e migrações, e não constrói o `Dockerfile.tailscale`.

---

## 5. Simplificação (só identificado, nada aplicado)

| # | O quê | Onde | Esforço |
|---|---|---|---|
| 1 | Uma dependência `get_visible_project_or_404` em vez de 7 versões de "projeto + 404" com regras ligeiramente diferentes | `routes_project_data.py:56`, `routes_safety_sheet.py:65`, `routes_project_credentials.py:55`, `routes_project_sim_cards.py:50`, `routes_project_surplus.py:37`, `routes_inventory.py:197`, `routes_project_photos.py:31` | S |
| 2 | `@app.exception_handler(PermissionDenied)` e `require_permission("x")` como dependência, eliminando 31 blocos `try/except → 403` e ~20 funções `_require_*` | 11 routers | S |
| 3 | Remover a fábrica de adaptadores morta e os mocks Claude/Financial/Graph (cerca de 500 linhas) | `backend/app/adapters/` | S |
| 4 | Uma só função `errorMessage(err, fallback)` em vez de 17 cópias | `frontend/src/pages/*`, `components/*` | S · **✅ Fase 2:** as 14 funções locais e ~60 expressões em linha usam `errorMessage` (e `errorDetail` em `utils/errors.ts` para a variante que também aproveita o `Error` genérico); ficam só as variantes com lógica própria (503 da cifra, 403/404 dos cabos), que delegam o resto |
| 5 | Um hook `useAuthenticatedBlob`, para evitar fugas de object URLs | `InventoryVisuals.tsx:55,195`, `ProjectPrimaryPhoto.tsx:55`, `InventoryItemDocuments.tsx:142` | S · **✅ Fase 2:** `useAuthenticatedBlob` e `useObjectUrl` (`utils/useAuthenticatedBlob.ts`, com testes: revoga no unmount e ao mudar de dependências, descarta respostas tardias) nos três componentes de imagem; o download de documentos já revogava o URL e ficou como estava |
| 6 | Juntar os utilitários de datas, pesquisa e números duplicados | `Planning.tsx:45,64`, `inventorySearch.ts:23`, `worksTimeline.ts:306`, `ClientReport(s).tsx` | S · **✅ Fase 2:** `utils/text.ts` (`normalizeSearchText`), `utils/dates.ts` (`formatDatePt`, `formatLisbonDateTime`) e `utils/numbers.ts` (`formatNumberPt`), com testes |
| 7 | Normalização de texto (`unicodedata` + lower) repetida em 7 módulos | `utils/text.py` como única fonte | S |
| 8 | Dividir `imports_licensing.py` (workbook vs. SIM) e `imports_notes.py` (sanitização vs. validação vs. aplicação) | backend/services | M |
| 9 | Dividir `api/client.ts` por domínio e unificar `requestHtml`/`getProjectPhotoBlob` com `handleResponse` | `frontend/src/api/client.ts:141,438,1380,2297` | M |
| 10 | O servidor envia flags `can_*` por projeto e o frontend deixa de recalcular permissões | `ProjectDetail.tsx:718-723` | M |
| 11 | Partir os componentes gigantes, começando por `ProjectInventoryTab` e `EditProjectModal` | `ProjectDetail.tsx`, `Inventory.tsx`, `ProjectLicensingPanel.tsx` | L (incremental) |
| 12 | Juntar `taskListConfig` e `projectListConfig` (estrutura gémea) | `frontend/src/utils/` | S · **✅ Fase 2:** `utils/listConfig.ts` (colunas, guardas, comparação natural, ordenação estável) partilhado; cada ficheiro fica só com o seu domínio |
| 13 | Um só Dockerfile de frontend com `ARG NGINX_CONF` e um compose base partilhado | `frontend/Dockerfile*`, `docker-compose.*.yml` | S · **◐ Fase 2:** `frontend/Dockerfile` único com `ARG NGINX_CONF` (`docker/nginx.conf` estático por omissão; `docker/nginx.proxy.conf`, antiga `nginx.demo.conf`, para demonstração e produção Tailscale); `Dockerfile.demo` e `Dockerfile.tailscale` removidos; composes versionados e CI ajustados. **Falta:** o compose base partilhado (`docker-compose.*.yml` continuam separados) e ajustar o compose de produção não versionado |
| 14 | Mover ~900 linhas de `.inventory-page` de `app.css` para `Inventory.css` e passar 167 cores hex para tokens | `frontend/src/styles/app.css:3616-4530` | M |

---

## 6. Roadmap priorizado

### Fase 0 — Quick wins (≈ 1 semana, 1 pessoa)

| # | Ação | Resolve | Esforço |
|---|---|---|---|
| 1 | Commitar o WIP em PRs por funcionalidade e passar a fazer o deploy só a partir de um commit identificado | A10 | 1–2 d |
| 2 | Corrigir a janela do scheduler (`send_time <=` agora + semana ISO) e fazer commit ou savepoint por projeto | C2 | 0,5 d |
| 3 | Utilizador de serviço do scheduler, `try/except` com log por iteração e heartbeat com healthcheck | A3 | 0,5 d |
| 4 | Estado `outbox_local` em vez de `sent` | A2 | 0,5 d |
| 5 | Token do Graph em form-urlencoded, mais testes com transporte falso | A1 | 0,5 d |
| 6 | Índice único parcial e `UPDATE` condicional nos envios | A4 | 0,5 d |
| 7 | Importação de notas: exigir `can_edit_project` e a allowlist de campos | A5 | 0,5 d |
| 8 | Esconder `/docs` e `/openapi.json` fora de local; cabeçalhos de segurança no nginx; `server_tokens off` | M1, M2 (parcial) | 0,5 d |
| 9 | `logging` estruturado mínimo (`main.py`, CLIs, `except`s críticos) | A6 | 1 d |
| 10 | Pequenos: B1, B3, B4, B5, B8, M12, M14 | — | 0,5 d |

**Estado da Fase 0 (2026-11-18, branch `fix/fase0-quick-wins`, ainda sem deploy):**

| # | Estado | Notas |
|---|---|---|
| 1 | ◐ Parcial | WIP consolidado num commit local (`chore/consolidate-published-wip-3`), sem push. Partir em PRs por funcionalidade fica para decisão. |
| 2 | ✅ | `due_configs`: a janela vai do dia/hora configurados até 48 h depois, uma vez por semana ISO. `run_due` faz commit por projeto. |
| 3 | ✅ | `CLIENT_REPORT_SCHEDULER_EMAIL` (ou o primeiro utilizador com `client_report.manage` e âmbito global); loop que não morre; heartbeat + `client_reports health`. |
| 4 | ✅ | Estado `outbox_local`: badge de aviso, a nota semanal mantém-se, não conta como entrega. |
| 5 | ✅ | Token em form-urlencoded, erro com o código AADSTS/Graph (sem o segredo), `from_email` codificado, testes com transporte falso. |
| 6 | ✅ | Migração `b9e1d3f5a7c2`: índice único parcial; `pending` gravado antes do envio; aprovação atómica. |
| 7 | ✅ | Num projeto existente: `can_edit_project`, a allowlist D-035 e as permissões de instalação/licenciamento → 403. Criar um projeto novo continua a exigir só `import.notes`. |
| 8 | ✅ | `API_DOCS_ENABLED` (fechado com `DEMO_REAL_DATA=true`); cabeçalhos de segurança e `server_tokens off` no nginx (sem CSP por enquanto). |
| 9 | ✅ | `app/logging_setup.py` (`LOG_LEVEL`), log no envio, no scheduler, na rejeição de tokens e no motor de cabos. |
| 10 | ✅ | B1, B4, B5, B8, M12, M14. B3: afinal a exposição é intencional (o frontend usa a flag para o aviso de dados reais, há um teste que o garante); foi o comentário em `config.py` que se corrigiu. Extra: `client_max_body_size 26m` em `/api/` no `nginx.demo.conf` (os documentos de inventário até 25 MB davam 413). |

**Deploy (2026-11-18):** a Fase 0 está em produção na instância Tailscale.
- Fez-se backup da BD e dos ficheiros antes do deploy. A migração `b9e1d3f5a7c2` foi aplicada e nenhum dado mudou (as contagens de todas as tabelas são iguais às de antes).
- O `demo-setup` voltou a rebentar no seed (C1) e deixou a instância em baixo cerca de 1 minuto. Foi substituído por um serviço `migrate`, que só corre `alembic upgrade head`. O C1 fica assim resolvido em parte: falta passar a instância a `APP_ENV=production`, a PostgreSQL e a um `SECRET_KEY` real.
- O scheduler tem agora healthcheck. `CLIENT_REPORT_SCHEDULER_EMAIL` ainda não está definido, por isso o scheduler usa o primeiro administrador elegível e regista um aviso.

### Fase 1 — Endurecer a instância real (≈ 2 semanas)

| # | Ação | Resolve | Esforço |
|---|---|---|---|
| 11 | Novo compose de produção: `APP_ENV=production`, sem `demo-setup`, `migrate` separado com backup prévio, `SECRET_KEY` real, JIT desligado (preparado, cutover pendente) | C1, A7 | 2 d |
| 12 | Migrar de SQLite para PostgreSQL (o caminho de migração já existe), com ensaio em staging (preparado, cutover pendente) | A8 | 3–4 d |
| 13 | Backups: incluir fotos, documentos e outbox; cópia off-site cifrada; ensaio de restauro; runbook | A9 | 1–2 d (fotos/documentos/outbox, ensaio e runbook feitos; falta off-site) |
| 14 | Defaults fail-closed (`APP_ENV=production` por omissão) | A7 | 0,5 d |
| 15 | Testes: autenticação em todas as rotas, validador Entra real, drift entre migrações e modelos, scheduler | Secção 4 | 2–3 d |
| 16 | CI: ruff, mypy (gradual), `pip-audit`/`npm audit`, gitleaks, Trivy, Dependabot, `npm ci`, build do Dockerfile de produção, `permissions:` | M9, M10 | 1–2 d |
| 17 | JWKS: 503 com log e timeout; estados de erro no frontend em vez de listas vazias (**frontend feito** no branch `fase1/frontend-error-states`, ainda sem deploy: M4 resolvido; falta a parte do JWKS, M3) | M3, M4 | 1–2 d |

**Estado da Fase 1 — frente A, backend (2026-11-18, branch `fase1/backend-hardening`, sem deploy):**

| # | Estado | Notas |
|---|---|---|
| 14 | ✅ | Escolhida a alternativa "recusar o arranque": `APP_ENV` sem valor por omissão. Em `main`/`alembic`/CLIs sem `APP_ENV` há uma `ConfigurationError` com mensagem clara. O CI tem de definir `APP_ENV` nos passos do Alembic. |
| 15 | ◐ Parcial | Feitos: autenticação em todas as rotas, validador Entra real, drift migrações/modelos (corrigidos 3 índices em falta no modelo) e `secret_box`. Falta o scheduler. |
| 17 | ◐ Parcial | Backend feito (503 + log + timeout). Faltam os estados de erro no frontend (M4). |

**Deploy da Fase 1 (2026-11-18, branch `fase1/integracao`, frentes A a E integradas):**
- **Testes antes do deploy:**
  - SQLite: 1 629 passaram, 23 foram ignorados, cobertura acima de 85 %.
  - PostgreSQL: 1 649 passaram, 3 foram ignorados.
  - Frontend: `tsc` sem erros e 825 testes Vitest a passar.
  - ruff e mypy sem erros.
- **Cutover para PostgreSQL e `APP_ENV=production`:**
  - Indisponibilidade de cerca de 1 minuto.
  - A cópia teve contagens e checksums iguais nas 109 tabelas (13 163 linhas), sem nenhuma linha rejeitada.
  - Testes de fumo: `/health` em `production`/`postgresql`, 401 sem token, `/docs` em 404, 307 projetos e 11 utilizadores.
  - O SQLite ficou parado no volume e serve de rollback.
- **nginx:** passou para `stable-alpine` 1.30.7.
- **Backup:** passou a `pg_dump -Fc`; o restauro foi ensaiado num PostgreSQL descartável e as contagens bateram certo.
- **Pendentes:**
  - `ENTRA_JIT_LINK_BY_EMAIL=true` é temporário; retirar quando os 4 utilizadores ativos sem `entra_object_id` tiverem entrado uma vez.
  - O script de ensaio de restauro (`op_pm_restore_drill.sh`) ainda é para SQLite e tem de ser adaptado ao `pg_dump`.
  - Falta o off-site.
  - Alinhar os `server_default` entre modelos e migrações.

### Fase 2 — Trabalho estrutural (≈ 3–5 semanas)

| # | Ação | Resolve | Esforço |
|---|---|---|---|
| 18 | Integração ClickUp real + Kanban de Vendas integrado no frontend + promoção transacional | Mock vs. real | 2–3 sem |
| 19 | `Perm(StrEnum)`, tipos TypeScript gerados a partir do OpenAPI (`openapi-typescript`), `Literal` nos schemas `*Read` | M6, tipos | 3–4 d |
| 20 | CHECKs na BD para os vocabulários e as quantidades; `lower(email)` único; `ProjectUpdate` com os mesmos limites de `ProjectCreate` | M5, M7, M8 | 2–3 d |
| 21 | Motor de cabos isolado (Web Worker ou iframe sandbox) + CSP estrita | M2 | 2–3 d · **✅ Fase 2** (iframe sandbox + CSP; ver M2) |
| 22 | Simplificações S (secção 5, #1–7, #12–13) | M15 | 3–4 d |
| 23 | Divisões M e L (imports, `client.ts`, componentes gigantes), de forma incremental | M15 | contínuo |

---

## 7. Checklist "pronto para produção"

**Segurança e autenticação**
- [x] Todas as rotas `/api` exigem token (241/241, verificado)
- [x] Validação Entra RS256 com iss/aud/scp/tid/oid
- [x] Âmbito de projeto aplicado no backend (404 fora de âmbito)
- [x] Segredos de projeto cifrados (Fernet), falha fechada, revelação auditada
- [x] Uploads validados pelo conteúdo, sem path traversal
- [ ] Instância real em `APP_ENV=production` com o hardening ativo (C1)
- [x] Defaults fail-closed (A7): `APP_ENV` obrigatório
- [ ] JIT por email desligado depois de ligar todos os utilizadores (C1)
- [ ] Importação de notas respeita a allowlist de campos (A5)
- [ ] `/docs` e `/openapi.json` fechados; CSP, HSTS e cabeçalhos de segurança; nginx sem root (M1, M2)
- [ ] Chave de teste fora do código da aplicação (M13)
- [x] Teste automático "todas as rotas exigem auth" e testes do validador real

**Dados**
- [ ] PostgreSQL em produção (A8)
- [ ] Migrações separadas do seed, com backup prévio automático (C1)
- [ ] Backups com fotos e documentos, restauro ensaiado e runbook (feitos); off-site cifrado (falta) (A9)
- [ ] CHECKs na BD para vocabulários e quantidades; e-mail único sem distinção de maiúsculas (M7, M8)
- [x] Cadeia Alembic linear, com um só head

**Operação**
- [ ] Deploy a partir de um commit identificado, sem WIP (A10)
- [ ] Logging estruturado no backend e nas CLIs (A6)
- [ ] Healthcheck/heartbeat do scheduler (A3)
- [x] Healthcheck do backend e `restart: unless-stopped`
- [x] Frontend publicado só em 127.0.0.1, sem portas do backend expostas
- [x] Imagens fixadas por digest e dependências com lock (M10)
- [ ] Alertas para falhas de envio e do scheduler

**Integrações**
- [ ] Scheduler de relatórios fiável e idempotente (C2, A3, A4)
- [ ] Graph `sendMail` funcional e testado (A1), com o outbox claramente distinguido (A2)
- [ ] ClickUp real com rate limit, retries e webhook + reconciliação
- [ ] Kanban de Vendas ligado ao backend, com promoção transacional e idempotente

**Qualidade e CI**
- [x] Pytest em SQLite + PostgreSQL; vitest; tsc; build; smoke test da demo
- [x] Lint e typecheck do backend (ruff, mypy gradual), auditoria de dependências (pip-audit, npm audit), scan de segredos (gitleaks) e de imagens (Trivy, ainda só informativo)
- [x] Limiar de cobertura (85 %)
- [x] Teste de drift entre modelos e migrações (só tipos e nulidade; os `server_default` ficam por alinhar)
- [ ] Teste intermitente B4 corrigido

**Documentação**
- [ ] README e docs alinhados com o Graph real, o scheduler e a instância Tailscale (M11, B12)
- [ ] `.env.example` com `GRAPH_CLIENT_SECRET_FILE`, `OPPM_SECRETS_KEY_FILE`, `CABLE_TOOL_FILE`, etc. (M12)
- [ ] `CLAUDE.md` no repositório (ver anexo A)

---

## Anexo A — Auditoria do CLAUDE.md (skill claude-md-improver)

**Ficheiros encontrados:** nenhum no repositório. O único em vigor é o `CLAUDE.md` do servidor, um nível acima, que fala do servidor e não do projeto. **Nota: F (0/100)** para o projeto. O README (24 kB) e o `docs/DECISIONS.md` têm a informação, mas são longos demais para servirem de contexto.

**Proposta** (`/opt/server/apps/Op_PM/CLAUDE.md`, a criar depois de aprovado):

```markdown
# Op_PM

Repositório PÚBLICO: nunca commitar dados reais, IDs de tenant, hostnames internos, .env, chaves ou o docker-compose.tailscale.yml.

## Comandos
- Backend: `cd backend && python -m pytest -q` · migrações: `python -m alembic upgrade head` · um teste: `python -m pytest tests/test_x.py -k nome`
- Frontend: `cd frontend && npm ci && npm test && npm run lint && npm run build`
- Demo (dados sintéticos): `docker compose -f docker-compose.demo.yml up --build`

## Arquitetura
- backend/app: api/routes_* (cada handler: `Depends(get_auth_context)` + `can_*`/`ctx.require`), services/, models/, schemas/, security/ (entra_auth, permissions, catalog, secret_box)
- frontend/src: api/client.ts (cliente único), pages/, components/, auth/msal.ts, session/
- Decisões numeradas em docs/DECISIONS.md (D-xxx): citar o número nos commits.

## Regras não óbvias
- Autorização é sempre no backend; o frontend só esconde UI.
- Campos de projeto editáveis por PM: security/project_fields.py (D-028/D-035).
- Nova permissão = migração Alembic + catalog.py + teste de migração.
- Locks em SQLite usam o padrão "UPDATE vazio" (ver services/inventory.py), não só with_for_update.
- Vocabulários fechados: seguir models/user_requests.py (CHECK na BD + Literal no schema + union em TS).
- Testes de CLI que verificam "ficheiro rastreado pelo git" falham fora de um checkout.

## Instância interna (Tailscale)
- Compose: docker-compose.tailscale.yml (não versionado). Dados reais em SQLite no volume op-pm-tailscale_data.
- Não fazer `up` sem backup prévio: o serviço demo-setup corre migrações e o seed.
```

## Anexo B — Automações Claude Code recomendadas (skill claude-automation-recommender)

| Tipo | Recomendação | Porquê |
|---|---|---|
| **Hook PreToolUse** | Bloquear Edit/Write em `.env*`, `*.key`, `secrets/`, `docker-compose.tailscale.yml` e a pasta privada de segredos do servidor | O repositório é público e a instância tem dados reais e chaves montadas. |
| **Hook PostToolUse** | Depois de editar `frontend/src/**/*.ts(x)`, correr `npx tsc --noEmit -p frontend`. Depois de editar `backend/app/**`, correr `ruff check` no ficheiro (quando o ruff for adotado). | Não há lint de backend. O typecheck apanha o drift de tipos. |
| **Subagente** `oppm-security-reviewer` | Revê mudanças em `security/`, `api/routes_*` e `services/imports_*` contra D-008/D-028/D-035, com a regra de que cada rota nova precisa de `get_auth_context` + verificação de âmbito. | Os achados A5 e M6 eram deste tipo. |
| **Subagente** `oppm-migration-reviewer` | Valida migrações Alembic: um só head, downgrade, CHECKs gerados a partir das constantes, compatibilidade com SQLite (`batch_alter_table`) e PostgreSQL. | 17 migrações novas por commitar e uma produção em SQLite. |
| **Skill** `/oppm-release` (só por invocação do utilizador) | Backup da BD e dos ficheiros → `git status` limpo → build → `alembic upgrade` → smoke test `/health` + login. | Atacar A9, A10 e C1 com um procedimento repetível. |
| **Skill** `/oppm-new-permission` | Gera a migração, a entrada em `catalog.py`, o teste de migração e o tipo TypeScript. | O padrão repete-se em quase todas as funcionalidades. |
| **MCP** | `context7` (documentação de FastAPI, SQLAlchemy 2, MSAL e Vite) e Playwright, para smoke tests da UI com login. O `gh` já cobre o GitHub. | Bibliotecas com APIs que mudam muito, e uma UI grande sem testes E2E. |
