# Sales Support — mockup ligado ao OP-PM

Subprojecto para gerir a passagem **Comercial / Sales Support → Operações** sem duplicar a plataforma OP-PM.

Branch inicial: `feature/sales-support-mockup`.

## Objectivo

1. Ler os projectos/tarefas comerciais a partir do ClickUp.
2. Apresentar um Kanban simples com três estados normalizados:
   - `Por fazer`
   - `A executar`
   - `Feito`
3. Mostrar o estado real do ClickUp em cada cartão, mesmo quando vários estados ClickUp caem na mesma coluna do Kanban.
4. Validar os campos mínimos antes da entrega a Operações.
5. Permitir uma acção explícita **Injectar projecto no OP-PM**.
6. Depois da injecção, guardar a relação estável `ClickUp task ID ↔ OP-PM project UUID` em `project_external_ids` (`source_system='clickup'`).
7. Correr no mesmo servidor e usar o mesmo backend / PostgreSQL do OP-PM.

## O que este mockup já demonstra

- visual baseado no design system actual do OP-PM;
- pipeline em Kanban de três colunas;
- pesquisa e filtro por responsável;
- estado de sincronização ClickUp;
- detalhe do projecto comercial;
- validação de campos obrigatórios;
- indicação de projecto já existente no OP-PM;
- contrato frontend para sincronização e injecção;
- modo mock por omissão para ser possível rever a UX sem credenciais reais.

## Execução local

```bash
cd sales-support
npm install
npm run dev
```

Abre em `http://localhost:5174`.

O Vite encaminha `/api/*` para o backend OP-PM em `http://localhost:8000`.

### Modo mock

`.env`:

```env
VITE_USE_MOCK=true
VITE_SALES_SUPPORT_API_BASE=/api/sales-support
```

### Modo backend real

```env
VITE_USE_MOCK=false
VITE_SALES_SUPPORT_API_BASE=/api/sales-support
```

Nesse modo o frontend espera estes contratos:

```text
GET  /api/sales-support/board
POST /api/sales-support/sync
POST /api/sales-support/items/{clickup_task_id}/promote
```

## Arquitectura proposta

```text
                     ClickUp
                       │
                       │ REST API / webhook + reconciliação
                       ▼
              ┌──────────────────┐
              │ OP-PM Backend    │
              │ FastAPI          │
              │                  │
              │ sales_support    │
              │ service          │
              └───────┬──────────┘
                      │
          ┌───────────┴────────────┐
          │                        │
          ▼                        ▼
 Sales Support UI             PostgreSQL OP-PM
 React/Vite                   mesma base de dados
          │                        │
          │                        ├─ projects
          │                        ├─ project_external_ids
          │                        └─ project_history
          │
          └──── utilizador confirma injecção ────►
```

### Porque não criar uma segunda base de dados

O ClickUp continua a ser a fonte de verdade do pipeline comercial e o OP-PM passa a ser a fonte de verdade operacional depois da entrega. Para o primeiro MVP não é necessário persistir uma cópia completa do Kanban: o backend pode ler ClickUp e usar `project_external_ids` para saber se cada item já foi promovido.

Se no futuro for necessário histórico comercial independente do ClickUp, auditoria de sincronizações ou funcionamento offline, adicionam-se tabelas próprias `sales_support_*` na mesma PostgreSQL.

## Regra da injecção

A injecção **não deve ser SQL directo vindo do browser**.

O botão chama um serviço backend transaccional que deve:

1. validar o utilizador e a permissão `sales_support.promote`;
2. voltar a confirmar que o `clickup_task_id` existe no ClickUp configurado;
3. confirmar que ainda não existe `ProjectExternalId(source_system='clickup', external_id=<task_id>)`;
4. validar os campos mínimos e mostrar erro se faltarem dados;
5. criar `Project` no OP-PM;
6. criar `ProjectExternalId` com o ID estável do ClickUp;
7. criar entradas `ProjectHistory` com `source='clickup'` / `source='sales_support'`;
8. fazer `commit` de tudo na mesma transacção;
9. devolver o UUID OP-PM ao frontend.

Se qualquer passo falhar, a transacção é revertida e não fica um projecto parcialmente criado.

## Mapeamento proposto ClickUp → OP-PM

