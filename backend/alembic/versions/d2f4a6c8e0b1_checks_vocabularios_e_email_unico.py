"""CHECKs dos vocabulários fechados e das quantidades; email único sem distinção de maiúsculas.

M7 — os vocabulários fechados (estados, tipos de movimento, modos do banco de
horas, ...) só eram garantidos em Python; como o stock e os saldos são
derivados por somas, uma linha inválida corrompe-os em silêncio. Cada
vocabulário passa a ter um CHECK, tal como `user_requests` (modelo a seguir),
e as quantidades de inventário ganham CHECKs de sinal:

- `inventory_movements.quantity`: nunca zero; `ajuste` tem sinal livre
  (delta ±); nos restantes tipos é positiva, excepto nas linhas de anulação
  (`reversal_of_movement_id` preenchido), que são sempre o simétrico (< 0);
- `material_request_items.quantity` e `project_material_requirements.quantity_required` > 0;
- `inventory_items.min_stock` >= 0.

M8 — `users.email` passa a ser guardado em minúsculas e sem espaços nas pontas
e ganha um índice único funcional em `lower(email)` (a autenticação compara com
`lower(email)`; `A@x` e `a@x` bloqueavam a ligação JIT sem dar erro).

Os valores dos vocabulários estão congelados em literais (uma migração tem de
continuar a significar o mesmo); `tests/test_check_constraints.py` confirma que
coincidem com os modelos.

ANTES de criar cada CHECK/índice, a migração procura linhas que o violariam e
aborta, sem alterar nada, com uma mensagem que diz tabela, coluna, contagem e
valores distintos ofensivos (nunca emails nem outros dados pessoais). Em SQLite
os CHECKs são criados com `batch_alter_table`.

O downgrade remove os CHECKs e o índice; a normalização do email não é
reversível (a capitalização original perdeu-se).

Revision ID: d2f4a6c8e0b1
Revises: b9e1d3f5a7c2
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d2f4a6c8e0b1"
down_revision: str | Sequence[str] | None = "b9e1d3f5a7c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMAIL_INDEX = "uq_users_email_lower"

_MATERIAL_REQUEST_STATUSES = (
    "rascunho",
    "pedido_enviado",
    "orcamento_recebido",
    "aprovado",
    "adjudicado",
    "enviado_financeiro",
    "pago",
    "cancelado",
)


def _in(column: str, values: Sequence[str], *, nullable: bool = False) -> str:
    clause = f"{column} IN ({', '.join(repr(v) for v in values)})"
    return f"{column} IS NULL OR {clause}" if nullable else clause


# (tabela, nome do CHECK, cláusula, expressão que descreve a linha ofensiva)
_CHECKS: tuple[tuple[str, str, str, str], ...] = (
    (
        "projects",
        "ck_projects_lifecycle_status",
        _in(
            "lifecycle_status",
            ("on_hold_cliente", "preparacao", "construcao", "construido", "entregue_cliente", "certificado_final"),
            nullable=True,
        ),
        "lifecycle_status",
    ),
    (
        "inventory_locations",
        "ck_inventory_locations_location_type",
        _in("location_type", ("central", "project", "vehicle", "supplier", "office")),
        "location_type",
    ),
    (
        "inventory_locations",
        "ck_inventory_locations_owner",
        _in("owner", ("solcor", "verde_milenar")),
        "owner",
    ),
    (
        "inventory_movements",
        "ck_inventory_movements_movement_type",
        _in(
            "movement_type",
            (
                "entrada",
                "saida",
                "reserva",
                "liberta_reserva",
                "consumo",
                "devolucao",
                "ajuste",
                "transito_entrada",
                "transito_saida",
                "entrega",
                "recolha",
            ),
        ),
        "movement_type",
    ),
    (
        "inventory_movements",
        "ck_inventory_movements_quantity_sign",
        "quantity <> 0 AND ("
        "movement_type = 'ajuste' "
        "OR (reversal_of_movement_id IS NULL AND quantity > 0) "
        "OR (reversal_of_movement_id IS NOT NULL AND quantity < 0))",
        "movement_type || ' com quantidade ' || CASE WHEN quantity = 0 THEN 'zero' "
        "WHEN quantity < 0 THEN 'negativa' ELSE 'positiva' END "
        "|| CASE WHEN reversal_of_movement_id IS NULL THEN '' ELSE ' (anulacao)' END",
    ),
    (
        "inventory_items",
        "ck_inventory_items_min_stock_non_negative",
        "min_stock >= 0",
        "'min_stock negativo'",
    ),
    (
        "project_material_requirements",
        "ck_project_material_requirements_quantity_positive",
        "quantity_required > 0",
        "'quantity_required nao positiva'",
    ),
    (
        "material_requests",
        "ck_material_requests_status",
        _in("status", _MATERIAL_REQUEST_STATUSES),
        "status",
    ),
    (
        "material_request_items",
        "ck_material_request_items_quantity_positive",
        "quantity > 0",
        "'quantity nao positiva'",
    ),
    (
        "material_request_history",
        "ck_material_request_history_from_status",
        _in("from_status", _MATERIAL_REQUEST_STATUSES, nullable=True),
        "from_status",
    ),
    (
        "material_request_history",
        "ck_material_request_history_to_status",
        _in("to_status", _MATERIAL_REQUEST_STATUSES),
        "to_status",
    ),
    (
        "time_bank_entries",
        "ck_time_bank_entries_calculation_mode",
        _in("calculation_mode", ("standard", "saturday", "manual", "imported")),
        "calculation_mode",
    ),
    (
        "time_bank_adjustments",
        "ck_time_bank_adjustments_kind",
        _in("kind", ("opening", "correction", "consumption")),
        "kind",
    ),
    (
        "time_bank_import_batches",
        "ck_time_bank_import_batches_status",
        _in("status", ("pending", "applied")),
        "status",
    ),
    (
        "project_issues",
        "ck_project_issues_category",
        _in("category", ("obra", "material", "documentacao", "visita", "outro")),
        "category",
    ),
    (
        "project_issues",
        "ck_project_issues_priority",
        _in("priority", ("low", "medium", "high", "urgent")),
        "priority",
    ),
    (
        "project_issues",
        "ck_project_issues_status",
        _in("status", ("aberta", "em_curso", "resolvida", "cancelada")),
        "status",
    ),
    (
        "tasks",
        "ck_tasks_status",
        _in("status", ("todo", "in_progress", "blocked", "done", "cancelled")),
        "status",
    ),
    (
        "tasks",
        "ck_tasks_priority",
        _in("priority", ("low", "medium", "high", "urgent")),
        "priority",
    ),
    (
        "tasks",
        "ck_tasks_category",
        _in("category", ("workflow", "field", "material", "documentation", "commercial", "other")),
        "category",
    ),
    (
        "absences",
        "ck_absences_type",
        _in("type", ("ferias", "baixa_medica", "outro")),
        "type",
    ),
    (
        "absences",
        "ck_absences_status",
        _in("status", ("pendente", "aprovada", "rejeitada", "cancelada")),
        "status",
    ),
    (
        "holidays",
        "ck_holidays_scope",
        _in("scope", ("nacional", "municipal", "empresa")),
        "scope",
    ),
    (
        "goal_periods",
        "ck_goal_periods_period_type",
        _in("period_type", ("year", "quarter", "semester", "month")),
        "period_type",
    ),
    (
        "goal_periods",
        "ck_goal_periods_metric",
        _in(
            "metric",
            (
                "installations",
                "kwp",
                "projects_completed",
                "projects_certified",
                "power_installed",
                "power_delivered",
            ),
        ),
        "metric",
    ),
    (
        "goal_periods",
        "ck_goal_periods_scope",
        _in("scope", ("company", "pm")),
        "scope",
    ),
    (
        "field_import_batches",
        "ck_field_import_batches_source_type",
        _in("source_type", ("notes_html", "notes_json", "licensing_excel")),
        "source_type",
    ),
    (
        "field_import_batches",
        "ck_field_import_batches_status",
        _in("status", ("pending_confirmation", "applied", "rejected")),
        "status",
    ),
    (
        "field_import_conflicts",
        "ck_field_import_conflicts_resolution",
        _in("resolution", ("pending", "use_new", "keep_old")),
        "resolution",
    ),
)

_MAX_DISTINCT_SHOWN = 15
_MAX_VALUE_LENGTH = 40


def _violations(bind: sa.Connection, table: str, clause: str, describe: str) -> list[tuple[str, int]]:
    """Valores distintos (com contagem) das linhas que violariam o CHECK.
    `NOT (cláusula)` tem a mesma semântica do CHECK: NULL não viola."""
    rows = bind.execute(
        sa.text(
            f"SELECT {describe} AS offending, COUNT(*) AS n FROM {table} "  # noqa: S608 - identificadores fixos, deste ficheiro
            f"WHERE NOT ({clause}) GROUP BY offending ORDER BY n DESC"
        )
    ).all()
    return [(str(value)[:_MAX_VALUE_LENGTH], int(count)) for value, count in rows]


def _check_existing_rows(bind: sa.Connection) -> None:
    problems: list[str] = []
    for table, name, clause, describe in _CHECKS:
        found = _violations(bind, table, clause, describe)
        if not found:
            continue
        total = sum(count for _, count in found)
        shown = ", ".join(f"{value!r} ({count})" for value, count in found[:_MAX_DISTINCT_SHOWN])
        extra = f" e mais {len(found) - _MAX_DISTINCT_SHOWN}" if len(found) > _MAX_DISTINCT_SHOWN else ""
        problems.append(f"  - {table} [{name}]: {total} linha(s) violam o CHECK; valores distintos: {shown}{extra}")

    duplicate_groups = bind.execute(
        sa.text(
            "SELECT COUNT(*), COALESCE(SUM(n), 0) FROM ("
            "SELECT COUNT(*) AS n FROM users GROUP BY lower(trim(email)) HAVING COUNT(*) > 1) d"
        )
    ).one()
    if duplicate_groups[0]:
        problems.append(
            f"  - users.email [{EMAIL_INDEX}]: {duplicate_groups[0]} grupo(s) de emails que só diferem "
            f"em maiúsculas/espaços ({duplicate_groups[1]} linhas no total). Desativar/fundir os duplicados "
            "antes de aplicar (os emails não são listados aqui)."
        )
    if problems:
        raise RuntimeError(
            "A migração d2f4a6c8e0b1 foi abortada sem alterar nada: há dados existentes que violariam "
            "as novas regras. Corrigir manualmente e repetir.\n" + "\n".join(problems)
        )


def upgrade() -> None:
    bind = op.get_bind()
    _check_existing_rows(bind)

    by_table: dict[str, list[tuple[str, str]]] = {}
    for table, name, clause, _ in _CHECKS:
        by_table.setdefault(table, []).append((name, clause))
    for table, checks in by_table.items():
        # Em SQLite recria a tabela (não há ALTER ... ADD CONSTRAINT); em
        # PostgreSQL emite ALTER TABLE ... ADD CONSTRAINT directamente.
        with op.batch_alter_table(table) as batch_op:
            for name, clause in checks:
                batch_op.create_check_constraint(name, sa.text(clause))

    op.execute(sa.text("UPDATE users SET email = lower(trim(email)) WHERE email <> lower(trim(email))"))
    op.create_index(EMAIL_INDEX, "users", [sa.text("lower(email)")], unique=True)


def downgrade() -> None:
    op.drop_index(EMAIL_INDEX, table_name="users")

    by_table: dict[str, list[str]] = {}
    for table, name, _, _ in _CHECKS:
        by_table.setdefault(table, []).append(name)
    for table, names in by_table.items():
        with op.batch_alter_table(table) as batch_op:
            for name in names:
                batch_op.drop_constraint(name, type_="check")
