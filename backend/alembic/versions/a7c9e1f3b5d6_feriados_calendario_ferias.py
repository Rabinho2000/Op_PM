"""Tabela/seed de feriados e provisionamento de ``holiday.manage``.

A migração regista as linhas de seed e as grants que cria para que o downgrade
não remova permissões nem atribuições que já existiam antes desta revisão.
"""
from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence

import app.db
import sqlalchemy as sa
from alembic import op

revision: str = "a7c9e1f3b5d6"
down_revision: str | Sequence[str] | None = "f6b8d0e2a4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROVISIONING_TABLE = "holiday_provisioning"
_PERMISSION_CODE = "holiday.manage"
_PERMISSION_DESCRIPTION = "Gerir feriados municipais e da empresa"
_GRANTED_ROLES = ("administrador", "chefe_operacoes")
_FIXED_HOLIDAYS = (
    (1, 1, "Ano Novo"),
    (4, 25, "Dia da Liberdade"),
    (5, 1, "Dia do Trabalhador"),
    (6, 10, "Dia de Portugal, de Camões e das Comunidades Portuguesas"),
    (8, 15, "Assunção de Nossa Senhora"),
    (10, 5, "Implantação da República"),
    (11, 1, "Dia de Todos os Santos"),
    (12, 1, "Restauração da Independência"),
    (12, 8, "Imaculada Conceição"),
    (12, 25, "Natal"),
)


def _easter_sunday(year: int) -> dt.date:
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return dt.date(year, month, day + 1)


def _national_holidays() -> list[tuple[dt.date, str]]:
    rows: list[tuple[dt.date, str]] = []
    for year in range(2025, 2031):
        rows.extend((dt.date(year, month, day), name) for month, day, name in _FIXED_HOLIDAYS)
        easter = _easter_sunday(year)
        rows.extend(
            (
                (easter - dt.timedelta(days=2), "Sexta-feira Santa"),
                (easter, "Domingo de Páscoa"),
                (easter + dt.timedelta(days=60), "Corpo de Deus"),
            )
        )
    return rows


def _tables():
    holidays = sa.table(
        "holidays",
        sa.column("id", app.db.GUID()),
        sa.column("date", sa.Date()),
        sa.column("name", sa.String(160)),
        sa.column("scope", sa.String(16)),
        sa.column("is_active", sa.Boolean()),
    )
    permissions = sa.table(
        "permissions",
        sa.column("id", app.db.GUID()),
        sa.column("code", sa.String(128)),
        sa.column("description", sa.String(512)),
    )
    roles = sa.table("roles", sa.column("id", app.db.GUID()), sa.column("code", sa.String(64)))
    role_permissions = sa.table(
        "role_permissions",
        sa.column("id", app.db.GUID()),
        sa.column("role_id", app.db.GUID()),
        sa.column("permission_id", app.db.GUID()),
    )
    provisioning = sa.table(
        _PROVISIONING_TABLE,
        sa.column("id", app.db.GUID()),
        sa.column("kind", sa.String(32)),
        sa.column("owned_row_id", app.db.GUID()),
        sa.column("permission_id", app.db.GUID()),
    )
    return holidays, permissions, roles, role_permissions, provisioning


def _track(bind, provisioning, kind: str, row_id, permission_id=None) -> None:
    bind.execute(
        provisioning.insert().values(
            id=uuid.uuid4(),
            kind=kind,
            owned_row_id=row_id,
            permission_id=permission_id,
        )
    )


def _ensure_permission(bind, permissions, provisioning):
    existing = bind.execute(
        sa.select(permissions.c.id).where(permissions.c.code == _PERMISSION_CODE)
    ).first()
    if existing is not None:
        return existing[0]
    permission_id = uuid.uuid4()
    bind.execute(
        permissions.insert().values(
            id=permission_id,
            code=_PERMISSION_CODE,
            description=_PERMISSION_DESCRIPTION,
        )
    )
    _track(bind, provisioning, "permission", permission_id, permission_id)
    return permission_id


def _ensure_grant(bind, role_permissions, provisioning, role_id, permission_id) -> None:
    existing = bind.execute(
        sa.select(role_permissions.c.id).where(
            role_permissions.c.role_id == role_id,
            role_permissions.c.permission_id == permission_id,
        )
    ).first()
    if existing is not None:
        return
    grant_id = uuid.uuid4()
    bind.execute(
        role_permissions.insert().values(
            id=grant_id,
            role_id=role_id,
            permission_id=permission_id,
        )
    )
    _track(bind, provisioning, "role_permission", grant_id, permission_id)


def upgrade() -> None:
    op.create_table(
        "holidays",
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_holidays_date_active", "holidays", ["date", "is_active"])
    op.create_table(
        _PROVISIONING_TABLE,
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("owned_row_id", app.db.GUID(), nullable=False),
        sa.Column("permission_id", app.db.GUID(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    bind = op.get_bind()
    holidays, permissions, roles, role_permissions, provisioning = _tables()
    for holiday_date, name in _national_holidays():
        holiday_id = uuid.uuid4()
        bind.execute(
            holidays.insert().values(
                id=holiday_id,
                date=holiday_date,
                name=name,
                scope="nacional",
                is_active=True,
            )
        )
        _track(bind, provisioning, "seed_holiday", holiday_id)

    if not all(sa.inspect(bind).has_table(table) for table in ("permissions", "roles", "role_permissions")):
        return
    permission_id = _ensure_permission(bind, permissions, provisioning)
    roles_to_grant = bind.execute(
        sa.select(roles.c.id, roles.c.code).where(roles.c.code.in_(_GRANTED_ROLES))
    ).all()
    for role_id, _role_code in roles_to_grant:
        _ensure_grant(bind, role_permissions, provisioning, role_id, permission_id)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table(_PROVISIONING_TABLE):
        holidays, permissions, _roles, role_permissions, provisioning = _tables()
        owned = bind.execute(
            sa.select(provisioning.c.kind, provisioning.c.owned_row_id, provisioning.c.permission_id)
        ).all()
        created_permissions = set()
        if inspector.has_table("role_permissions"):
            for kind, row_id, permission_id in owned:
                if kind == "role_permission":
                    bind.execute(role_permissions.delete().where(role_permissions.c.id == row_id))
                elif kind == "permission":
                    created_permissions.add(permission_id)
                elif kind == "seed_holiday" and inspector.has_table("holidays"):
                    bind.execute(holidays.delete().where(holidays.c.id == row_id))
        if inspector.has_table("permissions") and inspector.has_table("role_permissions"):
            for permission_id in created_permissions:
                still_granted = bind.execute(
                    sa.select(role_permissions.c.id)
                    .where(role_permissions.c.permission_id == permission_id)
                    .limit(1)
                ).first()
                if still_granted is None:
                    bind.execute(permissions.delete().where(permissions.c.id == permission_id))
        op.drop_table(_PROVISIONING_TABLE)

    if inspector.has_table("holidays"):
        op.drop_index("ix_holidays_date_active", table_name="holidays")
        op.drop_table("holidays")
