# Plano — Relatório semanal ao cliente (D-082)

> Branch `feat/relatorio-semanal-cliente` (a partir de `main` 18fab35).
> Estado: plano aprovado pelo utilizador em 2026-09-29.

## 1. Objetivo

Enquanto um projeto não está concluído, o PM envia todas as semanas ao cliente
um email com o estado do projeto. O PM escolhe os destinatários (Para e CC), o
dia e a hora, e pode rever antes de enviar.

## 2. Decisões do utilizador

| # | Decisão |
|---|---|
| D1 | O email sai da **caixa do PM do projeto** (o email do `User` do PM), via Microsoft Graph com **permissão de aplicação** `Mail.Send` (envio sem ninguém ligado). |
| D2 | Por omissão é **automático**: o PM configura destinatários, pode pausar, pré-visualizar e escrever uma nota da semana. **Opção por projeto**: "rever antes de enviar" — gera um rascunho que só sai depois de o PM aprovar. |
| D3 | Conteúdo: fase/etapa atual do processo, o que foi feito na semana, próximos passos, datas previstas da obra e a nota do PM. **Nunca** custos, notas internas, dados de licenciamento/comunicações, nomes de outros clientes. |
| D4 | **Dia da semana e hora configuráveis por projeto** pelo PM (fuso Europe/Lisbon). |

## 3. Regras (assumidas pelo orquestrador — reversíveis)

- **"Não concluído"** = `is_active = true` e `lifecycle_status` fora de
  `entregue_cliente`/`certificado_final`. Projetos sem estado (`NULL`) contam
  como não concluídos. **On hold pelo cliente não envia** (fica suspenso sem
  apagar a configuração).
- Cada projeto tem 0 ou 1 configuração. Sem configuração ou com `enabled=false`
  não se envia nada. Nunca se ativa sozinho.
- **Idempotência:** no máximo um relatório por projeto por semana ISO
  (Europe/Lisbon). Um reinício do agendador nunca duplica envios.
- **Recuperação:** se o agendador estiver parado à hora marcada, envia na
  próxima verificação dentro da mesma semana ISO; semanas passadas não são
  recuperadas.
- **Sem PM, PM sem `User` ativo ou sem email:** não envia; regista
  `skipped` com o motivo e mostra um aviso na página.
- **Destinatários:** 1–10 em Para, 0–10 em CC, emails validados, sem
  duplicados. O PM vai sempre em CC implícito? **Não** — só se o PM o
  acrescentar (evita surpresas); o email sai da caixa dele, por isso fica nos
  "Itens enviados".
- **Modo rever antes de enviar:** à hora marcada cria um rascunho
  (`pending_review`) e notifica o PM (notificação interna). O PM aprova
  (envia) ou descarta. Um rascunho não aprovado até ao fim da semana ISO
  expira (`expired`).
- **Envio manual:** "Enviar agora" (com confirmação) conta como o relatório da
  semana.
- **"Feito na semana":** subtarefas/contactos do processo marcados como feitos
  nos últimos 7 dias (`done_at`/`contact_done_at`) + mudanças de estado do
  ciclo de vida em `project_history` nos últimos 7 dias. Nada inventado: se
  não houver, "Sem alterações registadas esta semana".
- **Próximos passos:** as próximas etapas por concluir do processo (até 3) com
  datas previstas.
- **Permissões:** nova `client_report.manage`. PM (só nos seus projetos),
  Chefe e Administrador (todos). Comercial/Financeiro: podem **ver** o
  histórico (`client_report.view`) mas não configurar.
- **Auditoria:** cada envio/rascunho/erro fica guardado (`client_report_sends`)
  com assunto, corpo HTML enviado, destinatários, quem aprovou, estado,
  `graph_message_id`/erro.
- **Remetente e erros do Graph:** falha de envio → `failed` com a mensagem, e
  uma notificação interna ao PM. Sem novas tentativas automáticas na mesma
  semana além de 3 tentativas com espera crescente dentro da mesma execução.

## 4. Desenho técnico

### 4.1 Modelo (migração `a7c1e5d9f3b2`, `down_revision` = `b4d8f2a6c1e3`)

`client_report_configs`

| Coluna | Tipo |
|---|---|
| id | GUID PK |
| project_id | FK projects, **unique** |
| enabled | bool, default false |
| review_before_send | bool, default false |
| weekday | int 0–6 (0 = segunda) |
| send_time | time (hora local Europe/Lisbon) |
| to_emails | JSON list[str] |
| cc_emails | JSON list[str] |
| weekly_note | text nulo (nota da próxima emissão; limpa depois de enviada) |
| updated_by_person_id | FK people |
| created_at/updated_at | |

`client_report_sends`

