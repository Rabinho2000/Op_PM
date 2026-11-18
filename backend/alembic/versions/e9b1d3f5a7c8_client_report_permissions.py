"""Provision the weekly client-report permissions (`client_report.*`).

Revision ID: e9b1d3f5a7c8
Revises: d7a9c1e3f5b6

Migration ``a7c1e5d9f3b2`` created the client-report tables but never the
permissions, which only ``seed_dev`` created.  Instances that are not seeded
(real-data deployments) therefore answered "Permissão em falta:
client_report.view." to every role, administrators included.

Grants follow ``app.security.catalog.ROLE_PERMISSIONS``:

* ``client_report.manage`` -> administrador, chefe_operacoes, project_manager
* ``client_report.view``   -> administrador, comercial, financeiro

Idempotent: existing permissions/grants are left untouched and are not
recorded as owned by this migration.  ``downgrade`` removes only the rows that
this migration created (tracked in the provisioning table), keeping any
permission that an operator has since granted to another role.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence

import app.db
import sqlalchemy as sa
from alembic import op

revision: str = "e9b1d3f5a7c8"
down_revision: str | Sequence[str] | None = "d7a9c1e3f5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROVISIONING_TABLE = "client_report_permission_provisioning"
_PERMISSIONS = {
    "client_report.manage": (
        "Configurar, pré-visualizar, enviar e rever relatórios semanais ao cliente "
        "no âmbito permitido"
    ),
    "client_report.view": (
        "Ver configurações, pré-visualizações e histórico de relatórios semanais ao cliente"
    ),
}
# Snapshot of the catalog matrix at the time of this migration (kept literal on
# purpose: a migration must not change behaviour when the catalog evolves).
_GRANTS = {
    "client_report.manage": ("administrador", "chefe_operacoes", "project_manager"),
    "client_report.view": ("administrador", "comercial", "financeiro"),
}


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

    role_ids = {
        role_code: role_id
        for role_id, role_code in bind.execute(sa.select(roles.c.id, roles.c.code)).all()
    }
    for code, role_codes in _GRANTS.items():
        for role_code in role_codes:
            role_id = role_ids.get(role_code)
            if role_id is None:
                # Role not provisioned yet on this database (e.g. brand-new
                # schema before the seed): the seed grants it from the catalog.
                continue
            _ensure_role_permission(
                bind,
                role_permissions,
                provisioning,
                role_id,
                permission_ids[code],
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
