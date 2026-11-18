"""Cartões SIM como lista por projeto (PIN/PUK cifrados), email do portal e
data de registo UPAC.

Revision ID: c3e5a7b9d1f2
Revises: b2d4f6a8c0e1

Alterações:

* Tabela nova ``project_sim_cards`` (0..n por projeto): finalidade, operador,
  nº telefone/M2M, nº do cartão (ICCID), verificação no portal, notas e
  ``pin_encrypted``/``puk_encrypted`` (tokens Fernet, nunca em claro).
  Remoção lógica (``deleted_at``).
* Data migration: cada projeto com algum campo SIM preenchido em
  ``project_communication_data`` gera 1 linha em ``project_sim_cards``
  (finalidade ``comunicacoes``). Os PIN/PUK não existem nas colunas antigas,
  logo nada é cifrado aqui.
* ``project_communication_data``: remove ``operator``, ``gsm_m2m_number``,
  ``card_identifier``, ``operator_verified``, ``operator_verified_date``
  (passam a viver em ``project_sim_cards``).
* ``project_portal_credentials.email`` (email do portal, não é segredo).
* ``project_licensing_data.upac_registration_date`` (data de registo UPAC).

``downgrade`` repõe as colunas antigas e copia para elas o primeiro SIM
(por ordem de criação) de cada projeto; o resto da tabela é descartado.
PIN/PUK são sempre perdidos no downgrade (a coluna antiga não existia) —
por isso o downgrade falha se houver PIN/PUK guardados, a menos que o
operador confirme explicitamente (ver ``_guard_secrets_before_downgrade``).
"""
from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence

import app.db
import sqlalchemy as sa
from alembic import op

revision: str = "c3e5a7b9d1f2"
down_revision: str | Sequence[str] | None = "b2d4f6a8c0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SIM_FIELDS_OLD = ("operator", "gsm_m2m_number", "card_identifier", "operator_verified", "operator_verified_date")


def _guard_secrets_before_downgrade(bind) -> None:
    """Downgrade apaga PIN/PUK (não há coluna antiga para eles). Recusar em vez
    de perder segredos em silêncio."""
    count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM project_sim_cards "
            "WHERE (pin_encrypted IS NOT NULL OR puk_encrypted IS NOT NULL)"
        )
    ).scalar()
    if count:
        raise RuntimeError(
            f"Downgrade recusado: {count} SIM(s) com PIN/PUK guardados seriam perdidos. "
            "Remova-os (ou apague as linhas) antes de reverter."
        )


