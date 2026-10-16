# API — preferências e vistas pessoais da lista de Tarefas

## Âmbito

A configuração é pessoal do `User` autenticado. O cliente não envia `user_id`.
Guardar uma preferência ou vista não concede acesso a tarefas, projetos ou
pessoas: a listagem autorizada de Tarefas continua a ser a fonte de verdade.

O canal externo readonly puro não pode usar estes endpoints (`403`). As
capacidades de papéis combinados permanecem aditivas; uma capacidade adicional
não é removida para tornar o canal restrito.

## Configuração

Todos os campos abaixo são obrigatórios e a configuração é integral. Campos
extra, valores `null` e tipos não estritos são rejeitados com `422`.

```json
{
  "columns": ["task", "project", "assignee", "priority", "due_date", "status"],
  "sort_by": "default",
  "sort_direction": "asc",
  "view": "lista",
  "filters": {
    "project_id": "",
    "assigned_to_person_id": "",
    "priority": "",
    "status": "",
    "overdue_only": false
  }
}
```

Colunas permitidas: `task`, `project`, `assignee`, `priority`, `due_date`,
`status`, `category`, `created_at`. `task` é obrigatória e tem de ser a
primeira. Não há duplicados nem valores desconhecidos.

`sort_by` aceita `default`, `title`, `due_date`, `priority`, `created_at` e
`project_name`. `sort_direction` aceita `asc` ou `desc`. `view` aceita `lista`
ou `kanban`.

Os filtros aceitam strings vazias ou:

- `project_id`: UUID de um projeto alcançável pela união das consultas
  autorizadas de Projetos e Tarefas; um projeto ainda visível no seletor de
  Projetos continua válido mesmo quando não tem tarefas;
- `assigned_to_person_id`: UUID de um responsável alcançável pela consulta
  autorizada de Tarefas (ou a própria `Person` ativa quando pertence ao fluxo
  legítimo do utilizador, incluindo contextos com `task.view_all`);
- `priority`: `low`, `medium`, `high` ou `urgent`;
- `status`: `todo`, `in_progress`, `blocked`, `done` ou `cancelled`;
- `overdue_only`: booleano JSON estrito.

As referências fora do âmbito autorizado são rejeitadas em escritas com
`422`. O seletor `/api/people` pode mostrar outras pessoas por razões do
âmbito de Projetos mesmo sem tarefas; isso não cria uma permissão de diretório
nem torna esse ID guardável: fora das exceções acima, a pessoa tem de ser
alcançável por uma consulta autorizada de Tarefas. Se uma referência guardada
deixar de ser visível, as respostas de GET redigem apenas esse filtro para
`""`, numa cópia da configuração; o JSON persistido e o objeto ORM não são
alterados.

## Preferência de abertura

### `GET /api/me/task-list-preferences`

Devolve `{ "config": Config }`. Quando ainda não existe uma linha para a
conta, devolve os valores por omissão sem criar uma linha.

### `PUT /api/me/task-list-preferences`

Body:

```json
{"config": Config}
```

É um upsert por conta e devolve `{ "config": Config }` com `200`. A criação
inicial é serializada através do lock da linha existente de `User` e de uma
releitura antes do insert.

## Vistas guardadas

### `GET /api/me/task-list-views`

Devolve um array de vistas ativas, ordenado por nome sem distinguir maiúsculas:

```json
[
  {
    "id": "<uuid>",
    "name": "Operação",
    "config": Config,
    "created_at": "<datetime>",
    "updated_at": "<datetime>"
  }
]
```

### `POST /api/me/task-list-views`

Body:

```json
{"name": "Operação", "config": Config}
```

O nome é `trim` e tem de ter entre 1 e 120 caracteres. Nomes ativos são únicos
por utilizador. Sucesso: objeto da vista com `201`; duplicado ativo: `409`.

### `PATCH /api/me/task-list-views/{id}`

Body com `name` e/ou `config`. `config`, quando presente, substitui a
configuração inteira; `null` não significa omissão e é rejeitado com `422`.
Nome e configuração são validados atomicamente antes da escrita. Sucesso:
objeto da vista com `200`.

### `DELETE /api/me/task-list-views/{id}`

Faz remoção lógica (`is_active=false`) e devolve `204` sem corpo. Uma vista
removida pode libertar o seu nome para uma nova vista ativa.

Todos os PATCH/DELETE aplicam ownership na própria query `(user_id, id)`. UUID
inexistente, de outra conta ou de uma vista removida devolve `404` uniforme.

## Erros e persistência

- `401`: autenticação ausente ou inválida;
- `403`: canal externo readonly puro ou ausência de capacidade de leitura de
  Tarefas;
- `404`: vista não existente, removida ou de outra conta;
- `409`: nome ativo duplicado, incluindo corrida concorrente protegida pelo
  índice parcial da base de dados;
- `422`: payload, tipo, `null`, configuração, nome ou referência inválidos;
- `503`: falha de leitura/escrita da base de dados, com detalhe sanitizado e sem
  declarar sucesso.

As tabelas próprias são `task_list_preferences` (uma linha por conta) e
`task_list_views` (vistas ativas e soft-delete). A migração
`f3b5d7e9a1c2` sucede `e2f4a6c8b0d1`; o downgrade remove apenas estas duas
estruturas e o índice de nomes ativos.
