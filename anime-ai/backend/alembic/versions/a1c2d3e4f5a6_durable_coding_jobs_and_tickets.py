"""durable_coding_jobs_and_tickets

Revision ID: a1c2d3e4f5a6
Revises: f5b3c829d12e
Create Date: 2026-09-08 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = 'f5b3c829d12e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 1. coding_jobs table
    if not insp.has_table('coding_jobs'):
        op.create_table(
            'coding_jobs',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('task_id', sa.String(length=128), nullable=False),
            sa.Column('workspace_id', sa.UUID(), nullable=False),
            sa.Column('user_id', sa.UUID(), nullable=False),
            sa.Column('worker_id', sa.String(length=128), nullable=True),
            sa.Column('execution_attempt_id', sa.UUID(), nullable=True),
            sa.Column('status', sa.String(length=64), nullable=False, server_default='QUEUED'),
            sa.Column('instructions', sa.Text(), nullable=False),
            sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('cancel_requested', sa.Boolean(), nullable=False, server_default=sa.text('false')),
            sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('error', sa.Text(), nullable=True),
            sa.Column('verification_state', sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column('metadata_json', sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.ForeignKeyConstraint(['workspace_id'], ['repository_workspaces.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_coding_jobs_task_id', 'coding_jobs', ['task_id'])
        op.create_index('ix_coding_jobs_workspace_id', 'coding_jobs', ['workspace_id'])
        op.create_index('ix_coding_jobs_user_id', 'coding_jobs', ['user_id'])
        op.create_index('ix_coding_jobs_status', 'coding_jobs', ['status'])

    # 2. coding_task_events table
    if not insp.has_table('coding_task_events'):
        op.create_table(
            'coding_task_events',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('task_id', sa.String(length=128), nullable=False),
            sa.Column('job_id', sa.UUID(), nullable=True),
            sa.Column('sequence_number', sa.Integer(), nullable=False),
            sa.Column('phase', sa.String(length=64), nullable=False),
            sa.Column('event_type', sa.String(length=64), nullable=False),
            sa.Column('tool_name', sa.String(length=128), nullable=True),
            sa.Column('arguments_summary', sa.Text(), nullable=True),
            sa.Column('stdout_preview', sa.Text(), nullable=True),
            sa.Column('stderr_preview', sa.Text(), nullable=True),
            sa.Column('exit_code', sa.Integer(), nullable=True),
            sa.Column('diff_metadata', sa.JSON(), nullable=True),
            sa.Column('verification_metadata', sa.JSON(), nullable=True),
            sa.Column('message', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(['job_id'], ['coding_jobs.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_coding_task_events_task_id', 'coding_task_events', ['task_id'])
        op.create_index('ix_coding_task_events_job_id', 'coding_task_events', ['job_id'])
        op.create_index('ix_coding_task_events_seq', 'coding_task_events', ['task_id', 'sequence_number'])

    # 3. websocket_tickets table
    if not insp.has_table('websocket_tickets'):
        op.create_table(
            'websocket_tickets',
            sa.Column('ticket', sa.String(length=128), nullable=False),
            sa.Column('user_id', sa.UUID(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('ticket')
        )
        op.create_index('ix_websocket_tickets_user_id', 'websocket_tickets', ['user_id'])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table('websocket_tickets'):
        op.drop_table('websocket_tickets')

    if insp.has_table('coding_task_events'):
        op.drop_table('coding_task_events')

    if insp.has_table('coding_jobs'):
        op.drop_table('coding_jobs')
