"""mvp operacoes: inventario com localizacoes, dados satelite de projeto, mapa, calendario ligado a tarefas, metas

Revision ID: 65bf12876b1e
Revises: 207faad55b86
Create Date: 2026-09-17 11:00:34.630975

Nota: o autogenerate original usava `op.alter_column`/`op.create_foreign_key`
diretos nas tabelas já existentes (calendar_events, inventory_items,
inventory_movements, material_request_items, suppliers), que o SQLite não
suporta (ALTER TABLE muito limitado) — reescrito à mão para usar
`op.batch_alter_table`, mesmo padrão já usado em
f61c909abae0_hardening_fase_0_staging_persistente_.py, com nomes de
constraint explícitos (autogenerate deixava `None`, que falha ao correr).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import app.db  # necessário para o tipo de coluna portável app.db.GUID()


# revision identifiers, used by Alembic.
revision: str = '65bf12876b1e'
down_revision: Union[str, Sequence[str], None] = '207faad55b86'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FK_CALENDAR_EVENTS_TASK = "fk_calendar_events_task_id"
_FK_CALENDAR_EVENTS_ASSIGNED_TO = "fk_calendar_events_assigned_to_person_id"
_FK_INVENTORY_MOVEMENTS_LOCATION = "fk_inventory_movements_location_id"
_FK_INVENTORY_MOVEMENTS_DESTINATION = "fk_inventory_movements_destination_location_id"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('goal_periods',
    sa.Column('period_type', sa.String(length=16), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('quarter', sa.Integer(), nullable=True),
    sa.Column('semester', sa.Integer(), nullable=True),
    sa.Column('month', sa.Integer(), nullable=True),
    sa.Column('metric', sa.String(length=32), nullable=False),
    sa.Column('target_value', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('scope', sa.String(length=16), nullable=False),
    sa.Column('pm_person_id', app.db.GUID(), nullable=True),
    sa.Column('created_by_person_id', app.db.GUID(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('id', app.db.GUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['created_by_person_id'], ['people.id'], ),
    sa.ForeignKeyConstraint(['pm_person_id'], ['people.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('pickup_points',
    sa.Column('name', sa.String(length=256), nullable=False),
    sa.Column('supplier_id', app.db.GUID(), nullable=True),
    sa.Column('address', sa.String(length=512), nullable=True),
    sa.Column('lat', sa.Float(), nullable=True),
    sa.Column('lon', sa.Float(), nullable=True),
    sa.Column('schedule', sa.String(length=256), nullable=True),
    sa.Column('contact', sa.String(length=256), nullable=True),
    sa.Column('materials', sa.Text(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', app.db.GUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['supplier_id'], ['suppliers.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('goal_period_history',
    sa.Column('goal_period_id', app.db.GUID(), nullable=False),
    sa.Column('field_name', sa.String(length=128), nullable=False),
    sa.Column('old_value', sa.Text(), nullable=True),
    sa.Column('new_value', sa.Text(), nullable=True),
    sa.Column('changed_by_person_id', app.db.GUID(), nullable=True),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('changed_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('id', app.db.GUID(), nullable=False),
    sa.ForeignKeyConstraint(['changed_by_person_id'], ['people.id'], ),
    sa.ForeignKeyConstraint(['goal_period_id'], ['goal_periods.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('inventory_locations',
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=256), nullable=False),
    sa.Column('location_type', sa.String(length=32), nullable=False),
    sa.Column('project_id', app.db.GUID(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', app.db.GUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_table('project_communication_data',
    sa.Column('project_id', app.db.GUID(), nullable=False),
    sa.Column('operator', sa.String(length=128), nullable=True),
    sa.Column('gsm_m2m_number', sa.String(length=64), nullable=True),
    sa.Column('card_identifier', sa.String(length=128), nullable=True),
    sa.Column('communication_status', sa.String(length=64), nullable=True),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('id', app.db.GUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id')
    )
    op.create_table('project_data_history',
    sa.Column('project_id', app.db.GUID(), nullable=False),
    sa.Column('entity_type', sa.String(length=32), nullable=False),
    sa.Column('field_name', sa.String(length=128), nullable=False),
    sa.Column('old_value', sa.Text(), nullable=True),
    sa.Column('new_value', sa.Text(), nullable=True),
    sa.Column('changed_by_person_id', app.db.GUID(), nullable=True),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('changed_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('id', app.db.GUID(), nullable=False),
    sa.ForeignKeyConstraint(['changed_by_person_id'], ['people.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('project_installation_data',
    sa.Column('project_id', app.db.GUID(), nullable=False),
    sa.Column('client_nif', sa.String(length=32), nullable=True),
    sa.Column('contact_person_name', sa.String(length=256), nullable=True),
    sa.Column('contact_person_role', sa.String(length=128), nullable=True),
    sa.Column('contact_email', sa.String(length=320), nullable=True),
    sa.Column('contact_phone', sa.String(length=64), nullable=True),
    sa.Column('address', sa.String(length=512), nullable=True),
    sa.Column('district', sa.String(length=128), nullable=True),
    sa.Column('municipality', sa.String(length=128), nullable=True),
    sa.Column('power_kwp', sa.Float(), nullable=True),
    sa.Column('panel_count', sa.Integer(), nullable=True),
    sa.Column('panel_power_wp', sa.Float(), nullable=True),
    sa.Column('inverters', sa.Text(), nullable=True),
    sa.Column('batteries', sa.Text(), nullable=True),
    sa.Column('has_backup', sa.Boolean(), nullable=True),
    sa.Column('ev_chargers', sa.Text(), nullable=True),
    sa.Column('installation_type', sa.String(length=128), nullable=True),
    sa.Column('injection_type', sa.String(length=128), nullable=True),
    sa.Column('om_notes', sa.Text(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('id', app.db.GUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id')
    )
    op.create_table('project_licensing_data',
    sa.Column('project_id', app.db.GUID(), nullable=False),
    sa.Column('upac_number', sa.String(length=128), nullable=True),
    sa.Column('dgeg_number', sa.String(length=128), nullable=True),
    sa.Column('cadastro_number', sa.String(length=128), nullable=True),
    sa.Column('licensing_status', sa.String(length=64), nullable=True),
    sa.Column('registration_date', sa.Date(), nullable=True),
    sa.Column('certification_request_date', sa.Date(), nullable=True),
    sa.Column('inspecting_entity', sa.String(length=256), nullable=True),
    sa.Column('inspection_date', sa.Date(), nullable=True),
    sa.Column('certificate_date', sa.Date(), nullable=True),
    sa.Column('installer', sa.String(length=256), nullable=True),
    sa.Column('commercializer', sa.String(length=256), nullable=True),
    sa.Column('annual_production_kwh', sa.Float(), nullable=True),
    sa.Column('comments', sa.Text(), nullable=False),
    sa.Column('id', app.db.GUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id')
    )
    op.create_table('project_material_requirements',
    sa.Column('project_id', app.db.GUID(), nullable=False),
    sa.Column('item_id', app.db.GUID(), nullable=False),
    sa.Column('quantity_required', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('created_by_person_id', app.db.GUID(), nullable=True),
    sa.Column('id', app.db.GUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['created_by_person_id'], ['people.id'], ),
    sa.ForeignKeyConstraint(['item_id'], ['inventory_items.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'item_id', name='uq_project_material_requirement')
    )
    op.create_table('project_issues',
    sa.Column('project_id', app.db.GUID(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('category', sa.String(length=32), nullable=False),
    sa.Column('priority', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('assigned_to_person_id', app.db.GUID(), nullable=True),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('lat', sa.Float(), nullable=True),
    sa.Column('lon', sa.Float(), nullable=True),
    sa.Column('related_task_id', app.db.GUID(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('visible_on_map', sa.Boolean(), nullable=False),
    sa.Column('created_by_person_id', app.db.GUID(), nullable=True),
    sa.Column('id', app.db.GUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['assigned_to_person_id'], ['people.id'], ),
    sa.ForeignKeyConstraint(['created_by_person_id'], ['people.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.ForeignKeyConstraint(['related_task_id'], ['tasks.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    with op.batch_alter_table('calendar_events', schema=None) as batch_op:
        batch_op.add_column(sa.Column('task_id', app.db.GUID(), nullable=True))
        batch_op.add_column(sa.Column('assigned_to_person_id', app.db.GUID(), nullable=True))
        batch_op.create_foreign_key(_FK_CALENDAR_EVENTS_TASK, 'tasks', ['task_id'], ['id'])
        batch_op.create_foreign_key(_FK_CALENDAR_EVENTS_ASSIGNED_TO, 'people', ['assigned_to_person_id'], ['id'])

    with op.batch_alter_table('inventory_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.alter_column(
            'min_stock',
            existing_type=sa.FLOAT(),
            type_=sa.Numeric(precision=14, scale=3),
            existing_nullable=False,
        )
    with op.batch_alter_table('inventory_items', schema=None) as batch_op:
        batch_op.alter_column('is_active', server_default=None)

    with op.batch_alter_table('inventory_movements', schema=None) as batch_op:
        batch_op.add_column(sa.Column('location_id', app.db.GUID(), nullable=True))
        batch_op.add_column(sa.Column('destination_location_id', app.db.GUID(), nullable=True))
        batch_op.add_column(sa.Column('unit_cost', sa.Numeric(precision=12, scale=2), nullable=True))
        batch_op.add_column(sa.Column('idempotency_key', sa.String(length=128), nullable=True))
        batch_op.alter_column(
            'quantity',
            existing_type=sa.FLOAT(),
            type_=sa.Numeric(precision=14, scale=3),
            existing_nullable=False,
        )
        batch_op.create_unique_constraint('uq_inventory_movement_idempotency_key', ['idempotency_key'])
        batch_op.create_foreign_key(
            _FK_INVENTORY_MOVEMENTS_DESTINATION, 'inventory_locations', ['destination_location_id'], ['id']
        )
        batch_op.create_foreign_key(
            _FK_INVENTORY_MOVEMENTS_LOCATION, 'inventory_locations', ['location_id'], ['id']
        )

    with op.batch_alter_table('material_request_items', schema=None) as batch_op:
        batch_op.alter_column(
            'quantity',
            existing_type=sa.FLOAT(),
            type_=sa.Numeric(precision=14, scale=3),
            existing_nullable=False,
        )

    with op.batch_alter_table('suppliers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('materials', sa.Text(), nullable=False, server_default=""))
        batch_op.add_column(sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))
    with op.batch_alter_table('suppliers', schema=None) as batch_op:
        batch_op.alter_column('materials', server_default=None)
        batch_op.alter_column('is_active', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('suppliers', schema=None) as batch_op:
        batch_op.drop_column('is_active')
        batch_op.drop_column('materials')

    with op.batch_alter_table('material_request_items', schema=None) as batch_op:
        batch_op.alter_column(
            'quantity',
            existing_type=sa.Numeric(precision=14, scale=3),
            type_=sa.FLOAT(),
            existing_nullable=False,
        )

    with op.batch_alter_table('inventory_movements', schema=None) as batch_op:
        batch_op.drop_constraint(_FK_INVENTORY_MOVEMENTS_LOCATION, type_='foreignkey')
        batch_op.drop_constraint(_FK_INVENTORY_MOVEMENTS_DESTINATION, type_='foreignkey')
        batch_op.drop_constraint('uq_inventory_movement_idempotency_key', type_='unique')
        batch_op.alter_column(
            'quantity',
            existing_type=sa.Numeric(precision=14, scale=3),
            type_=sa.FLOAT(),
            existing_nullable=False,
        )
        batch_op.drop_column('idempotency_key')
        batch_op.drop_column('unit_cost')
        batch_op.drop_column('destination_location_id')
        batch_op.drop_column('location_id')

    with op.batch_alter_table('inventory_items', schema=None) as batch_op:
        batch_op.alter_column(
            'min_stock',
            existing_type=sa.Numeric(precision=14, scale=3),
            type_=sa.FLOAT(),
            existing_nullable=False,
        )
        batch_op.drop_column('is_active')

    with op.batch_alter_table('calendar_events', schema=None) as batch_op:
        batch_op.drop_constraint(_FK_CALENDAR_EVENTS_ASSIGNED_TO, type_='foreignkey')
        batch_op.drop_constraint(_FK_CALENDAR_EVENTS_TASK, type_='foreignkey')
        batch_op.drop_column('assigned_to_person_id')
        batch_op.drop_column('task_id')

    op.drop_table('project_issues')
    op.drop_table('project_material_requirements')
    op.drop_table('project_licensing_data')
    op.drop_table('project_installation_data')
    op.drop_table('project_data_history')
    op.drop_table('project_communication_data')
    op.drop_table('inventory_locations')
    op.drop_table('goal_period_history')
    op.drop_table('pickup_points')
    op.drop_table('goal_periods')
