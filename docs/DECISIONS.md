# Decisões de arquitetura — Op_PM

> Registo das decisões tomadas como arquiteto/implementador desta fase, com a
> justificação. Onde a decisão depende de informação que só o negócio tem
> (orçamento, sistema Financial real, tenant M365), fica marcada
> `DECISÃO NECESSÁRIA` e listada também em `OPEN_QUESTIONS.md` — este
> documento não inventa essas respostas, só regista o que foi decidido
> tecnicamente dentro do que já estava definido.

## D-001 — Monólito modular, não microserviços

**Decisão:** um único backend (FastAPI/Python) organizado em módulos internos
(`models`, `adapters`, `security`, `migration`, `api`, `audit`), não vários
serviços independentes. Um frontend separado (SPA). Um processo de
worker/scheduler separado (D-013) que reutiliza o mesmo código, não um
serviço com a sua própria base de código.

**Porquê:** até 5 utilizadores, sem requisito de escala horizontal, a
complexidade operacional de microserviços (deployment, rede interna,
observabilidade distribuída) não se paga a si própria. Um monólito modular
bem separado por módulos é mais simples de operar, depurar e evoluir, e
ainda assim mantém fronteiras claras (nenhum módulo de UI fala diretamente
com um SDK externo, por exemplo — sempre através de `adapters`).

## D-002 — PostgreSQL como alvo; SQLite como conveniência de Fase 0

**Decisão:** o schema (SQLAlchemy + Alembic) é desenhado para correr em
PostgreSQL (staging/produção) e em SQLite (local/CI), usando só tipos
portáveis — o único ponto de adaptação é `app/db.py:GUID`, um
`TypeDecorator` que usa `UUID` nativo em PostgreSQL e `CHAR(36)` em SQLite.
`DATABASE_URL` por omissão aponta para um ficheiro SQLite local
(`./data/op_pm_local.db`).

**Porquê:** o ambiente onde esta fase foi construída não tem Docker nem
PostgreSQL instalados (confirmado antes de decidir — ver verificação de
ambiente no histórico da sessão). Instalar e operar um PostgreSQL real fica
fora do que é razoável pedir a um scaffold de Fase 0 correr sozinho. SQLite
elimina essa dependência sem comprometer o desenho do schema, porque nenhum
tipo específico de PostgreSQL é usado nos modelos.

**Importante:** isto é uma conveniência de desenvolvimento, não uma mudança
de arquitetura-alvo. `docs/ARCHITECTURE_PROPOSAL.md` continua a definir o
PostgreSQL como a única fonte de verdade operacional em staging/produção.
`requirements-postgres.txt` e `docker-compose.yml` preparam esse caminho;
`docker-compose.yml` não pôde ser validado neste ambiente por falta de
Docker — reveja antes da primeira utilização real.

## D-003 — `Person` separado de `User`

**Decisão:** `people` guarda qualquer ser humano referenciado no histórico
operacional; `users` guarda só quem tem conta de login (no máximo os
utilizadores ativos decididos pelo negócio). Um `Person` sem `User`
associado continua visível em `pm_person_id`, `created_by_person_id`, etc.

**Porquê:** cumpre literalmente "até 5 utilizadores ativos, mas não pode
apagar o histórico dos 8 PMs existentes" — sem esta separação, reduzir o
número de contas de login obrigaria a apagar ou a inventar um dono para o
histórico de quem perdesse o acesso.

## D-004 — IDs internos UUID; nome nunca é chave

**Decisão:** toda a entidade de negócio usa um UUID gerado em Python
(`app/db.py:new_uuid`) como chave primária. A correspondência com sistemas
externos (ClickUp, Financial, o próprio export legado) vive em
`project_external_ids` (`source_system`, `external_id`), com restrição de
unicidade composta — nunca se infere a partir do nome do projeto em tempo de
leitura.

**Porquê:** corrige diretamente o risco C-07 do sistema legado
(`clickup_sync.py` fazia correspondência por nome exato — ver
`.planning/codebase/CONCERNS.md` no repositório do código legado), onde
uma renomeação podia criar um projeto duplicado ou atualizar o registo
errado. Um teste (`tests/test_external_ids.py`) confirma explicitamente que
renomear um projeto não quebra a ligação ao ClickUp.

## D-005 — Toda a sincronização externa passa por staging com fila de conflitos

**Decisão:** `app/migration/staging_import.py` nunca escreve num projeto
existente por adivinhação. Um registo de origem sem `ProjectExternalId`
prévio e com nome ambíguo (mais do que um candidato, seja já na base de
dados, seja dentro do mesmo lote importado) vai para `sync_conflicts` com
`status='pending'`, para revisão humana — nunca é ligado automaticamente.

