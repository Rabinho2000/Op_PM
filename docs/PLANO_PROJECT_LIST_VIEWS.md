# Projetos — colunas e vistas pessoais

Estado: implementação autorizada por o responsável do produto em 2026-10-16 ("ok, faz isso"), limitada à recomendação de colunas configuráveis + vistas pessoais na lista de Projetos. Sem modelos, ações em lote, exportações, novas permissões globais, push/commit/merge. Preparar entrega testada e revisão independente. Publicação segue o âmbito Tailscale previamente autorizado, sem mudanças de segurança.

## Base
Snapshot do conteúdo real do principal, incluindo WIP publicado; não apenas HEAD. Manifesto externo `../Op_PM-project-views-evidence-20261016/baseline-content-manifest.json`. Preservar integralmente Banco de Horas, acessos externos, calendário e agrupamento existente.

## Contrato fechado (backend/frontend)
Colunas permitidas, por esta ordem por omissão: `project`, `pm`, `lifecycle`, `progress`, `next_task`, `overdue`, `warnings`. Extras opcionais: `installer`, `start_date`, `power_kwp`. `project` obrigatória, sempre primeira; arrays sem repetição ou valores desconhecidos. Colunas visíveis são o array ordenado. Restaurar padrão na UI. Sem drag obrigatório: subir/descer acessíveis por teclado.

Config JSON completo:
```
{
 "columns": ["project","pm","lifecycle","progress","next_task","overdue","warnings"],
 "sort_by": "name",
 "sort_direction": "asc",
 "filters": {"search":"","status":"","lifecycle":["on_hold_cliente","preparacao","construcao","construido"],"pm":"","active":"active","startFrom":"","startTo":""}
}
```
A lista default `lifecycle` deve ser a mesma de IN_PROGRESS_LIFECYCLE efetivamente existente no frontend (ler antes de implementar; exemplos acima não a substituem). `lifecycle: []` significa todos. Ordenação permitida `name`, `start_date`, `power_kwp`, `created_at` com `asc|desc`; ordenar dentro dos grupos atuais, nomes numericamente (localeCompare numeric), valores nulos no fim, desempate estável. Não alterar significado da conclusão nem agrupar de outra forma.

Endpoints autenticados pessoais:
- GET `/api/me/project-list-preferences` -> `{config: Config}` (defaults sem escrita quando ausente).
- PUT mesma rota body `{config: Config}` -> `{config: Config}` (upsert).
- GET `/api/me/project-list-views` -> array de `{id,name,config,created_at,updated_at}`.
- POST mesma rota body `{name,config}` -> objeto, 201.
- PATCH `/api/me/project-list-views/{id}` body `{name?,config?}` -> objeto; config substitui integralmente se presente.
- DELETE mesma rota -> 204, remoção lógica da vista (is_active false), não alterar dados de projetos.
Nomes trim, 1..120 chars, únicos entre vistas ativas da mesma conta, duplicado 409. Unknown fields/tipos/nulls/UUIDs/datas inválidas -> 422, sem 500. Identificador alheio e inexistente -> 404 indistinguíveis. Lista de colunas/filtros estritamente validada, limites de pesquisa e arrays. Sem user_id fornecido pelo cliente.

Persistência nova separada de Works: tabela própria de preferências e de vistas, ownership pelo User autenticado. Uma migração após head real `d9e1f3a5b7c2`, sem tocar em grants/papéis ou dados reais. Reusar padrões atuais de autenticação, transação, JSON e datas. Nenhuma alteração às permissões de leitura dos projetos: listProjects continua a usar API scoped existente. PM só pode ser guardado se alcançável nos projetos visíveis (ou self se existente nesse âmbito); ao ler filtro cujo PM saiu do âmbito, redigir para vazio sem alterar ORM. Canal externo readonly puro não ganha escrita: recusar estes endpoints para is_installer_readonly_scope; mistura de papéis mantém semântica aditiva existente.

## UI
Preservar todos os comportamentos/testes publicados. Acrescentar seletor de colunas com mostrar/esconder, ordem e restaurar; seletor de ordenação; guardar vista atual, aplicar, atualizar, renomear e remover com confirmação; botão explícito de guardar como preferência de abertura. Não autosalvar filtros a cada tecla. Filtros, ordenação e colunas restauram após refresh/nova sessão via backend. URL explícito prevalece sobre preferências iniciais (preservar semântica `estado`, histórico back/forward); não aplicar preferência atrasada por cima de interação manual; cancelar efeitos de conta anterior. `Limpar filtros` não destrói colunas nem vistas. Erros de carregar/gravar explícitos, nunca falso sucesso. Tabela colSpan dinâmico e sem overflow da página a 390/360px (scroll apenas wrapper da tabela); menus acessíveis Escape/clique fora.

## Verificação
TDD focado backend SQLite e PostgreSQL: ownership entre duas contas, readonly, validar payloads, defaults sem escrita, upsert/replay, nomes duplicados, nulls, filtros estrangeiros, datas e migração up/down/up. Frontend preservar matriz de testes anteriores e adicionar colunas/reordenação, vistas CRUD, refresh, URL vs default, loading races/conta, erros, grupos dinâmicos e permissões PM. Depois suite integrada uma vez, lint/types/build, browser sintético desktop/mobile com API real, revisão independente do delta, artefacto exclusivo com preimagens/hashes e roundtrip. Sem dados pessoais ou credenciais em código/evidência.