def upgrade() -> None:
    op.create_table(
        "project_sim_cards",
        sa.Column("id", app.db.GUID(), nullable=False),
        sa.Column("project_id", app.db.GUID(), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("operator", sa.String(length=128), nullable=True),
        sa.Column("phone_number", sa.String(length=64), nullable=True),
        sa.Column("iccid", sa.String(length=128), nullable=True),
        sa.Column("verified_on_portal", sa.Boolean(), nullable=True),
        sa.Column("verified_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("pin_encrypted", sa.Text(), nullable=True),
        sa.Column("puk_encrypted", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_person_id", app.db.GUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["deleted_by_person_id"], ["people.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_project_sim_cards_project_id", "project_sim_cards", ["project_id"])

    bind = op.get_bind()
    comm = sa.table(
        "project_communication_data",
        sa.column("id", app.db.GUID()),
        sa.column("project_id", app.db.GUID()),
        sa.column("operator", sa.String()),
        sa.column("gsm_m2m_number", sa.String()),
        sa.column("card_identifier", sa.String()),
        sa.column("operator_verified", sa.Boolean()),
        sa.column("operator_verified_date", sa.Date()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    sim = sa.table(
        "project_sim_cards",
        sa.column("id", app.db.GUID()),
        sa.column("project_id", app.db.GUID()),
        sa.column("purpose", sa.String()),
        sa.column("operator", sa.String()),
        sa.column("phone_number", sa.String()),
        sa.column("iccid", sa.String()),
        sa.column("verified_on_portal", sa.Boolean()),
        sa.column("verified_date", sa.Date()),
        sa.column("notes", sa.Text()),
    )
    rows = bind.execute(
        sa.select(
            comm.c.project_id,
            comm.c.operator,
            comm.c.gsm_m2m_number,
            comm.c.card_identifier,
            comm.c.operator_verified,
            comm.c.operator_verified_date,
        )
    ).all()
    for project_id, operator, gsm, card, verified, verified_date in rows:
        if all(v in (None, "") for v in (operator, gsm, card, verified, verified_date)):
            continue
        bind.execute(
            sim.insert().values(
                id=uuid.uuid4(),
                project_id=project_id,
                purpose="comunicacoes",
                operator=operator,
                phone_number=gsm,
                iccid=card,
                verified_on_portal=verified,
                verified_date=verified_date,
                notes="",
            )
        )

    with op.batch_alter_table("project_communication_data") as batch:
        for column in _SIM_FIELDS_OLD:
            batch.drop_column(column)

    with op.batch_alter_table("project_portal_credentials") as batch:
        batch.add_column(sa.Column("email", sa.String(length=320), nullable=True))

    with op.batch_alter_table("project_licensing_data") as batch:
        batch.add_column(sa.Column("upac_registration_date", sa.Date(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    _guard_secrets_before_downgrade(bind)

    with op.batch_alter_table("project_licensing_data") as batch:
        batch.drop_column("upac_registration_date")
    with op.batch_alter_table("project_portal_credentials") as batch:
        batch.drop_column("email")

    with op.batch_alter_table("project_communication_data") as batch:
        batch.add_column(sa.Column("operator", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("gsm_m2m_number", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("card_identifier", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("operator_verified", sa.Boolean(), nullable=True))
        batch.add_column(sa.Column("operator_verified_date", sa.Date(), nullable=True))

    # Repõe o primeiro SIM (por criação) de cada projeto nas colunas antigas.
    # Tabelas tipadas (não `sa.text`): no SQLite a data só é convertida para `date`
    # se a coluna for tipada; em texto cru devolve str e o UPDATE rebenta.
    sim = sa.table(
        "project_sim_cards",
        sa.column("project_id", app.db.GUID()),
        sa.column("operator", sa.String()),
        sa.column("phone_number", sa.String()),
        sa.column("iccid", sa.String()),
        sa.column("verified_on_portal", sa.Boolean()),
        sa.column("verified_date", sa.Date()),
        sa.column("deleted_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("id", app.db.GUID()),
    )
    first_sim = bind.execute(
        sa.select(
            sim.c.project_id,
            sim.c.operator,
            sim.c.phone_number,
            sim.c.iccid,
            sim.c.verified_on_portal,
            sim.c.verified_date,
        )
        .where(sim.c.deleted_at.is_(None))
        .order_by(sim.c.created_at, sim.c.id)
    ).all()
    seen: set[str] = set()
    comm = sa.table(
        "project_communication_data",
        sa.column("project_id", app.db.GUID()),
        sa.column("operator", sa.String()),
        sa.column("gsm_m2m_number", sa.String()),
        sa.column("card_identifier", sa.String()),
        sa.column("operator_verified", sa.Boolean()),
        sa.column("operator_verified_date", sa.Date()),
    )
    for project_id, operator, phone, iccid, verified, verified_date in first_sim:
        key = str(project_id)
        if key in seen:
            continue
        seen.add(key)
        bind.execute(
            comm.update()
            .where(comm.c.project_id == project_id)
            .values(
                operator=operator,
                gsm_m2m_number=phone,
                card_identifier=iccid,
                operator_verified=verified,
                operator_verified_date=verified_date,
            )
        )

    op.drop_index("ix_project_sim_cards_project_id", table_name="project_sim_cards")
    op.drop_table("project_sim_cards")