**Porquê:** é exatamente o requisito "detetar duplicados e correspondências
ambíguas" + "criar uma fila de conflitos para revisão manual". Testado em
`tests/test_staging_migration.py`, incluindo o caso de dois registos do
mesmo lote partilharem nome (detetado mesmo em `dry_run`, que nunca toca na
base de dados — ver a nota técnica dentro do próprio módulo sobre porque
isso exige uma verificação em memória além da consulta à base de dados).

## D-006 — Histórico append-only aplicado por convenção nesta fase

**Decisão:** `project_history` não tem `updated_at` (testado explicitamente
— `test_project_history_has_no_updated_at_field`) e só é escrito através de
`app/audit/log.py:record_project_change`, que nunca faz UPDATE/DELETE.

**Limitação conhecida:** nesta fase, isto é imposto pela disciplina do
código (um serviço mal escrito no futuro *poderia* tecnicamente fazer
UPDATE na tabela). Reforçar isto com uma regra ao nível da base de dados
(trigger ou permissão que impede UPDATE/DELETE na tabela para o utilizador
aplicacional) é trabalho recomendado para quando a base de dados real for
PostgreSQL em produção — ver `docs/PLAN.md`, plano de segurança.

## D-007 — Workflow como dados em base de dados, não constantes no código

**Decisão:** `phases` → `workflow_stages` → `workflow_subtasks` são tabelas,
com `code` como chave estável e `id` (UUID) nunca reindexado por posição.
`project_stage_progress`/`project_subtask_progress` referenciam esses IDs
por chave estrangeira — nunca uma string posicional como `"12.3"`.

**Porquê:** corrige o padrão legado documentado em
`.planning/codebase/CONCERNS.md` (C-18): no sistema anterior, `STAGES` era
uma constante JavaScript em `solcor-gestao.html`, e tanto
`AtualizacoesSemanais_v6/app.py` como `mark_certified_done.py` duplicavam
essa estrutura separadamente (um por regex sobre o próprio HTML). Uma
mudança de fases exigia edição sincronizada em três sítios.

**Nota sobre os dados semeados:** o seed de desenvolvimento
(`app/migration/seed_dev.py`) usa fases/etapas **genéricas e fictícias**
com a mesma forma do processo legado (6 fases), não o texto real do
processo da empresa nem nomes de pessoas reais — este repositório é
público (ver D-015).

## D-008 — Permissões só no servidor, nunca "papel" escolhido no cliente

**Decisão:** `roles`/`permissions`/`role_permissions`/`user_roles` como
tabelas; `app/security/permissions.py:load_auth_context` calcula as
permissões efetivas de um utilizador a partir da base de dados a cada
pedido. `can_edit_project`/`can_view_project` verificam a permissão e, para
PMs, o `pm_person_id` do projeto — nunca um valor vindo do frontend.

