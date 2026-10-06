# API — Relatório semanal ao cliente

Contrato da primeira fatia backend. Os caminhos são os consumidos pelo frontend
existente; o scheduler automático e o adaptador Microsoft Graph são trabalho da
fatia seguinte.

## Autorização

- `client_report.manage`: PM, Chefe de Operações e Administrador, sempre
  limitado ao âmbito do projeto (o PM só gere projetos que lhe estejam
  atribuídos).
- `client_report.view`: Comercial e Financeiro, além de quem gere relatórios.
- Sem a capacidade adequada: `403`. Projeto fora do âmbito de gestão/consulta:
  `404`, sem revelar se existe configuração.

A autorização é aplicada no serviço, não apenas nas rotas.

## Configuração por projeto

### `GET /api/projects/{project_id}/client-report`

Devolve:

```json
{
  "enabled": false,
  "review_before_send": false,
  "weekday": 0,
  "send_time": "09:00:00",
  "to_emails": [],
  "cc_emails": [],
  "weekly_note": null,
  "config": null,
  "can_manage": true,
  "delivery_mode": "local",
  "preview_available": false,
  "next_send_at": null,
  "warnings": [],
  "last_sends": []
}
```

### `PUT /api/projects/{project_id}/client-report`

Requer `client_report.manage`. Corpo completo (campos extra são rejeitados):

```json
{
  "enabled": true,
  "review_before_send": true,
  "weekday": 0,
  "send_time": "09:00",
  "to_emails": ["cliente@example.com"],
  "cc_emails": [],
  "weekly_note": "Nota pública da semana"
}
```

`to_emails`: 1–10 endereços; `cc_emails`: 0–10; emails válidos e sem
duplicados, comparados sem distinguir maiúsculas/minúsculas. `weekday` é 0–6.
A validação de domínio e limite também é repetida no serviço para chamadas que
não passem pela API.

## Pré-visualização e envio

- `GET /api/projects/{project_id}/client-report/preview` — requer `view` ou
  `manage`; devolve `subject`, `body_html`, `from_email`, `to`, `cc`.
- `POST /api/projects/{project_id}/client-report/send-now` — requer `manage`;
  conta sempre a semana ISO corrente em `Europe/Lisbon` e é idempotente por
  projeto+semana. Devolve um `ClientReportSend`.
- `POST /api/client-report-sends/{send_id}/approve` — aprova e envia um rascunho
  `pending_review`.
- `POST /api/client-report-sends/{send_id}/discard` — marca o rascunho como
  `discarded`.

Estados possíveis: `pending`, `pending_review`, `sent`, `failed`, `skipped`,
`discarded`, `expired`. A nota semanal só é limpa depois de envio efetivo.
Rascunhos pendentes de semanas anteriores podem ser marcados como `expired`
por `expire_pending_reviews` (a chamada do scheduler fica para a fatia seguinte).

Quando `GRAPH_ENABLED=false`, o envio grava um `.eml` em
`GRAPH_FALLBACK_DIR`, devolve `graph_message_id` como `local:<ficheiro>` e
mantém o aviso de modo de teste em `error`. Com Graph ativo, esta fatia não
implementa client credentials nem envia para a rede; o adaptador injetável fica
preparado para a fatia seguinte.

Projetos ativos com `lifecycle_status = NULL` são elegíveis. São excluídos
estados entregues, certificados, concluídos e `on_hold`. Sem PM, sem User ativo
ou sem email do PM, o resultado é `skipped` com aviso; não há envio cego.

## Catálogo global

### `GET /api/client-reports?status={status}&pm_person_id={uuid}`

Requer `client_report.view` ou `client_report.manage`. Devolve uma lista de:

```json
{
  "project_id": "uuid",
  "project_name": "Projeto",
  "client_name": "Cliente",
  "pm": "Nome do PM",
  "lifecycle_status": null,
  "status_label": "sent",
  "enabled": true,
  "next_send_at": null,
  "last_send": null,
  "pending_review_count": 0,
  "to_emails": ["cliente@example.com"],
  "cc_emails": []
}
```

`status` filtra pelo último envio que corresponda ao estado; `pm_person_id`
filtra o PM. O serviço ainda aplica o âmbito do utilizador.

## Conteúdo

O HTML é PT-PT e escapa todos os valores. Inclui fase/etapa, alterações de
processo registadas nos últimos sete dias, até três próximos passos, datas
previstas e nota configurada. Não inclui custos, notas internas, campos
comerciais internos, credenciais, nem dados de outros clientes.
