# Regras de inventário — MVP de Operações

> Ver `docs/PLAN_OPERATIONS_MVP.md` secção 3 para o desenho completo e as
> decisões assumidas; este documento é a referência operacional rápida.

## Os quatro números

Para cada (item, projeto):

```
stock_fisico_central   = Σ entrada − Σ saida − Σ consumo + Σ devolucao + Σ ajuste (com sinal)
reservado[projeto]     = Σ reserva[projeto] − Σ liberta_reserva[projeto] − Σ consumo[projeto]
stock_disponivel       = stock_fisico_central − Σ reservado[*] (todos os projetos)
consumido[projeto]     = Σ consumo[projeto] − Σ devolucao[projeto]
```

Nunca existe uma coluna de saldo editável — tudo é sempre recalculado a
partir de `inventory_movements` (`app/services/inventory.py`).

## Operações e permissões

| Operação | Efeito | Permissão |
|---|---|---|
| Entrada | ↑ físico | `inventory.manage_central` (Chefe/Admin) |
| Ajuste (+/-) | ↑/↓ físico, nunca < 0 | `inventory.manage_central` |
| Reservar | ↓ disponível | `inventory.allocate_project` (+ âmbito de projeto) |
| Libertar reserva | ↑ disponível | `inventory.release_project` (+ âmbito de projeto) |
| Consumir | ↓ físico e ↓ reservado do projeto | `inventory.consume_project` (+ âmbito de projeto) |
| Devolver | ↑ físico, nunca reabre a reserva | `inventory.consume_project` (+ âmbito de projeto) |

"Âmbito de projeto" = `project.edit_all` (qualquer projeto) ou o ator ser o
PM desse projeto (`project.edit_own_progress`) — a mesma regra já usada
para editar a identidade do projeto, nunca uma segunda lógica de "próprio
projeto" duplicada.

**PM não tem `inventory.manage_central`** — só Chefe/Administrador podem
alterar o stock físico central (entrada/ajuste). Isto é uma decisão
assumida (o pedido original era contraditório entre secções) — ver
`docs/PLAN_OPERATIONS_MVP.md` secção 11 e `docs/OPEN_QUESTIONS.md`.

## Validações

- Reservar nunca deixa `stock_disponivel < 0`.
- Libertar nunca deixa `reservado[projeto] < 0`.
- **Consumir exige reserva ativa suficiente no projeto** — não existe
  "consumo sem reserva" nesta versão (decisão assumida, documentada em
  `docs/OPEN_QUESTIONS.md`).
- Devolver nunca deixa `consumido[projeto] < 0`.
- Ajuste nunca deixa `stock_fisico_central < 0`.
- Todas as operações são transacionais (um commit por operação) e
  idempotentes via `idempotency_key` opcional — repetir a mesma chave
  devolve o movimento já criado.
- Nenhum movimento é apagado ou editado depois de criado — reverter é
  sempre um novo movimento de sinal oposto.

## Necessidades de material (`ProjectMaterialRequirement`)

```
em_falta = max(0, quantidade_necessaria − reservado[projeto] − consumido[projeto])
```

`available_stock_sufficient` indica se o stock disponível atual do item
cobre o `em_falta` calculado — usado para o alerta "material em falta" na
UI.

## Localizações (`InventoryLocation`)

Tipos: `central | project | vehicle | supplier`. O seed cria uma única
localização central com `code="IDEALMINDE"` — nunca usado para decidir
lógica de negócio por comparação de texto, só para o seed encontrar o
registo que ele próprio cria (idempotência).

## Exemplo de referência (do pedido original, coberto por teste)

```
100 km entram (central)
reservar 20 km para o Projeto A  → disponível 80, reservado[A] 20
consumir 5 km                   → físico 95, reservado[A] 15
libertar 10 km                  → reservado[A] 5, disponível 90
```

Resultado: físico 95, disponível 90, reservado[A] 5, consumido[A] 5 — ver
`backend/tests/test_inventory_ledger.py::test_worked_example_from_the_request`.
O seed de demonstração (`app/migration/seed_dev.py:seed_map_and_inventory`)
estende este exemplo com uma segunda reserva de 10 km para chegar ao
estado final apresentado na demonstração: físico 95, disponível 80,
reservado 15, consumido 5.