**Porquê:** corrige diretamente C-03 do sistema legado ("PM" vs. "Chefe de
operações" era um `STATE.role` local, sem qualquer verificação real).
Testado em `tests/test_permissions.py`, incluindo o caso de um utilizador
sem papel associado não herdar nenhuma permissão.

## D-009 — Integrações só através de interface + fábrica de adapters

**Decisão:** `Claude`, `Microsoft Graph`, `ClickUp` e `Financial` são
acedidos exclusivamente através de uma interface (`Protocol`) definida em
`app/adapters/<integração>/base.py`. `app/adapters/__init__.py` decide qual
implementação devolver a partir das flags de configuração — hoje, sempre
mock ou fallback local; ativar uma flag `*_ENABLED` sem a implementação real
correspondente levanta `NotImplementedError` de propósito, em vez de cair
silenciosamente para o mock.

**Porquê:** nenhuma chamada real pode "escapar" por acidente nesta fase, e
trocar mock por implementação real mais tarde não exige tocar em código
fora do respetivo pacote de adapter.

## D-010 — Fallback do Graph nunca envia nem publica nada real

**Decisão:** `LocalFallbackGraphAdapter` escreve sempre um ficheiro `.eml`
ou `.ics` local. Mesmo os métodos `send_mail`/`create_event` — que exigem
`approved_by` preenchido — só gravam o ficheiro; nunca há entrega real.

**Porquê:** cumpre as regras de segurança do pedido ("não implementar envio
real de emails nem criação real de eventos nesta fase") de forma estrutural
— não é possível enviar um email real através deste adapter, seja qual for
o estado de aprovação, porque a implementação simplesmente não tem nenhum
código de entrega de rede.

## D-011 — Financial: modo CSV real além do mock

**Decisão:** além do mock, existe `CsvFinancialAdapter`, uma implementação
real (sem rede) que lê um CSV com colunas fixas
(`external_project_ref,category,amount,currency,reference`). Modos `api` e
`excel` ficam definidos na interface mas não implementados.

**Porquê:** o sistema Financial real não está identificado
(`OPEN_QUESTIONS.md`, pergunta bloqueante). Um conector CSV é o caminho mais
provável de funcionar no primeiro dia, independentemente da resposta final
— muitos sistemas financeiros exportam CSV mesmo sem API.

## D-012 — Autenticação: utilizador de desenvolvimento explícito, não Entra ID ainda

**Decisão:** `AUTH_ENABLED=false` por omissão. Com essa flag, o backend
resolve o "utilizador atual" a partir do cabeçalho `X-Dev-User-Email`, que
tem de corresponder a um `User` já semeado — nunca cria um utilizador a
partir do cabeçalho. Com `AUTH_ENABLED=true`, o código levanta
`NotImplementedError` de propósito.

**Porquê:** permite testar toda a camada de permissões/API sem depender de
um tenant Microsoft 365 configurado (que ainda não foi confirmado — ver
`OPEN_QUESTIONS.md`), sem fingir que existe autenticação real.

## D-013 — Worker/scheduler: desenhado, não implementado nesta fase

**Decisão:** as tarefas demoradas (sincronização ClickUp, importação
Financial, indexação documental) devem correr num processo separado do
backend web, que reutiliza os mesmos modelos SQLAlchemy e adapters — nunca
duplica lógica. Recomenda-se um scheduler leve (ex. APScheduler dentro de
um processo Python dedicado, ou uma tarefa cron do sistema operativo a
invocar um comando CLI do backend) em vez de uma fila pesada tipo
Celery+Redis, dado o volume esperado (5 utilizadores, sincronizações pouco
frequentes). Esta é uma recomendação revisível se o volume real justificar
uma fila de tarefas mais robusta.

**Porquê não está implementado já:** nesta fase não existe nenhuma tarefa
real para agendar — todas as integrações estão em modo mock/local (D-009).
Construir um processo de worker antes de haver algo real para ele fazer
seria trabalho especulativo. `app/migration/staging_import.py` já está
desenhado para ser chamado tanto por um endpoint da API como por um futuro
comando de worker, sem alteração.

## D-014 — CI sem serviços externos

**Decisão:** o workflow em `.github/workflows/ci.yml` corre os testes do
backend contra SQLite (não PostgreSQL) e faz build do frontend — sem
Docker, sem serviços externos.

**Porquê:** coerente com D-002; mantém o CI rápido e sem segredos/serviços a
gerir nesta fase. Adicionar um job de integração contra PostgreSQL real é
recomendado antes da Fase 1 (migração real), não antes.

## D-015 — Repositório mantém-se público

**Decisão:** conforme instrução explícita do utilizador nesta sessão, o
repositório `Op_PM` mantém-se público. Isto substitui a pergunta bloqueante
nº 1 do `docs/OPEN_QUESTIONS.md` anterior ("continuar público ou passar a
privado") — a resposta é: público, com a regra absoluta de nunca conter
dados reais, segredos, ou exports de produção, reforçada por `.gitignore`,
fixtures exclusivamente sintéticas, e revisão manual antes de cada commit.

## D-016 — Ambiente Python usado para validar esta fase

**Nota técnica (não uma decisão de arquitetura):** o ambiente onde esta fase
foi construída e testada tem Python 3.14 instalado; o CI usa 3.12 para
maior estabilidade/reprodutibilidade num runner padrão. Ambas as versões
foram confirmadas capazes de instalar todas as dependências, incluindo o
driver PostgreSQL opcional (`psycopg[binary]`).

## Âmbito deliberadamente deixado de fora desta fase

- Métodos de ficheiros (SharePoint/OneDrive) na interface do `GraphAdapter`
  — só existem hoje `get_availability`/`create_draft_email`/`send_mail`/
  `create_event`. Operações de documentos entram quando a Fase da biblioteca
  documental (ver `docs/PLAN.md`) for trabalhada.
- Qualquer endpoint de escrita na API além de `/health` e `/me` — os
  modelos e a lógica de permissões existem, mas os endpoints CRUD de
  projetos/visitas/inventário/etc. são trabalho da Fase 1 em diante.
- Migração dos 295 projetos reais — só a mecânica (staging, IDs externos,
  conflitos, dry-run/apply, checksum) está implementada e testada com dados
  sintéticos.
