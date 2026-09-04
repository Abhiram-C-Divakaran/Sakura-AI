"""durable_tasks_and_kb_isolation

Revision ID: 9a71bc9821ef
Revises: 8936a43c2fb5
Create Date: 2026-09-05 02:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '9a71bc9821ef'
down_revision: Union[str, Sequence[str], None] = '8936a43c2fb5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Update documents with knowledge base isolation columns
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_knowledge_base', sa.Boolean(), nullable=False, server_default=sa.text('0')))
        batch_op.add_column(sa.Column('indexing_status', sa.String(length=50), nullable=False, server_default='UPLOADED'))
        batch_op.create_index('ix_documents_is_knowledge_base', ['is_knowledge_base'], unique=False)
        batch_op.create_index('ix_documents_indexing_status', ['indexing_status'], unique=False)

    # 2. Create durable background_tasks table
    op.create_table(
        'background_tasks',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('type', sa.String(length=50), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='Queued'),
        sa.Column('progress', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('result', sa.Text(), nullable=True),
        sa.Column('result_metadata', sa.JSON(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('worker_id', sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_background_tasks_user_id', 'background_tasks', ['user_id'], unique=False)
    op.create_index('ix_background_tasks_type', 'background_tasks', ['type'], unique=False)
    op.create_index('ix_background_tasks_status', 'background_tasks', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_background_tasks_status', table_name='background_tasks')
    op.drop_index('ix_background_tasks_type', table_name='background_tasks')
    op.drop_index('ix_background_tasks_user_id', table_name='background_tasks')
    op.drop_table('background_tasks')

    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.drop_index('ix_documents_indexing_status')
        batch_op.drop_index('ix_documents_is_knowledge_base')
        batch_op.drop_column('indexing_status')
        batch_op.drop_column('is_knowledge_base')
