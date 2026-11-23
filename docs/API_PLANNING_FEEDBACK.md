# API de planeamento — feedback de calendário

Contrato backend da fatia de preferências, participantes/categorias e ligação
referencial ao Processo. Esta alteração não publica frontend nem usa Graph.

## Preferência por utilizador

- `GET /api/me/planning-preferences`
- `PATCH /api/me/planning-preferences`
- resposta: `{ "view": "month" | "week" | "list", "hide_weekends": boolean }`
- conta nova/sem linha guardada: `view=month`, `hide_weekends=false`.
- a linha é ligada ao `User` autenticado; não existe preferência global nem
  preferência partilhada entre contas no mesmo browser.
- `PATCH` aceita qualquer subconjunto dos dois campos. `view` só aceita os
  três códigos; `hide_weekends` é booleano. `null`/valores desconhecidos dão
  `422` e não alteram a linha. Se a linha não existir, o `GET` devolve o
  default mensal; uma falha de esquema/BD não é tratada como ausência e
  devolve `503` com detalhe sanitizado, para o consumidor poder aplicar o
  fallback sem esconder a falha de configuração.

## Catálogo, eventos manuais e participantes

- `GET /api/planning/event-categories` exige autenticação e a permissão
  `calendar.view`; sem sessão devolve `401` e sem essa permissão devolve `403`.
  Quando autorizado, devolve códigos, labels e cores do catálogo fechado:
  `meeting`, `technical_visit`, `commissioning`, `final_inspection`,
  `pending`, `work`, `other`.
- `GET /api/planning/events` e `GET /api/planning/calendar` mantêm o contrato
  existente e aceitam `category`, `assigned_to_person_id`, `mine_only`,
  `project_id`, `starts_from` e `starts_to`. O filtro de responsável considera
  a relação completa, não só o primário legado; o intervalo inclui eventos que
  intersectam a janela.
- `POST /api/planning/events` aceita `category`,
  `assigned_to_person_id` (compatibilidade) e `assigned_to_person_ids`.
- `PATCH /api/planning/events/{id}` tem semântica explícita para a lista:
  - campo **omitido**: preserva todos os participantes atuais;
  - `assigned_to_person_ids: []`: limpa todos e põe o primário legado a `null`;
  - `assigned_to_person_ids: null`: inválido (`422`);
  - IDs repetidos são deduplicados; quando o primário é enviado, tem de estar
    na lista e fica primeiro.
- IDs são validados antes de qualquer `INSERT`/alteração. Pessoa inexistente,
  inativa ou fora do âmbito devolve `422` de forma atómica. O read model só
  expõe IDs e `display_name`; nunca expõe email/contacto. Perfis com âmbito
  delegado não ganham acesso a projetos fora das delegações por terem um
  participante em comum. Papéis combinados unem âmbitos, sem substituir a
  restrição de projeto.
- A resposta acrescenta `assigned_to_person_ids`,
  `assigned_to_display_names`, `category_label`, `category_color`, `source`,
  `source_id`, `can_manage` e `project_url`. Eventos manuais têm
  `source=manual`, `source_id` igual ao ID persistido e `can_manage` calculado
  no servidor.
- A API aceita `starts_at`/`ends_at` com offset (`Z`, `+01:00`, `+00:00`,
  `-05:00`) e normaliza esses instantes para UTC antes de criar ou editar.
  Datetimes sem offset continuam aceites por compatibilidade histórica, mas a
  convenção explícita deste contrato é UTC — nunca são interpretados como hora
  local do browser ou como Europe/Lisbon.
- As respostas devolvem sempre `starts_at`/`ends_at` com offset conhecido. Em
  SQLite, onde `DateTime(timezone=True)` perde o `tzinfo` ao carregar, os
  valores persistidos em UTC são re-hidratados como UTC no serializer. Os
  limites de `starts_from`/`starts_to` usam a mesma normalização UTC nos dois
  motores; não há conversão nem reescrita de eventos legados.

## Ligação referencial ao Processo

Os bodies de criação/edição aceitam `process_stage_id` e/ou
`process_subtask_id`. A API valida:

- existe `project_id` e o utilizador pode gerir esse projeto;
- a etapa/subtarefa existe;
- a subtarefa pertence à etapa indicada (quando ambas são enviadas).

A ligação não altera o Processo nem cria uma `Task`; a escrita é atómica e um
erro dá `422`. A resposta resolve `process_stage_code/title`,
`process_subtask_code/title`, `responsible_person_ids` seguros,
`responsible_display_names` e `project_url=/projects/{id}?tab=processo`.

