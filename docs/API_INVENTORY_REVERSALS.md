# API — anulação compensatória de movimentos de inventário

Estado: contrato backend/API da fatia de inventário. A UI não faz parte deste snapshot.

## Endpoint

`POST /api/projects/{project_id}/inventory/movements/{movement_id}/reverse`

Request body opcional:

```json
{"reason": "Lançamento duplicado"}
```

`reason` tem no máximo 220 caracteres. Sem body ou sem `reason`, usa `Anulação manual`.

## Regras

- O projeto e o movimento têm de coincidir; um movimento de outro projeto responde `404`.
- A capability `inventory.reverse_project` é verificada no backend e exige o âmbito de edição do projeto: PM no projeto próprio; Chefe de Operações/Admin nas obras visíveis.
- O movimento original nunca é editado nem apagado.
- A operação cria exatamente uma linha compensatória com a mesma classe de movimento e quantidade com sinal oposto. `reversal_of_movement_id` liga a compensação ao original e é único; uma segunda tentativa responde `409`.
- A resposta inclui o ator (`created_by_person_id`), `created_at`, razão no `reference` (`Anulação: ...`) e a ligação ao original.
- A operação é atómica: lock + refresh do movimento e do artigo precedem os cálculos. PostgreSQL usa `FOR UPDATE`; SQLite toma o lock de escrita com um update neutro e relê o ORM.
- A anulação é recusada (`400`) se qualquer saldo dependente ficar negativo: reservado, consumido, stock físico, material no local ou stock disponível.
- Quantidades mantêm a precisão `Numeric(14, 3)`; não há arredondamento silencioso além da precisão contratada.

## Migração

`d4e6f8a1b2c3_inventario_anulacao_movimentos.py`

- `down_revision = e8b2c4d6f0a1` (o docstring e o valor Python têm o mesmo predecessor).
- Acrescenta a ligação auto-referente e a unicidade de uma compensação.
- Provisiona apenas `inventory.reverse_project` nos papéis existentes Administrador, Chefe de Operações e Project Manager, registando as linhas próprias para downgrade seguro.
- O downgrade remove apenas grants/permissão criados por esta migração e remove a coluna/constraint que o upgrade criou; não apaga movimentos nem histórico de auditoria.

## Fora do âmbito

Catálogo de inventário, fornecedores/equipas herdados, frontend, publicação, produção e dados reais não são alterados por esta fatia.