| Coluna | Tipo |
|---|---|
| id | GUID PK |
| project_id | FK projects |
| iso_week | string `YYYY-Www` |
| status | `pending_review` / `sent` / `failed` / `skipped` / `discarded` / `expired` |
| trigger | `schedule` / `manual` |
| subject, body_html | text |
| from_email | string |
| to_emails, cc_emails | JSON |
| approved_by_person_id | FK people nulo |
| graph_message_id | string nulo |
| error | text nulo |
| created_at, sent_at | |

Índice único parcial lógico: no máximo um `sent` ou `pending_review` por
(`project_id`, `iso_week`) — garantido no serviço com lock/transação e
testado (SQLite não suporta todos os índices parciais de igual forma: usar
verificação transacional + teste de concorrência simples).

### 4.2 Graph (backend/app/adapters/graph/)

- `GraphMailSender` real: client credentials com **certificado** (preferido) ou
  segredo lido **só de ficheiro** (`GRAPH_CLIENT_CERT_FILE` +
  `GRAPH_CLIENT_CERT_THUMBPRINT`, ou `GRAPH_CLIENT_SECRET_FILE`), nunca de
  variável com o valor. `POST /users/{from}/sendMail` com
  `saveToSentItems=true`. Token cacheado até expirar. Usa `httpx`.
  Implementa só o envio de email (as restantes operações do adapter continuam
  `NotImplementedError`/fallback).
- `GRAPH_ENABLED=false` (omissão): o fallback local grava `.eml` e o envio fica
  `sent` com `graph_message_id = "local:<ficheiro>"` **e** um aviso claro na
  página "Modo de teste — nenhum email foi entregue". Mantém D-010.
- Testes com `httpx.MockTransport` — nunca rede real.

### 4.3 Agendador

- CLI `python -m app.cli.client_reports run-due [--now ISO] [--dry-run]`:
  processa todas as configurações devidas (idempotente).
- CLI `python -m app.cli.client_reports loop --interval 300`: ciclo simples
  para um serviço `scheduler` no docker-compose (mesma imagem do backend).
- A lógica fica em `app/services/client_reports.py`, testável com uma data
  injetada.

### 4.4 API

```
GET    /api/projects/{id}/client-report            → config + preview_available + last_sends(10) + warnings + can_manage
PUT    /api/projects/{id}/client-report            → cria/atualiza config
GET    /api/projects/{id}/client-report/preview    → {subject, body_html, from_email, to, cc}
POST   /api/projects/{id}/client-report/send-now   → envia já (conta para a semana)
POST   /api/client-report-sends/{send_id}/approve  → envia um pending_review
POST   /api/client-report-sends/{send_id}/discard  → descarta um pending_review
GET    /api/client-reports?status=&pm_person_id=   → lista para a página dos PMs (projetos visíveis, estado da config, próximo envio, último envio)
```

Âmbito: fora do âmbito → 404; sem permissão → 403; validação → 400/422.

### 4.5 Frontend

- **Página nova "Relatórios a clientes"** (`/client-reports`, menu lateral):
  lista dos projetos visíveis não concluídos com estado (Ativo / Pausado /
  Sem configuração / A aguardar revisão / Falhou), próximo envio, último
  envio, destinatários; filtros; alerta de rascunhos por aprovar.
- **Separador/cartão "Relatório semanal"** no detalhe do projeto: formulário
  (ativar, dia, hora, Para, CC, rever antes de enviar, nota da semana),
  pré-visualização do email, "Enviar agora" com confirmação, histórico com
  estado, aprovar/descartar rascunhos. Aviso "Modo de teste" quando o Graph
  não está ligado.
- Tudo com texto além de cor; só mostra ações que o servidor permite.

### 4.6 Template do email

HTML simples e responsivo (tabelas inline, sem imagens externas), em PT-PT,
assunto `Ponto de situação semanal — {projeto} — semana {n}`. Rodapé: "Para
questões, responda a este email." Tudo escapado (sem injeção de HTML a partir
de dados do projeto/nota).

## 5. Fases de trabalho (subagentes)

1. **Backend** — modelo, migração, serviço, conteúdo, Graph, CLI, API, testes.
2. **Frontend** — página e cartão, contra o contrato da secção 4.4 (tipos
   tolerantes; acompanha `docs/API_CLIENT_REPORTS.md` escrito pelo backend).
3. **Validação do orquestrador** — suite completa, migração, revisão de
   segurança (escape, âmbito, idempotência, segredos), teste ponta a ponta com
   o fallback local; erros devolvidos aos subagentes.

## 6. O que é preciso fora do código (para funcionar a sério)

Ver resposta final ao utilizador (Entra: permissão de aplicação `Mail.Send`
com consentimento, certificado, e **Application RBAC/Application Access
Policy do Exchange limitada a um grupo com as caixas dos PMs**; serviço
`scheduler` no compose; utilizadores reais dos PMs com email).
