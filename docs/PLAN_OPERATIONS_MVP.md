# Plano — MVP de Operações (Fase 2)

> Ver `docs/PLAN.md` para o roadmap geral, `docs/ARCHITECTURE_PROPOSAL.md` para
> a arquitetura-alvo, e `docs/DECISIONS.md` para o histórico de decisões
> (D-001 a D-051). Este documento cobre especificamente o âmbito pedido para
> o "MVP de Operações" — inventário com reservas, dados completos de
> instalação/licenciamento, mapa operacional, calendário ligado a tarefas,
> importação de notas iniciais e do Excel de licenciamento, e a página única
> de metas e indicadores — construído sobre a Fase 1.5/1.6/1.7 já entregue
> (dashboard, tarefas, férias, demo).

## 0. Como este documento está organizado

O pedido original tem 24 secções e é, à letra, várias semanas de trabalho de
equipa (≈15 entidades novas, 30+ endpoints, dois importadores de ficheiros,
mapa com fornecedores/pendências, livro de reservas de inventário,
reformulação de permissões de tarefas, página de metas fundida com
histórico, suites de teste completas backend+frontend, migrações,
documentação). Consistente com a forma como este repositório sempre entregou
(ver `docs/PLAN.md` — Fase 0 → 0-hardening → 1 → 1-hardening → 1.5 → 1.6 →
1.7, cada uma um incremento testado, nunca tudo de uma vez), este MVP é
entregue em **fatias (slices)**, cada uma com o mesmo rigor de testes e
permissões já estabelecido, não como mocks visuais.

- **Secção 1** — arquitetura e decisões transversais (vale para todas as
  fatias).
- **Secção 2** — modelo de dados completo (entidades-alvo de todo o pedido,
  mesmo as que só chegam numa fatia seguinte — para não haver duas fontes de
  verdade sobre o desenho final).
- **Secções 3 a 9** — cada área funcional do pedido (inventário, dados de
  projeto, mapa, calendário, tarefas, metas, importações), com o desenho
  completo e uma marca explícita **[Fatia 1 — nesta PR]** ou **[Fatia
  seguinte]** por funcionalidade.
- **Secção 10** — o que a Fatia 1 (esta PR) entrega de facto, testado.
- **Secção 11** — riscos, decisões assumidas, e perguntas registadas em
  `docs/OPEN_QUESTIONS.md`.

## 1. Arquitetura e decisões transversais

Mantém-se tudo o que já está decidido (D-001 a D-051): monólito modular,
UUID como chave primária, `Person`/`User` separados, permissões só no
servidor, histórico append-only, `Numeric`/`Decimal` para dinheiro,
adapters mock/fallback para integrações externas, staging+promoção explícita
para qualquer ingestão de dados externos. Nada disto muda nesta fase.

Decisões novas, transversais a todo o MVP de Operações:

- **Quantidades de inventário passam de `Float` para `Numeric(14, 3)`**
  (`app/models/inventory.py:QUANTITY`, novo). Já era pedido explícito desta
  fase ("usar Numeric/Decimal, não Float, para quantidades") e corrige uma
  inconsistência com o resto do modelo (`cost_lines.amount` já usa
  `Numeric` desde D-018, só as quantidades de inventário tinham ficado de
  fora, ver nota em D-018). Migração reversível: `Float`→`Numeric` primeiro,
  `Numeric`→`Float` no downgrade, sem perda de dados (SQLite/PostgreSQL
  ambos suportam a conversão direta para os intervalos de valores esperados
  aqui).
- **Todas as tabelas novas seguem exatamente os mesmos mixins** (`UUIDPk`,
  `TimestampMixin`), a mesma convenção de nomes (`snake_case`, FK explícita),
  e o mesmo padrão de histórico append-only (`*_history` sem `updated_at`)
  onde o pedido exige auditoria de alterações de campo.
- **Nenhuma tabela nova introduz um total editável diretamente** onde já
  existe um livro de movimentos (inventário) — reforça o princípio já
  aplicado a `cost_lines`/`inventory_movements`.
