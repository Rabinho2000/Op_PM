"""instaladores, equipas e datas da obra

Revision ID: c8d2e4f6a1b7
Revises: a3f5d81c9e42
Create Date: 2026-09-24 20:00:00.000000

"""
import datetime as dt
import unicodedata
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.db  # necessário para o tipo de coluna portável app.db.GUID()


# revision identifiers, used by Alembic.
revision: str = 'c8d2e4f6a1b7'
down_revision: Union[str, Sequence[str], None] = 'a3f5d81c9e42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Cópia congelada de app/services/installers.py: uma migração não depende de
# código de aplicação que pode mudar depois.
WORK_START_BUSINESS_DAY = 41
WORK_END_BUSINESS_DAY = 49


def _key(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", " ".join(text.split()).lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _business_day(start: dt.date, n: int) -> dt.date:
    day = start
    while day.weekday() >= 5:
        day += dt.timedelta(days=1)
    counted = 1
    while counted < n:
        day += dt.timedelta(days=1)
        if day.weekday() < 5:
            counted += 1
    return day


def _as_date(value):
    if value is None or isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value)[:10])


def upgrade() -> None:
    """Upgrade schema.

    Cria `installers` e `installer_teams` e acrescenta a `projects` o instalador,
    a equipa (chave estrangeira composta: a equipa tem de pertencer ao
    instalador) e a janela da obra (`work_start_date`/`work_end_date`, com
    `work_dates_estimated`). Preenche:
    - as datas da obra de cada projeto com `start_date`, como **estimadas**
      (dia útil 41 a 49 desde o arranque — o modelo base do processo);
    - o instalador dos projetos que tinham o texto livre em
      `project_licensing_data.installer`. O texto antigo mantém-se.
    """
    op.create_table(
        'installers',
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('name_key', sa.String(length=256), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('id', app.db.GUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name_key'),
    )
    op.create_table(
        'installer_teams',
        sa.Column('installer_id', app.db.GUID(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('name_key', sa.String(length=128), nullable=False),
        sa.Column('leader_name', sa.String(length=256), nullable=True),
        sa.Column('leader_phone', sa.String(length=64), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('id', app.db.GUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['installer_id'], ['installers.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('installer_id', 'id', name='uq_installer_team_pair'),
        sa.UniqueConstraint('installer_id', 'name_key', name='uq_installer_team_name'),
    )
    with op.batch_alter_table('installer_teams', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_installer_teams_installer_id'), ['installer_id'], unique=False)

    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('installer_id', app.db.GUID(), nullable=True))
        batch_op.add_column(sa.Column('installer_team_id', app.db.GUID(), nullable=True))
        batch_op.add_column(sa.Column('work_start_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('work_end_date', sa.Date(), nullable=True))
        # server_default só para as linhas existentes; o valor em runtime vem do ORM.
        batch_op.add_column(sa.Column('work_dates_estimated', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.create_index(batch_op.f('ix_projects_installer_id'), ['installer_id'], unique=False)
        batch_op.create_foreign_key('fk_project_installer', 'installers', ['installer_id'], ['id'])
        batch_op.create_foreign_key(
            'fk_project_team_belongs_to_installer',
            'installer_teams',
            ['installer_id', 'installer_team_id'],
            ['installer_id', 'id'],
        )
        batch_op.create_check_constraint(
            'ck_project_team_needs_installer', 'installer_team_id IS NULL OR installer_id IS NOT NULL'
        )
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.alter_column('work_dates_estimated', server_default=None)

    bind = op.get_bind()

    # 1) Datas estimadas da obra.
    for project_id, start in bind.execute(sa.text("SELECT id, start_date FROM projects WHERE start_date IS NOT NULL")).fetchall():
        start_date = _as_date(start)
        bind.execute(
            sa.text(
                "UPDATE projects SET work_start_date = :s, work_end_date = :e, work_dates_estimated = :t WHERE id = :i"
            ),
            {
                "s": _business_day(start_date, WORK_START_BUSINESS_DAY),
                "e": _business_day(start_date, WORK_END_BUSINESS_DAY),
                "t": True,
                "i": project_id,
            },
        )

    # 2) Instalador a partir do texto livre antigo (quando existir).
    installers_tbl = sa.table(
        'installers',
        sa.column('id', app.db.GUID()),
        sa.column('name', sa.String()),
        sa.column('name_key', sa.String()),
        sa.column('is_active', sa.Boolean()),
    )
    by_key: dict = {}
    rows = bind.execute(
        sa.text(
            "SELECT project_id, installer FROM project_licensing_data "
            "WHERE installer IS NOT NULL AND TRIM(installer) <> ''"
        )
    ).fetchall()
    for project_id, installer in rows:
        display = " ".join(str(installer).split())
        key = _key(display)
        if key not in by_key:
            installer_id = uuid.uuid4()
            bind.execute(sa.insert(installers_tbl).values(id=installer_id, name=display, name_key=key, is_active=True))
            by_key[key] = installer_id
        bind.execute(
            sa.text("UPDATE projects SET installer_id = :n WHERE id = :i"),
            {"n": by_key[key] if bind.dialect.name == "postgresql" else str(by_key[key]), "i": project_id},
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_constraint('ck_project_team_needs_installer', type_='check')
        batch_op.drop_constraint('fk_project_team_belongs_to_installer', type_='foreignkey')
        batch_op.drop_constraint('fk_project_installer', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_projects_installer_id'))
        batch_op.drop_column('work_dates_estimated')
        batch_op.drop_column('work_end_date')
        batch_op.drop_column('work_start_date')
        batch_op.drop_column('installer_team_id')
        batch_op.drop_column('installer_id')
    with op.batch_alter_table('installer_teams', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_installer_teams_installer_id'))
    op.drop_table('installer_teams')
    op.drop_table('installers')
