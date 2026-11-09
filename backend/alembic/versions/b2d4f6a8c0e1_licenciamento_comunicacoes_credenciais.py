"""Licenciamento e comunicações por projeto: credenciais de portais, contratos
de excedente, etapas do licenciamento, campos SIM e permissões.

Revision ID: b2d4f6a8c0e1
Revises: a1c3e5f7b9d2

Alterações:

* ``project_licensing_data.provisional_certificate_date`` (etapa do certificado
  provisório; o estado derivado usa as datas das etapas).
* ``project_communication_data``: ``whereversim_login``, ``operator_verified``,
  ``operator_verified_date``.
* ``project_data_history.record_id``: id do registo afetado quando a entidade
  tem várias linhas (credenciais, contratos de excedente).
* Tabelas novas ``project_portal_credentials`` (password cifrada, nunca em
  claro) e ``project_surplus_contracts``, ambas com remoção lógica.
* Permissões ``project.credentials.edit`` e ``project.credentials.reveal``,
  com a matriz fixada aqui (não lida do catálogo).

Idempotente nas permissões: as existentes e as suas concessões não são tocadas
nem registadas como próprias. ``downgrade`` remove só o que esta migração criou.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence

import app.db
import sqlalchemy as sa
from alembic import op

revision: str = "b2d4f6a8c0e1"
down_revision: str | Sequence[str] | None = "a1c3e5f7b9d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROVISIONING_TABLE = "project_credentials_permission_provisioning"
_PERMISSIONS = {
    "project.credentials.edit": "Criar, editar e remover credenciais de portais do projeto",
    "project.credentials.reveal": "Revelar a password de uma credencial de portal (regista quem e quando)",
}
# Literal de propósito: uma migração não muda de comportamento quando o catálogo evolui.
_GRANTS = {
    "project.credentials.edit": ("administrador", "chefe_operacoes", "project_manager"),
    "project.credentials.reveal": ("administrador", "chefe_operacoes", "project_manager"),
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


def _provision_permissions(bind) -> None:
    permissions, roles, role_permissions, provisioning = _tables()
    permission_ids: dict[str, uuid.UUID] = {}
    for code, description in _PERMISSIONS.items():
        row = bind.execute(sa.select(permissions.c.id).where(permissions.c.code == code)).first()
        if row is None:
            permission_id = uuid.uuid4()
            bind.execute(permissions.insert().values(id=permission_id, code=code, description=description))
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
        role_code: role_id for role_id, role_code in bind.execute(sa.select(roles.c.id, roles.c.code)).all()
    }
    for code, role_codes in _GRANTS.items():
        for role_code in role_codes:
            role_id = role_ids.get(role_code)
            if role_id is None:
                # Papel ainda não provisionado (BD nova antes do seed): o seed concede.
                continue
            existing = bind.execute(
                sa.select(role_permissions.c.id).where(
                    role_permissions.c.role_id == role_id,
                    role_permissions.c.permission_id == permission_ids[code],
                )
            ).first()
            if existing is not None:
                continue
            assignment_id = uuid.uuid4()
            bind.execute(
                role_permissions.insert().values(
                    id=assignment_id, role_id=role_id, permission_id=permission_ids[code]
                )
            )
            bind.execute(
                provisioning.insert().values(
                    id=uuid.uuid4(),
                    kind="role_permission",
                    owned_row_id=assignment_id,
                    permission_id=permission_ids[code],
                    role_id=role_id,
                )
            )


def upgrade() -> None:
    with op.batch_alter_table("project_licensing_data") as batch:
        batch.add_column(sa.Column("provisional_certificate_date", sa.Date(), nullable=True))

    with op.batch_alter_table("project_communication_data") as batch:
        batch.add_column(sa.Column("whereversim_login", sa.String(length=256), nullable=True))
        batch.add_column(sa.Column("operator_verified", sa.Boolean(), nullable=True))
        batch.add_column(sa.Column("operator_verified_date", sa.Date(), nullable=True))

    with op.batch_alter_table("project_data_history") as batch:
        batch.add_column(sa.Column("record_id", app.db.GUID(), nullable=True))

    op.create_table(
        "project_portal_credentials",
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("project_id", app.db.GUID(), nullable=False),
        sa.Column("portal", sa.String(length=32), nullable=False),
        sa.Column("username", sa.String(length=256), nullable=False),
        sa.Column("password_encrypted", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_person_id", app.db.GUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["deleted_by_person_id"], ["people.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_project_portal_credentials_project_id", "project_portal_credentials", ["project_id"]
    )

    op.create_table(
        "project_surplus_contracts",
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("project_id", app.db.GUID(), nullable=False),
        sa.Column("commercializer", sa.String(length=256), nullable=True),
        sa.Column("contract_type", sa.String(length=128), nullable=True),
        sa.Column("contract_sent_date", sa.Date(), nullable=True),
        sa.Column("signed_received_date", sa.Date(), nullable=True),
        sa.Column("sent_to_commercializer_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=True),
        sa.Column("duration_months", sa.Integer(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_person_id", app.db.GUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["deleted_by_person_id"], ["people.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_project_surplus_contracts_project_id", "project_surplus_contracts", ["project_id"])

    op.create_table(
        _PROVISIONING_TABLE,
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("owned_row_id", app.db.GUID(), nullable=False),
        sa.Column("permission_id", app.db.GUID(), nullable=False),
        sa.Column("role_id", app.db.GUID(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    _provision_permissions(op.get_bind())


def downgrade() -> None:
    bind = op.get_bind()
    _permissions_table, _roles_table, role_permissions, provisioning = _tables()
    permissions = sa.table("permissions", sa.column("id", app.db.GUID()))

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
        still_used = bind.execute(
            sa.select(role_permissions.c.id).where(role_permissions.c.permission_id == permission_id).limit(1)
        ).first()
        if still_used is None:
            bind.execute(permissions.delete().where(permissions.c.id == permission_id))

    op.drop_table(_PROVISIONING_TABLE)
    op.drop_index("ix_project_surplus_contracts_project_id", table_name="project_surplus_contracts")
    op.drop_table("project_surplus_contracts")
    op.drop_index("ix_project_portal_credentials_project_id", table_name="project_portal_credentials")
    op.drop_table("project_portal_credentials")

    with op.batch_alter_table("project_data_history") as batch:
        batch.drop_column("record_id")
    with op.batch_alter_table("project_communication_data") as batch:
        batch.drop_column("operator_verified_date")
        batch.drop_column("operator_verified")
        batch.drop_column("whereversim_login")
    with op.batch_alter_table("project_licensing_data") as batch:
        batch.drop_column("provisional_certificate_date")