- **Permissões novas seguem o padrão `<recurso>.<ação>[_all|_own]`** já
  usado em `app/security/catalog.py`, e são sempre resolvidas em
  `app/security/permissions.py` a partir da base de dados — nunca
  hardcoded por papel no código de rota.
- **Nenhuma integração externa nova é ligada de verdade** — o mapa usa um
  provider de tiles configurável (nunca assumido), e as importações nunca
  chamam serviços externos (sem geocoding automático nesta fase, à imagem
  da decisão já tomada para a Fase 1 — ver `docs/ARCHITECTURE_PROPOSAL.md`
  secção 5, `lat`/`lon`).

## 2. Modelo de dados completo (alvo)

### 2.1 Projeto — dados satélite

| Entidade | Estado |
|---|---|
| `ProjectExternalId` | **já existe** (`project_external_ids`) — é exatamente o "ProjectExternalIdentifier" pedido; unicidade por `(source_system, external_id)`, `external_reference`/`source_file_hash` ficam como campos novos nesta fase (ver 2.2). |
| `ProjectInstallationData` | **novo — Fatia 1.** Um registo 1:1 por projeto: cliente/NIF (já parcialmente em `Project`, ver nota abaixo), pessoa de contacto/função/email/telefone (complementam `client_contact`/`client_email`), morada/distrito/concelho, potência, nº painéis, potência dos painéis, inversores, baterias, backup, carregadores VE, tipo de instalação, injeção, O&M, observações. |
| `ProjectLicensingData` | **novo — Fatia 1.** 1:1 por projeto: nº UPAC, nº DGEG, nº de cadastro, estado do licenciamento, data de registo, data de pedido de certificação, entidade inspetora, data de inspeção, data de certificado, instalador, comercializador, produção anual, comentários. |
| `ProjectCommunicationData` | **novo — Fatia 1.** 1:1 por projeto, permissão dedicada (`project.view_communication_data`/`project.edit_communication_data`): operador, número GSM/M2M, identificador do cartão, estado da comunicação, observações. **Nunca guarda PIN/PUK/password/login/token** — campo de texto livre validado para rejeitar padrões óbvios de credenciais fica fora de âmbito (não é fiável); a regra é de processo (nunca inserir isso aqui) e de código (o modelo não tem campos para isso). |
| `SurplusContract` | **novo — Fatia seguinte** (depende do importador Excel, secção 9). |
| Rastreio por campo (origem/data de importação/lote/utilizador/valor anterior/valor novo) | **Fatia 1**, reaproveitando o padrão `ProjectHistory` já existente — cada `PATCH` a estes três modelos novos grava uma entrada por campo alterado, tal como `Project` já faz (D-025), com `source='ui'` ou `source='import_notes'`/`source='import_licensing'` quando vier de um importador (Fatia seguinte). |

**Nota sobre `client_name`/NIF:** `Project.client_name`/`client_contact`/
`client_email` já existem e continuam a fonte de verdade para identidade do
cliente; `ProjectInstallationData` não duplica esses três campos — só
acrescenta o que falta (NIF, morada estruturada, dados técnicos). Evita:
duas fontes de verdade discordantes para o mesmo dado.

### 2.2 Inventário

| Entidade | Estado |
|---|---|
| `InventoryLocation` | **novo — Fatia 1.** `code` (único), `name`, `location_type` (`central\|project\|vehicle\|supplier`), `project_id` (FK, nullable — só para `type='project'`), `is_active`. Seed cria `IDEALMINDE`/`central`, sem verificação hardcoded pelo nome em nenhum lugar do código (só pelo `code` quando o seed precisa de encontrar o registo que ele próprio criou). |
| `InventoryItem` | **alterado.** `min_stock`: `Float`→`Numeric(14,3)`. Resto inalterado. |
| `InventoryMovement` | **alterado.** `quantity`: `Float`→`Numeric(14,3)`. Ganha `location_id`/`destination_location_id` (FK `InventoryLocation`, nullable — nem toda entrada/consumo tem as duas pontas), `unit_cost` (`MONEY`, nullable), `idempotency_key` (`String`, único quando presente — pedido explícito "não permitir movimentações duplicadas"). Tipos de movimento ganham `consumo`/`devolucao` explícitos (o pedido distingue reserva/consumo/libertação/devolução como operações distintas — ver secção 3). |
| `ProjectMaterialRequirement` | **novo — Fatia 1.** `project_id`, `item_id`, `quantity_required` (`Numeric(14,3)`), `notes`, `source`, `created_by_person_id`. |

