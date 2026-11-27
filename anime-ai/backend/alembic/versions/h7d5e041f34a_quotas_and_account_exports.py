"""quotas_and_account_exports

Revision ID: h7d5e041f34a
Revises: g6c4d930e23f
Create Date: 2026-11-26 23:20:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'h7d5e041f34a'
down_revision: Union[str, Sequence[str], None] = 'g6c4d930e23f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 1. user_usage_quotas table
    if not insp.has_table('user_usage_quotas'):
        op.create_table(
            'user_usage_quotas',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('user_id', sa.UUID(), nullable=False),
            sa.Column('category', sa.String(length=64), nullable=False),
            sa.Column('window_key', sa.String(length=32), nullable=False),
            sa.Column('usage_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id', 'category', 'window_key', name='uq_user_usage_quota_window'),
        )
        op.create_index('ix_user_usage_quotas_user_id', 'user_usage_quotas', ['user_id'], unique=False)
        op.create_index('ix_user_usage_quotas_category', 'user_usage_quotas', ['category'], unique=False)
        op.create_index('ix_user_usage_quotas_window_key', 'user_usage_quotas', ['window_key'], unique=False)

    # 2. user_data_exports table
    if not insp.has_table('user_data_exports'):
        op.create_table(
            'user_data_exports',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('user_id', sa.UUID(), nullable=False),
            sa.Column('status', sa.String(length=32), nullable=False, server_default='QUEUED'),
            sa.Column('storage_backend', sa.String(length=50), nullable=True),
            sa.Column('storage_key', sa.String(length=1024), nullable=True),
            sa.Column('storage_size', sa.Integer(), nullable=True),
            sa.Column('error', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_user_data_exports_user_id', 'user_data_exports', ['user_id'], unique=False)
        op.create_index('ix_user_data_exports_status', 'user_data_exports', ['status'], unique=False)

    # 3. account_audit_events table (no FK to users so audit survives account deletion)
    if not insp.has_table('account_audit_events'):
        op.create_table(
            'account_audit_events',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('subject_user_id', sa.UUID(), nullable=False),
            sa.Column('event_type', sa.String(length=64), nullable=False),
            sa.Column('details_json', sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_account_audit_events_subject_user_id', 'account_audit_events', ['subject_user_id'], unique=False)
        op.create_index('ix_account_audit_events_event_type', 'account_audit_events', ['event_type'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table('account_audit_events'):
        op.drop_table('account_audit_events')

    if insp.has_table('user_data_exports'):
        op.drop_table('user_data_exports')

    if insp.has_table('user_usage_quotas'):
        op.drop_table('user_usage_quotas')
