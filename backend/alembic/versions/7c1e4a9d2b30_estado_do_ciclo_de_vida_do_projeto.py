"""estado do ciclo de vida do projeto

Revision ID: 7c1e4a9d2b30
Revises: 01366c322464
Create Date: 2026-09-24 12:00:00.000000

"""
import unicodedata
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c1e4a9d2b30'
down_revision: Union[str, Sequence[str], None] = '01366c322464'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Cópia congelada do mapeamento de app/services/project_lifecycle.py: uma
# migração não deve depender de código de aplicação que pode mudar depois.
_LEGACY_MAP = {
    "on hold pelo cliente": "on_hold_cliente",
    "em preparacao": "preparacao",
    "preparacao": "preparacao",
    "em construcao": "construcao",
    "construcao": "construcao",
    "construido": "construido",
    "entregue ao cliente": "entregue_cliente",
    "certificado final": "certificado_final",
    "vendido": "on_hold_cliente",
}


def _normalize(raw: str) -> str:
    decomposed = unicodedata.normalize("NFKD", raw.strip().lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def upgrade() -> None:
    """Upgrade schema.

    Acrescenta `projects.lifecycle_status` (nullable) e preenche-o a partir do
    espelho do estado ClickUp. Projetos importados do legado (têm um
    `project_external_ids` com `legacy_json`) sem estado ClickUp ficam em
    "On hold pelo cliente" (D2); qualquer outro projeto ou valor desconhecido
    fica sem estado — nunca se adivinha.
    """
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('lifecycle_status', sa.String(length=32), nullable=True))
        batch_op.create_index(batch_op.f('ix_projects_lifecycle_status'), ['lifecycle_status'], unique=False)

    bind = op.get_bind()
    legacy_ids = {
        row[0]
        for row in bind.execute(
            sa.text("SELECT project_id FROM project_external_ids WHERE source_system = 'legacy_json'")
        )
    }
    rows = bind.execute(sa.text("SELECT id, clickup_status_mirror FROM projects")).fetchall()
    for project_id, mirror in rows:
        if mirror is not None and mirror.strip():
            status = _LEGACY_MAP.get(_normalize(mirror))
        else:
            status = "on_hold_cliente" if project_id in legacy_ids else None
        if status is not None:
            bind.execute(
                sa.text("UPDATE projects SET lifecycle_status = :s WHERE id = :i"),
                {"s": status, "i": project_id},
            )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_projects_lifecycle_status'))
        batch_op.drop_column('lifecycle_status')
