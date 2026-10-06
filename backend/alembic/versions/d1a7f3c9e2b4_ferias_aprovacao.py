"""fluxo de aprovação de férias e auditoria das decisões

Revision ID: d1a7f3c9e2b4
Revises: 8a1d3f4c6b90
Create Date: 2026-09-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.db  # tipo de coluna portável app.db.GUID()


# revision identifiers, used by Alembic.
revision: str = "d1a7f3c9e2b4"
down_revision: Union[str, Sequence[str], None] = "8a1d3f4c6b90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Adiciona os dados de decisão sem alterar ausências existentes.

    Os estados antigos (`aprovada` e `cancelada`) continuam válidos no novo
    esquema. As linhas existentes recebem `decision_note=''` e mantêm os
    restantes campos de decisão a nulo; não se reabre nem se aprova de novo
    histórico já registado.
    """
    with op.batch_alter_table("absences", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("decided_by_person_id", app.db.GUID(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("decision_note", sa.Text(), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column("cancelled_by_person_id", app.db.GUID(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_absences_decided_by_person_id_people",
            "people",
            ["decided_by_person_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_absences_cancelled_by_person_id_people",
            "people",
            ["cancelled_by_person_id"],
            ["id"],
        )

    # O default só serve para preencher linhas legadas durante a alteração;
    # os defaults do modelo passam a ser a fonte de verdade em runtime.
    with op.batch_alter_table("absences", schema=None) as batch_op:
        batch_op.alter_column("decision_note", server_default=None)


def downgrade() -> None:
    """Volta ao esquema antigo, preservando estados representáveis.

    `pendente` e `rejeitada` não existem no esquema anterior. Como o histórico
    não pode ser apagado nem convertido em aprovação falsa, ficam `cancelada`
    antes de remover as colunas de decisão.
    """
    absences = sa.table("absences", sa.column("status", sa.String(length=32)))
    op.get_bind().execute(
        absences.update()
        .where(absences.c.status.in_(["pendente", "rejeitada"]))
        .values(status="cancelada")
    )

    with op.batch_alter_table("absences", schema=None) as batch_op:
        batch_op.drop_constraint("fk_absences_decided_by_person_id_people", type_="foreignkey")
        batch_op.drop_constraint("fk_absences_cancelled_by_person_id_people", type_="foreignkey")
        batch_op.drop_column("decision_note")
        batch_op.drop_column("decided_at")
        batch_op.drop_column("decided_by_person_id")
        batch_op.drop_column("cancelled_at")
        batch_op.drop_column("cancelled_by_person_id")
