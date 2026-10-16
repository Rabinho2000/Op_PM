"""Banco de Horas: ledger, auditoria, import batches e permissões.

Revision ID: c8f0a2b4d6e1
Revises: b7e8f9a0c1d2
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence

import app.db
import sqlalchemy as sa
from alembic import op

revision: str = "c8f0a2b4d6e1"
down_revision: str | Sequence[str] | None = "b7e8f9a0c1d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROVISIONING_TABLE = "time_bank_permission_provisioning"
_PERMISSIONS = {
    "time_bank.view_own": "Consultar os próprios lançamentos e saldo do Banco de Horas",
    "time_bank.view_all": "Consultar os lançamentos e saldos de todas as pessoas",
    "time_bank.manage_all": "Registar, ajustar, anular e importar Banco de Horas de qualquer pessoa",
}


def upgrade() -> None:
    op.create_table(
        "time_bank_entries",
        sa.Column("person_id", app.db.GUID(), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("start_minute", sa.Integer(), nullable=True),
        sa.Column("end_minute", sa.Integer(), nullable=True),
        sa.Column("lunch_taken", sa.Boolean(), nullable=True),
        sa.Column("balance_seconds", sa.Integer(), nullable=False),
        sa.Column("calculated_seconds", sa.Integer(), nullable=True),
        sa.Column("calculation_mode", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("review_flags", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("source_key", sa.String(length=256), nullable=True),
        sa.Column("created_by_user_id", app.db.GUID(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("reversal_of_id", app.db.GUID(), nullable=True),
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reversal_of_id"], ["time_bank_entries.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_key", name="uq_time_bank_entry_source_key"),
        sa.UniqueConstraint("reversal_of_id", name="uq_time_bank_entry_one_reversal"),
    )
    op.create_index("ix_time_bank_entries_person_date", "time_bank_entries", ["person_id", "work_date"])

    op.create_table(
        "time_bank_adjustments",
        sa.Column("person_id", app.db.GUID(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("delta_seconds", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("source_key", sa.String(length=256), nullable=True),
        sa.Column("created_by_user_id", app.db.GUID(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("reversal_of_id", app.db.GUID(), nullable=True),
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reversal_of_id"], ["time_bank_adjustments.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_key", name="uq_time_bank_adjustment_source_key"),
        sa.UniqueConstraint("reversal_of_id", name="uq_time_bank_adjustment_one_reversal"),
    )
    op.create_index("ix_time_bank_adjustments_person_date", "time_bank_adjustments", ["person_id", "effective_date"])

    op.create_table(
        "time_bank_audit",
        sa.Column("actor_user_id", app.db.GUID(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_id", app.db.GUID(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "time_bank_import_batches",
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("parser_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source_year", sa.Integer(), nullable=True),
        sa.Column("parsed_payload", sa.JSON(), nullable=False),
        sa.Column("resolutions", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", app.db.GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sha256", "parser_version", name="uq_time_bank_import_hash_version"),
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

    permission_ids: dict[str, object] = {}
    for code, description in _PERMISSIONS.items():
        row = bind.execute(sa.select(permissions.c.id).where(permissions.c.code == code)).first()
        if row is None:
            permission_id = uuid.uuid4()
            bind.execute(permissions.insert().values(id=permission_id, code=code, description=description))
            bind.execute(
                provisioning.insert().values(
                    id=uuid.uuid4(), kind="permission", owned_row_id=permission_id,
                    permission_id=permission_id, role_id=None,
                )
            )
        else:
            permission_id = row[0]
        permission_ids[code] = permission_id

    global_roles = ("administrador", "admin", "chefe_operacoes")
    role_rows = bind.execute(sa.select(roles.c.id, roles.c.code)).all()
    for role_id, role_code in role_rows:
        codes = (
            ("time_bank.view_all", "time_bank.manage_all")
            if role_code in global_roles
            else ("time_bank.view_own",)
        )
        for code in codes:
            permission_id = permission_ids[code]
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
                role_permissions.insert().values(id=assignment_id, role_id=role_id, permission_id=permission_id)
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
    owned = bind.execute(sa.select(provisioning.c.kind, provisioning.c.owned_row_id, provisioning.c.permission_id)).all()
    permission_ids: set[object] = set()
    for kind, owned_row_id, permission_id in owned:
        if kind == "role_permission":
            bind.execute(role_permissions.delete().where(role_permissions.c.id == owned_row_id))
        elif kind == "permission":
            permission_ids.add(permission_id)
    for permission_id in permission_ids:
        used = bind.execute(
            sa.select(role_permissions.c.id).where(role_permissions.c.permission_id == permission_id)
        ).first()
        if used is None:
            bind.execute(permissions.delete().where(permissions.c.id == permission_id))

    op.drop_table(_PROVISIONING_TABLE)
    op.drop_index("ix_time_bank_adjustments_person_date", table_name="time_bank_adjustments")
    op.drop_table("time_bank_adjustments")
    op.drop_index("ix_time_bank_entries_person_date", table_name="time_bank_entries")
    op.drop_table("time_bank_entries")
    op.drop_table("time_bank_audit")
    op.drop_table("time_bank_import_batches")
