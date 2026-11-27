"""outbox_leases_and_image_batches

Revision ID: i8e6f152a45b
Revises: h7d5e041f34a
Create Date: 2026-11-27 14:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'i8e6f152a45b'
down_revision: Union[str, Sequence[str], None] = 'h7d5e041f34a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 1. Add multi-worker lease/claim columns to storage_deletion_outbox
    if insp.has_table('storage_deletion_outbox'):
        existing_cols = {c['name'] for c in insp.get_columns('storage_deletion_outbox')}
        existing_indexes = {idx['name'] for idx in insp.get_indexes('storage_deletion_outbox')}

        with op.batch_alter_table('storage_deletion_outbox') as batch_op:
            if 'worker_id' not in existing_cols:
                batch_op.add_column(sa.Column('worker_id', sa.String(length=128), nullable=True))
            if 'claim_token' not in existing_cols:
                batch_op.add_column(sa.Column('claim_token', sa.UUID(), nullable=True))
            if 'claimed_at' not in existing_cols:
                batch_op.add_column(sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True))
            if 'lease_expires_at' not in existing_cols:
                batch_op.add_column(sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True))

        if 'ix_storage_deletion_outbox_worker_id' not in existing_indexes:
            op.create_index('ix_storage_deletion_outbox_worker_id', 'storage_deletion_outbox', ['worker_id'], unique=False)
        if 'ix_storage_deletion_outbox_claim_token' not in existing_indexes:
            op.create_index('ix_storage_deletion_outbox_claim_token', 'storage_deletion_outbox', ['claim_token'], unique=False)
        if 'ix_storage_deletion_outbox_lease_expires_at' not in existing_indexes:
            op.create_index('ix_storage_deletion_outbox_lease_expires_at', 'storage_deletion_outbox', ['lease_expires_at'], unique=False)

    # 2. Create image_variation_batches table for idempotent multi-job variation batches
    if not insp.has_table('image_variation_batches'):
        op.create_table(
            'image_variation_batches',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('user_id', sa.UUID(), nullable=False),
            sa.Column('idempotency_key', sa.String(length=128), nullable=False),
            sa.Column('parent_image_id', sa.UUID(), nullable=True),
            sa.Column('job_ids', sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['parent_image_id'], ['generated_images.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id', 'idempotency_key', name='uq_image_var_batches_user_idem'),
        )
        op.create_index('ix_image_variation_batches_user_id', 'image_variation_batches', ['user_id'], unique=False)
        op.create_index('ix_image_variation_batches_idempotency_key', 'image_variation_batches', ['idempotency_key'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table('image_variation_batches'):
        op.drop_table('image_variation_batches')

    if insp.has_table('storage_deletion_outbox'):
        existing_cols = {c['name'] for c in insp.get_columns('storage_deletion_outbox')}
        existing_indexes = {idx['name'] for idx in insp.get_indexes('storage_deletion_outbox')}

        for idx_name in (
            'ix_storage_deletion_outbox_lease_expires_at',
            'ix_storage_deletion_outbox_claim_token',
            'ix_storage_deletion_outbox_worker_id',
        ):
            if idx_name in existing_indexes:
                op.drop_index(idx_name, table_name='storage_deletion_outbox')

        with op.batch_alter_table('storage_deletion_outbox') as batch_op:
            for col_name in ('lease_expires_at', 'claimed_at', 'claim_token', 'worker_id'):
                if col_name in existing_cols:
                    batch_op.drop_column(col_name)
