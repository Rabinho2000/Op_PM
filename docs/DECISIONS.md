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

**Decisão:** `app/migration/staging.py` nunca escreve num projeto existente
por adivinhação. Um registo de origem sem `ProjectExternalId` prévio e com
nome ambíguo (mais do que um candidato, seja já na base de dados, seja
dentro do mesmo lote importado) fica em `staging_project_records` com
`status='conflict'`, para revisão humana — nunca é ligado automaticamente.

**Porquê:** é exatamente o requisito "detetar duplicados e correspondências
ambíguas" + "criar uma fila de conflitos para revisão manual". Testado em
`tests/test_staging_persistence.py`, incluindo o caso de dois registos do
mesmo lote partilharem nome.

**Revisto na revisão de hardening da Fase 0 — ver D-017**: esta decisão
mantém-se, mas o desenho original (`dry_run`/`apply` numa única função, que
nunca persistia nada em `dry_run`) foi substituído por um staging
persistente com promoção explícita, porque a ingestão em si já não tem
nada de arriscado a simular — nunca toca em `projects`.

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
seria trabalho especulativo. `app/migration/staging.py` já está desenhado
para ser chamado tanto por um endpoint da API como por um futuro comando de
worker, sem alteração.

## D-014 — CI com SQLite e PostgreSQL

**Decisão original:** o workflow em `.github/workflows/ci.yml` corria só
contra SQLite. **Revisto na revisão de hardening (ver D-021):** passou a
ter dois jobs de backend — um contra SQLite (rápido, sem serviços) e outro
contra um serviço PostgreSQL do próprio GitHub Actions — mais o build do
frontend.

**Porquê:** SQLite continua a ser o suficiente para desenvolvimento local
rápido, mas só correr testes contra SQLite escondia divergências de
comportamento entre motores (ex. `Numeric`, tipos de data, `batch_alter_table`
nas migrações) até só serem descobertas em staging/produção — já tarde
demais. Ver D-021 para o detalhe do job novo.

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

## Revisão de hardening da Fase 0 (antes de iniciar a Fase 1)

As decisões D-017 a D-021 documentam a revisão de hardening pedida
explicitamente antes de avançar para a Fase 1 — nenhuma delas liga
qualquer integração real (Entra ID, Graph, ClickUp, Financial, Claude
continuam todos em modo mock/fallback).

## D-017 — Staging persistente + promoção explícita substitui `dry_run`/`apply`

**Decisão:** o mecanismo de migração deixou de ser uma única função
`run_staging_import(mode='dry_run'|'apply')` (que nunca persistia nada em
`dry_run`) e passou a três etapas distintas e persistentes, em
`app/migration/staging.py`:

1. `ingest_export` — lê o export, cria `ImportBatch` +
   `StagingProjectRecord`. Sempre persiste (commit imediato). Nunca toca em
   `projects`.
2. `resolve_conflict` — só para registos com `status='conflict'`; decide
   `create_new`/`link_existing`/`skip`.
3. `promote_staging_record` — só isto escreve em `projects`
   (criação ou atualização), sempre com entradas de `project_history` por
   campo alterado.

Mais `rollback_promotion`, que desfaz uma promoção: inativa
(`is_active=False`, nunca `DELETE`) se a promoção tinha criado o projeto;
reaplica os valores anteriores campo a campo (via `project_history`,
correlacionado por `related_staging_record_id` — nunca por adivinhação de
texto) se a promoção tinha atualizado um projeto já existente.

**Porquê:** o desenho anterior confundia duas coisas distintas —
"experimentar sem consequência" (que já não fazia sentido, porque a
ingestão nunca tocava em `projects`) e "aplicar de vez" — numa única
função com um parâmetro `mode`. Separar em três funções/tabelas torna cada
etapa auditável, testável e revertível isoladamente, e cumpre à letra o
pedido: "separa: ingestão do export; revisão de conflitos; promoção
explícita para os dados canónicos. Todas as promoções devem gerar
auditoria e permitir rollback."

**Âmbito conhecido:** a deteção de duplicados por nome só olha para
`projects` já promovidos e para o lote atual — não deteta dois lotes
diferentes, ainda não promovidos, com o mesmo nome. Aceitável para Fase 0
(só dados sintéticos); antes de uma migração real, promover um lote de
cada vez (ou reforçar a deteção) evita este cenário.

## D-018 — `Numeric`/`Decimal` para todos os valores monetários

**Decisão:** `cost_lines.amount` e `material_request_items.unit_price`
passaram de `Float` para `Numeric(12, 2)` (`decimal.Decimal` em Python).
`FinancialCostRecord.amount` (adapter) e `CsvFinancialAdapter` seguiram a
mesma mudança — o CSV é lido com `Decimal(str)` diretamente, nunca
`float(...)` a meio do caminho.

**Porquê:** `float` não representa exatamente a maioria dos valores
decimais em binário (`0.1 + 0.1 + 0.1 != 0.3`) — inaceitável para dinheiro.
`Numeric` é portável entre SQLite e PostgreSQL sem tipo customizado (ao
contrário de UUID, não precisou de um `GUID`-like `TypeDecorator`). Testado
em `tests/test_monetary_precision.py` com um caso que demonstra o erro que
`float` cometeria.

**Nota:** quantidades (`inventory_movements.quantity`,
`material_request_items.quantity`, `inventory_items.min_stock`)
mantiveram-se `Float` — não são valores monetários, e o pedido delimitou
explicitamente "valores monetários".

## D-019 — Campos legados adicionais como texto, não `Date`/`Integer`

**Decisão:** os novos campos do `Project` vindos do IDF legado
(`upac_connection_date_raw`, `award_year_raw`, e também `power_raw`) são
`String`, não `Date`/`Integer` — apesar de os nomes sugerirem esses tipos.

**Porquê:** o formato real destes campos no export legado não foi
confirmado nesta fase (o repositório do código legado não foi tocado para
esta revisão). Tipar como `Date`/`Integer` e falhar ao importar um valor
real com formato inesperado seria pior do que preservar o texto — cada um
tem também um campo companheiro com o melhor esforço de interpretação
(`start_date` como `Date`, `power_kwp` como `float`) quando a extração é
possível, sem nunca perder o original. Revisitar quando os formatos reais
forem confirmados.

## D-020 — Duas barreiras independentes contra configuração insegura em staging/produção

**Decisão:**

1. `Settings` (pydantic) valida, à construção — logo, ao arrancar a
   aplicação — que `APP_ENV in ('staging', 'production')` implica
   `AUTH_ENABLED=true`, `SECRET_KEY` diferente do valor de desenvolvimento,
   e `DATABASE_URL` não-SQLite. Viola qualquer uma → `ValidationError`,
   processo não arranca.
2. `get_current_user` (o mecanismo de utilizador de desenvolvimento)
   verifica `settings.app_env` a cada pedido, independentemente da
   validação acima — defesa em profundidade para o caso (não esperado em
   condições normais) de a aplicação correr com `APP_ENV=local`/`test` mas
   ligada por engano a infraestrutura de staging/produção.

**Porquê:** o pedido foi explícito — "impede que a aplicação arranque" E
"o cabeçalho X-Dev-User-Email deve funcionar apenas em local/test" são duas
garantias distintas; a primeira sozinha não cobre o cenário de
configuração parcialmente incorreta (`APP_ENV` errado, mas o resto certo).
Testado em `tests/test_config_hardening.py`.

## D-021 — CI: job PostgreSQL adicional, sem remover o job SQLite

**Decisão:** `.github/workflows/ci.yml` ganhou um segundo job de backend
(`backend-postgres`), que sobe um serviço `postgres:16` no próprio runner
do GitHub Actions, corre `alembic upgrade head` e `pytest -q` contra
`DATABASE_URL=postgresql+psycopg://...`, com `requirements.txt` +
`requirements-postgres.txt` instalados. O job SQLite original mantém-se.

**Porquê:** cumpre o pedido diretamente; garante que a migração
(`batch_alter_table`, `Numeric`, `GUID`) e a suite de testes funcionam
também no motor de produção-alvo, não só em SQLite.

**Tentativa real de validação local (revisão de hardening seguinte) e o
que bloqueou:** sem Docker disponível (D-002), tentou-se instalar
PostgreSQL embebido via o pacote `pgserver` (binários portáveis, sem
serviço de sistema, sem admin) — foi necessário instalar Python 3.12 à
parte (só há wheels `pgserver` até cp312), o que funcionou. O `initdb`
do PostgreSQL embebido, porém, falha sempre neste computador com
`FATAL: invalid byte sequence for encoding "UTF8"`, independentemente do
diretório de dados escolhido ou de `--locale`/variáveis de ambiente
`USERNAME` sobrepostas: o binário lê o nome da conta Windows atual
("Sérgio", com acento) através de uma API que não faz a transcodificação
correta para UTF-8 antes de o passar ao script de bootstrap SQL — um
problema conhecido de builds de PostgreSQL para Windows com nomes de
utilizador não-ASCII, não um problema no código deste repositório.
Não foi contornável em tempo razoável sem alterar a conta Windows do
utilizador (fora de questão) ou compilar um binário próprio.

Conclusão: o job continua **não executado localmente**, mas por uma
limitação confirmada do ambiente local (não do código), depois de uma
tentativa real e documentada — não apenas por falta de Docker. A primeira
execução real continua a ficar para o GitHub Actions, onde os runners
`ubuntu-latest` não têm este problema (contas de serviço Linux, sempre
ASCII).

## D-022 — `conftest.py` nunca sobrescreve `DATABASE_URL`; dialect verificado explicitamente

**Decisão:** `tests/conftest.py` só cria/gere um ficheiro SQLite temporário
quando `DATABASE_URL` **não** está definido no ambiente. Quando está
definido — pelo CI (`backend-postgres`) ou por um dev a testar contra
PostgreSQL manualmente — é respeitado tal como está, nunca sobreposto.
Além disso, `_prepare_database` (fixture de sessão, `autouse=True`) chama
`pytest.exit(...)` — abortando toda a sessão de testes, antes de qualquer
teste correr — se a variável `EXPECTED_DB_DIALECT` estiver definida e não
corresponder ao dialect do motor realmente ligado
(`engine.dialect.name`). `tests/test_database_dialect.py` acrescenta um
resultado nomeado e visível para a mesma garantia.
`.github/workflows/ci.yml` define `EXPECTED_DB_DIALECT=postgresql` no job
`backend-postgres` e `EXPECTED_DB_DIALECT=sqlite` no job `backend-sqlite`.

