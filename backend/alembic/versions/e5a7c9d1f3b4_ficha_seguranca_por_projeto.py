"""Ficha de segurança por projeto e capacidade de edição.

Revision ID: e5a7c9d1f3b4
Revises: d4f6b8c0e2a3
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence

import app.db
import sqlalchemy as sa
from alembic import op

revision: str = "e5a7c9d1f3b4"
down_revision: str | Sequence[str] | None = "d4f6b8c0e2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROVISIONING_TABLE = "project_safety_sheet_permission_provisioning"
_PERMISSION_CODE = "project.safety_sheet.edit"
_PERMISSION_DESCRIPTION = "Editar a ficha de segurança do projeto"
_GRANT_ROLES = ("administrador", "chefe_operacoes", "project_manager", "suporte_operacoes")


def _permission_tables():
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
    return permissions, roles, role_permissions, provisioning


def _ensure_role_grant(bind, role_permissions, provisioning, role_id, permission_id) -> None:
    existing = bind.execute(
        sa.select(role_permissions.c.id).where(
            role_permissions.c.role_id == role_id,
            role_permissions.c.permission_id == permission_id,
        )
    ).first()
    if existing is not None:
        return
    grant_id = uuid.uuid4()
    bind.execute(role_permissions.insert().values(id=grant_id, role_id=role_id, permission_id=permission_id))
    bind.execute(
        provisioning.insert().values(
            id=uuid.uuid4(),
            kind="role_permission",
            owned_row_id=grant_id,
            permission_id=permission_id,
            role_id=role_id,
        )
    )


def upgrade() -> None:
    op.create_table(
        "project_safety_sheets",
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("project_id", app.db.GUID(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("roof_type", sa.String(length=40), nullable=True),
        sa.Column("roof_other", sa.Text(), nullable=True),
        sa.Column("approximate_height_m", sa.Float(), nullable=True),
        sa.Column("access_method", sa.String(length=40), nullable=True),
        sa.Column("access_other", sa.Text(), nullable=True),
        sa.Column("risks_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("risk_other", sa.Text(), nullable=True),
        sa.Column("safety_measures_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("measure_other", sa.Text(), nullable=True),
        sa.Column("safety_responsible", sa.Text(), nullable=True),
        sa.Column("emergency_contacts", sa.Text(), nullable=True),
        sa.Column("observations", sa.Text(), nullable=True),
        sa.Column("work_start_date", sa.Date(), nullable=True),
        sa.Column("work_end_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_project_safety_sheet_project"),
    )
    op.create_table(
        "project_safety_sheet_workers",
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("safety_sheet_id", app.db.GUID(), nullable=False),
        sa.Column("person_id", app.db.GUID(), nullable=True),
        sa.Column("name_snapshot", sa.String(length=256), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("installer_id", app.db.GUID(), nullable=True),
        sa.Column("team_id", app.db.GUID(), nullable=True),
        sa.ForeignKeyConstraint(["installer_id"], ["installers.id"]),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"]),
        sa.ForeignKeyConstraint(["safety_sheet_id"], ["project_safety_sheets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["installer_teams.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("safety_sheet_id", "position", name="uq_safety_sheet_worker_position"),
    )
    op.create_index(
        "ix_project_safety_sheet_workers_safety_sheet_id",
        "project_safety_sheet_workers",
        ["safety_sheet_id"],
        unique=False,
    )
    op.create_table(
        "project_safety_sheet_history",
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("project_id", app.db.GUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("changed_by_person_id", app.db.GUID(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["changed_by_person_id"], ["people.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "version", name="uq_safety_sheet_history_version"),
    )
    op.create_index(
        "ix_project_safety_sheet_history_project_id",
        "project_safety_sheet_history",
        ["project_id"],
        unique=False,
    )

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
    permissions, roles, role_permissions, provisioning = _permission_tables()
    permission_row = bind.execute(
        sa.select(permissions.c.id).where(permissions.c.code == _PERMISSION_CODE)
    ).first()
    if permission_row is None:
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
        permission_id = permission_row[0]

    role_ids = {
        code: role_id
        for role_id, code in bind.execute(sa.select(roles.c.id, roles.c.code)).all()
    }
    for role_code in _GRANT_ROLES:
        role_id = role_ids.get(role_code)
        if role_id is not None:
            _ensure_role_grant(bind, role_permissions, provisioning, role_id, permission_id)


def downgrade() -> None:
    bind = op.get_bind()
    permissions, _roles, role_permissions, provisioning = _permission_tables()
    owned = bind.execute(
        sa.select(provisioning.c.kind, provisioning.c.owned_row_id, provisioning.c.permission_id)
    ).all()
    created_permission_ids = set()
    for kind, owned_row_id, permission_id in owned:
        if kind == "role_permission":
            bind.execute(role_permissions.delete().where(role_permissions.c.id == owned_row_id))
        elif kind == "permission":
            created_permission_ids.add(permission_id)
    for permission_id in created_permission_ids:
        referenced = bind.execute(
            sa.select(role_permissions.c.id)
            .where(role_permissions.c.permission_id == permission_id)
            .limit(1)
        ).first()
        if referenced is None:
            bind.execute(permissions.delete().where(permissions.c.id == permission_id))

    op.drop_index("ix_project_safety_sheet_history_project_id", table_name="project_safety_sheet_history")
    op.drop_table("project_safety_sheet_history")
    op.drop_index(
        "ix_project_safety_sheet_workers_safety_sheet_id", table_name="project_safety_sheet_workers"
    )
    op.drop_table("project_safety_sheet_workers")
    op.drop_table("project_safety_sheets")
    op.drop_table(_PROVISIONING_TABLE)