### 2.3 Mapa

| Entidade | Estado |
|---|---|
| `Supplier` | **já existe**, ganha `materials` (`Text`, lista livre — sem nova tabela de associação nesta fase, ver "decisões assumidas") e `is_active` (`Boolean`, novo). |
| `PickupPoint` | **novo — Fatia 1.** `name`, `supplier_id` (FK, nullable), `address`, `lat`/`lon`, `schedule`, `contact`, `materials`, `notes`, `is_active`. |
| `ProjectIssue` | **novo — Fatia 1.** `project_id`, `description`, `category` (`obra\|material\|documentacao\|visita\|outro`), `priority`, `status` (`aberta\|em_curso\|resolvida\|cancelada`), `assigned_to_person_id`, `due_date`, `lat`/`lon` (opcional — pode herdar do projeto), `related_task_id` (FK `Task`, nullable), `notes`, `visible_on_map`. Conversão para tarefa: endpoint dedicado que cria uma `Task` e preenche `related_task_id` — nunca duplica a entidade. |
| Configuração de tiles | **novo — Fatia 1**, em `Settings`: `MAP_TILE_URL`, `MAP_TILE_ATTRIBUTION`, `MAP_PROVIDER_ENABLED` (todas opcionais; sem elas, o endpoint do mapa continua a devolver dados, o frontend mostra aviso claro e a lista de locais como alternativa). |

### 2.4 Calendário

`Visit`/`CalendarEvent` já existem (Fase 0). **Alterado — Fatia 1**:
`CalendarEvent` ganha `task_id` (FK `Task`, nullable) — quando presente, a
camada de serviço valida sempre `CalendarEvent.project_id ==
CalendarEvent.task.project_id` antes de gravar (nunca à confiança do
cliente). Continua sem `graph_event_id` real (fica vazio — sem Microsoft
Graph nesta fase, D-010 mantém-se).

### 2.5 Metas e indicadores

| Entidade | Estado |
|---|---|
| `GoalPeriod` | **novo — Fatia 1.** `period_type` (`year\|quarter\|semester\|month`), `year`, `quarter`/`semester`/`month` (nullable conforme `period_type`), `metric` (`installations\|kwp\|projects_completed\|projects_certified\|power_installed\|power_delivered`), `target_value` (`Numeric`), `pm_person_id` (nullable — meta individual ou global), `scope` (`company\|pm`), `created_by_person_id`, `created_at`. Histórico de alterações de meta via uma tabela `GoalPeriodHistory` (append-only, mesmo padrão). |

### 2.6 Importação (modelo de staging dedicado)

| Entidade | Estado |
|---|---|
| `ImportBatch`/`StagingProjectRecord` | **já existem**, mas são específicos da migração de projetos legados (`app/migration/staging.py`) — **não reaproveitados tal como estão** para notas iniciais/Excel de licenciamento, que têm forma de conflito diferente (campo a campo, não projeto inteiro). |
| `FieldImportBatch`, `FieldImportRecord`, `FieldImportConflict` | **novo — Fatia seguinte** (importadores). Desenho: um lote por ficheiro (hash, origem, utilizador, timestamp), um registo por entidade-alvo detetada (projeto existente ou novo), um conflito por campo com valor divergente — cada conflito guarda valor antigo/novo/origem, exige resolução explícita antes de escrever em `ProjectInstallationData`/`ProjectLicensingData`/`Project`. Documentado em detalhe na secção 9; não implementado nesta PR — ver secção 10. |

## 3. Inventário — regras de negócio (contrato exato, Fatia 1)

Livro de movimentos, nunca saldo editável. Quatro números por
(item, projeto):

