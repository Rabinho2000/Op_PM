"""Add project payment milestones and scoped payment permissions.

Revision ID: a6c8e0f2d4b1
Revises: f9c2a4e6b8d0
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence

import app.db
import sqlalchemy as sa
from alembic import op

revision: str = "a6c8e0f2d4b1"
down_revision: str | Sequence[str] | None = "f9c2a4e6b8d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROVISIONING_TABLE = "project_payment_permission_provisioning"
_PROVISIONS = (
    (
        "payment.view",
        "Ver marcos de pagamento dos projetos visíveis",
        ("administrador", "chefe_operacoes", "financeiro", "project_manager"),
    ),
    (
        "payment.edit",
        "Marcar marcos de pagamento recebidos nos projetos visíveis",
        ("administrador", "financeiro"),
    ),
)
_MILESTONES_CHECK = "milestone IN ('adjudicacao', 'entrada_obra', 'fim_obra', 'certificado_final')"


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


def _create_payment_table() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("project_payment_milestones"):
        op.create_table(
            "project_payment_milestones",
            sa.Column("id", app.db.GUID(), nullable=False),
            sa.Column("project_id", app.db.GUID(), nullable=False),
            sa.Column("milestone", sa.String(length=32), nullable=False),
            sa.Column("received", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            sa.Column("marked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("marked_by_person_id", app.db.GUID(), nullable=True),
            sa.CheckConstraint(_MILESTONES_CHECK, name="ck_project_payment_milestone_code"),
            sa.ForeignKeyConstraint(
                ["project_id"], ["projects.id"], name="fk_project_payment_project", ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["marked_by_person_id"], ["people.id"], name="fk_project_payment_marked_by", ondelete="SET NULL"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("project_id", "milestone", name="uq_project_payment_milestone"),
        )
        op.create_index(
            "ix_project_payment_milestones_project_id", "project_payment_milestones", ["project_id"]
        )


def upgrade() -> None:
    bind = op.get_bind()
    permissions, roles, role_permissions, provisioning = _tables()

    # Check the whole existing catalog before making any catalog changes.
    existing_role_rows = bind.execute(sa.select(roles.c.id, roles.c.code)).all()
    permission_ids: dict[str, uuid.UUID | None] = {}
    for code, _description, allowed_roles in _PROVISIONS:
        ids = bind.execute(sa.select(permissions.c.id).where(permissions.c.code == code)).scalars().all()
        if len(ids) > 1:
            raise RuntimeError(f"Multiple permission rows exist for {code!r}; refusing migration.")
        permission_id = ids[0] if ids else None
        permission_ids[code] = permission_id
        if permission_id is not None:
            assigned_roles = bind.execute(
                sa.select(roles.c.code)
                .select_from(role_permissions.outerjoin(roles, role_permissions.c.role_id == roles.c.id))
                .where(role_permissions.c.permission_id == permission_id)
            ).scalars().all()
            conflicting_roles = sorted(
                {role_code or "<unknown role>" for role_code in assigned_roles if role_code not in allowed_roles}
            )
            if conflicting_roles:
                raise RuntimeError(
                    f"Unexpected role grants for {code!r}: {', '.join(conflicting_roles)}; "
                    "refusing migration before any catalog writes."
                )

    _create_payment_table()
    if not sa.inspect(bind).has_table(_PROVISIONING_TABLE):
        op.create_table(
            _PROVISIONING_TABLE,
            sa.Column("id", app.db.GUID(), nullable=False),
            sa.Column("kind", sa.String(length=32), nullable=False),
            sa.Column("owned_row_id", app.db.GUID(), nullable=False),
            sa.Column("permission_id", app.db.GUID(), nullable=False),
            sa.Column("role_id", app.db.GUID(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    # A schema-only/test database with no provisioned roles gets no permission
    # rows or grants. The schema migration itself remains available.
    if not existing_role_rows:
        return

    role_ids = {code: role_id for role_id, code in existing_role_rows}
    for code, description, allowed_roles in _PROVISIONS:
        permission_id = permission_ids[code]
        if permission_id is None:
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

        for role_code in allowed_roles:
            role_id = role_ids.get(role_code)
            if role_id is None:
                continue
            existing_grant = bind.execute(
                sa.select(role_permissions.c.id).where(
                    role_permissions.c.role_id == role_id,
                    role_permissions.c.permission_id == permission_id,
                )
            ).first()
            if existing_grant is not None:
                continue
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


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("project_payment_milestones"):
        op.drop_index("ix_project_payment_milestones_project_id", table_name="project_payment_milestones")
        op.drop_table("project_payment_milestones")

    if not sa.inspect(bind).has_table(_PROVISIONING_TABLE):
        return

    permissions, _roles, role_permissions, provisioning = _tables()
    owned = bind.execute(
        sa.select(
            provisioning.c.kind,
            provisioning.c.owned_row_id,
            provisioning.c.permission_id,
        )
    ).all()
    created_permission_ids: set[uuid.UUID] = set()
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
