"""inventario: histórico append-only do catálogo

Revision ID: 8a1d3f4c6b90
Revises: b4d8f2a6c1e3
Create Date: 2026-09-30

"""
import hashlib
import json
import uuid
from collections.abc import Sequence
from decimal import Decimal

import app.db  # necessário para o tipo de coluna portável app.db.GUID()
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8a1d3f4c6b90"
down_revision: str | Sequence[str] | None = "b4d8f2a6c1e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIVE_CENTRAL_INDEX = "uq_inventory_locations_one_active_central"
_PROVISIONING_TABLE = "inventory_manage_catalog_provisioning"


def upgrade() -> None:
    op.create_table(
        "inventory_catalog_history",
        sa.Column("entity_type", sa.String(length=16), nullable=False),
        sa.Column("entity_id", app.db.GUID(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("changes_json", sa.Text(), nullable=False),
        sa.Column("changed_by_person_id", app.db.GUID(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.ForeignKeyConstraint(["changed_by_person_id"], ["people.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # Existing movement rows remain valid; new rows carry the canonical
    # request fingerprint used to bind an idempotency key to its request.
    # Backfill legacy idempotency rows deterministically.  Central movements
    # used NULL location_id before the catalog migration; the compatibility
    # token keeps retries equivalent to new rows with the central UUID.
    with op.batch_alter_table("inventory_movements", schema=None) as batch_op:
        batch_op.add_column(sa.Column("idempotency_fingerprint", sa.String(length=64), nullable=True))
    bind = op.get_bind()
    movements = sa.table(
        "inventory_movements",
        sa.column("id", app.db.GUID()),
        sa.column("item_id", app.db.GUID()),
        sa.column("movement_type", sa.String(length=32)),
        sa.column("quantity", sa.Numeric(14, 3)),
        sa.column("project_id", app.db.GUID()),
        sa.column("location_id", app.db.GUID()),
        sa.column("destination_location_id", app.db.GUID()),
        sa.column("reference", sa.String(length=256)),
        sa.column("unit_cost", sa.Numeric(12, 2)),
        sa.column("idempotency_key", sa.String(length=128)),
        sa.column("idempotency_fingerprint", sa.String(length=64)),
    )

    def fingerprint_value(value: object) -> object:
        if value is None:
            return None
        if isinstance(value, Decimal):
            return format(value.normalize(), "f")
        return str(value) if isinstance(value, uuid.UUID) else value

    legacy_rows = bind.execute(
        sa.select(
            movements.c.id,
            movements.c.item_id,
            movements.c.movement_type,
            movements.c.quantity,
            movements.c.project_id,
            movements.c.location_id,
            movements.c.destination_location_id,
            movements.c.reference,
            movements.c.unit_cost,
            movements.c.idempotency_key,
        ).where(
            movements.c.idempotency_key.is_not(None),
            movements.c.idempotency_fingerprint.is_(None),
        )
    ).all()

    # A central location is only needed to canonicalize legacy entrada/ajuste
    # rows that still have NULL location_id. Empty databases and rows that
    # already carry an explicit location can be migrated without one.
    needs_central = any(
        row.movement_type in {"entrada", "ajuste"} and row.location_id is None for row in legacy_rows
    )
    central_id = None
    if needs_central:
        central_id = bind.execute(
            sa.select(sa.table("inventory_locations", sa.column("id", app.db.GUID())).c.id).where(
                sa.text("location_type = 'central' AND is_active = :active")
            ),
            {"active": True},
        ).scalar_one_or_none()
        if central_id is None:
            raise RuntimeError("Não existe localização central ativa para o backfill de fingerprints.")

    for row in legacy_rows:
        location = central_id if row.movement_type in {"entrada", "ajuste"} and row.location_id is None else row.location_id
        payload = {
            "item_id": fingerprint_value(row.item_id),
            "movement_type": row.movement_type,
            "quantity": fingerprint_value(row.quantity),
            "project_id": fingerprint_value(row.project_id),
            "location_id": fingerprint_value(location),
            "destination_location_id": fingerprint_value(row.destination_location_id),
            "reference": row.reference,
            "unit_cost": fingerprint_value(row.unit_cost),
        }
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        bind.execute(
            movements.update()
            .where(movements.c.id == row.id)
            .values(idempotency_fingerprint=fingerprint)
        )

    bind = op.get_bind()
    duplicate_centrals = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM inventory_locations "
            "WHERE location_type = 'central' AND is_active = :active"
        ),
        {"active": True},
    ).scalar_one()
    if duplicate_centrals > 1:
        raise RuntimeError(
            "Não é possível criar a garantia de localização central: "
            f"existem {duplicate_centrals} centrais ativas; resolva os dados antes da migração."
        )
    op.create_index(
        _ACTIVE_CENTRAL_INDEX,
        "inventory_locations",
        ["location_type"],
        unique=True,
        sqlite_where=sa.text("location_type = 'central' AND is_active = 1"),
        postgresql_where=sa.text("location_type = 'central' AND is_active"),
    )

    # Track only rows created by this migration. Downgrade can therefore
    # remove its own permission/assignments without deleting pre-existing
    # permissions or grants from a live database.
    op.create_table(
        _PROVISIONING_TABLE,
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("owned_row_id", app.db.GUID(), nullable=False),
        sa.Column("permission_id", app.db.GUID(), nullable=False),
        sa.Column("role_id", app.db.GUID(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

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

    permission_row = bind.execute(
        sa.select(permissions.c.id).where(permissions.c.code == "inventory.manage_catalog")
    ).first()
    if permission_row is None:
        permission_id = uuid.uuid4()
        bind.execute(
            permissions.insert().values(
                id=permission_id,
                code="inventory.manage_catalog",
                description="Criar, editar e desativar artigos e localizações de inventário",
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

    for role_code in ("administrador", "admin", "chefe_operacoes"):
        role_row = bind.execute(sa.select(roles.c.id).where(roles.c.code == role_code)).first()
        if role_row is None:
            continue
        role_id = role_row[0]
        assignment = bind.execute(
            sa.select(role_permissions.c.id).where(
                role_permissions.c.role_id == role_id,
                role_permissions.c.permission_id == permission_id,
            )
        ).first()
        if assignment is not None:
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
        still_used = bind.execute(
            sa.text("SELECT 1 FROM role_permissions WHERE permission_id = :permission_id LIMIT 1"),
            {"permission_id": str(permission_id)},
        ).first()
        if still_used is None:
            bind.execute(permissions.delete().where(permissions.c.id == permission_id))
    op.drop_table(_PROVISIONING_TABLE)
    op.drop_index(_ACTIVE_CENTRAL_INDEX, table_name="inventory_locations")
    with op.batch_alter_table("inventory_movements", schema=None) as batch_op:
        batch_op.drop_column("idempotency_fingerprint")
    op.drop_table("inventory_catalog_history")