```
stock_fisico_central   = Σ movimentos na localização central (entrada − saída − consumo + devolução ± ajuste)
reservado[projeto]     = Σ reservas − Σ libertações − Σ consumos, para esse projeto
stock_disponivel       = stock_fisico_central − Σ reservado[*] (todas as reservas ativas, todos os projetos)
consumido[projeto]     = Σ consumos, para esse projeto
```

Operações (`app/services/inventory.py`, novo), todas transacionais
(uma transação SQL por operação) e idempotentes (`idempotency_key` opcional
— repetir a mesma chave devolve o movimento já criado, não cria um
segundo):

- **`enter_stock`** (`entrada`): `inventory.manage_central`. Aumenta stock
  físico central. Não toca em reservas.
- **`adjust_stock`** (`ajuste`): `inventory.manage_central`. Pode ser
  positivo ou negativo; nunca deixa `stock_fisico_central < 0`.
- **`reserve_for_project`** (`reserva`): `inventory.allocate_project`
  (chefe/admin em qualquer projeto; PM só no seu). Reduz
  `stock_disponivel`; nunca deixa `stock_disponivel < 0` (não pode reservar
  mais do que o disponível). Não toca em stock físico.
- **`release_reservation`** (`liberta_reserva`): `inventory.release_project`.
  Aumenta `stock_disponivel`; nunca deixa `reservado[projeto] < 0`.
- **`consume_from_project`** (`consumo`): `inventory.consume_project`.
  Reduz `stock_fisico_central` **e** `reservado[projeto]` na mesma
  transação (consumir sem reserva prévia suficiente é rejeitado — o pedido
  não define "consumo sem reserva"; a opção mais segura é exigir reserva
  cobrindo o consumo, documentado em `docs/OPEN_QUESTIONS.md`).
- **`return_to_stock`** (`devolucao`): mesma permissão que consumo. Reverte
  um consumo anterior — aumenta `stock_fisico_central`, não reabre reserva
  automaticamente (decisão: devolução volta ao stock físico central "livre
  para reservar de novo", não ao mesmo projeto — documentado como decisão
  assumida, secção 11).

Nenhuma operação apaga ou edita um `InventoryMovement` existente — reverter
é sempre um novo movimento de sinal oposto, auditável.

**Exemplo do pedido, verificado por teste (`test_inventory_ledger.py`):**
100 km de cabo DC entram na central → reservar 20 km para o Projeto A →
consumir 5 km → libertar 10 km ⇒ físico 95, disponível 90, reservado
Projeto A 5, consumido Projeto A 5. (O enunciado do pedido tinha um estado
intermédio "reservado 15" antes de libertar 10 — reproduzido também como
passo intermédio no teste.)

## 4. Permissões novas (Fatia 1)

```
inventory.view                 — já existe
inventory.manage_central       — novo (entrada/ajuste no stock central)
inventory.allocate_project     — novo (reservar)
inventory.consume_project      — novo (consumir)
inventory.release_project      — novo (libertar)
inventory.manage_requirements  — novo (criar/editar necessidades de material do projeto)
project.view_installation_data / project.edit_installation_data   — novo
project.view_licensing_data    / project.edit_licensing_data      — novo
project.view_communication_data/ project.edit_communication_data  — novo
map.view                       — novo (ver mapa — todos os papéis com project.view_*)
supplier.manage                — novo
pickup_point.manage            — novo
project_issue.view / project_issue.manage — novo
calendar.view / calendar.manage — novo (Visit/CalendarEvent não tinham endpoints nem permissões dedicadas ainda — só calendar.propose/approve_send, que são sobre envio real, não sobre CRUD local)
performance.view_all / performance.view_own — novo
performance.manage_goals       — novo (só chefe/admin)
```

Matriz por papel (resumo — ver `app/security/catalog.py` para a lista
exata): Administrador e Chefe de Operações recebem tudo; PM recebe
`inventory.allocate_project`/`consume_project`/`release_project`/`view`
(mas não `manage_central`, **decisão revista** — ver nota abaixo),
`project.edit_installation_data`/`licensing_data` só nos seus projetos
(reaproveita `can_edit_project` como base), `calendar.view`/`manage` nos
seus projetos, `performance.view_own`; Comercial/Financeiro só as
variantes `view`.

