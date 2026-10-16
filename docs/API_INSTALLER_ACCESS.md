# API — acesso de colaborador externo por instalador

Contrato backend para `ROLE_INSTALLER_COLLABORATOR` (`instalador_colaborador`). O frontend futuro deve tratar este canal como leitura; não criar contas nem assumir permissões globais.

## Capacidades

| Capability | Uso |
|---|---|
| `project.view_assigned_installer` | projetos associados a instaladores ativos da pessoa |
| `task.view_assigned_installer` | tarefas de projetos visíveis, leitura básica |
| `works_calendar.view_assigned_installer` | obras/calendário de projetos visíveis |
| `installer_team.view_assigned_installer` | equipas/instaladores associados, com contactos reduzidos |
| `inventory.view_assigned_installer` | inventário mínimo por projeto visível |
| `time_bank.view_own` | próprio Banco de Horas |

O papel não inclui permissões globais, escrita, custos, documentos, people global, stock central ou planeamento.

## Escopo de identidade

`InstallerAccessMembership(person_id, installer_id, is_active)` é a fonte de autorização. O carregamento de `AuthContext` lê apenas memberships ativas por `person_id`; email/nome não participam na autorização. Projetos são filtrados pela query canónica, cobrindo `Project.installer_id` e `ProjectTeamAssignment.installer_id` (incluindo atribuições históricas). O mesmo predicado é reutilizado no detalhe.

## Endpoints

### `GET /api/installer-access/teams`

Resposta mínima:

```json
{
  "teams": [
    {"id": "uuid", "name": "string", "is_active": true, "installer_id": "uuid"}
  ],
  "installers": [
    {"id": "uuid", "name": "string", "is_active": true}
  ],
  "scoped": true
}
```

Só devolve equipas/instaladores ligados aos projetos/equipas do escopo. Não devolve email, telefone ou contactos externos.

### `GET /api/installer-access/inventory`

Parâmetros opcionais: `project_id`, `limit` (1–100), `offset` (>=0).

Resposta mínima:

```json
{
  "items": [
    {
      "project_id": "uuid",
      "article_name": "string",
      "unit": "string|null",
      "required_quantity": 0,
      "reserved_quantity": 0,
      "consumed_quantity": 0,
      "delivered_quantity": 0,
      "locations": [{"id": "uuid", "label": "string"}]
    }
  ],
  "total": 1,
  "limit": 100,
  "offset": 0
}
```

`project_id`, quando enviado, é validado contra a query de projetos visíveis. Projeto não autorizado e UUID inexistente resultam em 404 uniforme. O endpoint não expõe preços/custos, fornecedores, stock central, movimentos globais, atores, notas de auditoria ou IDs de projetos estrangeiros.

### Projetos, tarefas, obras e processo existentes

Os endpoints existentes reutilizam `visible_projects_query`/`get_visible_project` e as queries equivalentes de tarefas. O detalhe não usa `db.get()` sem escopo. O canal externo recebe DTOs redigidos: sem PM/contactos/email, notas administrativas, auditoria, custos, integração ou gestão. Histórico administrativo e mutações de processo/calendário/vistas guardadas respondem 403.

### APIs auxiliares fora do canal externo

O canal externo não usa o planeamento genérico (`/api/planning/*` nem as
preferências de `/api/me/planning-preferences`): essas rotas respondem 403 sem
consultar o recurso pedido. O dashboard global também responde 403. A lista de
pessoas é uma exceção mínima e devolve apenas a `Person` autenticada, com
`email` nulo; perfis internos combinados mantêm as regras RBAC existentes.

As leituras de `/api/me/works-preferences` e
`/api/me/works-saved-views` são permitidas para o Calendário de obras dedicado,
mas a resposta é uma cópia redigida: `pm_person_id` fica sempre nulo,
`installer_id` limita-se aos instaladores ativos da associação e `team_id`
limita-se a equipas desses instaladores. A leitura nunca altera a linha privada
persistida. Escrita, aplicação e eliminação de vistas continuam proibidas.

`time_bank.view_own` é independente da associação ativa a um instalador: a
revogação da associação esvazia apenas o escopo de projetos/obras associado,
sem retirar a leitura do Banco de Horas próprio. Dados de outra pessoa continuam
proibidos.

### Banco de Horas existente

`GET /api/time-bank/people` devolve apenas a Person autenticada para `time_bank.view_own`. `GET /api/time-bank/entries`, `/adjustments` e `/summary` resolvem `person_id` omitido para `ctx.person_id` e recusam outra pessoa com 403. `POST`, reverse, import preview/resolve/apply e gestão exigem `time_bank.manage_all`, portanto o papel externo não pode alterar o ledger nem importar dados.

## Regras para frontend

- Não esconder uma falha de autorização apenas removendo menus; respeitar 403/404 do servidor.
- Não enviar filtros de PM/equipa/instalador esperando ampliar escopo; filtros são sempre interseção com o conjunto visível.
- Ocultar ações de drag/planning, guardar/aplicar vistas, mutação de preferências e todo CRUD.
- Não mostrar campos ausentes como `null` se o contrato não os declara.
- Usar `total`/paginação devolvidos pelo servidor; nunca calcular total a partir de dados globais.
