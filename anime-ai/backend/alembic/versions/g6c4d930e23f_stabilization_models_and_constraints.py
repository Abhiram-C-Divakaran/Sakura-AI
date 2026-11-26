"""stabilization_models_and_constraints

Revision ID: g6c4d930e23f
Revises: a1c2d3e4f5a6
Create Date: 2026-11-26 21:55:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'g6c4d930e23f'
down_revision: Union[str, Sequence[str], None] = 'a1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 1. users: email column
    if insp.has_table('users'):
        cols = [c['name'] for c in insp.get_columns('users')]
        with op.batch_alter_table('users', schema=None) as batch_op:
            if 'email' not in cols:
                batch_op.add_column(sa.Column('email', sa.String(length=255), nullable=True))
                batch_op.create_index('ix_users_email', ['email'], unique=False)

    # 2. documents: deletion_status column
    if insp.has_table('documents'):
        cols = [c['name'] for c in insp.get_columns('documents')]
        with op.batch_alter_table('documents', schema=None) as batch_op:
            if 'deletion_status' not in cols:
                batch_op.add_column(
                    sa.Column('deletion_status', sa.String(length=32), nullable=False, server_default='ACTIVE')
                )
                batch_op.create_index('ix_documents_deletion_status', ['deletion_status'], unique=False)

    # 3. coding_tasks: completed_at column
    if insp.has_table('coding_tasks'):
        cols = [c['name'] for c in insp.get_columns('coding_tasks')]
        with op.batch_alter_table('coding_tasks', schema=None) as batch_op:
            if 'completed_at' not in cols:
                batch_op.add_column(sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True))

    # 4. coding_jobs: intensity, idempotency_key, indexes & unique constraint
    if insp.has_table('coding_jobs'):
        cols = [c['name'] for c in insp.get_columns('coding_jobs')]
        idxs = {i['name'] for i in insp.get_indexes('coding_jobs')}
        uqs = {u['name'] for u in insp.get_unique_constraints('coding_jobs')}
        with op.batch_alter_table('coding_jobs', schema=None) as batch_op:
            if 'intensity' not in cols:
                batch_op.add_column(sa.Column('intensity', sa.String(length=32), nullable=False, server_default='high'))
            if 'idempotency_key' not in cols:
                batch_op.add_column(sa.Column('idempotency_key', sa.String(length=128), nullable=True))
            if 'ix_coding_jobs_idempotency_key' not in idxs:
                batch_op.create_index('ix_coding_jobs_idempotency_key', ['idempotency_key'], unique=False)
            if 'ix_coding_jobs_execution_attempt_id' not in idxs:
                batch_op.create_index('ix_coding_jobs_execution_attempt_id', ['execution_attempt_id'], unique=False)
            if 'ix_coding_jobs_lease_expires_at' not in idxs:
                batch_op.create_index('ix_coding_jobs_lease_expires_at', ['lease_expires_at'], unique=False)
            if 'uq_coding_jobs_user_idempotency' not in uqs:
                batch_op.create_unique_constraint('uq_coding_jobs_user_idempotency', ['user_id', 'idempotency_key'])

    # 5. coding_task_events: unique (task_id, sequence_number)
    if insp.has_table('coding_task_events'):
        uqs = {u['name'] for u in insp.get_unique_constraints('coding_task_events')}
        if 'uq_coding_task_events_task_seq' not in uqs:
            with op.batch_alter_table('coding_task_events', schema=None) as batch_op:
                batch_op.create_unique_constraint('uq_coding_task_events_task_seq', ['task_id', 'sequence_number'])

    # 6. image_generation_jobs table
    if not insp.has_table('image_generation_jobs'):
        op.create_table(
            'image_generation_jobs',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('user_id', sa.UUID(), nullable=False),
            sa.Column('prompt', sa.Text(), nullable=False),
            sa.Column('requested_pipeline', sa.String(length=64), nullable=False, server_default='auto'),
            sa.Column('actual_provider', sa.String(length=64), nullable=True),
            sa.Column('actual_model', sa.String(length=128), nullable=True),
            sa.Column('status', sa.String(length=32), nullable=False, server_default='QUEUED'),
            sa.Column('attempt_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='3'),
            sa.Column('error', sa.Text(), nullable=True),
            sa.Column('output_image_id', sa.UUID(), nullable=True),
            sa.Column('worker_id', sa.String(length=128), nullable=True),
            sa.Column('execution_attempt_id', sa.UUID(), nullable=True),
            sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('cancel_requested', sa.Boolean(), nullable=False, server_default=sa.text('false')),
            sa.Column('idempotency_key', sa.String(length=128), nullable=True),
            sa.Column('parameters', sa.JSON(), nullable=False, server_default='{}'),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['output_image_id'], ['generated_images.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id', 'idempotency_key', name='uq_image_jobs_user_idempotency'),
        )
        op.create_index('ix_image_generation_jobs_user_id', 'image_generation_jobs', ['user_id'], unique=False)
        op.create_index('ix_image_generation_jobs_status', 'image_generation_jobs', ['status'], unique=False)
        op.create_index('ix_image_generation_jobs_execution_attempt_id', 'image_generation_jobs', ['execution_attempt_id'], unique=False)
        op.create_index('ix_image_generation_jobs_lease_expires_at', 'image_generation_jobs', ['lease_expires_at'], unique=False)
        op.create_index('ix_image_generation_jobs_idempotency_key', 'image_generation_jobs', ['idempotency_key'], unique=False)

    # 7. storage_deletion_outbox table
    if not insp.has_table('storage_deletion_outbox'):
        op.create_table(
            'storage_deletion_outbox',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('user_id', sa.UUID(), nullable=True),
            sa.Column('document_id', sa.UUID(), nullable=True),
            sa.Column('storage_backend', sa.String(length=50), nullable=False, server_default='local'),
            sa.Column('storage_key', sa.String(length=1024), nullable=False),
            sa.Column('legacy_path', sa.String(length=1024), nullable=True),
            sa.Column('status', sa.String(length=32), nullable=False, server_default='PENDING'),
            sa.Column('attempt_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='5'),
            sa.Column('last_error', sa.Text(), nullable=True),
            sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_storage_deletion_outbox_user_id', 'storage_deletion_outbox', ['user_id'], unique=False)
        op.create_index('ix_storage_deletion_outbox_document_id', 'storage_deletion_outbox', ['document_id'], unique=False)
        op.create_index('ix_storage_deletion_outbox_storage_key', 'storage_deletion_outbox', ['storage_key'], unique=False)
        op.create_index('ix_storage_deletion_outbox_status', 'storage_deletion_outbox', ['status'], unique=False)
        op.create_index('ix_storage_deletion_outbox_next_retry_at', 'storage_deletion_outbox', ['next_retry_at'], unique=False)

    # 8. password_reset_tokens table
    if not insp.has_table('password_reset_tokens'):
        op.create_table(
            'password_reset_tokens',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('user_id', sa.UUID(), nullable=False),
            sa.Column('token_hash', sa.String(length=128), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_password_reset_tokens_user_id', 'password_reset_tokens', ['user_id'], unique=False)
        op.create_index('ix_password_reset_tokens_token_hash', 'password_reset_tokens', ['token_hash'], unique=True)
        op.create_index('ix_password_reset_tokens_expires_at', 'password_reset_tokens', ['expires_at'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table('password_reset_tokens'):
        op.drop_table('password_reset_tokens')

    if insp.has_table('storage_deletion_outbox'):
        op.drop_table('storage_deletion_outbox')

    if insp.has_table('image_generation_jobs'):
        op.drop_table('image_generation_jobs')

    if insp.has_table('coding_task_events'):
        uqs = {u['name'] for u in insp.get_unique_constraints('coding_task_events')}
        if 'uq_coding_task_events_task_seq' in uqs:
            with op.batch_alter_table('coding_task_events', schema=None) as batch_op:
                batch_op.drop_constraint('uq_coding_task_events_task_seq', type_='unique')

    if insp.has_table('coding_jobs'):
        cols = [c['name'] for c in insp.get_columns('coding_jobs')]
        idxs = {i['name'] for i in insp.get_indexes('coding_jobs')}
        uqs = {u['name'] for u in insp.get_unique_constraints('coding_jobs')}
        with op.batch_alter_table('coding_jobs', schema=None) as batch_op:
            if 'uq_coding_jobs_user_idempotency' in uqs:
                batch_op.drop_constraint('uq_coding_jobs_user_idempotency', type_='unique')
            if 'ix_coding_jobs_lease_expires_at' in idxs:
                batch_op.drop_index('ix_coding_jobs_lease_expires_at')
            if 'ix_coding_jobs_execution_attempt_id' in idxs:
                batch_op.drop_index('ix_coding_jobs_execution_attempt_id')
            if 'ix_coding_jobs_idempotency_key' in idxs:
                batch_op.drop_index('ix_coding_jobs_idempotency_key')
            if 'idempotency_key' in cols:
                batch_op.drop_column('idempotency_key')
            if 'intensity' in cols:
                batch_op.drop_column('intensity')

    if insp.has_table('coding_tasks'):
        cols = [c['name'] for c in insp.get_columns('coding_tasks')]
        if 'completed_at' in cols:
            with op.batch_alter_table('coding_tasks', schema=None) as batch_op:
                batch_op.drop_column('completed_at')

    if insp.has_table('documents'):
        cols = [c['name'] for c in insp.get_columns('documents')]
        idxs = {i['name'] for i in insp.get_indexes('documents')}
        with op.batch_alter_table('documents', schema=None) as batch_op:
            if 'ix_documents_deletion_status' in idxs:
                batch_op.drop_index('ix_documents_deletion_status')
            if 'deletion_status' in cols:
                batch_op.drop_column('deletion_status')

    if insp.has_table('users'):
        cols = [c['name'] for c in insp.get_columns('users')]
        idxs = {i['name'] for i in insp.get_indexes('users')}
        with op.batch_alter_table('users', schema=None) as batch_op:
            if 'ix_users_email' in idxs:
                batch_op.drop_index('ix_users_email')
            if 'email' in cols:
                batch_op.drop_column('email')
