"""storage_durability_and_worker_fencing

Revision ID: e4a2b918f01c
Revises: c3e1a89f4b20
Create Date: 2026-09-08 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e4a2b918f01c'
down_revision: Union[str, Sequence[str], None] = 'c3e1a89f4b20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 1. documents table: storage_backend, storage_key, storage_size
    if insp.has_table('documents'):
        cols = [c['name'] for c in insp.get_columns('documents')]
        with op.batch_alter_table('documents', schema=None) as batch_op:
            if 'storage_backend' not in cols:
                batch_op.add_column(sa.Column('storage_backend', sa.String(50), nullable=False, server_default='local'))
            if 'storage_key' not in cols:
                batch_op.add_column(sa.Column('storage_key', sa.String(510), nullable=True))
            if 'storage_size' not in cols:
                batch_op.add_column(sa.Column('storage_size', sa.Integer(), nullable=True))

        # Create index on storage_key if table has column and index missing
        existing_indices = [idx['name'] for idx in insp.get_indexes('documents')]
        if 'ix_documents_storage_key' not in existing_indices:
            op.create_index('ix_documents_storage_key', 'documents', ['storage_key'], unique=False)

    # 2. generated_images table: storage_backend, storage_key, storage_size
    if insp.has_table('generated_images'):
        cols = [c['name'] for c in insp.get_columns('generated_images')]
        with op.batch_alter_table('generated_images', schema=None) as batch_op:
            if 'storage_backend' not in cols:
                batch_op.add_column(sa.Column('storage_backend', sa.String(50), nullable=False, server_default='local'))
            if 'storage_key' not in cols:
                batch_op.add_column(sa.Column('storage_key', sa.String(510), nullable=True))
            if 'storage_size' not in cols:
                batch_op.add_column(sa.Column('storage_size', sa.Integer(), nullable=True))

        existing_indices = [idx['name'] for idx in insp.get_indexes('generated_images')]
        if 'ix_generated_images_storage_key' not in existing_indices:
            op.create_index('ix_generated_images_storage_key', 'generated_images', ['storage_key'], unique=False)

    # 3. background_tasks table: execution_attempt_id (UUID fencing token)
    if insp.has_table('background_tasks'):
        cols = [c['name'] for c in insp.get_columns('background_tasks')]
        with op.batch_alter_table('background_tasks', schema=None) as batch_op:
            if 'execution_attempt_id' not in cols:
                batch_op.add_column(sa.Column('execution_attempt_id', sa.UUID(), nullable=True))

        existing_indices = [idx['name'] for idx in insp.get_indexes('background_tasks')]
        if 'ix_background_tasks_execution_attempt_id' not in existing_indices:
            op.create_index('ix_background_tasks_execution_attempt_id', 'background_tasks', ['execution_attempt_id'], unique=False)

    # 4. Data Backfill: authoritative Knowledge Base state and storage keys
    # Backfill is_knowledge_base = True where metadata JSON has is_knowledge_base=true or chunks > 0
    try:
        is_postgres = bind.dialect.name == 'postgresql'
        if is_postgres:
            # PostgreSQL json/jsonb query
            bind.execute(sa.text("""
                UPDATE documents
                SET is_knowledge_base = true,
                    indexing_status = 'READY'
                WHERE (
                    metadata->>'is_knowledge_base' = 'true'
                    OR (metadata->>'chunks')::int > 0
                )
                AND is_knowledge_base = false
            """))
            # Populate storage_key if null using storage_path or filename
            bind.execute(sa.text("""
                UPDATE documents
                SET storage_key = 'users/' || user_id || '/documents/' || id || '/' || filename
                WHERE storage_key IS NULL
            """))
        else:
            # SQLite / generic query
            bind.execute(sa.text("""
                UPDATE documents
                SET is_knowledge_base = 1,
                    indexing_status = 'READY'
                WHERE (
                    metadata LIKE '%"is_knowledge_base": true%'
                    OR metadata LIKE '%"is_knowledge_base":true%'
                )
                AND (is_knowledge_base = 0 OR is_knowledge_base IS NULL)
            """))
            bind.execute(sa.text("""
                UPDATE documents
                SET storage_key = 'users/' || user_id || '/documents/' || id || '/' || filename
                WHERE storage_key IS NULL
            """))
    except Exception as e:
        # Non-fatal backfill in environments without documents
        pass


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table('background_tasks'):
        existing_indices = [idx['name'] for idx in insp.get_indexes('background_tasks')]
        if 'ix_background_tasks_execution_attempt_id' in existing_indices:
            op.drop_index('ix_background_tasks_execution_attempt_id', table_name='background_tasks')
        with op.batch_alter_table('background_tasks', schema=None) as batch_op:
            batch_op.drop_column('execution_attempt_id')

    if insp.has_table('generated_images'):
        existing_indices = [idx['name'] for idx in insp.get_indexes('generated_images')]
        if 'ix_generated_images_storage_key' in existing_indices:
            op.drop_index('ix_generated_images_storage_key', table_name='generated_images')
        with op.batch_alter_table('generated_images', schema=None) as batch_op:
            batch_op.drop_column('storage_size')
            batch_op.drop_column('storage_key')
            batch_op.drop_column('storage_backend')

    if insp.has_table('documents'):
        existing_indices = [idx['name'] for idx in insp.get_indexes('documents')]
        if 'ix_documents_storage_key' in existing_indices:
            op.drop_index('ix_documents_storage_key', table_name='documents')
        with op.batch_alter_table('documents', schema=None) as batch_op:
            batch_op.drop_column('storage_size')
            batch_op.drop_column('storage_key')
            batch_op.drop_column('storage_backend')
