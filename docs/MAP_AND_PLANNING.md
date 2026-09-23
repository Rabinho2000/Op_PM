# Mapa operacional e calendário de planeamento

> Ver `docs/PLAN_OPERATIONS_MVP.md` secções 5 e 6 para o desenho completo.
> **Estado: backend e UI completos e testados** — `/map`
> (`frontend/src/pages/Map.tsx`) e `/planning`
> (`frontend/src/pages/Planning.tsx`), ambos atrás de `map.view` e
> `calendar.view` no menu lateral (`app/components/Layout.tsx`).

## Mapa (`GET /api/map/data`)

Um único payload, já filtrado pela visibilidade do utilizador (nunca a
lista completa enviada para o cliente filtrar):

```json
{
  "config": {"provider_enabled": false, "tile_url": "", "tile_attribution": ""},
  "projects": [...],
  "projects_without_coordinates": [...],
  "suppliers": [...],
  "pickup_points": [...],
  "issues": [...],
  "summary": {
    "visible_active_projects": 295, "mapped_projects": 187, "unmapped_projects": 108,
    "map_coverage_percent": 63.4,
    "green_projects": 150, "yellow_projects": 28, "red_projects": 9,
    "operational_clean_percent": 50.8,
    "projects_with_material": 6
  }
}
```

### `attention` por projeto (green/yellow/red) — ver D-058

Cada entrada em `projects`/`projects_without_coordinates` ganhou:
`attention`, `operational_tasks_count`, `overdue_operational_tasks_count`,
`blocked_operational_tasks_count`, `urgent_operational_tasks_count`,
`next_operational_task` (`{id, title, due_date, priority}` ou `null`),
`material_visible`, `has_material_on_site` (`bool | null`),
`material_sku_count` (`int | null`).

Nunca persistido — calculado sempre a partir de `Task.category`
(`app/models/task.py`: `workflow|field|material|documentation|commercial|other`)
e, quando `inventory.view`, do saldo reservado de inventário. Só
`OPERATIONAL_TASK_CATEGORIES` (`field`/`material`) conta para o
semáforo — uma tarefa `workflow`/`documentation` aberta nunca muda
`attention`. `red` = tarefa operacional aberta `blocked`, `urgent`, ou
atrasada (`Europe/Lisbon`); `yellow` = tarefa operacional aberta, ou
material físico visível no local; `green` = nenhuma das anteriores. Sem
`inventory.view`, `has_material_on_site`/`material_sku_count` ficam
sempre `null` (nunca `false`) — material nunca influencia `attention`
para quem não o pode ver. Ver `docs/DECISIONS.md` D-058 para o detalhe
completo (incluindo a correção de N+1 já existente neste endpoint) e
`backend/tests/test_map_attention.py` para os casos testados.

**Fora de âmbito nesta revisão:** UI do mapa a colorir pins por
`attention`/mostrar `summary` — o frontend de `/map` continua a usar
`open_tasks_count`/`issues_count`, como antes; fica para uma sessão
seguinte, com o contrato do backend já fechado.

- `config.provider_enabled` reflete `MAP_PROVIDER_ENABLED` (`backend/.env`).
  Sem provider configurado, o endpoint continua a devolver todos os
  dados — a UI deve mostrar um aviso claro em vez de tiles, e a lista de
  locais (`projects`/`suppliers`/`pickup_points`) como alternativa. Nunca
  depender de um serviço externo para o resto da aplicação funcionar.
- `projects_without_coordinates` existe para o painel "sem localização"
  pedido — permite editar `lat`/`lon` via `PATCH /api/projects/{id}`
  (já existente, sujeito às mesmas regras de `PM_EDITABLE_PROJECT_FIELDS`).
- Fornecedores/pontos de recolha: CRUD em `/api/suppliers` e
  `/api/pickup-points` (`supplier.manage`/`pickup_point.manage`).
- Pendências (`ProjectIssue`): CRUD em
  `/api/projects/{id}/issues`, mais
  `POST /api/projects/{id}/issues/{issue_id}/convert-to-task` — cria uma
  `Task` e liga `related_task_id`, nunca duplica a entidade.

