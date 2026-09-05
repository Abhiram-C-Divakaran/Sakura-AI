"""worker_leases_and_scheduled_runs

Revision ID: b1c4e72089fa
Revises: 9a71bc9821ef
Create Date: 2026-09-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c4e72089fa'
down_revision: Union[str, Sequence[str], None] = '9a71bc9821ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 1. Update background_tasks with worker lease and cancellation fields
    if insp.has_table('background_tasks'):
        existing_cols = [c['name'] for c in insp.get_columns('background_tasks')]
        with op.batch_alter_table('background_tasks', schema=None) as batch_op:
            if 'lease_expires_at' not in existing_cols:
                batch_op.add_column(sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True))
                batch_op.create_index('ix_background_tasks_lease_expires_at', ['lease_expires_at'], unique=False)
            if 'heartbeat_at' not in existing_cols:
                batch_op.add_column(sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True))
            if 'cancel_requested' not in existing_cols:
                batch_op.add_column(sa.Column('cancel_requested', sa.Boolean(), nullable=False, server_default=sa.text('0')))

    # 2. Update scheduled_task_runs with scheduled_for and occurrence index
    if insp.has_table('scheduled_task_runs'):
        existing_run_cols = [c['name'] for c in insp.get_columns('scheduled_task_runs')]
        with op.batch_alter_table('scheduled_task_runs', schema=None) as batch_op:
            if 'scheduled_for' not in existing_run_cols:
                batch_op.add_column(sa.Column('scheduled_for', sa.DateTime(timezone=True), nullable=True))
                batch_op.create_index('ix_scheduled_task_runs_scheduled_for', ['scheduled_for'], unique=False)
                batch_op.create_index('ix_scheduled_task_runs_task_occurrence', ['task_id', 'scheduled_for'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('scheduled_task_runs', schema=None) as batch_op:
        batch_op.drop_index('ix_scheduled_task_runs_task_occurrence')
        batch_op.drop_index('ix_scheduled_task_runs_scheduled_for')
        batch_op.drop_column('scheduled_for')

    with op.batch_alter_table('background_tasks', schema=None) as batch_op:
        batch_op.drop_column('cancel_requested')
        batch_op.drop_column('heartbeat_at')
        batch_op.drop_index('ix_background_tasks_lease_expires_at')
        batch_op.drop_column('lease_expires_at')