| ClickUp | OP-PM | Regra |
|---|---|---|
| task id | `project_external_ids.external_id` | obrigatório, chave estável |
| task name / campo projecto | `projects.name` | obrigatório |
| cliente | `projects.client_name` | recomendado |
| contacto | `projects.client_contact` | recomendado |
| email | `projects.client_email` | recomendado |
| morada/local | `projects.address` | recomendado |
| latitude | `projects.lat` | opcional |
| longitude | `projects.lon` | opcional |
| potência | `projects.power_kwp` | recomendado |
| PM / responsável operacional | `projects.pm_person_id` | pode ser definido na entrega |
| data prevista | `projects.start_date` | recomendado |
| estado ClickUp | `projects.clickup_status_mirror` | espelho só de leitura |
| equipamento | `projects.equipment_notes` | opcional |
| injecção/rede | `projects.injection_notes` | opcional |
| pressupostos comerciais | `projects.commercial_assumptions` | opcional |

O mapeamento real deve usar **IDs de custom fields ClickUp**, não nomes visíveis, quando esses IDs forem conhecidos.

## Estados do Kanban

O Sales Support não deve obrigar o ClickUp a ter exactamente três estados. O backend normaliza os estados ClickUp para as três colunas, mas mantém `clickup_status` original visível.

Exemplo:

```text
Lead / levantamento / proposta pendente  -> Por fazer
Em proposta / engenharia / negociação    -> A executar
Contrato assinado / adjudicado / fechado -> Feito
```

O mapeamento final depende dos estados reais do espaço/lista ClickUp.

## Sincronização ClickUp

Para produção recomenda-se:

- webhook ClickUp para actualizações rápidas;
- reconciliação periódica (por exemplo a cada 10-15 min) para recuperar eventos perdidos;
- token/credencial apenas no backend, nunca no Vite/frontend;
- `CLICKUP_ENABLED=true` apenas depois de configurar token e List ID(s);
- logs sem payloads sensíveis nem tokens.

O repositório OP-PM já tem a interface `ClickUpAdapter`, configuração `CLICKUP_TOKEN` / `CLICKUP_LIST_ID` e `project_external_ids`; falta implementar/activar a chamada REST real e o módulo `sales_support` depois de fechar os pontos abaixo.

## Decisões que preciso do negócio antes de ligar produção

1. **Qual é o Workspace / Space / Folder / List do ClickUp** que contém estes projectos? Preciso dos List IDs exactos.
2. Um projecto comercial é **uma task**, uma parent task, ou outra entidade no ClickUp?
3. Quais são os **estados reais do ClickUp** e como queres mapeá-los para `Por fazer`, `A executar` e `Feito`?
4. Qual é o estado que significa **“já pode ir para OP-PM”**? `Contrato assinado`, `Adjudicado`, outro, ou um custom field booleano?
5. Que **custom fields** existem hoje no ClickUp para cliente, contacto, email, morada, potência, data prevista, equipamento e notas? Idealmente enviar os nomes e IDs.
6. A injecção deve ser **manual por botão** ou automática assim que o projecto chega ao estado aprovado? Recomendação inicial: manual, 1 clique, com pré-visualização.
7. Quem pode injectar: qualquer utilizador de Sales Support, apenas chefe comercial, Administrador/Chefe de Operações, ou combinação?
8. Depois de injectado, o Sales Support fica apenas a mostrar o link para OP-PM ou ainda permite alterações comerciais? Se o ClickUp mudar depois, quais campos podem continuar a actualizar o OP-PM?
9. O Sales Support precisa de **escrever de volta no ClickUp** (por exemplo marcar `Entregue a Operações` e guardar o UUID/link OP-PM) ou fica estritamente read-only?
10. Queres reaproveitar exactamente o mesmo **Microsoft Entra ID** e utilizadores/roles do OP-PM? Recomendação: sim.
11. O acesso vai ser por um caminho do mesmo domínio (`/sales-support`) ou por subdomínio (`sales.<dominio>`)?
12. Precisamos de trazer **anexos/documentos** do ClickUp para a entrega a Operações ou só os campos de dados?

## Próxima implementação depois destas respostas

- adapter REST ClickUp real;
- endpoint `GET /api/sales-support/board`;
- normalização configurável de estados;
- permissão `sales_support.view` e `sales_support.promote`;
- serviço transaccional de promoção para OP-PM;
- histórico/auditoria;
- webhook + reconciliação periódica;
- autenticação Entra partilhada;
- testes backend e frontend;
- integração no reverse proxy / Docker do mesmo servidor.
