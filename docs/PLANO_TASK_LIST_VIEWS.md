# Tarefas — colunas configuráveis e vistas pessoais

Estado: implementação autorizada por o responsável do produto em 2026-10-16 ("faz isso" após recomendação delimitada de levar as opções de Projetos a Tarefas). Continuar a fase até testes, revisão independente e publicação no destino Tailscale já autorizado, com backup e readback. Sem commit/push/merge. Exclusões: modelos de trabalho, ações em lote, exports, novas permissões, alterações da máquina de estados ou da visibilidade.

## Base e reutilização
Snapshot de conteúdo do principal, incluindo WIP publicado, com manifesto externo `../Op_PM-task-views-evidence-20261016/baseline-content-manifest.json` (496 ficheiros). Head runtime verificado `e2f4a6c8b0d1`. Projetos, Obras, Banco de Horas e canal externo ficam preservados. Reusar padrões de project_list_views e a correção comprovada do upsert inicial; não construir um framework de workflows nem fazer refatoração transversal de Projetos nesta fase.

## Contrato congelado backend/frontend
Config JSON completo:
```
{
 "columns": ["task","project","assignee","priority","due_date","status"],
 "sort_by": "default",
 "sort_direction": "asc",
 "view": "lista",
 "filters": {"project_id":"","assigned_to_person_id":"","priority":"","status":"","overdue_only":false}
}
```
Colunas permitidas: seis acima (default), extras `category`, `created_at`. `task` obrigatória e primeira. O array é a ordem visível, sem duplicados/unknown/null; não esconder colunas do Kanban (essas representam estados e não são colunas de tabela). Na tabela, manter renderers existentes, links de projeto, Avatar, sinais de atraso/prioridade, TaskStatusControl e can_edit.

Sort permitido: `default`, `title`, `due_date`, `priority`, `created_at`, `project_name`; direção `asc|desc`. `default` preserva ordem recebida da API (não muda a experiência legada); demais são client-side sobre resultados já autorizados. Título/nome natural/numeric; prioridade com ordem de negócio urgent/high/medium/low (asc = urgente primeiro); nulos no fim mesmo em desc, desempate estável. No Kanban, ordenar só dentro de cada estado, preservar a paginação 20 e Mostrar mais.

Filtros status: vazio ou `todo|in_progress|blocked|done|cancelled`; priority vazio ou `low|medium|high|urgent`; UUIDs vazios ou UUIDs válidos; overdue_only StrictBool. `view`: `lista|kanban`. `status` continua sem ser aplicado em Kanban, conforme contrato publicado; preservar ao alternar para lista e deixar claro na UI que esse filtro pertence à lista.

Endpoints pessoais autenticados (não adicionar user_id recebido do cliente):
- GET `/api/me/task-list-preferences` -> `{config: Config}`, defaults sem escrita se ausente.
- PUT mesma rota body `{config: Config}` -> `{config: Config}`.
- GET `/api/me/task-list-views` -> array de `{id,name,config,created_at,updated_at}`.
- POST mesma rota body `{name,config}` -> objeto com 201.
- PATCH `/api/me/task-list-views/{id}` body `{name?,config?}` -> objeto; config é substituição integral se presente.
- DELETE mesma rota -> 204, remoção lógica.
Nomes trim 1..120, únicos entre vistas ativas por utilizador; conflito409, foreign/inexistente404 uniforme, payload/tipo/null inválido422, storagefalha sanitizada sem falso sucesso. Datas de auditoria servidor, sem aceitar do cliente.

Tabelas próprias `task_list_preferences`, `task_list_views`, migração única após `e2f4a6c8b0d1`. Não alterar tabelas de tarefas/histórico, dados existentes, grants/papéis. Serializar primeira criação de preferências no User existente e reler após lock; duas sessões PostgreSQL reais devem obter [200,200] e uma só linha. Concorrência de nomes vistas [201,409]. Montar DTO antes do commit; falhas pós-commit não podem fingir escrita falhada.

## Âmbito e segurança
Reusar a autorização real de Tarefas/serviço list_tasks e permissões aditivas existentes, não nomes de papéis. Canal externo readonly puro não ganha estes endpoints de escrita/personalização (página externa distinta inalterada); papéis combinados preservam união de âmbitos. Filtros de projeto/responsável só podem referir IDs já alcançáveis por consultas autorizadas de Projetos/Tarefas, mais a própria Person se isso já pertence ao fluxo legítimo. Não criar diretório global novo. Rejeitar filtros estrangeiros na escrita sem revelar detalhes; redigir IDs que deixaram de ser visíveis no GET, numa cópia sem mutar ORM. Guardar uma vista não concede acesso: GET /api/tasks continua a ser a fonte scoped. Testar A/B, apoio delegado e externo puro + combinado.

## Interface
Mostrar/esconder colunas; ordem com subir/descer acessível; restaurar padrão. Seletor de ordenação. Vistas criar/aplicar/atualizar/renomear/remover com confirmação, erros explícitos. Guardar preferência de abertura por botão explícito; não autosalvar a cada alteração.

Persistir também lista/kanban no backend por conta. A antiga chave global localStorage `op_pm_tasks_view` não pode sobrepor preferências de outra conta; remover como fonte de verdade ou limitar fallback à conta autenticada sem importar dados entre contas. Preservar alternância lista/kanban e justificar/atualizar apenas testes de persistência local substituídos por contrato backend equivalente.

URL explícita prevalece sobre preferência na abertura, mantendo os aliases publicados `prioridade` e `atrasadas=1`. Usar `project_id`, `assigned_to_person_id`, `status`, `view`, `sort_by`, `sort_direction`, `columns` (repetido) para restantes parâmetros, validar e normalizar sem ciclos. Back/forward deve restaurar estado. Preferência GET atrasada não pisa interação, conta trocada nem URL explícita. Guardar/apply não mistura respostas de contas anteriores. Limpar filtros não elimina colunas/vistas/ordenação. ListTasks assíncrono obsoleto não pisa a resposta mais recente.

Preservar criar tarefa, TaskFormModal, feedback busy/justDone, transições permitidas, dragdrop de cartões, recusa can_edit, kanban paginação, erros/retry e filtros. Sem novos side effects externos. Menus Escape/clique fora, teclado e foco; 390 e 360px sem overflow global (scroll só wrapper de tabela/Kanban), sem ocultar conteúdo para mascarar erros.

## Gates
TDD focado backend SQLite e PG, ownership/validação/redação/upsertconcorrente/nomes/softdelete, migração up/down/up em ambos; logs reais e comando/exit. Frontend mapear asserções legadas antes de editar, preservar ou equivalente mais forte, testes de vistas/colunas/refresh/URL/conta/erros e Kanban. Suite integrada BE SQLite/PG e FE uma vez após escritores fecharem, tipos/build/diffcheck. Browser contra API real e fixtures sintéticas, CRUD e refresh, desktop/390/360. Revisão independente e patch exclusivo com preimagens/hash/roundtrip, publicação do snapshot exato, readback de dados/auth/runtime. Nada de identidades privadas em fixtures/docs/logs públicos.
