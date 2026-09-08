"""index_generation_and_network_authorizations

Revision ID: f5b3c829d12e
Revises: e4a2b918f01c
Create Date: 2026-09-08 01:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f5b3c829d12e'
down_revision: Union[str, Sequence[str], None] = 'e4a2b918f01c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 1. documents table: index_generation
    if insp.has_table('documents'):
        cols = [c['name'] for c in insp.get_columns('documents')]
        with op.batch_alter_table('documents', schema=None) as batch_op:
            if 'index_generation' not in cols:
                batch_op.add_column(sa.Column('index_generation', sa.Integer(), nullable=False, server_default='0'))

    # 2. sandbox_network_authorizations table
    if not insp.has_table('sandbox_network_authorizations'):
        op.create_table(
            'sandbox_network_authorizations',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('user_id', sa.UUID(), nullable=False),
            sa.Column('workspace_id', sa.UUID(), nullable=False),
            sa.Column('command_hash', sa.String(length=64), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['workspace_id'], ['repository_workspaces.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_sandbox_network_authorizations_user_id', 'sandbox_network_authorizations', ['user_id'], unique=False)
        op.create_index('ix_sandbox_network_authorizations_workspace_id', 'sandbox_network_authorizations', ['workspace_id'], unique=False)
        op.create_index('ix_sandbox_network_authorizations_command_hash', 'sandbox_network_authorizations', ['command_hash'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table('sandbox_network_authorizations'):
        op.drop_table('sandbox_network_authorizations')

    if insp.has_table('documents'):
        with op.batch_alter_table('documents', schema=None) as batch_op:
            batch_op.drop_column('index_generation')