**Nota sobre "PM pode alterar o inventário central":** o pedido diz
explicitamente, em dois sítios diferentes, coisas distintas — secção 2
("Podem alterar o inventário central: Administrador; Chefe de Operações;
Project Managers") vs. secção 10, permissões ("PM: pode alterar stock
central e operar os seus próprios projetos"). Isto contradiz o exemplo de
negócio do próprio pedido (só operações centrais — entrada/ajuste — deviam
ficar reservadas a quem gere o armazém). **Decisão assumida (opção mais
seguraa, documentada em `docs/OPEN_QUESTIONS.md` pergunta nova):** PM
recebe as permissões de projeto (`allocate`/`consume`/`release`), não
`manage_central` — evita qualquer PM poder inflar/reduzir o stock físico
central sem revisão, o que teria impacto em todos os projetos, não só nos
seus. Reversível numa linha em `catalog.py` se o negócio confirmar o texto
da secção 2 literalmente.

## 5. Mapa operacional — desenho (Fatia 1: backend; frontend ver secção 10)

`GET /api/map/data` devolve, num único payload (evita N+1 pedidos do
frontend): projetos com coordenadas (com PM/estado/potência/tarefas
abertas/pendências/aviso de material em falta), projetos sem coordenadas
(lista separada, para o painel "sem localização"), fornecedores ativos,
pontos de recolha ativos, e pendências (`ProjectIssue`) com
`visible_on_map=true` — cada um já filtrado por `can_view_project`
(nunca a lista completa enviada e filtrada no cliente). `PATCH
/api/projects/{id}` (já existente) aceita `lat`/`lon` para permitir a edição
manual de coordenadas em falta, sujeita às mesmas regras de
`PM_EDITABLE_PROJECT_FIELDS` (D-028) já em vigor — sem alteração aí, `lat`/
`lon` já eram editáveis por PM.

**Fora de âmbito, explicitamente pedido para ficar de fora:** otimização
automática de rotas. Endpoint devolve só os dados; seleção/ordenação manual
e link para uma rota externa (Google/Apple Maps com múltiplos pontos) são
trabalho de frontend (Fatia seguinte, ver secção 10).

## 6. Calendário ligado a tarefas (Fatia 1: backend; frontend ver secção 10)

`POST/PATCH /api/planning/events` valida sempre
`CalendarEvent.project_id == CalendarEvent.task.project_id` quando
`task_id` é fornecido — rejeita com 400 caso contrário (nunca liga um
evento a uma tarefa de outro projeto). `GET /api/planning/calendar`
devolve eventos num intervalo, com filtros `project_id`/
`assigned_to_person_id`/`mine_only`. Continua sem qualquer chamada a
Microsoft Graph (`graph_event_id` fica sempre vazio nesta fase).

## 7. Tarefas — permissões revistas (Fatia 1)

Estado atual (`app/security/permissions.py`): um PM só vê tarefas dos seus
próprios projetos + tarefas atribuídas a si (`task.view_own`), e só pode
editar tarefas do seu próprio projeto (por projeto, não por
criador/atribuído). **Isto já não cumpre o pedido**, que exige:

1. PM vê **todas** as tarefas (de todos os projetos), não só as suas.
2. PM só pode **criar** tarefas atribuídas a si mesmo (nunca a outra
   pessoa) — hoje um PM pode atribuir a qualquer pessoa no seu projeto.
3. PM só pode **editar** tarefas que criou ou que lhe estão atribuídas
   (hoje pode editar qualquer tarefa do seu próprio projeto, incluindo
   tarefas de outra pessoa nesse projeto).
4. PM nunca pode reatribuir uma tarefa (mudar `assigned_to_person_id`).

Mudança em `app/security/permissions.py`/`app/services/tasks.py`:

- `task.view_own` passa a significar, para quem também tem
  `project.view_own` (papel PM), visibilidade **global** de leitura —
  implementado dando ao papel PM a permissão `task.view_all` (mantendo
  `task.edit_own`, que continua a controlar escrita) em vez de reinterpretar
  o significado de `task.view_own` para outros papéis que já a usam de
  forma diferente (nenhum outro papel tem `task.view_own` hoje). Sem
  ambiguidade de permissão: `task.view_all` passa a significar
  literalmente "vê todas", concedida também ao PM.
- `can_create_task`: quando o ator só tem `task.edit_own` (PM), o campo
  `assigned_to_person_id` do pedido, se presente, tem de ser igual a
  `ctx.person_id` — senão 403; se omitido, o serviço preenche
  automaticamente com `ctx.person_id`. `created_by_person_id` é sempre
  `ctx.person_id`, nunca aceite do cliente (já assim hoje).
- `can_edit_task`: quando o ator só tem `task.edit_own`, passa a exigir
  `task.created_by_person_id == ctx.person_id OR
  task.assigned_to_person_id == ctx.person_id` — deixa de bastar ser o PM
  do projeto. `update_task` rejeita por inteiro (nenhuma escrita parcial)
  qualquer pedido que tente alterar `assigned_to_person_id` vindo de um
  ator só com `task.edit_own`.
- `task.edit_all` (chefe/admin) mantém-se sem alteração — continua a poder
  criar/editar/atribuir/reatribuir qualquer tarefa.

## 8. Metas e indicadores — página única (Fatia 1: backend; frontend ver secção 10)

`GET /api/performance/summary` — realizado vs. objetivo por métrica/
período/PM, percentagem, valor em falta, ritmo esperado (linear sobre os
dias decorridos do período), projeção (extrapolação linear simples do
ritmo atual até ao fim do período — documentado como método simples,
revisível), mais os indicadores históricos pedidos (instalações/kWp por
ano, estado das obras, kWp por estado, kWp acumulado por mês, kWp mensal,
portfólio por estado). **Regra de "instalação concluída"**: reaproveita a
métrica já usada pelo dashboard (`Task.status == 'done'` para
`task_type == 'comissionamento'`, ver `app/services/dashboard.py`) como
fonte de verdade única — evita inventar uma segunda definição divergente,
documentado explicitamente aqui como pedido pelo enunciado ("se o código
existente tiver fonte mais adequada, reutilizá-la e documentar").
`GET/POST/PATCH /api/performance/goals` — CRUD de `GoalPeriod`, sujeito a
`performance.manage_goals`. Todo o cálculo no backend — nenhum KPI derivado
no frontend a partir de listas completas (mesma regra já aplicada ao
dashboard, D-041).

## 9. Importações — desenho completo (Fatia seguinte, não implementada nesta PR)

Documentado aqui em detalhe (arquitetura, endpoints, validações) porque o
pedido exige o desenho mesmo sem implementação imediata — para a fatia
seguinte não ter de redesenhar do zero.

### 9.1 Notas iniciais (`notas-iniciais-v11.html`)

- **Nunca executar JavaScript enviado pelo utilizador.** O parser lê o
  ficheiro como texto e extrai apenas o bloco
  `<script type="application/json" id="notas-iniciais-data">...</script>`
  com um parser HTML (`html.parser`/`BeautifulSoup`, sem `eval`/`exec`,
  sem motor de JS) — nunca interpreta `<script>` como código. Aceita
  também JSON solto (sem HTML à volta) e o par JSON+HTML separado.
- Fluxo: `POST /api/imports/notes/preview` (multipart, limite de tamanho
  configurável, extensões `.html`/`.htm`/`.json` só) → calcula
  `sha256` do ficheiro, rejeita se já importado (mesmo hash em
  `FieldImportBatch.source_file_hash`) → extrai JSON (do `<script
  id="notas-iniciais-data">` se HTML, ou o corpo se `.json`) → valida
  contra um schema mínimo (campos esperados, tipos) → tenta encontrar
  projeto existente (por `client_email`/telefone/morada normalizada —
  nunca por nome, mesmo princípio de D-004) → devolve preview com campos
  em falta e candidatos a conflito, **sem escrever nada**. `POST
  .../apply` grava em staging (`FieldImportBatch`/`FieldImportRecord`),
  nunca direto em `Project`/`ProjectInstallationData` — precisa de
  confirmação por campo em conflito (`GET .../{batch_id}/conflicts` +
  endpoint de resolução, mesmo padrão de `resolve_conflict` já usado pela
  migração de projetos). Versão do formulário lida do conteúdo
  (`payload.get("formVersion")` ou campo equivalente), nunca do nome do
  ficheiro — aceita as versões compatíveis conhecidas, rejeita com
  mensagem clara uma versão desconhecida (não assume compatibilidade).
- Um HTML sem o bloco JSON estruturado e sem conseguir extrair o mínimo
  (cliente + um campo técnico) não cria projeto vazio — devolve preview
  vazio pedindo introdução manual.

### 9.2 Excel de licenciamento (`SIM card Numbers Projects.xlsx`)

- Nunca commitado ao repositório (ficheiro real do negócio) — só fixtures
  sintéticas em `backend/fixtures/`.
- CLI (`python -m app.cli.import_licensing --file <path>
  --dry-run|--apply|--rollback`), mesmo padrão de `app.cli.ingest_staging`
  (comando controlado, não endpoint casual). `Sheet1` mapeado para
  `Project`+`ProjectInstallationData` por `Internal_reference` (chave
  preferencial, nunca `Project_number` sozinho — repetido no legado); `Dados
  gerais` mapeado para `ProjectLicensingData`/`ProjectCommunicationData`,
  **ignorando explicitamente** PIN/PUK/password/login/token mesmo que a
  coluna exista na fonte (allowlist de colunas aceites, não denylist —
  qualquer coluna não reconhecida é ignorada e reportada no relatório, nunca
  importada "por precaução"); `Venda do excedente` mapeado para
  `SurplusContract` quando o vínculo ao projeto for inequívoco, senão fila
  de conflitos. `--rollback` reverte um lote específico pelo mesmo mecanismo
  de reversão por histórico já usado em `rollback_promotion` (D-017).

### 9.3 Porque fica para a fatia seguinte

Isto é, de longe, a parte de maior risco do pedido inteiro — parsing de
ficheiros de terceiros (HTML gerado por um formulário próprio, Excel de
origem desconhecida), com dados pessoais (NIF, contactos) e superfícies de
ataque reais (HTML/JS malicioso, ficheiros Excel malformados, encoding
inválido). Entregar isto apressadamente, a par de mais 8 áreas funcionais
na mesma PR, arrisca exatamente o tipo de erro que este repositório existe
para evitar (ver D-004/D-005/D-017 — todo o cuidado posto na migração de
projetos legados). A opção mais segura, e a que o próprio pedido prevê
("se encontrares dúvidas que não bloqueiem o desenvolvimento... continua"),
é: desenho completo e revisto aqui, implementação com fixtures sintéticas e
suite de testes dedicada (validação, duplicados, versão desconhecida,
campos em falta, conflitos, idempotência, dados sensíveis ignorados) numa
PR própria, mais pequena e mais fácil de rever isoladamente.

## 10. O que a Fatia 1 (esta PR) entrega, testado

- Modelo de dados: `ProjectInstallationData`, `ProjectLicensingData`,
  `ProjectCommunicationData`, `InventoryLocation`, `ProjectMaterialRequirement`,
  `PickupPoint`, `ProjectIssue`, `GoalPeriod`+`GoalPeriodHistory`; alterações
  a `InventoryItem`/`InventoryMovement` (Numeric, novas colunas), `Supplier`
  (`materials`/`is_active`), `CalendarEvent` (`task_id`). Uma migração
  Alembic reversível.
- Permissões novas (secção 4), aplicadas no servidor, testadas por papel.
- Serviços: `app/services/inventory.py` (livro de movimentos, secção 3),
  `app/services/project_data.py` (CRUD com histórico por campo para os três
  modelos satélite de projeto), `app/services/map.py`, `app/services/
  planning.py` (calendário+validação de tarefa), `app/services/
  performance.py`. `app/services/tasks.py`/`permissions.py` corrigidos
  (secção 7).
- Endpoints REST para tudo o que precede (ver secções 3 a 8).
- Seed de demonstração atualizado: localização IdealMinde, 2 fornecedores,
  1 ponto de recolha, projetos com e sem coordenadas, 2 pendências de obra,
  5 itens de inventário incluindo o cenário exato do pedido (100 km
  entram → 20 reservados → 5 consumidos → 10 libertados ⇒ físico 95/
  disponível 90/reservado 5... e depois mais 10 reservados para chegar ao
  estado final pedido: físico 95, disponível 80, reservado 15, consumido
  5), necessidades de material, metas anuais/trimestrais com progresso.
- Frontend: menu atualizado (uma única entrada "Metas e indicadores", sem
  "Dashboards" separado), página `/inventory` (stock central, disponível,
  reservas por projeto, criar necessidade de material) e página
  `/performance` (metas + indicadores históricos) ligadas aos endpoints
  reais acima. `/map`, `/planning` (calendário) e as tabs de dados de
  instalação/licenciamento no detalhe do projeto ficam com backend pronto
  e testado mas **sem UI nesta PR** — ver `docs/OPEN_QUESTIONS.md` para o
  registo explícito, e secção 9 para a razão de priorização (importações
  primeiro na fila de UI que falta, por serem o bloqueio de dados reais
  mais adiante no roadmap).
- Testes: backend (novo por área — ver `docs/INVENTORY_RULES.md`/
  `docs/MAP_AND_PLANNING.md`/`docs/PERFORMANCE_METRICS.md` para a lista
  exaustiva por ficheiro), suite completa a continuar 100% verde; frontend
  (Vitest) para as duas páginas novas e a correção de permissões de tarefas
  refletida na UI existente.
- Documentação: este ficheiro, `docs/DATA_IMPORTS.md` (desenho da secção 9,
  para a fatia seguinte), `docs/MAP_AND_PLANNING.md`,
  `docs/INVENTORY_RULES.md`, `docs/PERFORMANCE_METRICS.md`, atualizações a
  `README.md`/`docs/MVP_DEMO.md`/`docs/OPEN_QUESTIONS.md`/`docs/DECISIONS.md`.

## 11. Riscos e decisões assumidas nesta fatia

| Decisão assumida | Porquê é a opção mais segura | Reversível? |
|---|---|---|
| PM não recebe `inventory.manage_central` (só `allocate/consume/release`) | O pedido é internamente contraditório entre secção 2 e secção 10; restringir o stock físico central a quem gere o armazém evita um PM afetar todos os projetos por engano | Sim, uma linha em `catalog.py` |
| Consumo exige reserva ativa suficiente no projeto | O pedido não define "consumo sem reserva"; exigir reserva prévia é o comportamento mais previsível e auditável | Sim, é uma verificação isolada em `services/inventory.py` |
| Devolução volta ao stock físico central livre, não reabre a reserva do projeto de origem | Idem — o pedido não especifica; esta opção nunca inventa uma ligação implícita entre uma devolução e uma reserva específica | Sim |
| Importadores (secção 9) ficam desenhados mas não implementados nesta PR | Maior risco de dados sensíveis/segurança de todo o pedido; melhor revisto isoladamente (ver secção 9.3) | N/A — trabalho pendente, não uma decisão de desenho a reverter |
| `/map` e `/planning` sem UI nesta PR (backend completo) | Escopo de frontend do pedido inteiro (mapa interativo com camadas/filtros/seleção de rota, calendário semanal/mensal/lista) é, por si só, maior que todo o resto da Fatia 1 combinado | N/A — trabalho pendente |
| `GoalPeriod.metric` é uma lista fechada (enum de string), não um catálogo configurável | O pedido lista métricas concretas; um catálogo configurável de métricas é complexidade não pedida | Sim, extensível por migração simples |

Todas as perguntas que dependiam de confirmação de negócio (não bloqueantes
para continuar, por instrução explícita do pedido) estão registadas em
`docs/OPEN_QUESTIONS.md`, secção nova "MVP de Operações".
