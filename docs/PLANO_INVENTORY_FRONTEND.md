# Plano — fatia frontend de inventário

> **Estado:** implementado no snapshot local; por rever/aprovar antes de qualquer publicação. Esta
> fatia altera apenas `frontend/**` e este plano. Não altera o contrato
> `docs/API_INVENTORY_REVERSALS.md`, backend, fornecedores/equipas, dark mode ou dados reais.

## Âmbito fechado

- Consumir o endpoint `POST /api/projects/{project_id}/inventory/movements/{movement_id}/reverse`.
- Mostrar **Anular** apenas quando a sessão tem `inventory.reverse_project`; o servidor continua a ser a autoridade de capability e âmbito.
- Esconder a ação no movimento compensatório e no movimento original que já tem compensação.
- Confirmar numa modal simples, pedir motivo até 220 caracteres, impedir duplo clique durante o POST e manter erros 400/404/409 visíveis.
- Após sucesso, recarregar o resumo do projeto e os artigos ativos usados para unidades/saldos; manter o original no histórico.
- Centralizar a apresentação de quantidades: artigos contados à unidade removem apenas zeros decimais (`1.000 un` → `1 un`); unidades fracionárias preservam a precisão recebida (`1.500 km` → `1.500 km`); valores fracionários marcados como `un` permanecem visíveis.
- Aplicar o helper a stock central, necessidades, material no local, movimentos, pedidos e planos/mapa.
- Preservar o WIP existente de catálogo, fornecedores, equipas, dark mode e mobile; o delta não copia a UI antiga inteira.

## Contrato e separação de conceitos

- A anulação é compensatória e append-only; a UI não edita nem cancela necessidades de material.
- Necessidades (`ProjectMaterialRequirement`) e movimentos (`InventoryMovement`) continuam separados.
- A UI filtra artigos inativos dos seletores operacionais conforme a implementação herdada; o backend valida referências, permissões, âmbito, saldos e idempotência.

## Alterações frontend

| Ficheiro | Alteração |
|---|---|
| `src/api/client.ts` | campo `reversal_of_movement_id` e cliente tipado do endpoint |
| `src/pages/ProjectDetail.tsx` | modal de motivo/confirmação, estados de loading/erro, capability, ocultação de ação e refresh |
| `src/utils/quantities.ts` | helper unit-aware partilhado |
| `src/pages/Inventory.tsx` | helper no catálogo/stock central e movimentos |
| `src/components/MaterialRequests.tsx` | helper nas linhas dos pedidos |
| `src/components/TripPlanModal.tsx`, `src/utils/tripPlan.ts` | helper em material a recolher |
| testes inventory/project/map/material requests/trip plan + `utils/quantities.test.ts` | regressões de permissões, compensação, erro, loading, refresh e precisão |

## Verificação

- RED observado antes do helper: Vitest não resolveu `src/utils/quantities`.
- Focos inventory/reversal/quantities/trip plan/map/material requests: executados com Vitest após implementação.
- Suite frontend completa, `tsc --noEmit`, lint, build, `git diff --check` e smoke browser continuam gates do handoff; backend suite, produção, deploy, commit, push e merge ficam fora desta fatia.

## Critérios de aceitação

1. Capability ausente não expõe a ação; capability presente expõe-a só em movimento elegível.
2. O original permanece imutável; movimento compensatório e já compensado não podem ser novamente anulados pela UI.
3. Motivo é enviado, o botão fica disabled enquanto aguarda, erros dependentes continuam visíveis e sucesso atualiza os dados.
4. Formatação nunca arredonda silenciosamente precisão fracionária.
5. O delta exclusivo aplica sobre a preimagem frontend capturada e não inclui `dist`, `node_modules`, `tsbuildinfo`, backend ou `docs/DECISIONS.md`.