**Porquê — bug real corrigido, não só um risco teórico:** a versão
anterior de `conftest.py` fazia sempre
`os.environ["DATABASE_URL"] = f"sqlite:///{...}"` incondicionalmente, ANTES
de qualquer teste correr — isto significava que o job `backend-postgres`
do CI (que define `DATABASE_URL=postgresql+psycopg://...` no ambiente)
teria essa variável **imediatamente substituída por SQLite** assim que
`pytest` importasse `conftest.py`, e a suite inteira corria — e "passava"
— contra SQLite, sem nunca tocar em PostgreSQL. O job ficaria verde sem
validar nada do que dizia validar. Confirmado e corrigido nesta revisão,
com teste de regressão (`test_dev_header_mechanism_*` e a suite geral
correndo com um `DATABASE_URL` externo antes e depois da correção).

## D-023 — Reconciliação de PM como etapa explícita antes da promoção de projetos

**Decisão:** `app/migration/people_reconciliation.py` introduz uma etapa
— chamada antes de `ingest_export`, mas cujo efeito de bloqueio se aplica
durante toda a ingestão/promoção — com duas responsabilidades:

1. `reconcile_pm_names(db, payload=...)`: para cada nome de PM distinto no
   export, verifica se corresponde a exatamente um `Person` conhecido; se
   não (zero ou mais do que uma correspondência), regista um
   `PersonReconciliationItem` (`status='pending'`) — nunca cria nem liga
   uma `Person` sozinho. Idempotente por nome normalizado.
2. `resolve_person_reconciliation(...)`: a única forma de sair de
   `pending` — `link_existing` (liga a uma `Person` já existente),
   `create_new` (cria uma `Person` nova, **sempre `is_active=False` e sem
   `User`** — nunca dá login automaticamente), ou `ignore` (decisão
   explícita de não associar nenhuma pessoa a este nome).

`app/migration/staging.py` usa `classify_pm_name` (a mesma função usada
pela reconciliação) em três pontos, para nunca haver duas lógicas de
decisão divergentes sobre o que conta como "PM resolvido":

- `ingest_export`: se um registo tem PM presente mas não resolvido, fica
  `status='conflict'`, `conflict_reason='pm_unresolved'` — mesmo que a
  parte de identidade do projeto (nome, sem duplicados) esteja
  perfeitamente limpa. A resolução do projeto (`create_new`/
  `update_existing`) fica já calculada e guardada, para não se perder
  quando o PM for resolvido.
- `resolve_conflict`: ganhou a ação `proceed_without_pm` (só válida para
  `conflict_reason='pm_unresolved'`) — decisão humana explícita de avançar
  sem PM. Quando um conflito de NOME de projeto é resolvido
  (`create_new`/`link_existing`) e o registo tinha também um PM por
  resolver, o registo não salta para `ready_to_promote`: volta a ficar
  `conflict`/`pm_unresolved`, porque o problema de PM nunca tinha sido
  endereçado (só o de nome). Ambos os caminhos passam pelo mesmo
  `_finalize_status_given_pm`, para nunca divergirem.
- `promote_staging_record`: verifica **outra vez**, já na promoção, se o
  PM está resolvido ou explicitamente dispensado — mesmo que o registo
  tenha chegado a `ready_to_promote` por alguma via que não passasse pelas
  barreiras normais (testado explicitamente forçando o estado
  diretamente). Esta é a garantia final e não contornável de "nunca
  promover silenciosamente um projeto com PM conhecido mas não resolvido".
- `retry_pm_resolution`: reclassifica um registo bloqueado por
  `pm_unresolved` depois de a reconciliação resolver o nome em causa —
  desbloqueia sem repetir a ingestão.

**Porquê:** cumpre os quatro requisitos pedidos diretamente — preservar
todos os PMs históricos como `Person` já era uma propriedade do modelo
(D-003), aqui reforçada ao nunca apagar/ignorar um `Person` existente;
`User` só é criado por decisão humana separada (a reconciliação nunca cria
um); nomes desconhecidos/ambíguos vão sempre para a fila
`person_reconciliation_items`; e a barreira em `promote_staging_record` é
estrutural, não contornável por um caminho alternativo dentro do código.
Testado em `tests/test_people_reconciliation.py` (16 testes) e no ajuste
correspondente em `tests/test_staging_persistence.py`.

**Âmbito conhecido:** tal como a deteção de duplicados de projeto (D-017),
`reconcile_pm_names` só vê o `payload` que lhe é passado — não deteta
proativamente nomes de PM pendentes de lotes anteriores ainda por
reconciliar; isso já é coberto, na prática, porque `classify_pm_name`
consulta sempre `person_reconciliation_items` para decisões já tomadas
(`ignored`/resolvidas), e um item `pending` de um lote anterior continua
`pending` e continua a bloquear qualquer registo com esse nome, em
qualquer lote.

## Âmbito deliberadamente deixado de fora da Fase 0

- Métodos de ficheiros (SharePoint/OneDrive) na interface do `GraphAdapter`
  — só existem hoje `get_availability`/`create_draft_email`/`send_mail`/
  `create_event`. Operações de documentos entram quando a Fase da biblioteca
  documental (ver `docs/PLAN.md`) for trabalhada.
- Migração dos 295 projetos reais — só a mecânica (ingestão, staging, IDs
  externos, conflitos, promoção explícita, rollback, checksum) está
  implementada e testada com dados sintéticos.
- Deteção de duplicados entre lotes de importação diferentes ainda não
  promovidos (ver D-017, âmbito conhecido).
- Regra de base de dados (trigger/permissão) que impeça UPDATE/DELETE em
  `project_history` — continua aplicada só por convenção de código (D-006).

# Fase 1 — Autenticação real, CRUD, reconciliação por API, frontend

Nenhuma destas decisões liga uma integração externa real — Graph, ClickUp,
Financial e Claude continuam mock/fallback (D-009 a D-011); os 295
projetos reais continuam por migrar (D-005/D-017).

## D-024 — Validação real de token Entra ID, dupla barreira contra o modo mock

**Decisão:** `app/security/entra_auth.py` valida tokens OIDC do Microsoft
Entra ID (assinatura RS256, `iss`, `aud`, `exp`/`iat`, claims obrigatórias)
com duas implementações atrás da mesma interface:

- `RealEntraTokenValidator`: busca o JWKS do tenant real via rede
  (`PyJWKClient`, com cache), issuer/audience derivados de
  `ENTRA_TENANT_ID`/`ENTRA_CLIENT_ID` (ou explícitos via
  `ENTRA_ISSUER`/`ENTRA_AUDIENCE`/`ENTRA_JWKS_URL`).
- `MockEntraTokenValidator`: valida contra uma chave RSA de teste fixa,
  gerada uma única vez para este repositório, embutida no código — sem
  qualquer chamada de rede. **Não é um segredo real**: nunca validaria
  nada vindo de um Entra ID de verdade (issuer/audience diferentes), serve
  só para assinar/validar tokens sintéticos em `issue_mock_token` (testes).

`Settings.entra_validation_mode` (`'real'` por omissão) escolhe qual —
`app/security/entra_auth.py:get_token_validator` é o único ponto que
decide isto, nunca instanciado diretamente fora daí.

`get_current_user` (app/security/current_user.py) liga o `oid` do token a
`User.entra_object_id`; se ainda não houver ligação, tenta uma ligação
"just-in-time" por email — só para um `User` já existente, ativo, sem
`entra_object_id`, e só se exatamente um corresponder (nunca cria um
`User` novo a partir de um token; provisionamento continua um passo
administrativo separado). Ambíguo ou inexistente → 401 genérico (nunca
revela ao chamador HTTP qual validação específica falhou — assinatura,
issuer, audience, ou validade — só ao log do servidor).

**Porquê a dupla barreira ser necessária:** `ENTRA_VALIDATION_MODE=mock`
nunca pode ser alcançável em staging/produção, senão qualquer token
assinado com a chave de teste (pública neste repositório) autenticaria
como qualquer utilizador. `Settings._enforce_hardening_in_non_local_envs`
(D-020) foi estendida para também exigir `ENTRA_VALIDATION_MODE='real'`
nesses ambientes — a aplicação recusa-se a arrancar caso contrário.
Testado em `tests/test_config_hardening.py` (bloqueio de arranque) e
`tests/test_auth_entra.py` (12 testes: token válido, ligação por email,
segunda autenticação já ligada por `entra_object_id`, assinatura inválida,
token malformado, `Authorization` em falta, token expirado, audience
errada, issuer errado, utilizador sem papel, email/object_id
desconhecidos, e X-Dev-User-Email nunca é sequer lido quando
`AUTH_ENABLED=true`).

## D-025 — CRUD de projetos: permissões e histórico só na camada de serviço

**Decisão:** `app/services/projects.py` é o único sítio que escreve num
`Project` a partir da API (`app/api/routes_projects.py`). `update_project`
verifica `can_edit_project` (D-008) antes de tocar em qualquer campo, e usa
`model_dump(exclude_unset=True)` para só considerar campos explicitamente
presentes no pedido — um campo omitido nunca é tocado, um campo presente
com `null` limpa-o explicitamente. Cada campo efetivamente alterado gera
uma entrada de `project_history` (`source='ui'`,
`changed_by_person_id=<pessoa do utilizador autenticado>`) através do
mesmo `record_project_change` já usado pela migração (D-005) — nunca uma
escrita silenciosa, e um valor igual ao anterior não gera entrada (mesma
regra que corrige C-08 desde a Fase 0).

`GET /api/projects` e `GET /api/projects/{id}` filtram por
`can_view_project`/`visible_projects_query` — um PM sem `project.view_all`
só vê os seus próprios projetos, nunca recebe uma lista completa filtrada
no cliente. Não existe nenhum endpoint que escreva em `project_history`
diretamente — só leitura (`GET /api/projects/{id}/history`).

`clickup_status_mirror` fica deliberadamente fora de `ProjectUpdate` — é
espelho só-de-leitura do ClickUp (fonte de verdade externa), nunca editado
pela UI desta plataforma.

