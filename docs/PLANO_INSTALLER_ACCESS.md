# Plano — acesso externo delimitado por instalador

Estado: implementação backend isolada, sem provisionamento de contas reais.

## Decisões fechadas

- `instalador_colaborador` é um papel genérico; a autorização efetiva vem da união de permissões e da tabela `installer_access_memberships`.
- A associação Pessoa–Instalador é por IDs internos, única por par e auditada na mesma transação. Não há matching por email/nome.
- Projetos visíveis são a união de `projects.installer_id` e `project_team_assignments.installer_id`, sempre pela query SQL canónica.
- O acesso é de leitura: projetos, processo/tarefas básicas, obras/calendário, equipas associadas, inventário por projeto e Banco de Horas próprio.
- Projetos fora do âmbito e UUIDs inexistentes têm resposta uniforme 404 nos detalhes.
- O DTO externo remove emails/contactos, notas administrativas, integração, auditoria, custos/supplier data e pessoas estrangeiras.
- Inventário externo não inclui stock central, movimentos globais, preços, fornecedores, atores ou notas de auditoria.
- Nenhuma migração cria `Person`, `User`, `UserRole` ou ligação Entra; a migração só cria catálogo, memberships e histórico.

## Migração

`d9e1f3a5b7c2` segue `c8f0a2b4d6e1`, cria as tabelas de associação/histórico e um tracking de grants próprios para downgrade seguro. O downgrade remove apenas grants/catalog rows criados pela revisão e nunca remove `user_roles`.

## Fora desta fase

Provisionamento real a partir da fonte privada, Microsoft Entra, M365, UI/frontend e execução em produção.