`GET /api/planning/process-options/{project_id}` fornece às caixas de seleção
as etapas e subtarefas existentes. Subtarefas não recebem datas inventadas.

## Projeção automática

- `GET /api/planning/process-events` é um read model separado para o frontend
  fazer merge com `/events`.
- Cada etapa do catálogo com `start_date` do projeto e **ambos** os offsets
  planeados produz um evento determinístico; sem datas completas não se cria
  evento. A data é calculada pelo mesmo `business_day` do Processo. As
  categorias usam códigos estáveis da fase (`visita`, `comissionamento`,
  `inspecao_final`, `obra`, `pendencia`), nunca títulos ou nomes reais.
- Eventos automáticos têm `source=process`, `source_id`/`id` UUID5 estável,
  `status=projected`, `can_manage=false`, referência de etapa, responsáveis
  seguros e deep-link. O intervalo usa sobreposição inclusiva; os limites
  date-only são construídos como meia-noite Europe/Lisbon e o fim do evento é
  a meia-noite seguinte, preservando DST.
- `project_id`, `category`, `assigned_to_person_id`, `mine_only`,
  `starts_from` e `starts_to` filtram sem alargar a visibilidade do projeto.
  A leitura de detalhe de um evento fora do âmbito continua a devolver `404`,
  mas `PATCH`/cancel de um evento persistido fora do âmbito de escrita chega à
  verificação de servidor e devolve `403`. Um ID inexistente, incluindo um
  UUID de projeção não persistido, devolve `404`.
- Eventos manuais ligados à mesma referência continuam linhas próprias. O
  consumidor deve deduplicar apenas a chave exata
  `(project_id, process_stage_id, process_subtask_id, starts_at, ends_at)`;
  duas ocorrências válidas com datas diferentes não são removidas.

## Migração

A revisão `f5a7c9d1e3b2` encadeia sobre `d4e6f8a1b2c3` e cria:

- `planning_preferences` (uma linha por `user_id`);
- `calendar_event_assignees` (relação many-to-many);
- `calendar_events.category`, `process_stage_id`, `process_subtask_id`.

O `assigned_to_person_id` legado é preservado e copiado para a relação na
migração. `upgrade -> downgrade -> upgrade` mantém as linhas legadas e
reaplica o backfill sem duplicar participantes.

## Recorrência semanal

- Eventos únicos mantêm o contrato anterior. A criação de uma série envia
  `recurrence="weekly"`, `recurrence_until` (data inclusiva obrigatória) e
  `idempotency_key`. O servidor limita a série a 52 ocorrências e grava cada
  ocorrência como `CalendarEvent`, ligada por `series_id` e índice único.
  A chave é única por conta criadora; um retry com o mesmo conteúdo devolve a
  primeira ocorrência existente, enquanto reutilizá-la com conteúdo diferente
  devolve `409`.
- As horas são locais a `Europe/Lisbon`: cada semana mantém as horas de parede,
  incluindo quando o offset muda. Uma hora inexistente no avanço de primavera
  rejeita toda a série antes de gravar; quando o formulário recebe uma hora
  repetida no outono, usa a segunda ocorrência. Não há deslocação silenciosa.
- `PATCH /api/planning/events/{id}?scope=occurrence` edita uma ocorrência
  (âmbito predefinido e compatível). `scope=series` aplica os campos a toda a
  série; só um `starts_at` explícito desloca todas as ocorrências pelo mesmo
  número de dias e mantém o espaçamento semanal e a hora local. Uma edição sem
  alteração de início preserva as datas e horas reais de cada ocorrência,
  incluindo exceções movidas individualmente.
- `POST /api/planning/events/{id}/cancel?scope=occurrence|series` marca a
  ocorrência ou a série como `cancelado`; nenhuma ocorrência é apagada.
- Operações com `scope=series` exigem permissão de gestão **e** leitura sobre
  todas as ocorrências (`403` caso contrário) e são atómicas.
- `CalendarEventRead` expõe `recurrence_series_id`, `recurrence_rule`,
  `recurrence_index`, `recurrence_count` e `recurrence_until`.
- Cada criação, alteração e cancelamento de evento (incluindo cada ocorrência
  de uma série) fica registado em `calendar_event_audit` (append-only, com
  autor e diferenças campo a campo).
- Migração `c4e6a8b0d2f1` (sobre `d3f5a7c9e1b2`): cria `calendar_event_series`
  e duas colunas opcionais em `calendar_events`; eventos anteriores ficam com
  ambas nulas. Migração `d7a9c3e5f1b2`: cria `calendar_event_audit`. O
  downgrade de `c4e6a8b0d2f1` mantém as ocorrências como eventos únicos mas
  perde o vínculo à série e a chave de idempotência.
