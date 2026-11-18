"""Alarmes de etapas do processo: subscrições por utilizador e notificações in-app.

Revision ID: a1c3e5f7b9d2
Revises: e9b1d3f5a7c8

* Tabela ``process_stage_subscriptions`` (user_id, stage_id, created_at), única por par.
* ``notifications`` ganha ``project_id``, ``stage_id`` e ``read_at`` (a tabela já existia
  desde o esquema inicial e continua a ser a das notificações in-app).
* Permissão ``process_alert.use`` provisionada aqui, no padrão de ``e9b1d3f5a7c8``
  (grants literais; ``downgrade`` remove só o que esta migração criou).

Grants: administrador, chefe_operacoes, project_manager, comercial, financeiro,
suporte_operacoes. ``instalador_colaborador`` (leitura externa) não recebe.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence

import app.db
import sqlalchemy as sa
from alembic import op

revision: str = "a1c3e5f7b9d2"
down_revision: str | Sequence[str] | None = "e9b1d3f5a7c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROVISIONING_TABLE = "process_alert_permission_provisioning"
_PERMISSION_CODE = "process_alert.use"
_PERMISSION_DESCRIPTION = (
    "Subscrever alarmes de etapas do processo e ver as próprias notificações (in-app)"
)
# Snapshot literal (não importar o catálogo: uma migração não pode mudar de comportamento
# quando o catálogo evolui).
_GRANT_ROLES = (
    "administrador",
    "chefe_operacoes",
    "project_manager",
    "comercial",
    "financeiro",
    "suporte_operacoes",
)


def _tables():
    permissions = sa.table(
        "permissions",
        sa.column("id", app.db.GUID()),
        sa.column("code", sa.String(length=128)),
        sa.column("description", sa.String(length=512)),
    )
    roles = sa.table(
        "roles",
        sa.column("id", app.db.GUID()),
        sa.column("code", sa.String(length=64)),
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("id", app.db.GUID()),
        sa.column("role_id", app.db.GUID()),
        sa.column("permission_id", app.db.GUID()),
    )
    provisioning = sa.table(
        _PROVISIONING_TABLE,
        sa.column("id", app.db.GUID()),
        sa.column("kind", sa.String(length=32)),
        sa.column("owned_row_id", app.db.GUID()),
        sa.column("permission_id", app.db.GUID()),
        sa.column("role_id", app.db.GUID()),
    )
    return permissions, roles, role_permissions, provisioning


def _ensure_role_permission(bind, role_permissions, provisioning, role_id, permission_id) -> None:
    existing = bind.execute(
        sa.select(role_permissions.c.id).where(
            role_permissions.c.role_id == role_id,
            role_permissions.c.permission_id == permission_id,
        )
    ).first()
    if existing is not None:
        return
    assignment_id = uuid.uuid4()
    bind.execute(
        role_permissions.insert().values(
            id=assignment_id, role_id=role_id, permission_id=permission_id
        )
    )
    bind.execute(
        provisioning.insert().values(
            id=uuid.uuid4(),
            kind="role_permission",
            owned_row_id=assignment_id,
            permission_id=permission_id,
            role_id=role_id,
        )
    )


def upgrade() -> None:
    op.create_table(
        _PROVISIONING_TABLE,
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("owned_row_id", app.db.GUID(), nullable=False),
        sa.Column("permission_id", app.db.GUID(), nullable=False),
        sa.Column("role_id", app.db.GUID(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "process_stage_subscriptions",
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("user_id", app.db.GUID(), nullable=False),
        sa.Column("stage_id", app.db.GUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["stage_id"], ["workflow_stages.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "stage_id", name="uq_process_stage_subscription"),
    )
    op.create_index(
        "ix_process_stage_subscriptions_user_id",
        "process_stage_subscriptions",
        ["user_id"],
    )
    op.create_index(
        "ix_process_stage_subscriptions_stage_id",
        "process_stage_subscriptions",
        ["stage_id"],
    )

    with op.batch_alter_table("notifications") as batch:
        batch.add_column(sa.Column("project_id", app.db.GUID(), nullable=True))
        batch.add_column(sa.Column("stage_id", app.db.GUID(), nullable=True))
        batch.add_column(sa.Column("read_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key(
            "fk_notifications_project_id", "projects", ["project_id"], ["id"]
        )
        batch.create_foreign_key(
            "fk_notifications_stage_id", "workflow_stages", ["stage_id"], ["id"]
        )
    op.create_index(
        "ix_notifications_user_id_is_read",
        "notifications",
        ["user_id", "is_read"],
    )

    bind = op.get_bind()
    permissions, roles, role_permissions, provisioning = _tables()
    row = bind.execute(
        sa.select(permissions.c.id).where(permissions.c.code == _PERMISSION_CODE)
    ).first()
    if row is None:
        permission_id = uuid.uuid4()
        bind.execute(
            permissions.insert().values(
                id=permission_id,
                code=_PERMISSION_CODE,
                description=_PERMISSION_DESCRIPTION,
            )
        )
        bind.execute(
            provisioning.insert().values(
                id=uuid.uuid4(),
                kind="permission",
                owned_row_id=permission_id,
                permission_id=permission_id,
                role_id=None,
            )
        )
    else:
        permission_id = row[0]

    role_ids = {
        role_code: role_id
        for role_id, role_code in bind.execute(sa.select(roles.c.id, roles.c.code)).all()
    }
    for role_code in _GRANT_ROLES:
        role_id = role_ids.get(role_code)
        if role_id is None:
            # Papel ainda não provisionado (BD nova, antes do seed): o seed concede
            # a partir do catálogo.
            continue
        _ensure_role_permission(bind, role_permissions, provisioning, role_id, permission_id)


def downgrade() -> None:
    bind = op.get_bind()
    _permissions_table, _roles_table, role_permissions, provisioning = _tables()
    permissions = sa.table("permissions", sa.column("id", app.db.GUID()))

    owned = bind.execute(
        sa.select(
            provisioning.c.kind,
            provisioning.c.owned_row_id,
            provisioning.c.permission_id,
        )
    ).all()
    created_permission_ids = set()
    for kind, owned_row_id, permission_id in owned:
        if kind == "role_permission":
            bind.execute(role_permissions.delete().where(role_permissions.c.id == owned_row_id))
        elif kind == "permission":
            created_permission_ids.add(permission_id)

    for permission_id in created_permission_ids:
        still_used = bind.execute(
            sa.select(role_permissions.c.id)
            .where(role_permissions.c.permission_id == permission_id)
            .limit(1)
        ).first()
        if still_used is None:
            bind.execute(permissions.delete().where(permissions.c.id == permission_id))

    op.drop_table(_PROVISIONING_TABLE)

    op.drop_index("ix_notifications_user_id_is_read", table_name="notifications")
    with op.batch_alter_table("notifications") as batch:
        batch.drop_constraint("fk_notifications_stage_id", type_="foreignkey")
        batch.drop_constraint("fk_notifications_project_id", type_="foreignkey")
        batch.drop_column("read_at")
        batch.drop_column("stage_id")
        batch.drop_column("project_id")

    op.drop_index("ix_process_stage_subscriptions_stage_id", table_name="process_stage_subscriptions")
    op.drop_index("ix_process_stage_subscriptions_user_id", table_name="process_stage_subscriptions")
    op.drop_table("process_stage_subscriptions")
