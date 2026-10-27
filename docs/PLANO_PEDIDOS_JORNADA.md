# Pedidos (chat) + lançamento da própria jornada no Banco de Horas

Estado: decisões fechadas pelo responsável do produto (19/10/2026). Base: `main` @ `e49a224`, head Alembic `a1c3e5f7b9d0`.
Publicação direta no Tailscale autorizada depois de validação (backup + ensaio de migração).

## Decisões fechadas

1. **Pedidos**: botão flutuante em todas as páginas para qualquer utilizador autenticado; o utilizador escreve um pedido, vê o estado (aberto/resolvido) e as respostas. Quem vê a caixa de entrada e responde são os papéis com a permissão `requests.manage` (Administrador e Chefe de Operações) — **por permissão, nunca por nome** (D-073).
2. **Banco de Horas**: o utilizador lança a **própria** jornada; entra logo no saldo (sem aprovação); avisos de limites mantêm-se (não bloqueiam); correção só por **anulação compensatória** (mecanismo existente; o utilizador pode anular os seus próprios lançamentos self-service).
3. **Formulário de 1 dia**: data (hoje por omissão), entrada, saída, almoço Sim/Não, saldo calculado a aparecer **antes** de guardar. Sábado usa regra ×1,5. Domingos/feriados/exceções manuais só via Chefe/Admin (ecrã de gestão existente).
4. Suposições reversíveis (assinaladas): data futura recusada; um lançamento ativo por dia/pessoa (409 se já existe; anular primeiro); feriados em dia útil não são detetáveis (aceita-se).

## O que já existe → consequência

| Existe | Consequência |
|---|---|
| `POST /api/time-bank/entries` exige `time_bank.manage_all` e recebe `person_id` | Novo endpoint `/my-entries` que **deriva a pessoa do contexto** e o modo de cálculo da data; reutiliza `calculate_work_seconds` e `_audit` |
| `reverse_entry` exige `manage_all`; `uq_time_bank_entry_one_reversal` | Extrair o núcleo e reutilizar; versão self-service só para lançamentos `provenance.source == "self_service"` do próprio |
| Frontend: `InstallerTimeBankPage` (só leitura) para instaladores e `IsolatedTimeBank` para staff | Novo `MyTimeBank` (formulário + saldo + histórico) para quem **não** tem `time_bank.manage_all` |
| `isInstallerCollaborator` é por capabilities | Dar a um colaborador os papéis Chefe+PM (dados, fora do código) muda automaticamente a UI dele para staff |

## Permissões novas (catálogo + migração M1)

- `time_bank.log_own` — "Registar e anular a própria jornada no Banco de Horas". Concedida a **todos os papéis cuja lista já contém `time_bank.view_own`**.
- `requests.create` — "Enviar pedidos à equipa de operações". Concedida a **todos os papéis**.
- `requests.manage` — "Ver e responder a todos os pedidos". `administrador` e `chefe_operacoes`.

### M1 `b5e7a9c1d3f4_pedidos_jornada_permissoes.py` (`down_revision = "a1c3e5f7b9d0"`)
Só permissões/grants (sem tabelas). Seguir o padrão de provisionamento rastreado de `8a1d3f4c6b90` e de `c8f0a2b4d6e1`/`d9e1f3a5b7c2`: tabela de tracking, downgrade remove só o que criou, lista literal, **no-op seguro em base vazia**, não toca `user_roles`.

### M2 `c6f8b0d2e4a5_user_requests.py` (`down_revision = "b5e7a9c1d3f4"`) — tabelas dos pedidos (Fase 2)

## API Banco de Horas (prefixo `/api/time-bank`)

Corpo `MyEntryCreate` (`extra="forbid"`): `work_date: date`, `start_minute: StrictInt 0..1439`, `end_minute: StrictInt 1..1440`, `lunch_taken: StrictBool`.

- `POST /my-entries/preview` → `200 {work_date, calculation_mode, balance_seconds, warnings:[{code,message}], duplicate: bool}`. Não grava. Mesmas validações de data/hora/domingo/futuro; `duplicate=true` se já existe lançamento ativo nesse dia (em vez de 409).
- `POST /my-entries` → `201 EntryRead` (mesmo schema de `/entries`). Grava com `provenance={"source":"self_service"}`, `created_by_user_id=ctx.user.id`, audit `entry.create_self` na mesma transação.
- `POST /my-entries/{entry_id}/reverse` corpo `{reason: str 1..2000}` → `200 EntryRead` (a compensação). Só se `entry.person_id == ctx.person_id`, `provenance.source == "self_service"`, `created_by_user_id == ctx.user.id`; caso contrário 404 (não existe/não é seu) ou 403 (existe, é seu, mas não é self-service). Audit `entry.reverse_self`.

