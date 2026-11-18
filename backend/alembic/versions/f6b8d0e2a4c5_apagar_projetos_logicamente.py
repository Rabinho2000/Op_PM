"""Remoção lógica e restauro de projetos.

Revision ID: f6b8d0e2a4c5
Revises: e5a7c9d1f3b4
Create Date: 2026-10-21
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence

import app.db
import sqlalchemy as sa
from alembic import op

revision: str = "f6b8d0e2a4c5"
down_revision: str | Sequence[str] | None = "e5a7c9d1f3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROVISIONING_TABLE = "project_deletion_provisioning"
_DELETED_INDEX = "ix_projects_deleted_at"
_PERMISSIONS = (
    ("project.delete", "Apagar projetos (remoção lógica)"),
    ("project.restore", "Restaurar projetos apagados"),
)
_ROLE_GRANTS = {
    "project.delete": ("administrador", "admin", "chefe_operacoes"),
    "project.restore": ("administrador", "admin"),
}


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column(
                "deleted_by_person_id",
                app.db.GUID(),
                sa.ForeignKey("people.id", name="fk_projects_deleted_by_person_id_people"),
                nullable=True,
            )
        )
    op.create_index(_DELETED_INDEX, "projects", ["deleted_at"], unique=False)
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
    permissions = sa.table(
        "permissions",
        sa.column("id", app.db.GUID()),
        sa.column("code", sa.String(length=128)),
        sa.column("description", sa.String(length=512)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    roles = sa.table("roles", sa.column("id", app.db.GUID()), sa.column("code", sa.String(length=64)))
    role_permissions = sa.table(
        "role_permissions",
        sa.column("id", app.db.GUID()),
        sa.column("role_id", app.db.GUID()),
        sa.column("permission_id", app.db.GUID()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    provisioning = sa.table(
        _PROVISIONING_TABLE,
        sa.column("id", app.db.GUID()),
        sa.column("kind", sa.String(length=32)),
        sa.column("owned_row_id", app.db.GUID()),
        sa.column("permission_id", app.db.GUID()),
        sa.column("role_id", app.db.GUID()),
    )

    permission_ids: dict[str, uuid.UUID] = {}
    for code, description in _PERMISSIONS:
        existing = bind.execute(sa.select(permissions.c.id).where(permissions.c.code == code)).first()
        if existing is not None:
            permission_ids[code] = existing[0]
            continue
        permission_id = uuid.uuid4()
        bind.execute(
            permissions.insert().values(
                id=permission_id,
                code=code,
                description=description,
                created_at=sa.func.now(),
                updated_at=sa.func.now(),
            )
        )
        bind.execute(
            provisioning.insert().values(
                id=uuid.uuid4(), kind="permission", owned_row_id=permission_id,
                permission_id=permission_id, role_id=None,
            )
        )
        permission_ids[code] = permission_id

    for code, role_codes in _ROLE_GRANTS.items():
        permission_id = permission_ids[code]
        for role_code in role_codes:
            role_row = bind.execute(sa.select(roles.c.id).where(roles.c.code == role_code)).first()
            if role_row is None:
                continue
            role_id = role_row[0]
            existing = bind.execute(
                sa.select(role_permissions.c.id).where(
                    role_permissions.c.role_id == role_id,
                    role_permissions.c.permission_id == permission_id,
                )
            ).first()
            if existing is not None:
                continue
            assignment_id = uuid.uuid4()
            bind.execute(
                role_permissions.insert().values(
                    id=assignment_id, role_id=role_id, permission_id=permission_id,
                    created_at=sa.func.now(), updated_at=sa.func.now(),
                )
            )
            bind.execute(
                provisioning.insert().values(
                    id=uuid.uuid4(), kind="role_permission", owned_row_id=assignment_id,
                    permission_id=permission_id, role_id=role_id,
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    provisioning = sa.table(
        _PROVISIONING_TABLE,
        sa.column("kind", sa.String(length=32)),
        sa.column("owned_row_id", app.db.GUID()),
        sa.column("permission_id", app.db.GUID()),
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("id", app.db.GUID()),
        sa.column("permission_id", app.db.GUID()),
    )
    permissions = sa.table("permissions", sa.column("id", app.db.GUID()))
    owned = bind.execute(
        sa.select(provisioning.c.kind, provisioning.c.owned_row_id, provisioning.c.permission_id)
    ).all()
    permission_ids: set[uuid.UUID] = set()
    for kind, owned_row_id, permission_id in owned:
        if kind == "role_permission":
            bind.execute(role_permissions.delete().where(role_permissions.c.id == owned_row_id))
        elif kind == "permission":
            permission_ids.add(permission_id)
    for permission_id in permission_ids:
        still_used = bind.execute(
            sa.select(role_permissions.c.id).where(role_permissions.c.permission_id == permission_id).limit(1)
        ).first()
        if still_used is None:
            bind.execute(permissions.delete().where(permissions.c.id == permission_id))
    op.drop_table(_PROVISIONING_TABLE)
    op.drop_index(_DELETED_INDEX, table_name="projects")
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_column("deleted_by_person_id")
        batch_op.drop_column("deleted_at")