**Fora de âmbito, por pedido explícito:** otimização automática de rotas.
Na UI, a seleção é manual (caixas de verificação na lista) e o botão
"Abrir rota" apenas monta um link do Google Maps com os locais na ordem
escolhida — nenhuma otimização, nenhum pedido a um serviço de routing.

### UI (`frontend/src/pages/Map.tsx`)

- Mapa visual com Leaflet quando `config.provider_enabled` é verdadeiro
  (`MAP_TILE_URL`); caso contrário, mostra sempre a lista funcional dos
  locais — a aplicação nunca fica "quebrada" por falta de um provider de
  tiles. Marcadores por camada (instalações/fornecedores/recolhas/
  pendências), com um `divIcon` colorido por tipo (sem depender dos
  ícones por omissão do Leaflet, que partem em bundlers como o Vite).
- Filtros: pesquisa por projeto/cliente, PM, estado, e checkboxes por
  camada.
- Painel "Sem coordenadas": edição manual de `lat`/`lon` por projeto.
- Clicar num marcador ou item da lista abre um painel de detalhe
  (`Modal`) com link para o projeto quando aplicável.
- Formulários de fornecedor/ponto de recolha atrás de
  `supplier.manage`/`pickup_point.manage`; pendências criam-se a partir
  do detalhe do projeto e podem converter-se em tarefa
  (`convertIssueToTask`).

## Calendário de planeamento (`/api/planning/*`)

- `GET /api/planning/events` / `GET /api/planning/calendar` — mesma
  lista, dois paths (um para "lista de eventos", outro para "vista de
  calendário" com intervalo de datas) — filtros `project_id`,
  `assigned_to_person_id`, `mine_only`, `starts_from`/`starts_to`.
- `POST`/`PATCH /api/planning/events` — `task_id`, quando presente, tem de
  pertencer ao mesmo `project_id` do evento; validado sempre no servidor
  (`app/services/planning.py:_validate_task_matches_project`), nunca
  confiado ao cliente. Um pedido inconsistente é rejeitado com 400.
- `POST /api/planning/events/{id}/cancel` — marca `status="cancelado"`
  (novo valor, além de `rascunho`/`aprovado`/`publicado`).
- Continua **inteiramente local** — nenhuma chamada a Microsoft Graph,
  `graph_event_id` nunca é preenchido (D-010 mantém-se). Isso fica para a
  Fase 6 do roadmap geral (`docs/PLAN.md`).

### UI (`frontend/src/pages/Planning.tsx`)

- Três vistas: semana (colunas por dia), mês (grelha 6×7) e lista
  (agrupada por dia) — seletor "Vista".
- Filtro "Ver": todos / meus (`mine_only`) / por PM (filtro no cliente,
  cruzando `CalendarEvent.project_id` com `Project.pm_person_id`, porque
  o endpoint não tem esse parâmetro) / por projeto / por responsável.
- Criar e reagendar usam o mesmo formulário (`EventModal`); reagendar é
  um `PATCH` a partir do painel de detalhe, sem arrastar-e-largar.
- **Deteção de conflitos é só no cliente**: ao escolher um responsável e
  um horário, compara com os eventos já carregados para esse período e
  avisa sobreposições para a mesma pessoa. Não bloqueia — exige uma
  confirmação explícita ("Guardar mesmo assim") porque o backend não tem
  nenhuma restrição de sobreposição (ver `docs/OPEN_QUESTIONS.md`).
- `can_manage` (calculado no servidor a partir de
  `can_manage_calendar_event`) decide se aparecem os botões "Reagendar"/
  "Cancelar evento" no painel de detalhe — nunca calculado no cliente.

## Permissões novas

`map.view`, `supplier.manage`, `pickup_point.manage`, `project_issue.view`,
`project_issue.manage`, `calendar.view`, `calendar.manage` — ver
`app/security/catalog.py` para a matriz completa por papel.