Regras (todas no serviço, não na rota):
- Exigir `time_bank.log_own` **e** `ctx.person_id` não nulo, senão 403.
- A pessoa vem **sempre** do contexto; nunca do corpo.
- `calculation_mode` derivado: seg–sex `standard`; sábado `saturday`; domingo → 422 "Domingos e feriados só podem ser lançados por um Chefe ou Administrador."
- `work_date` > hoje (Europe/Lisbon) → 422.
- Já existe entrada para (pessoa, data) que não é compensação e não foi anulada → 409 "Já existe um lançamento para este dia. Anule-o primeiro se quiser corrigir."
- Saída ≤ entrada → 422 (já vem do cálculo existente).
- Aviso `daily_limit` no preview se `balance_seconds` > limite diário já definido no código existente (reutilizar a constante/código; não inventar outro).
- Erros mapeados como no resto de `routes_time_bank.py` (sem 500 por entrada inválida).

## API Pedidos (prefixo `/api/requests`) — Fase 2

Tabelas: `user_requests` (`id`, `created_by_user_id` FK, `status` `open|resolved`, `page_path` ≤256 nullable, `created_at`, `updated_at` = última atividade, `resolved_at`, `resolved_by_user_id`) e `user_request_messages` (`id`, `request_id` FK cascade, `author_user_id` FK, `is_staff_reply` bool, `body` Text, `created_at`). Índices `(request_id, created_at)` e `(status, updated_at)`. Nada se apaga.

- `GET ?scope=mine|all&status=open|resolved|all&limit&offset` (omissão `mine`/`all`; `scope=all` exige `requests.manage` senão 403) → `{items:[{id,status,page_path,created_at,updated_at,author_name,message_count,last_message_preview,last_message_is_staff}], total}`. Ordenar por `updated_at desc`.
- `GET /summary` → `{open: int}` (com `requests.manage`: todos os abertos; senão: os abertos do próprio).
- `POST` `{body, page_path?}` → thread completa com a 1.ª mensagem (exige `requests.create`). Máx. 20 pedidos abertos por autor (409).
- `GET /{id}` → `{id,status,page_path,created_at,updated_at,author_name,messages:[{id,author_name,is_staff_reply,is_mine,body,created_at}]}`; só o autor ou `requests.manage`; senão 404.
- `POST /{id}/messages` `{body}` → mensagem; autor ou `requests.manage`. Mensagem do autor em pedido `resolved` reabre-o. `is_staff_reply = ctx.has_permission("requests.manage")`.
- `POST /{id}/status` `{status}` → só `requests.manage` (403). `resolved` define `resolved_at/by`; `open` limpa-os.
- `body`: strip, 1..2000 chars. `page_path`: tem de começar por `/`, sem query/hash, senão ignorado (None). Respostas **não** expõem emails; `author_name` = `Person.display_name` ou "Utilizador".
- `extra="forbid"`; erro de validação sem eco do corpo é desejável mas não bloqueante.

## UX (frontend)

### Banco de Horas (`MyTimeBank`)
Cartão «Registar jornada»: data (`<input type=date>`, `max` = hoje), entrada/saída (`<input type=time>`; predefinição seg–qui 09:00–18:30, sex 09:00–14:00, sáb vazio-friendly 09:00–13:00), controlo segmentado «Almoço: Sim / Não» (predefinição Sim), pré-visualização viva (debounce ~300 ms contra `/my-entries/preview`): «Saldo deste dia: +00:30» (verde/vermelho), nota «Sábado conta ×1,5», aviso de limite, mensagem clara se domingo/futuro/duplicado. Botão «Guardar jornada» (desativado se inválido/duplicado). Depois: saldo, período, avisos do resumo e histórico em tabela (Data · Entrada–Saída · Almoço · Saldo · estado) com «Anular» nos lançamentos self-service ainda não anulados («Tens a certeza?» + motivo obrigatório). Compensações aparecem como linha própria com badge «anulação». PT-PT; legível em telemóvel (sem overflow horizontal).

### Pedidos
Botão flutuante (canto inferior direito; acima da barra inferior em mobile), painel com «Novo pedido» e «Os meus pedidos» (estado, respostas, responder). Quem tem `requests.manage` vê também ligação «Caixa de pedidos» → página `/requests` (item de menu «Pedidos» com contagem de abertos): lista + conversa, filtro aberto/resolvido/todos, responder, «Marcar como resolvido»/«Reabrir».

## Fases

1. **F1** backend Banco de Horas + permissões + M1 (T1) ‖ frontend `MyTimeBank` (T2).
2. **F2** backend pedidos + M2 (T3) ‖ frontend pedidos (T4).
3. Validação (`validate_oppm.sh` + PostgreSQL), revisão do diff, `D-101`, publicação.

## Critérios de aceitação
- Um utilizador `view_own`+`log_own` lança, vê saldo atualizado e anula o seu lançamento; não consegue lançar para outra pessoa nem anular lançamentos importados/de gestão (testes por API).
- Admin/Chefe continuam a usar o ecrã de gestão sem regressões.
- Qualquer utilizador cria um pedido e vê a resposta; só `requests.manage` vê os de outros e responde/resolve.
- Migração `upgrade → downgrade → upgrade` em SQLite e PostgreSQL; `grants` provisionados nos papéis existentes.
