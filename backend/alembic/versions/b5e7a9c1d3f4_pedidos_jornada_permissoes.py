"""Self-service time-bank and requests capability provisioning.

Revision ID: b5e7a9c1d3f4
Revises: a1c3e5f7b9d0
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence

import app.db
import sqlalchemy as sa
from alembic import op

revision: str = "b5e7a9c1d3f4"
down_revision: str | Sequence[str] | None = "a1c3e5f7b9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROVISIONING_TABLE = "pedidos_jornada_permission_provisioning"
_PERMISSIONS = {
    "time_bank.log_own": "Registar e anular a própria jornada no Banco de Horas",
    "requests.create": "Enviar pedidos à equipa de operações",
    "requests.manage": "Ver e responder a todos os pedidos",
}

# These are the catalog roles whose default permission list includes
# time_bank.view_own.  The migration also detects existing view_own grants so
# custom consultation roles are covered without changing their membership.
_OWN_ROLE_CODES = {
    "project_manager",
    "comercial",
    "financeiro",
    "suporte_operacoes",
    "instalador_colaborador",
    "consulta",
}
_MANAGE_ROLE_CODES = {"administrador", "admin", "chefe_operacoes"}


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
            id=assignment_id,
            role_id=role_id,
            permission_id=permission_id,
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

    bind = op.get_bind()
    permissions, roles, role_permissions, provisioning = _tables()
    permission_ids = {}
    for code, description in _PERMISSIONS.items():
        row = bind.execute(sa.select(permissions.c.id).where(permissions.c.code == code)).first()
        if row is None:
            permission_id = uuid.uuid4()
            bind.execute(
                permissions.insert().values(
                    id=permission_id,
                    code=code,
                    description=description,
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
        permission_ids[code] = permission_id

    role_rows = bind.execute(sa.select(roles.c.id, roles.c.code)).all()
    own_role_ids = {
        role_id for role_id, role_code in role_rows if role_code in _OWN_ROLE_CODES
    }
    view_own_row = bind.execute(
        sa.select(permissions.c.id).where(permissions.c.code == "time_bank.view_own")
    ).first()
    if view_own_row is not None:
        own_role_ids.update(
            role_id
            for (role_id,) in bind.execute(
                sa.select(role_permissions.c.role_id).where(
                    role_permissions.c.permission_id == view_own_row[0]
                )
            ).all()
        )

    for role_id in own_role_ids:
        _ensure_role_permission(
            bind,
            role_permissions,
            provisioning,
            role_id,
            permission_ids["time_bank.log_own"],
        )

    for role_id, _role_code in role_rows:
        _ensure_role_permission(
            bind,
            role_permissions,
            provisioning,
            role_id,
            permission_ids["requests.create"],
        )

    for role_id, role_code in role_rows:
        if role_code in _MANAGE_ROLE_CODES:
            _ensure_role_permission(
                bind,
                role_permissions,
                provisioning,
                role_id,
                permission_ids["requests.manage"],
            )


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
