# Plano — fatia frontend de equipas e afectações

> **Estado:** implementado no snapshot local; por rever/aprovar antes de qualquer publicação. Esta
> fatia não altera backend, dados reais, migração, `docs/API_TEAM_ASSIGNMENTS.md` ou
> `docs/DECISIONS.md`.

## Âmbito fechado

- Consumir o contrato `docs/API_TEAM_ASSIGNMENTS.md` através de funções tipadas no cliente:
  listar/criar/alterar/remover afectações e ler `/api/works/teams`.
- Mostrar e gerir várias afectações no cartão **Obra** do detalhe do projeto.
- Adicionar a rota `/works/teams`, ligação no calendário e entrada na navegação existente.
- Renderizar a vista operacional por instalador/equipa com período, data e filtro de instalador.
- Fazer o calendário consumir `assignment_id`, datas/nomes de equipa e uma barra por afectação.
- Preservar o WIP existente de dark mode, mobile, fornecedores e arrastar obras legadas.

## Regras de UI reconciliadas com o contrato

| Regra | Implementação frontend |
|---|---|
| Leitura depende apenas de `project.view` | O cartão carrega a lista mesmo quando `can_plan_work` é falso; só oculta as operações de escrita. |
| Escrita depende de autorização do servidor | Adicionar/editar/remover só aparece com `project.can_plan_work`; o backend continua a ser a autoridade. |
| Datas inclusivas e fim não anterior ao início | Formulário exige equipa/início/fim, aplica `min` no fim e valida novamente antes do POST/PATCH. |
| Equipa nova activa; histórica inactiva pode ser mantida | Novo selector lista apenas equipas activas; edição preserva a equipa actualmente ligada mesmo inactiva. |
| Aviso de janela é diagnóstico | `warning` aparece sem bloquear a afectação. |
| Equipa ocupada fora do âmbito não revela a obra | `ocupada_noutra_obra` mostra apenas o estado; a UI nunca inventa nem tenta renderizar uma atribuição vazia. |
| Várias afectações da mesma obra | A chave visual é `assignment_id`, as datas da barra vêm da afectação e os lanes não colidem pelo `project_id`. |
| Endpoint legado `/work-plan` não edita datas de afectação | Barras com `assignment_id` são de leitura no drag; a alteração é feita no cartão através de `/team-assignments`. |

## Compatibilidade visual

- CSS novo usa apenas tokens existentes (`--border`, `--danger`, `--warning`, `--text-*`), sem
  paleta clara fixa que furasse o tema escuro.
- A tabela da vista mantém scroll interno no telemóvel e o cartão de afectações passa a coluna
  única no breakpoint mobile existente (`760px`); não há alterações à infraestrutura de tema.
- Dados sintéticos usados nos testes não contêm nomes de pessoas/clientes reais.

## Provas executadas

- Vitest focado: `src/utils/worksTimeline.test.ts`, `src/components/TeamAssignments.test.tsx`,
  `src/pages/WorksTeams.test.tsx`, `src/pages/Works.test.tsx` — 4 ficheiros, 47 testes.
- TypeScript: `npx tsc --noEmit`.
- Build Vite: `npm run build` — exit 0.

## Fora deste handoff

- Backend, migração, testes backend, produção/deploy, browser com dados reais e aprovação global
  da funcionalidade. O backend/evidência de contrato continuam a ser gates do parent.
