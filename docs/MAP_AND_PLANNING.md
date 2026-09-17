# Mapa operacional e calendário de planeamento

> Ver `docs/PLAN_OPERATIONS_MVP.md` secções 5 e 6 para o desenho completo.
> **Estado nesta PR: backend completo e testado, sem UI ainda** (ver
> `docs/OPEN_QUESTIONS.md`) — os endpoints abaixo já podem ser usados por
> um cliente HTTP (Swagger em `/docs`) ou por uma UI futura sem alterações.

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
  "issues": [...]
}
```

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
O endpoint só devolve dados; seleção/ordenação manual de vários locais e
o link para uma rota externa (Google/Apple Maps) são trabalho de UI, não
implementados nesta PR.

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

## Permissões novas

`map.view`, `supplier.manage`, `pickup_point.manage`, `project_issue.view`,
`project_issue.manage`, `calendar.view`, `calendar.manage` — ver
`app/security/catalog.py` para a matriz completa por papel.
