"""Cable dimensioning studies, revisions, history and capabilities.

Revision ID: a1c3e5f7b9d0
Revises: f3b5d7e9a1c2
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence

import app.db
import sqlalchemy as sa
from alembic import op

revision: str = "a1c3e5f7b9d0"
down_revision: str | Sequence[str] | None = "f3b5d7e9a1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROVISIONING_TABLE = "cable_design_permission_provisioning"


def _provision_permission(
    bind,
    *,
    permissions,
    provisioning,
    code: str,
    description: str,
):
    row = bind.execute(sa.select(permissions.c.id).where(permissions.c.code == code)).first()
    if row is not None:
        return row[0]
    permission_id = uuid.uuid4()
    bind.execute(
        permissions.insert().values(id=permission_id, code=code, description=description)
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
    return permission_id


def _provision_role_permission(
    bind,
    *,
    role_id,
    permission_id,
    role_permissions,
    provisioning,
):
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
        "cable_designs",
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("project_id", app.db.GUID(), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="rascunho"),
        sa.Column("current_revision", sa.String(length=8), nullable=False, server_default="A"),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_person_id", app.db.GUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('rascunho', 'em_analise', 'aprovado')",
            name="ck_cable_designs_status",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_person_id"], ["people.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cable_designs_project_id", "cable_designs", ["project_id"])

    op.create_table(
        "cable_design_revisions",
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("design_id", app.db.GUID(), nullable=False),
        sa.Column("rev", sa.String(length=8), nullable=False),
        sa.Column("input_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("engine_version", sa.String(length=64), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("unresolved_circuits", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="rascunho"),
        sa.Column("approved_by_person_id", app.db.GUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_person_id", app.db.GUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('rascunho', 'aprovada')",
            name="ck_cable_design_revisions_status",
        ),
        sa.ForeignKeyConstraint(["design_id"], ["cable_designs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["approved_by_person_id"], ["people.id"]),
        sa.ForeignKeyConstraint(["created_by_person_id"], ["people.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("design_id", "rev", name="uq_cable_design_revision"),
    )
    op.create_index(
        "ix_cable_design_revisions_design_id",
        "cable_design_revisions",
        ["design_id"],
    )

    op.create_table(
        "cable_design_history",
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("design_id", app.db.GUID(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("actor_person_id", app.db.GUID(), nullable=False),
        sa.Column("rev", sa.String(length=8), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["design_id"], ["cable_designs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_person_id"], ["people.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cable_design_history_design_id", "cable_design_history", ["design_id"])

    # Track only rows created by this migration. A database without roles yet
    # is valid during bootstrap; the schema still upgrades successfully and
    # the seed/provisioning path can add the grants later.
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
    inspector = sa.inspect(bind)
    if not inspector.has_table("permissions") or not inspector.has_table("roles"):
        return

    permissions = sa.table(
        "permissions",
        sa.column("id", app.db.GUID()),
        sa.column("code", sa.String(length=128)),
        sa.column("description", sa.String(length=512)),
    )
    roles = sa.table("roles", sa.column("id", app.db.GUID()), sa.column("code", sa.String(length=64)))
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

    view_permission_id = _provision_permission(
        bind,
        permissions=permissions,
        provisioning=provisioning,
        code="cable_design.view",
        description="Consultar estudos de dimensionamento de cabos no âmbito do projeto",
    )
    edit_permission_id = _provision_permission(
        bind,
        permissions=permissions,
        provisioning=provisioning,
        code="cable_design.edit",
        description="Criar, editar, aprovar e desativar estudos de dimensionamento de cabos",
    )

    role_grants = {
        "administrador": (view_permission_id, edit_permission_id),
        "chefe_operacoes": (view_permission_id, edit_permission_id),
        "project_manager": (view_permission_id, edit_permission_id),
        "suporte_operacoes": (view_permission_id,),
    }
    for role_code, permission_ids in role_grants.items():
        role_row = bind.execute(sa.select(roles.c.id).where(roles.c.code == role_code)).first()
        if role_row is None:
            continue
        for permission_id in permission_ids:
            _provision_role_permission(
                bind,
                role_id=role_row[0],
                permission_id=permission_id,
                role_permissions=role_permissions,
                provisioning=provisioning,
            )


def downgrade() -> None:
    bind = op.get_bind()
    provisioning = sa.table(
        _PROVISIONING_TABLE,
        sa.column("kind", sa.String(length=32)),
        sa.column("owned_row_id", app.db.GUID()),
        sa.column("permission_id", app.db.GUID()),
    )
    role_permissions = sa.table("role_permissions", sa.column("id", app.db.GUID()))
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
        # Use a direct, parameterised SQLAlchemy select so pre-existing grants
        # remain untouched. The local table object is rebound with
        # permission_id below because the first declaration only carries the
        # delete key.
        role_permission_usage = sa.table(
            "role_permissions",
            sa.column("permission_id", app.db.GUID()),
        )
        still_used = bind.execute(
            sa.select(role_permission_usage.c.permission_id)
            .where(role_permission_usage.c.permission_id == permission_id)
            .limit(1)
        ).first()
        if still_used is None:
            bind.execute(permissions.delete().where(permissions.c.id == permission_id))

    op.drop_table(_PROVISIONING_TABLE)
    op.drop_index("ix_cable_design_history_design_id", table_name="cable_design_history")
    op.drop_table("cable_design_history")
    op.drop_index("ix_cable_design_revisions_design_id", table_name="cable_design_revisions")
    op.drop_table("cable_design_revisions")
    op.drop_index("ix_cable_designs_project_id", table_name="cable_designs")
    op.drop_table("cable_designs")
