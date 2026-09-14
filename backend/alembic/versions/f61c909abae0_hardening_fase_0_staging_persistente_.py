"""hardening fase 0: staging persistente, campos legados, montante numerico

Revision ID: f61c909abae0
Revises: 80a4e9cb153e
Create Date: 2026-09-14 12:03:41.501364

Nota: o autogenerate original usava `op.alter_column`/`op.create_foreign_key`
diretos, que o SQLite não suporta (ALTER TABLE muito limitado). Reescrito
à mão para usar `op.batch_alter_table`, que funciona em SQLite (recria a
tabela por baixo) e em PostgreSQL (ALTER direto) sem alterar o resultado.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import app.db  # necessário para o tipo de coluna portável app.db.GUID()


# revision identifiers, used by Alembic.
revision: str = 'f61c909abae0'
down_revision: Union[str, Sequence[str], None] = '80a4e9cb153e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FK_PROJECT_HISTORY_STAGING = "fk_project_history_related_staging_record_id"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('import_batches',
    sa.Column('source_system', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('started_by_person_id', app.db.GUID(), nullable=True),
    sa.Column('checksum', sa.String(length=128), nullable=False),
    sa.Column('raw_payload_json', sa.Text(), nullable=False),
    sa.Column('records_seen', sa.Integer(), nullable=False),
    sa.Column('records_ready', sa.Integer(), nullable=False),
    sa.Column('records_conflicted', sa.Integer(), nullable=False),
    sa.Column('id', app.db.GUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['started_by_person_id'], ['people.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('staging_project_records',
    sa.Column('import_batch_id', app.db.GUID(), nullable=False),
    sa.Column('source_system', sa.String(length=32), nullable=False),
    sa.Column('external_id', sa.String(length=256), nullable=False),
    sa.Column('raw_record_json', sa.Text(), nullable=False),
    sa.Column('mapped_fields_json', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('conflict_reason', sa.String(length=64), nullable=True),
    sa.Column('candidate_project_ids_json', sa.Text(), nullable=False),
    sa.Column('resolved_action', sa.String(length=32), nullable=True),
    sa.Column('resolved_target_project_id', app.db.GUID(), nullable=True),
    sa.Column('resolved_by_person_id', app.db.GUID(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolution_note', sa.Text(), nullable=False),
    sa.Column('promoted_project_id', app.db.GUID(), nullable=True),
    sa.Column('promoted_by_person_id', app.db.GUID(), nullable=True),
    sa.Column('promoted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reverted_by_person_id', app.db.GUID(), nullable=True),
    sa.Column('reverted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reverted_reason', sa.Text(), nullable=False),
    sa.Column('id', app.db.GUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['import_batch_id'], ['import_batches.id'], ),
    sa.ForeignKeyConstraint(['promoted_by_person_id'], ['people.id'], ),
    sa.ForeignKeyConstraint(['promoted_project_id'], ['projects.id'], ),
    sa.ForeignKeyConstraint(['resolved_by_person_id'], ['people.id'], ),
    sa.ForeignKeyConstraint(['resolved_target_project_id'], ['projects.id'], ),
    sa.ForeignKeyConstraint(['reverted_by_person_id'], ['people.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.drop_table('sync_conflicts')
    op.drop_table('sync_runs')

    with op.batch_alter_table('cost_lines', schema=None) as batch_op:
        batch_op.alter_column(
            'amount',
            existing_type=sa.FLOAT(),
            type_=sa.Numeric(precision=12, scale=2),
            existing_nullable=False,
        )

    with op.batch_alter_table('material_request_items', schema=None) as batch_op:
        batch_op.alter_column(
            'unit_price',
            existing_type=sa.FLOAT(),
            type_=sa.Numeric(precision=12, scale=2),
            existing_nullable=True,
        )

    with op.batch_alter_table('project_history', schema=None) as batch_op:
        batch_op.add_column(sa.Column('related_staging_record_id', app.db.GUID(), nullable=True))
        batch_op.create_foreign_key(
            _FK_PROJECT_HISTORY_STAGING,
            'staging_project_records',
            ['related_staging_record_id'],
            ['id'],
        )

    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('power_raw', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('role', sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column('equipment_notes', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('injection_notes', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('om_notes', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('commercial_assumptions', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('upac_registration', sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column('m2m_card', sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column('upac_connection_date_raw', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('award_year_raw', sa.String(length=16), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_column('award_year_raw')
        batch_op.drop_column('upac_connection_date_raw')
        batch_op.drop_column('m2m_card')
        batch_op.drop_column('upac_registration')
        batch_op.drop_column('commercial_assumptions')
        batch_op.drop_column('om_notes')
        batch_op.drop_column('injection_notes')
        batch_op.drop_column('equipment_notes')
        batch_op.drop_column('role')
        batch_op.drop_column('power_raw')

    with op.batch_alter_table('project_history', schema=None) as batch_op:
        batch_op.drop_constraint(_FK_PROJECT_HISTORY_STAGING, type_='foreignkey')
        batch_op.drop_column('related_staging_record_id')

    with op.batch_alter_table('material_request_items', schema=None) as batch_op:
        batch_op.alter_column(
            'unit_price',
            existing_type=sa.Numeric(precision=12, scale=2),
            type_=sa.FLOAT(),
            existing_nullable=True,
        )

    with op.batch_alter_table('cost_lines', schema=None) as batch_op:
        batch_op.alter_column(
            'amount',
            existing_type=sa.Numeric(precision=12, scale=2),
            type_=sa.FLOAT(),
            existing_nullable=False,
        )

    op.create_table('sync_runs',
    sa.Column('source_system', sa.VARCHAR(length=32), nullable=False),
    sa.Column('mode', sa.VARCHAR(length=16), nullable=False),
    sa.Column('status', sa.VARCHAR(length=32), nullable=False),
    sa.Column('started_at', sa.DATETIME(), nullable=False),
    sa.Column('finished_at', sa.DATETIME(), nullable=True),
    sa.Column('records_seen', sa.INTEGER(), nullable=False),
    sa.Column('records_created', sa.INTEGER(), nullable=False),
    sa.Column('records_updated', sa.INTEGER(), nullable=False),
    sa.Column('records_conflicted', sa.INTEGER(), nullable=False),
    sa.Column('checksum', sa.VARCHAR(length=128), nullable=True),
    sa.Column('report_json', sa.TEXT(), nullable=False),
    sa.Column('id', sa.CHAR(length=36), nullable=False),
    sa.Column('created_at', sa.DATETIME(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DATETIME(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('sync_conflicts',
    sa.Column('sync_run_id', sa.CHAR(length=36), nullable=False),
    sa.Column('source_system', sa.VARCHAR(length=32), nullable=False),
    sa.Column('external_id', sa.VARCHAR(length=256), nullable=False),
    sa.Column('reason', sa.VARCHAR(length=128), nullable=False),
    sa.Column('candidate_project_ids_json', sa.TEXT(), nullable=False),
    sa.Column('payload_json', sa.TEXT(), nullable=False),
    sa.Column('status', sa.VARCHAR(length=32), nullable=False),
    sa.Column('resolved_by_person_id', sa.CHAR(length=36), nullable=True),
    sa.Column('resolution_note', sa.TEXT(), nullable=False),
    sa.Column('id', sa.CHAR(length=36), nullable=False),
    sa.Column('created_at', sa.DATETIME(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DATETIME(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['resolved_by_person_id'], ['people.id'], ),
    sa.ForeignKeyConstraint(['sync_run_id'], ['sync_runs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.drop_table('staging_project_records')
    op.drop_table('import_batches')