Testado em `tests/test_project_api.py`: PM só edita o seu próprio projeto
(403 no outro), Chefe de Operações edita qualquer um, Comercial só lê
(403 em qualquer PATCH), histórico criado por cada campo alterado, nenhuma
entrada gerada quando o valor não muda, pedido não autenticado rejeitado.

## D-026 — Endpoints de migração: consulta e resolução, nunca ingestão

**Decisão:** `app/api/routes_migration.py` expõe leitura
(`import-batches`, `staging-records`, `reconciliation-items`) e as ações
de resolução já existentes em `app/migration/staging.py`/
`people_reconciliation.py` (`resolve-conflict`, `promote`, `rollback`,
`retry-pm-resolution`, `reconciliation-items/{id}/resolve`) — mas
**nenhum endpoint para `ingest_export`**. Duas novas permissões:
`migration.view` e `migration.resolve`, concedidas a Administrador e
Chefe de Operações (a recomendação por omissão da pergunta aberta nº 17).

**Porquê não expor ingestão via API:** a ingestão de um export real é uma
operação controlada e pouco frequente (por lote, não por pedido HTTP
casual), e expor um endpoint para ela convidaria a experimentar com dados
reais antes de tempo — contrariando a regra explícita desta fase ("não
migrar ainda os 295 projetos reais"). Quando a fase de migração real
chegar (Fase 2 no roadmap desta altura, renumerada para Fase 4 em
docs/PLAN.md — ver D-037), a ingestão real continua a ser um
comando/script operado deliberadamente (`app/cli/ingest_staging.py`),
não um botão da UI.

Testado em `tests/test_migration_api.py`: bloqueio de promoção com
registo em conflito (incluindo `pm_unresolved`), resolução de PM
desconhecido via API seguida de promoção bem-sucedida,
`proceed_without_pm` via API, e que um PM sem `migration.view` não
consegue ver nem resolver nada de migração.

## D-027 — Frontend Fase 1: login (mecanismo de dev), lista, detalhe, reconciliação

**Decisão:** primeira interface web funcional — `Login` (guarda o email de
desenvolvimento em `localStorage`, nunca um token — ver nota abaixo),
`ProjectsList` (filtros por PM/estado/pesquisa), `ProjectDetail` (edição
dos campos permitidos + histórico ao lado), `ReconciliationQueue` (liga/
cria/ignora um nome de PM pendente). `react-router-dom` para a navegação;
`RequireAuth` redireciona para `/login` sem um email de dev guardado.

**Login com Entra ID real não foi ligado ao frontend nesta fase** — exigia
MSAL.js e valores reais de app registration (tenant ID, client ID) que
este repositório não tem (ver `docs/OPEN_QUESTIONS.md`, pergunta 1); o
ecrã de login diz isto explicitamente ao utilizador, em vez de fingir uma
opção que não funciona. O backend já valida tokens reais (D-024) — falta
só a configuração do tenant para o MSAL.js ter com quem falar.

Validado manualmente ponta-a-ponta (backend + frontend a correr
localmente): login, listagem com filtros, edição de um projeto com
histórico a aparecer imediatamente com autor/fonte corretos, fila de
reconciliação vazia a renderizar sem erros, logout a limpar a sessão.

## Âmbito deliberadamente deixado de fora da Fase 1

- Endpoints de workflow (`project_stage_progress`/`project_subtask_progress`)
  — só os campos de identidade do `Project` são editáveis via API nesta
  fase; progresso de checklist fica para quando o workflow (fases/etapas)
  ganhar a sua própria UI.
- Ingestão real de projetos via API (D-026, decisão deliberada).
- Testes de UI automatizados (Playwright/Cypress) — validação desta fase
  e da revisão de hardening seguinte (D-028 a D-031) foi manual, via
  navegador, documentada acima e abaixo.

> As duas lacunas identificadas nesta lista na versão anterior deste
> documento — "restrição de campos por perfil" e "autenticação real
> ponta-a-ponta (MSAL.js)" — foram fechadas pela revisão de hardening a
> seguir (D-028 e D-031, respetivamente). O tenant Microsoft 365 real
> continua por confirmar (pergunta bloqueante nº 1) — D-031 deixa o login
> real MSAL implementado e configurável, mas sem um `VITE_ENTRA_CLIENT_ID`/
> `VITE_ENTRA_TENANT_ID`/`VITE_ENTRA_API_SCOPE` reais para lhe dar
> credenciais, o botão fica visivelmente desativado.

## Revisão de hardening da Fase 1 (antes de iniciar a Fase 2)

As decisões D-028 a D-031 documentam a revisão de hardening pedida
explicitamente antes de avançar para a Fase 2 (a partir do commit
`401ebf6`) — nenhuma liga qualquer integração real (Entra ID, Graph,
ClickUp, Financial e Claude continuam todos em modo mock/fallback) nem
migra qualquer um dos 295 projetos reais.

## D-028 — Permissões de edição de projeto: lista explícita de campos por perfil, aplicada no servidor

**Decisão:** `project.edit_all` (Chefe de Operações/Administrador) continua
a poder alterar qualquer campo de `ProjectUpdate`. Quem só tem
`project.edit_own_progress` (PM, no seu próprio projeto) fica limitado a
uma lista explícita — `PM_EDITABLE_PROJECT_FIELDS` em
`app/security/project_fields.py` (`lat`, `lon`, `power_kwp`, `power_raw`,
`start_date`, `role`, `equipment_notes`, `injection_notes`, `om_notes`,
`commercial_assumptions`, `upac_connection_date_raw`, `award_year_raw`,
`notes`) — nunca pode tocar em `name`, `client_name`, `client_contact`,
`client_email`, `address`, `pm_person_id`, `is_active`,
`upac_registration` ou `m2m_card` (`ADMIN_ONLY_PROJECT_FIELDS`, a mesma
lista documentada por oposição, para nunca haver um campo "esquecido" no
meio).

**Desenho deliberado — allowlist, não denylist:** `PM_EDITABLE_PROJECT_FIELDS`
é a lista que importa; `ADMIN_ONLY_PROJECT_FIELDS` existe só para um teste
confirmar que as duas juntas cobrem exatamente `ProjectUpdate.model_fields`
(nenhum campo esquecido de um lado ou do outro). Um campo novo adicionado
a `ProjectUpdate` no futuro e esquecido nesta lista fica automaticamente
só para quem tem `project.edit_all` — nunca editável por omissão.

**Aplicado inteiramente no servidor**, independentemente do frontend:
`update_project()` (`app/services/projects.py`) calcula
`disallowed_fields = alterações pedidas − PM_EDITABLE_PROJECT_FIELDS`
depois de confirmar que o ator pode editar o projeto mas antes de
escrever qualquer campo — um pedido com um único campo fora da lista é
rejeitado por inteiro (nenhum efeito secundário parcial), com a mensagem
a nomear os campos recusados.

**Testes (`tests/test_project_field_permissions.py`, 12 casos):**
disjunção e cobertura total das duas listas contra `ProjectUpdate`; PM
edita um campo permitido (200); PM tenta cada campo administrativo
individualmente (403, parametrizado); PM tenta reatribuir `pm_person_id`
(403); pedido misto (um campo permitido + um proibido) rejeitado por
inteiro, confirmado sem qualquer alteração na BD nem entrada de
histórico; Chefe de Operações edita campos administrativos (200); PM
tenta editar um projeto que não é seu, mesmo só com campos permitidos
(403).

## D-029 — Reforço da autenticação Entra ID: `oid` obrigatório, tenant/scp/`nbf` validados, JIT linking configurável e auditado, validador cacheado

**Decisão:**

- **`oid` obrigatório, nunca `sub` como identidade persistente** — um
  token sem `oid` (ou com `oid` vazio) é sempre recusado; `sub` deixou de
  ser sequer consultado para identidade (`REQUIRED_CLAIMS` inclui `oid`).
- **Tenant, issuer, audience, assinatura, expiração e `nbf`** — issuer/
  audience/assinatura/`exp` já eram validados desde D-024; `nbf`, quando
  presente, é validado pelo comportamento por omissão do PyJWT (nunca
  desativado); `tid` é comparado a `ENTRA_TENANT_ID` quando este está
  configurado (sem tenant configurado, `tid` não é verificado —
  comportamento existente, preservado deliberadamente).
- **Só tokens delegados** — `_validate_delegated_token` exige a claim
  `scp` não vazia; um token só com `roles` (aplicação, não delegado) é
  recusado. `ENTRA_REQUIRED_SCOPE`, quando configurado, tem de aparecer
  literalmente em `scp`.
- **JIT linking por email configurável, desligado por omissão fora de
  local/test** — `Settings.entra_jit_link_by_email` (`bool | None`);
  `resolved_entra_jit_link_by_email()` devolve o valor explícito se
  definido, senão `True` em local/test e `False` em staging/produção. Uma
  ligação automática bem-sucedida grava sempre uma entrada em
  `AuthAuditLog` (evento `jit_link_by_email`, com o `oid` de origem).
- **Validador e cliente JWKS cacheados no processo** —
  `get_token_validator` passou a devolver uma instância partilhada via
  `functools.lru_cache` (chave: issuer/audience/jwks_url/tenant_id/
  required_scope), tanto para o validador real (que usa `PyJWKClient`,
  cujo cache HTTP das chaves passa a ser reaproveitado entre pedidos) como
  para o mock — nunca um `PyJWKClient` novo por pedido.

**Nova tabela `auth_audit_log`** (`AuthAuditLog`, append-only, sem
`updated_at`) — migração `67150240f450`.

**Testes (`tests/test_auth_entra_hardening.py`, 15 casos):** token sem
`oid` (com/sem `sub`) recusado; `nbf` no futuro recusado, no passado
aceite; token sem `scp` recusado como token de aplicação; âmbito
configurado a corresponder aceite, a não corresponder recusado; tenant
errado recusado quando configurado, correto aceite, sem verificação
quando não configurado; ligação JIT grava auditoria; JIT desligado
recusa um utilizador por ligar e não altera `entra_object_id`; JIT
desligado por omissão em staging (e ligado por omissão em local),
substituível explicitamente; validador é a mesma instância para
configurações equivalentes, instância diferente para `required_scope`
diferente.

## D-030 — Migração: `target_project_id` validado contra os candidatos detetados, ligação a projeto arbitrário exige permissão + nota

**Decisão:** `resolve_conflict(..., action="link_existing")` passou a
validar `target_project_id` contra `resolve_candidate_project_ids()` — o
conjunto de projetos que o sistema detetou automaticamente como
candidatos para este registo (por nome, na ingestão). Ligar a um projeto
fora desse conjunto exige `allow_target_outside_candidates=True` **e**
uma nota não vazia; sem as duas coisas, `resolve_conflict` recusa com
`ValueError`, mesmo chamado diretamente sem passar pela API (defesa em
profundidade deliberada — a decisão de permitir isto é da API, mas o
valor por omissão do serviço continua a recusar).

A API (`POST /api/migration/staging-records/{id}/resolve-conflict`)
verifica isto antes de chamar o serviço: se o alvo estiver fora dos
candidatos, exige a nova permissão `migration.link_arbitrary_project`
(403 sem ela — só concedida ao Administrador por omissão, não ao Chefe de
Operações) e uma nota não vazia (400 sem ela) antes de passar
`allow_target_outside_candidates=True` ao serviço.

**Bug encontrado e corrigido durante a implementação:** um candidato
detetado dentro do mesmo lote de importação (duplicado por nome, D-017)
fica registado como `"batch:<id_externo>"` até o registo irmão ser
promovido — só nesse momento é que existe um `Project` real para essa
referência. Uma primeira versão desta validação filtrava esses
candidatos "batch:" fora do conjunto válido em vez de os resolver,
partindo silenciosamente o fluxo legítimo já testado em
`test_resolve_conflict_then_promote_links_to_target_project`. Corrigido
com `resolve_candidate_project_ids()` — usada tanto pelo serviço como
pela API, para nunca haver duas lógicas divergentes sobre o que conta
como candidato válido — que traduz `"batch:<id>"` para o `Project` real
via `ProjectExternalId`, quando este já existe.

**Testes (`tests/test_migration_target_validation.py`, 7 casos, mais o
teste de regressão já existente em `test_staging_persistence.py`):**
alvo fora dos candidatos recusado por omissão; aceite com
`allow_target_outside_candidates=True` + nota; nota vazia continua
recusada mesmo com a flag; um candidato "batch:" já promovido resolve
corretamente e não exige a permissão especial; Chefe de Operações sem a
permissão recebe 403 pela API; Administrador com a permissão mas sem nota
recebe 400; Administrador com permissão + nota liga com sucesso, promove,
e a reversão (`rollback_promotion`) continua a funcionar normalmente —
ação sempre auditada e reversível, tal como pedido.

## D-031 — Login real MSAL no frontend (Authorization Code + PKCE), configurável, login de desenvolvimento claramente separado

**Decisão:** `frontend/src/auth/msal.ts` usa `@azure/msal-browser`
diretamente (`PublicClientApplication`) — sem `@azure/msal-react`, para
manter a mesma forma de módulo singleton já usada em `api/client.ts`, sem
introduzir Context/Provider só para isto. O MSAL browser só suporta
Authorization Code + PKCE para SPAs desde a v2 — não há "implicit flow"
para desativar, é sempre PKCE.

- **Nunca o ID token como autorização** — `acquireTokenSilent`/
  `loginRedirect` pedem sempre um âmbito dedicado à API
  (`VITE_ENTRA_API_SCOPE`, ex. `api://<client-id-da-api>/access_as_user`);
  só `result.accessToken` sai deste módulo, nunca `result.idToken`.
- **`Authorization: Bearer <token>` em todos os pedidos** —
  `api/client.ts:request()` decide por sessão (nunca por pedido): havendo
  uma conta MSAL ativa, todo o pedido leva o Bearer token; senão, cai
  para `X-Dev-User-Email` se houver um utilizador de desenvolvimento —
  os dois nunca são enviados ao mesmo tempo, tal como o backend só aceita
  um dos dois caminhos por `AUTH_ENABLED` (nunca ambos).
- **Renovação silenciosa** — cada pedido chama `acquireTokenSilent`
  (dentro de `getApiAccessToken()`), que o MSAL já resolve com o token em
  cache ou renovado silenciosamente sem qualquer interação visível;
  só levanta `SessionExpiredError` quando o MSAL confirma
  `InteractionRequiredAuthError` (refresh token expirado/revogado, MFA
  adicional exigido).
- **Logout e sessão expirada** — `logoutCurrentSession()` chama
  `logoutRedirect()` para uma sessão MSAL real (ou só limpa o
  `localStorage` para uma sessão de desenvolvimento); um `401` do backend
  numa sessão MSAL, ou uma `SessionExpiredError` do MSAL, redirecionam
  sempre para `/login?sessionExpired=1` em vez de repetir o pedido às
  cegas ou deixar a app num estado inconsistente.
- **Login de desenvolvimento claramente separado** —
  `devLoginEnabled` (`src/auth/msal.ts`) fica ligado por omissão em
  `vite dev`/testes (`import.meta.env.DEV`) e desligado por omissão num
  build de produção, substituível só por `VITE_ENABLE_DEV_LOGIN`
  explícito; o ecrã de login (`src/pages/Login.tsx`) só renderiza essa
  secção quando `devLoginEnabled` é true, sempre visualmente separada
  (aviso "Apenas desenvolvimento/testes", nunca disponível em
  staging/produção — mesma regra que o backend já aplicava do lado do
  servidor).

**Sem tenant/app registration reais** (pergunta bloqueante nº 1 — por
resolver), `VITE_ENTRA_CLIENT_ID`/`VITE_ENTRA_TENANT_ID`/
`VITE_ENTRA_API_SCOPE` ficam vazios por omissão; `isEntraConfigured` fica
`false` e o botão "Entrar com Microsoft" aparece desativado com uma
explicação — nunca inventa credenciais nem finge uma sessão real.

**Dependência nova:** `@azure/msal-browser` (`^5.21.0`).

**Vulnerabilidades npm revistas, não corrigidas nesta revisão:**
`npm audit` reporta 4 vulnerabilidades (3 moderadas, 1 alta) em `vite`
(via `esbuild`, servidor de desenvolvimento) e `react-router-dom`
(open-redirect via `\` em `<Link>`/`useNavigate`) — nenhuma tem correção
dentro do intervalo semver já instalado (`npm outdated` confirma "Wanted"
= "Current" para ambos); a única correção disponível é um salto de versão
maior (`vite` 5→8, `react-router-dom` 6→7), uma alteração desnecessária e
potencialmente disruptiva para uma revisão de hardening focada noutra
coisa. Registado como risco pendente (ver `docs/OPEN_QUESTIONS.md`) em
vez de forçado com `npm audit fix --force`.

**Atualizado por D-048:** a vulnerabilidade **alta** do `vite` tem, afinal,
correção sem salto de major — `vite@6.4.3` (não precisa de ir a 8) resolve
GHSA-fx2h-pf6j-xcff mantendo compatibilidade total com o resto do
frontend. Aplicado na integração dos dois PRs (`mvp-ready`) — ver D-048.
A de `react-router-dom` (moderada) continua sem correção fora de um
major e foi mantida como risco aceite.

**Validado manualmente ponta-a-ponta** (backend + frontend a correr
localmente, sem tenant Entra real): ecrã de login sem erros de consola
com a configuração MSAL vazia (placeholder), botão "Entrar com Microsoft"
visivelmente desativado com a explicação, secção de desenvolvimento
separada por um divisor visual; login de desenvolvimento continua
funcional ponta-a-ponta (entrar, `NavBar` a mostrar a sessão, listagem de
projetos a carregar, logout a limpar a sessão e devolver a `/login`).

## D-032 — Validação de configuração obrigatória, completa, em staging/produção

**Decisão:** `Settings._enforce_hardening_in_non_local_envs` (D-020,
`app/config.py`) passa a exigir, além das quatro condições já existentes
(`AUTH_ENABLED=true`, `SECRET_KEY` real e não vazio, `DATABASE_URL`
PostgreSQL, `ENTRA_VALIDATION_MODE=real`):

- `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID` e `ENTRA_REQUIRED_SCOPE`
  preenchidos — sem eles não há tenant/scope real a validar, e
  `resolved_entra_issuer()`/`resolved_entra_jwks_url()` apontariam para um
  URL Entra ID sintaticamente válido mas apontado a um tenant vazio
  (`.../v2.0`), um erro silencioso só visível ao primeiro pedido real.
- `CORS_ALLOWED_ORIGINS` não vazio — em staging/produção, vazio significa
  "nenhuma origem aceite" (`resolved_cors_origins`), que quase certamente
  não é a intenção de quem está a configurar; falha já no arranque em vez
  de deixar a API inacessível a qualquer frontend sem explicação.
- Se algum de `ENTRA_ISSUER`/`ENTRA_JWKS_URL`/`ENTRA_AUDIENCE` for
  definido explicitamente, os três têm de estar — um override parcial
  deixaria os campos não definidos a cair para o valor derivado de
  `ENTRA_TENANT_ID`/`ENTRA_CLIENT_ID`, uma mistura inesperada entre um
  valor manual e um valor derivado que nunca foi pedida como
  funcionalidade e é fácil de configurar por engano.

Todos os problemas continuam a ser reportados de uma vez na mesma mensagem
(comportamento já existente desde D-020), nunca só o primeiro — poupa
ciclos de tentativa-erro em staging.

**Porquê agora:** parte do fecho técnico da Fase 1 antes da preparação de
staging/produção — a validação anterior já impedia as combinações mais
óbvias, mas deixava passar uma configuração "tecnicamente válida" (auth
ligado, Postgres, modo real) que na prática nunca conseguiria autenticar
ninguém (tenant/scope em falta) ou nunca seria alcançável por um frontend
real (CORS vazio).

**Testado em** `tests/test_config_hardening.py` — um teste por condição
nova (staging e produção), mais o override parcial de
issuer/jwks/audience (com e sem os três presentes) e a mensagem agregada
com todos os problemas em simultâneo. `local`/`test` continuam nunca
bloqueados (mesmos testes de sempre, sem alteração).

**Sem impacto em `local`/`test`:** estas variáveis continuam opcionais
nesses ambientes — a Fase 1 já funciona sem tenant real via o mecanismo de
desenvolvimento (D-012); só passam a ser exigidas quando `APP_ENV` é
`staging`/`production`.

## D-033 — Login de desenvolvimento nunca sobrevive num build de produção, mesmo com `localStorage` antigo

**Decisão:** `src/pages/Login.tsx` já só renderizava a secção de login de
desenvolvimento quando `devLoginEnabled` (D-031); mas `src/api/client.ts`
continuava a ler/escrever `localStorage` incondicionalmente
(`getDevUser`/`setDevUser`/`hasActiveSession`/`request()`), pelo que um
valor gravado numa sessão de desenvolvimento anterior (ou escrito
manualmente por alguém a inspecionar o browser) continuava a ser enviado
como `X-Dev-User-Email` mesmo num build com `devLoginEnabled=false`.
Corrigido:

- `getDevUser()`/`setDevUser()` devolvem/ignoram sempre que
  `devLoginEnabled` é `false` — nunca tocam em `localStorage` nesse caso;
  `clearDevUser()` continua incondicional (limpar é sempre seguro).
- Ao carregar o módulo com `devLoginEnabled=false`, qualquer valor antigo
  já em `localStorage` é limpo imediatamente — nunca fica só "invisível
  para a leitura seguinte", é removido.
- `hasActiveSession()`/`getSessionDisplayName()`/`request()` já usavam
  `getDevUser()`, por isso herdam o bloqueio sem alteração adicional.

**Testado em** `frontend/src/api/client.dev-login.test.ts` (Vitest, novo —
o frontend não tinha nenhum framework de testes automatizados até agora,
só validação manual ponta-a-ponta e `tsc --noEmit`/`vite build`): grava e
lê corretamente com `devLoginEnabled=true`; nunca grava nem lê com
`devLoginEnabled=false`; um valor antigo em `localStorage` é limpo ao
carregar o módulo; um pedido HTTP nunca leva `X-Dev-User-Email` mesmo com
`localStorage` manipulado depois de o módulo já estar carregado. CI
(`frontend` job) passa a correr `npm run test` antes de `npm run build`.

**Dependências novas (dev):** `vitest@^3.2.7`, `jsdom` — só para testes,
sem impacto no bundle de produção (`vite build` não os inclui). Fixado em
`3.2.7` (não `^2`, a versão inicialmente instalada) especificamente porque
`npm audit` reportou uma vulnerabilidade **crítica** no servidor de UI do
Vitest (`GHSA-5xrq-8626-4rwp`, corrigida em `vitest@3.2.6`) — nunca
aceitável deixar por corrigir só porque é uma dependência de
desenvolvimento. Uma vulnerabilidade moderada remanescente em
`@vitest/mocker` (`GHSA-82fw-gwwq-j7x9`) só se resolve com `vitest@5`
(exige `vite@6+`, fora do âmbito desta revisão) — registada em
`docs/OPEN_QUESTIONS.md` junto das outras atualizações major já adiadas
(`vite`, `react-router-dom`).

## D-034 — Provisionamento administrativo de `User.entra_object_id`: comando controlado, nunca um endpoint HTTP

**Decisão:** `app/cli/provision_entra_user.py` — comando de linha de
comandos (`python -m app.cli.provision_entra_user`), corrido manualmente
por alguém com acesso direto ao servidor/base de dados de
staging/produção, nunca um endpoint da API. Liga `User.entra_object_id` a
um `User` já existente e ativo — este é o mecanismo real de
provisionamento dos 5 utilizadores em staging/produção, onde o JIT linking
por email fica desligado por omissão (`resolved_entra_jit_link_by_email`,
D-029).

**Regras, sempre no núcleo `link_user_to_entra_object_id`** (nunca só no
`main()` da CLI, para que os testes exerçam exatamente a mesma lógica):

- **Nunca cria um `User` novo** — só liga a um já existente e ativo; email
  desconhecido ou inativo é sempre erro.
- **Nunca reatribui** — um `User` já ligado a qualquer `entra_object_id`
  (mesmo repetir o mesmo valor) é sempre erro; desligar fica fora do
  âmbito deste comando, de propósito (mantém-no pequeno e sem
  ambiguidade).
- **Nunca reutiliza um `entra_object_id` em dois utilizadores** —
  verificação explícita (mensagem compreensível) mais a restrição UNIQUE
  já existente em `User.entra_object_id` na base de dados como barreira
  final, independente da aplicação.
- **Sempre auditado** — uma entrada `AuthAuditLog` (evento
  `admin_provision_link`) com o email do utilizador, o `entra_object_id`, e
  `actor_label` (quem executou, obrigatório — sem isto o comando recusa-se
  a correr).
- **`--confirm` obrigatório para escrever** — sem essa flag, a CLI só
  mostra o que faria (dry-run), proteção simples contra execução
  acidental.

**Porquê um comando, não um endpoint:** até 5 utilizadores (D-003) é uma
operação rara — um endpoint novo seria uma superfície de API permanente
para uma ação administrativa esporádica, e manteria `get_current_user`
livre de qualquer lógica de "criar/ligar identidade" (separação já
deliberada — ver docstring de `app/security/current_user.py`). Satisfaz o
requisito "permissão administrativa OU comando administrativo controlado"
pela segunda via: quem consegue correr este comando já precisa de acesso
direto ao servidor/base de dados, um controlo de acesso independente do
`admin.manage_users` da aplicação.

**JIT linking continua desligado em produção por omissão** (D-029, sem
alteração aqui) — este comando é o caminho normal; o JIT por email
continua disponível só como conveniência de local/test, ou se alguém
definir `ENTRA_JIT_LINK_BY_EMAIL=true` explicitamente em staging/produção
(decisão de negócio explícita, não a omissão).

**Testado em** `tests/test_provision_entra_user.py` (12 testes): ligação
bem-sucedida, entrada de auditoria correta, case-insensitive no email,
email desconhecido/inativo rejeitados, nunca cria `User`, reatribuição
rejeitada, `entra_object_id` duplicado rejeitado (com e sem a verificação
explícita — o teste da restrição UNIQUE da base de dados confirma a
barreira final independente da aplicação), argumentos vazios rejeitados.

## D-035 — Allowlist de campos PM revista: campos com impacto comercial ficam administrativos até decisão de negócio

**Decisão:** `app/security/project_fields.py` (D-028) tinha classificado
`lat`, `lon`, `power_kwp`, `power_raw`, `start_date`,
`commercial_assumptions`, `upac_connection_date_raw` e `award_year_raw`
como PM-editáveis (`project.edit_own_progress`) — uma omissão técnica
razoável na Fase 1, mas nunca confirmada como decisão de negócio. Revisto
nesta preparação para staging/produção: estes oito campos passam a
`ADMIN_ONLY_PROJECT_FIELDS` (só `project.edit_all` os edita). Ficam
PM-editáveis só `role`, `equipment_notes`, `injection_notes`, `om_notes` e
`notes` — texto de acompanhamento operacional, sem valor comercial nem
usado por outra integração.

**Porquê:** potência e coordenadas afetam o dimensionamento e a
localização real reportada da instalação; `commercial_assumptions` é, pelo
nome, um pressuposto comercial; as datas legadas (`start_date`,
`upac_connection_date_raw`, `award_year_raw`) podem ter valor contratual.
Nenhum destes teve uma resposta explícita de "um PM pode corrigir isto no
seu próprio projeto sem aprovação?" — seguindo a regra geral desta revisão
("sem confirmação de negócio, usar a opção mais restritiva"), ficam
administrativos até essa confirmação existir. Registado como pergunta em
aberto — `docs/OPEN_QUESTIONS.md`, pergunta 5-B.

**Impacto operacional conhecido, aceite deliberadamente:** uma correção
legítima destes campos por um PM (ex.: coordenadas erradas vindas da
migração) passa a exigir sempre um Chefe de Operações/Administrador —
possível atrito se a resposta de negócio acabar por ser "sim, o PM pode
editar X". Prefere-se este atrito a um PM poder alterar, sem aprovação,
um valor com peso comercial/contratual antes de existir uma decisão.

**Testado em** `tests/test_project_field_permissions.py` — teste novo
confirma explicitamente que os oito campos ficam em
`ADMIN_ONLY_PROJECT_FIELDS` e que um PM recebe 403 ao tentar alterar
`power_kwp` no seu próprio projeto; os testes existentes (disjunção,
cobertura total de `ProjectUpdate`, `notes` continua PM-editável)
continuam a passar sem alteração.

## D-036 — Repetir a promoção depois de um rollback: nunca um segundo projeto

**Problema encontrado:** `rollback_promotion` (D-017) desativa o projeto
(caso `create_new`) ou restaura os valores anteriores (caso
`update_existing`/`link_existing`), e deixa o registo de staging em
`pending_review`. Nenhuma função existente devolvia esse registo a
`ready_to_promote` — `promote_staging_record` exige exatamente esse
estado, `resolve_conflict` exige `conflict`. Pior: mesmo que alguém forçasse
manualmente `status='ready_to_promote'` num registo `resolved_action=
'create_new'` já revertido, promover outra vez criaria um **segundo**
`Project` com o mesmo `external_id` — violando a restrição UNIQUE
`(source_system, external_id)` de `ProjectExternalId` já a meio da
transação, ou pior, duplicando o projeto se a violação não fosse
apanhada a tempo. Isto é exatamente o cenário "promover → algo está
errado → reverter → corrigir → promover outra vez" que uma migração real
dos 295 projetos vai precisar.

**Decisão:** `app/migration/staging.py:retry_promotion_after_rollback` —
passo explícito e obrigatório entre um rollback e uma nova promoção (nunca
automático, tal como `resolve_conflict`/`promote_staging_record` já eram
dois passos distintos):

- Só aceita um registo `pending_review` com `reverted_at` preenchido
  (ou seja, que passou mesmo por `rollback_promotion`) — rejeita qualquer
  outro estado, incluindo um registo nunca promovido.
- Se `resolved_action` era `'create_new'`, reescreve para
  `'update_existing'` apontado ao `promoted_project_id` já existente —
  **nunca volta a passar por `create_new`**, eliminando a via de
  duplicação. Para `'update_existing'`/`'link_existing'`, o alvo já
  estava certo, sem alteração.
- Reativa o projeto (`is_active=True`) se necessário, com uma entrada de
  `project_history` própria (fonte nova `migration_retry`, distinta de
  `migration_rollback` — nunca esconde que uma reativação aconteceu numa
  entrada que parece um rollback).
- Reaplica a mesma verificação de PM (`_finalize_status_given_pm`) das
  outras etapas — nunca duas lógicas divergentes sobre quando promover.

Endpoint novo, mesma permissão (`migration.resolve`):
`POST /api/migration/staging-records/{id}/retry-promotion`.

**Testado em** `tests/test_staging_persistence.py` (3 testes: caso
`create_new` confirma mesmo `project.id`, nenhuma duplicação de
`ProjectExternalId`, contagem de projetos inalterada; caso
`update_existing` confirma reaplicação do campo; rejeição de um registo
nunca revertido) e `tests/test_migration_api.py` (2 testes: ciclo completo
via API — promover → reverter → repetir → promover, mesmo `project_id`; e
a permissão `migration.resolve` exigida, PM sem essa permissão recebe
403).

## D-037 — Ingestão controlada para staging: comando administrativo, modo staging-only, contagens de revisão

**Decisão:** `app/cli/ingest_staging.py` — comando de linha de comandos
(`python -m app.cli.ingest_staging --file <export.json> [--actor-email
...]`), a única forma de invocar `ingest_export` fora dos testes. Nunca um
endpoint HTTP (D-026 já excluía isso deliberadamente da API).

- **Modo staging-only:** `assert_staging_only_environment` recusa-se a
  correr com `APP_ENV=production` — a migração real passa sempre primeiro
  por `staging` para revisão manual da fila de conflitos
  (docs/DATA_MIGRATION_RUNBOOK.md), nunca diretamente para produção por
  este comando. `local`/`test` continuam permitidos, para ensaiar o fluxo
  com fixtures sintéticas. Segunda barreira independente: em `production`
  real (configuração completa — D-032), `get_settings()` já teria
  bloqueado o processo inteiro no arranque (`AUTH_ENABLED`, PostgreSQL,
  etc.) antes mesmo deste comando correr — mas esta verificação cobre
  também o caso (impossível em produção real, mas possível num ambiente
  mal configurado) de alguém correr o comando com `APP_ENV=production`
  apontado a uma base de dados que não devia.
- **Contagens de revisão** (`app/migration/staging.py:summarize_import_batch`):
  `projects_seen`, `ready_to_promote`, `conflicts`, `distinct_pm_names`,
  `with_email`, `with_contact`, `with_coordinates` — sempre derivadas de
  `mapped_fields_json` já persistido, nunca relidas do payload bruto (para
  nunca divergir de `_map_legacy_fields`). Nunca inclui nada sobre
  `projects` — só sobre os registos de staging deste lote.
- **`--actor-email` opcional** — quando fornecido, tem de corresponder a um
  `User` ativo já existente (nunca inventa nem ignora silenciosamente um
  email desconhecido); grava `ImportBatch.started_by_person_id`.
- **Nunca escreve em `projects`** (comportamento herdado de `ingest_export`,
  sem alteração) — a mensagem final do comando lembra sempre isto e aponta
  para o endpoint de revisão da fila de conflitos.

**Testado em** `tests/test_ingest_staging_cli.py` (10 testes): barreira
staging-only (produção rejeitada, os restantes ambientes permitidos);
nunca escreve em `projects`; payload preservado verbatim; contagens
corretas contra a fixture sintética (`synthetic_legacy_export.json`, 3
projetos: 2 PMs distintos, 2 com email, 2 com contacto, 2 com
coordenadas); resolução de `--actor-email` (existente, desconhecido,
omitido). Validado manualmente também via linha de comandos: recusa
correta em `APP_ENV=production` (bloqueado já pela validação de
configuração — D-032) e execução completa com resumo correto em `local`.

## D-038 — Roadmap funcional reordenado: Dashboard → Workflow → Migração → Inventário → Graph → Claude

**Decisão:** `docs/PLAN.md` renumerado por pedido explícito — a ordem de
prioridade passa a ser Dashboard inicial (Fase 2, nova) → Workflow de
projetos (Fase 3, nova) → Migração real dos 295 projetos (Fase 4, era
Fase 2) → Inventário e pedidos de material (Fase 5, sem alteração de
número) → Microsoft Graph real (Fase 6, era Fase 3) → Claude — propostas
de agenda, preparação de emails e relatórios, sempre com aprovação humana
(Fase 7, era Fase 7, âmbito reduzido — ver abaixo). ClickUp real (Fase 8,
era Fase 4) e Biblioteca documental (Fase 9, era Fase 6) não faziam parte
da ordem de seis itens pedida — mantidos no roadmap, colocados depois
dessas seis, sem prioridade relativa inventada; cada secção documenta a
sua própria dependência técnica (ClickUp de Fase 4, Documental de Fase 6).

**Duas fases novas, só roadmap nesta revisão (sem implementação):**
- **Fase 2 — Dashboard inicial:** estatísticas semanais, trabalhos
  pendentes, visão operacional, visão comercial, férias e aniversários.
  Nenhuma métrica/campo obrigatório foi assumido — "férias e aniversários"
  não tem sequer modelo de dados hoje (`Person` sem data de nascimento,
  sem entidade de ausências). Registado como pergunta 18 em
  `docs/OPEN_QUESTIONS.md`.
- **Fase 3 — Workflow de projetos:** o modelo de dados
  (`phases`/`workflow_stages`/`workflow_subtasks`/
  `project_stage_progress`/`project_subtask_progress`) já existe desde a
  Fase 0, semeado só com um processo genérico de exemplo — carregar o
  processo real de 6 fases da Solcor e definir os requisitos para avançar
  de fase (hoje nada bloqueia isto) ficam como decisão de negócio,
  registada como pergunta 19.

**Consequência aceite:** a Fase 4 (Migração) só depende tecnicamente da
Fase 1, não das Fases 2/3 — a nova sequência é uma escolha de prioridade
de negócio, não uma dependência técnica; a tabela "Dependências entre
fases" em `docs/PLAN.md` documenta isto explicitamente para não passar a
impressão de um bloqueio que não existe. O âmbito da Fase 7 (Claude) fica
reduzido face à versão anterior do roadmap: a pesquisa documental (RAG)
sobre a biblioteca dependia da Biblioteca Documental, que passa a vir
depois (Fase 9) — fica registada como um incremento futuro de Claude,
não como parte do âmbito imediato desta fase.

**Nada disto implica trabalho de implementação nesta sessão** — pedido
explícito era só reordenar o roadmap, nunca implementar as integrações
externas ou o dashboard/workflow em si.
# Fase 1.5 — MVP dashboard/workflow

Pedido explicitamente pelo negócio como o MVP a entregar antes da Fase 2
(migração real dos 295 projetos) — ver a secção "MVP recomendado" em
`docs/PLAN.md` para a justificação de porque este MVP avança antes daquele.
Nenhuma integração real (Graph/ClickUp/Financial/Claude), sem envio de
email, sem eventos reais, sem mapas/inventário/pedidos de
material/biblioteca documental, sem migração de dados reais — tudo isso
continua fora de âmbito e documentado no roadmap (`docs/PLAN.md`).

## D-039 — `Task` como entidade nova, não reaproveitamento de `Phase`/`WorkflowStage`/`ProjectSubtaskProgress`

**Contexto:** já existia em `app/models/workflow.py` +
`app/models/project.py` um sistema de processo fixo — `Phase` →
`WorkflowStage` → `WorkflowSubtask` (catálogo) e
`ProjectStageProgress`/`ProjectSubtaskProgress` (progresso booleano por
projeto). O pedido deste MVP é uma tarefa genérica com responsável,
prioridade, prazo, notas, estado (`todo`/`in_progress`/`blocked`/`done`/
`cancelled`) e histórico de alterações — criável/editável livremente pelo
utilizador, não só um checklist de catálogo fixo.

**Decisão:** criar `app/models/task.py` (`Task`, `TaskHistory`) como
entidade nova, em vez de alargar `ProjectSubtaskProgress` com todos estes
campos. As duas estruturas **coexistem nesta fase, sem nenhuma migração de
dados entre elas** — `Phase`/`WorkflowStage`/`WorkflowSubtask` continuam
semeados (`seed_workflow`) mas sem endpoint nem UI ligados nesta fase (já
assim antes desta sessão — ver "Âmbito deixado de fora da Fase 1").

**Porquê não reaproveitar:** `ProjectSubtaskProgress` é uma tabela de
junção `(projeto, subtarefa) → done`, com a subtarefa definida uma vez no
catálogo (`WorkflowSubtask`) e partilhada por todos os projetos —
alargá-la para ter responsável/prioridade/prazo/notas próprios por
projeto exigiria duplicar `WorkflowSubtask` por projeto (perdendo a
vantagem de catálogo único) ou mover esses campos para uma tabela nova de
qualquer forma. Criar `Task` direta e simples é menos código e mais claro
do que forçar um encaixe.

**Consequência assumida:** o sistema tem agora dois modelos de "trabalho a
fazer" com propósitos ligeiramente diferentes — decisão consciente,
registada aqui e em `docs/OPEN_QUESTIONS.md` como pergunta em aberto para
uma fase futura decidir se compensa unificar (ex.: `WorkflowSubtask`
passar a gerar automaticamente uma `Task` por projeto).

## D-040 — Máquina de estados de `Task`: `blocked` nunca salta direto para `done`; `done`/`cancelled` só reabrem para `todo`/`in_progress`

**Decisão** (`app/services/tasks.py:TASK_TRANSITIONS`):

```text
todo         -> todo, in_progress, blocked, done, cancelled
in_progress  -> in_progress, todo, blocked, done, cancelled
blocked      -> blocked, todo, in_progress, cancelled       (nunca done)
done         -> done, todo, in_progress                     (reabertura)
cancelled    -> cancelled, todo                              (reabertura)
```

Uma transição para o mesmo estado é sempre um no-op permitido (sem gerar
histórico); qualquer transição fora desta tabela é rejeitada com `400` e
sem qualquer escrita (`InvalidTaskTransition`,
`app/api/routes_tasks.py`).

**Porquê:** o pedido explícito era "criadas, editadas, atribuídas,
concluídas, reabertas" — não uma máquina de estados detalhada, por isso a
regra concreta é uma decisão de implementação, não um requisito do
negócio (registado aqui para revisão, não assumido como definitivo). A
única regra de negócio considerada não-arbitrária: uma tarefa bloqueada
não devia poder "saltar" para concluída sem primeiro ser desbloqueada —
sinaliza um erro operacional real (ex. marcar como feito por engano sem
resolver o bloqueio). `done`/`cancelled` só reabrirem para `todo`/
`in_progress` (nunca um do outro diretamente) mantém o histórico legível:
reabrir sempre volta ao início do fluxo ativo, nunca troca diretamente
entre dois estados terminais.

`completed_at` é sempre derivado do lado do servidor a partir da
transição de/para `done` — nunca um campo editável em `TaskUpdate`
(`app/schemas/tasks.py`), para não haver uma segunda fonte de verdade
sobre "quando foi concluída".

**Testes:** `tests/test_tasks_api.py` (transição válida com histórico e
`completed_at`; `blocked → done` rejeitado; `cancelled` só reabre para
`todo`; reabrir `done` limpa `completed_at`).

## D-041 — Dashboard: endpoint de resumo único, calculado inteiramente no servidor; semana sempre em Europe/Lisbon; indicadores operacionais só contam projetos ativos

**Decisão:** `GET /api/dashboard/summary` (`app/services/dashboard.py`)
devolve todos os indicadores da página inicial já calculados e já
filtrados pela visibilidade do utilizador — o frontend nunca soma/filtra
listas completas para produzir uma métrica (requisito explícito: "os
dados devem vir de endpoints próprios de resumo/dashboard").

**Fuso horário centralizado:** `app/utils/timezones.py` (`today_lisbon()`,
`week_range_lisbon()`) é o único ponto que sabe que "hoje"/"esta semana"
usam `Europe/Lisbon` — usado por `Task.is_overdue`,
`app/services/tasks.py` (filtro `overdue_only`), e
`app/services/dashboard.py`. Sem isto, um servidor alojado noutro fuso
(UTC, por exemplo) calcularia "esta semana" de forma diferente do que uma
pessoa em Portugal veria no calendário. Dependência nova: `tzdata` — o
Windows (e alguns Linux mínimos) não trazem a base de dados IANA que
`zoneinfo` precisa; confirmado neste ambiente de desenvolvimento
(`ZoneInfoNotFoundError` sem o pacote).

**Só projetos ativos entram nos indicadores operacionais** —
`active_projects_count`, "a começar em 30 dias", "sem PM", "dados em
falta" já filtravam por `is_active` desde a primeira versão; durante a
verificação manual em navegador desta sessão encontrou-se um bug real: as
tarefas de um projeto inativo (`Instalação Sintética H — Inativa`, com
checklist padrão semeada de propósito para testar isto) apareciam em
"visitas técnicas pendentes"/"comissionamentos pendentes"/"tarefas
atrasadas", porque esses indicadores vinham de `visible_tasks_query` sem
o mesmo filtro. Corrigido filtrando pelas tarefas do **próprio projeto**
(`t.project.is_active`), não pela lista de projetos ativos já calculada —
para não excluir por engano uma tarefa atribuída diretamente ao
utilizador num projeto ativo que não é o seu como PM. Teste de regressão:
`tests/test_dashboard.py::test_tasks_of_inactive_projects_never_appear_in_operational_lists`.

**Testes:** `tests/test_dashboard.py` (escopo por perfil, semana em
Europe/Lisbon, cada indicador com pelo menos um caso semeado real).

## D-042 — `Absence`: modelo mínimo, sem fluxo de aprovação nesta fase

**Decisão:** `Absence` (`app/models/absence.py`) tem só os campos
pedidos — pessoa, data inicial, data final, tipo (`ferias`/
`baixa_medica`/`outro`), nota, estado (`aprovada`/`cancelada`). Criar uma
ausência já a marca `aprovada` — não existe um estado `pendente` nem um
passo de aprovação por outra pessoa. Depois de criada, só `status` e
`note` são editáveis (`AbsenceUpdate`) — alterar datas/pessoa/tipo exige
cancelar e criar de novo, para o registo nunca ficar ambíguo sobre "o que
mudou realmente" sem precisar de histórico próprio (ao contrário de
`Task`/`Project`, `Absence` não tem uma tabela de histórico — âmbito
deliberadamente mínimo).

**Porquê:** o pedido foi "criar entidade... e uma interface simples para
consultar e registar férias" — não descreveu um fluxo de
pedido→aprovação. Assumir `aprovada` por omissão evita inventar um
fluxo que o negócio pode não querer. **Registado como pergunta em
aberto** em `docs/OPEN_QUESTIONS.md`: se for necessário um fluxo real de
aprovação (ex. PM pede, Chefe aprova), isto exige um novo estado
`pendente` e uma ação de aprovação — mudança pequena e aditiva quando
decidido.

**Testes:** `tests/test_absences_api.py` (criação fica `aprovada`, datas
inválidas rejeitadas, permissões por perfil, cancelamento).

## D-043 — Aviso de fotos pendentes: reaproveita a tarefa padrão `fotos_drive`, sem novo campo booleano

**Decisão:** o pedido "quando uma tarefa de visita técnica ou
comissionamento for concluída, mostrar um aviso persistente para
confirmar que as fotos foram colocadas na Drive" é resolvido inteiramente
a partir das tarefas já existentes — `ProjectRead.photos_pending_warning`
(`app/services/projects.py:compute_project_task_summary`) é `True` quando
pelo menos uma tarefa `visita_tecnica`/`comissionamento` está `done` **e**
a tarefa `fotos_drive` desse projeto ainda não está `done`. Sem nenhum
campo novo em `Project` nem em `Task` — o aviso desaparece sozinho assim
que alguém marcar "Colocar fotos na Drive" como concluída.

**Porquê:** a checklist padrão de 5 tarefas por projeto já inclui
"Colocar fotos na Drive" como a última etapa (pedido explícito da secção
2) — usá-la como o próprio sinal do aviso evita um segundo lugar para a
mesma informação poder divergir (ex. um booleano `photos_confirmed` que
alguém esquece de sincronizar com o estado real da tarefa).

**Nesta fase o aviso é só informativo** (banner na página do projeto,
ícone ⚠️ na lista de projetos) — nunca bloqueia nenhuma ação, tal como
pedido explicitamente ("nesta fase o aviso é apenas interno; não fazer
integração com a Drive").

**Testes:** `tests/test_project_task_summary.py` (aviso só quando visita/
comissionamento concluída e fotos não; desaparece ao concluir fotos);
validado também manualmente no browser (ver verificação end-to-end desta
sessão).

## D-044 — Visibilidade de férias/aniversários no dashboard ligada a `absence.view_all`/`absence.view_own`

**Decisão:** quem tem `absence.view_all` (Chefe de Operações,
Administrador) vê as férias/ausências e os aniversários de toda a gente
no dashboard; quem só tem `absence.view_own` (PM, Comercial, Financeiro)
só vê os seus próprios — nunca os de terceiros. O mesmo par de permissões
controla os dois indicadores (não há uma permissão separada só para
aniversários) porque são a mesma categoria de informação pessoal de baixa
sensibilidade, tratada com o mesmo nível de acesso.

**`PersonRead` (`GET /api/people`, disponível a qualquer utilizador
autenticado para preencher filtros/dropdowns) nunca inclui `birth_date`**
— só o endpoint do dashboard expõe data de nascimento, e só ao subconjunto
de pessoas que a permissão do utilizador autoriza (`BirthdayMini`, via
`_birthday_scoped_people_query` em `app/services/dashboard.py`). Evita que
adicionar `birth_date` a `Person` vaze essa informação por um caminho não
pensado para isso.

**Porquê esta escolha e não "todos veem tudo":** o pedido dizia
explicitamente "não expor informação sensível desnecessária" na secção de
férias/aniversários — restringir por omissão é mais seguro do que expor
por omissão e ter de restringir depois. **Registado como pergunta em
aberto** em `docs/OPEN_QUESTIONS.md`: pode ser que o negócio prefira que
todos vejam as férias/aniversários da equipa toda (prática comum em
empresas pequenas) — mudar é trivial (dar `absence.view_all` a mais
perfis), mas decidido aqui pelo lado mais restritivo até confirmação.

**Testes:** `tests/test_dashboard.py::test_pm_without_absence_view_all_only_sees_own_birthday`.

## D-045 — Matriz de permissões alargada: `task.*`/`absence.*`, e o que cada perfil ganhou

**Decisão** (`app/security/catalog.py`):

| Permissão | Chefe Operações | PM | Comercial | Financeiro |
|---|---|---|---|---|
| `task.view_all` / `task.view_own` | `view_all` | `view_own` | `view_all` | `view_all` |
| `task.edit_all` / `task.edit_own` | `edit_all` | `edit_own` | — | — |
| `absence.view_all` / `absence.view_own` | `view_all` | `view_own` | `view_own` | `view_own` |
| `absence.manage_all` / `absence.manage_own` | `manage_all` | `manage_own` | `manage_own` | `manage_own` |

`can_edit_task`/`can_create_task`/`can_view_task` e
`can_manage_absence`/`can_view_absence`/`can_create_absence_for`
(`app/security/permissions.py`) seguem exatamente o mesmo padrão já
estabelecido por `can_edit_project`/`can_view_project` — nunca um "papel"
lido do cliente, sempre a permissão + a relação (PM do projeto, ou
responsável direto pela tarefa/ausência).

**Comercial e Financeiro passam a ter `task.view_all`** (consistente com
o `project.view_all` que já tinham) mas **não** `task.edit_all`/`_own` —
continuam só de leitura sobre tarefas, tal como já eram só de leitura
sobre projetos (`test_comercial_is_read_only_on_tasks`). Nenhuma alteração
a permissões pré-existentes (`project.*`, `cost.*`, etc.) — só aditivo.

**Sobre dados financeiros na vista Comercial** (requisito explícito: "a
vista Comercial não deve mostrar dados financeiros que não tenha
permissão para consultar"): nenhum indicador do dashboard, da lista de
projetos, ou de tarefas desta fase depende de `cost.view` ou mostra
qualquer valor monetário — o módulo Financial está inteiramente fora
deste MVP. O requisito fica automaticamente satisfeito por
não haver dado financeiro nenhum para mostrar; quando a Fase 5
(custos/margens) for construída, quem desenhar essas vistas tem de
repetir este cuidado explicitamente (não há nada nesta fase que o faça
automaticamente para telas futuras).

## D-046 — Frontend: Vitest + Testing Library como primeira infraestrutura de testes automatizados

**Decisão:** `vitest`, `@testing-library/react`, `@testing-library/jest-dom`
e `jsdom` adicionados a `devDependencies`; configuração em
`frontend/vitest.config.ts` (ambiente `jsdom`, `globals: true`, setup em
`src/setupTests.ts`); `npm test` corre `vitest run`. Não existia nenhuma
suite de testes de frontend antes desta fase (`docs/PLAN.md` já
documentava isto como lacuna conhecida — "Frontend (além do build e
validação manual): sem testes automatizados de UI ainda").

**Cobertura desta fase:** funções puras (`src/utils/dates.ts`,
`src/utils/dates.test.ts`), invariantes da máquina de estados espelhada no
cliente (`src/api/taskTransitions.test.ts` — mesma tabela de D-040, só
para desenhar a UI, nunca a fonte de verdade), e um teste de fumo do
painel inicial com a API mockada (`src/pages/Home.test.tsx`) confirmando
que os indicadores devolvidos pelo endpoint aparecem no ecrã. Não é
cobertura exaustiva de componentes — âmbito deliberadamente pequeno para
esta fase, ver `docs/OPEN_QUESTIONS.md` sobre Playwright/Cypress
end-to-end como possível passo seguinte.

## D-047 — `/` passa a ser o painel operacional; conteúdo anterior movido para `/status`

**Decisão:** `frontend/src/pages/Home.tsx` (novo) é a página inicial —
antes, `/` redirecionava para `/projects` e a página `Dashboard.tsx`
(saúde do backend + utilizador de desenvolvimento) vivia em `/status`.
Esse conteúdo técnico foi preservado tal como estava, só renomeado para
`SystemStatus.tsx`, continua acessível em `/status` como diagnóstico —
nada foi perdido, só deixou de ser a primeira coisa que se vê ao entrar
(requisito explícito: "criar a página `/` como página principal depois do
login").

**Testes:** `tests/test_dashboard.py` (backend); `Home.test.tsx`
(frontend, ver D-046).

## D-048 — Integração de PR #1 (hardening) + PR #2 (MVP) em `mvp-ready`

**Contexto:** os dois PRs foram desenvolvidos em paralelo a partir do
mesmo commit em `main` (`b39be01`), cada um continuando a numeração de
decisões a partir de D-031 — resultando em duas séries de decisões D-032
a D-040/D-038 incompatíveis, e conflitos reais em `docs/PLAN.md`,
`docs/DECISIONS.md`, `docs/OPEN_QUESTIONS.md`, `README.md`,
`.github/workflows/ci.yml` e `frontend/package.json`/`vitest.config.ts`.

**Decisão:**
1. `mvp-ready` parte de `origin/main`, integra primeiro
   `staging-prod-hardening` (fast-forward, sem conflitos — as duas séries
   de commits não se sobrepõem em código) e só depois
   `mvp-dashboard-workflow` (onde os conflitos reais acontecem).
2. As decisões do MVP (D-032 a D-040 na numeração original do PR #2) foram
   renumeradas para D-039 a D-047, preservando a numeração D-032 a D-038
   do hardening (PR #1) inalterada — evita reescrever qualquer referência
   já feita a D-032..D-038 fora deste merge.
3. `docs/PLAN.md`: a numeração de fases do hardening (Fase 4 = Migração,
   Fase 5 a 9 = Inventário/Graph/Claude/ClickUp/Biblioteca) foi mantida
   sem alteração — evita quebrar as várias referências cruzadas a "Fase N"
   espalhadas pelo documento. As antigas Fase 2 (Dashboard inicial) e
   Fase 3 (Workflow de projetos), que eram só roadmap por implementar,
   foram anotadas como cobertas pela nova Fase 1.5 (MVP, implementada) —
   ver essas secções para o detalhe de o que ficou coberto e o que não
   (o processo fixo `Phase`/`WorkflowStage` continua sem endpoints).
4. `frontend/package.json`: Vitest mantido em `3.2.7` (nunca voltar a
   2.x — vulnerabilidade crítica que motivou o hardening). `vite`
   atualizado de `5.4.11` para `6.4.3` — necessário para eliminar
   GHSA-fx2h-pf6j-xcff (`server.fs.deny` bypass no Windows, severidade
   alta, CVSS 7.5), que não tem correção na série 5.x; compatível com
   `@vitejs/plugin-react@4.3.4` (aceita `vite ^6.0.0`) e com a suite
   Vitest existente — `npm run lint`/`npm test`/`npm run build`
   confirmados depois da atualização. Vulnerabilidades moderadas
   remanescentes (`@vitest/mocker`/`vitest` — precisa de Vitest 4.x;
   `react-router`/`react-router-dom` — precisa de major 7.x) não foram
   corrigidas nesta revisão para não forçar upgrades major
   desnecessários fora do que foi pedido — mesma política já registada
   acima para o `npm audit` da Fase 1.
5. `.github/workflows/ci.yml`/`vitest.config.ts`: combinados sem perda —
   o job de frontend corre `lint` + `test` (Vitest) antes do `build`
   (D-039 do PR #2, preservado), e a configuração de testes junta
   `globals`/`setupFiles` (suite de UI, D-046) com o `include` explícito
   do hardening.
6. `Task` mantém-se como a única unidade operacional usada pelo MVP; os
   modelos antigos `Phase`/`WorkflowStage`/`WorkflowSubtask` não foram
   tocados nem migrados — decisão explícita de não arriscar uma migração
   de dados agora (ver `docs/OPEN_QUESTIONS.md` perguntas 22 e 24). Um
   futuro formulário de visita técnica/comissionamento tem de escolher
   uma única fonte de verdade entre as duas antes de ser construído.

**Validação pós-merge:** 224 testes de backend a passar + 2 skipped
(SQLite; PostgreSQL não pôde ser validado neste ambiente Windows por
falta de Docker — mesmo bloqueio já documentado em D-021 — fica para o
job `backend-postgres` do CI em `GitHub Actions`); 18 testes Vitest no
frontend; `npm run build`/`npm run lint` sem erros; testado manualmente
no browser com os 5 utilizadores sintéticos do seed (permissões de
PM/Chefe/Comercial/Financeiro/Admin, aviso de fotos pendentes,
transições de estado inválidas bloqueadas, validação de datas de férias,
projeto inativo excluído do dashboard, fluxo de ingestão para staging
com contagens/conflitos/promoção/rollback).

## D-049 — Preparação para staging: piloto de importação, seed bloqueado, .env.staging.example

**Contexto:** antes de um primeiro piloto com dados reais em staging,
faltavam três coisas: uma forma segura de testar 5 a 10 projetos reais
sem arriscar os 295 de uma vez; uma barreira de código (não só
disciplina documentada) contra o seed sintético correr em staging; e
exemplos de configuração dedicados a staging, distintos dos de
local/dev, com todos os valores obrigatórios já assinalados.

**Decisão:**

1. `app.migration.staging.ingest_export` ganha `only_external_ids`,
   `limit` e `dry_run`, expostos em `app.cli.ingest_staging` como
   `--only-ids`, `--limit`, `--dry-run` — permite pré-visualizar
   (contagens, conflitos) e depois ingerir só um subconjunto do export
   real, sem tocar nos restantes 285-290 projetos. `dry_run=True` corre
   exatamente a mesma lógica (incl. deteção de duplicados contra a base
   de dados real) mas nunca commita — o chamador reverte a transação
   depois de ler o resumo, para não deixar nenhum vestígio nem em
   `import_batches`/`staging_project_records`.
2. `app.cli.ingest_staging` recusa-se a ler um ficheiro que esteja
   dentro da árvore de trabalho do Git e que **não** esteja coberto pelo
   `.gitignore` (`assert_file_is_not_trackable_by_git`) — uma segunda
   barreira, em código, contra um export com dados reais ser
   acidentalmente `git add`ado, além da disciplina manual já documentada
   em `docs/DATA_MIGRATION_RUNBOOK.md`. Nunca falha "a fechado": qualquer
   erro a invocar o Git (ausente, timeout, ambiente sem repositório)
   deixa passar — o disparador real (`.gitignore` + revisão manual de
   `git status`) continua sempre ativo.
3. `app.migration.seed_dev.run_seed()` recusa-se a correr em
   `staging`/`production` (`assert_seed_allowed_environment`, mesma
   barreira `HARDENED_ENVIRONMENTS` de `app/config.py`) — antes desta
   revisão, nada impedia tecnicamente correr o seed sintético contra uma
   base de dados de staging, só a disciplina documentada em
   `docs/STAGING_CHECKLIST.md`.
4. `backend/.env.staging.example` e `frontend/.env.staging.example`
   (novos, distintos de `.env.example` de local/dev): todos os valores
   obrigatórios em staging já com placeholder explícito (nunca um valor
   plausível-mas-falso que alguém possa esquecer-se de substituir),
   comentários a explicar a origem de cada um (qual app registration
   Entra ID, qual secção do runbook). `docs/STAGING_RUNBOOK.md` (novo) é
   o procedimento operacional completo — comandos exatos para as duas
   app registrations Entra ID, PostgreSQL, migrações, os 5 utilizadores,
   health checks, logs, backups/rollback, testes de aceitação, o piloto
   de 5 a 10 projetos, e como parar o ambiente; `docs/STAGING_CHECKLIST.md`
   passa a ser só o registo de sign-off, apontando para lá.

**Por decidir, não assumido nesta revisão (ver `docs/OPEN_QUESTIONS.md`):**
quem cria `Person`/`User`/`UserRole` reais em staging antes do primeiro
provisionamento (não existe ainda um script de seed dedicado a staging,
só o SQL/Python manual documentado em `docs/STAGING_RUNBOOK.md` secção
9.1); alojamento concreto (condiciona os comandos exatos de arranque,
logs e backups automáticos); "who can consent" no scope
`access_as_user`; ativar `ENTRA_JIT_LINK_BY_EMAIL` em staging (por
omissão, desligado).

**Testes:** `tests/test_ingest_staging_cli.py` (+8 — dry-run, subconjunto
por IDs/limite, barreira do Git), `tests/test_seed_dev_staging_guard.py`
(4, novo).
