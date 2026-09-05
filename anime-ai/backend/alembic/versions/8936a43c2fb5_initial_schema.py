"""initial_schema

Revision ID: 8936a43c2fb5
Revises: 
Create Date: 2026-09-05 01:39:51.596197

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8936a43c2fb5'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_baseline_tables(insp) -> None:
    if not insp.has_table('users'):
        op.create_table(
            'users',
            sa.Column('id', sa.UUID(), primary_key=True),
            sa.Column('username', sa.String(100), unique=True, nullable=False),
            sa.Column('hashed_password', sa.String(255), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index('ix_users_username', 'users', ['username'], unique=True)

    if not insp.has_table('characters'):
        op.create_table(
            'characters',
            sa.Column('id', sa.String(50), primary_key=True),
            sa.Column('name', sa.String(100), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('config', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if not insp.has_table('conversations'):
        op.create_table(
            'conversations',
            sa.Column('id', sa.UUID(), primary_key=True),
            sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('character_id', sa.String(50), default='sakura'),
            sa.Column('title', sa.String(200), default='New Thread'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index('ix_conversations_user_id', 'conversations', ['user_id'], unique=False)

    if not insp.has_table('messages'):
        op.create_table(
            'messages',
            sa.Column('id', sa.UUID(), primary_key=True),
            sa.Column('conversation_id', sa.UUID(), sa.ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False),
            sa.Column('sender', sa.String(50), nullable=False),
            sa.Column('text', sa.Text(), nullable=False),
            sa.Column('media_url', sa.String(500), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index('ix_messages_conversation_id', 'messages', ['conversation_id'], unique=False)

    if not insp.has_table('memories'):
        op.create_table(
            'memories',
            sa.Column('id', sa.UUID(), primary_key=True),
            sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('memory_type', sa.String(50), default='preference'),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('confidence', sa.Float(), default=1.0),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index('ix_memories_user_id', 'memories', ['user_id'], unique=False)

    if not insp.has_table('documents'):
        op.create_table(
            'documents',
            sa.Column('id', sa.UUID(), primary_key=True),
            sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('filename', sa.String(255), nullable=False),
            sa.Column('mime_type', sa.String(100), nullable=False),
            sa.Column('storage_path', sa.String(510), nullable=False),
            sa.Column('metadata', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index('ix_documents_user_id', 'documents', ['user_id'], unique=False)

    if not insp.has_table('document_chunks'):
        op.create_table(
            'document_chunks',
            sa.Column('id', sa.UUID(), primary_key=True),
            sa.Column('document_id', sa.UUID(), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
            sa.Column('chunk_index', sa.Integer(), nullable=False),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('embedding', sa.JSON(), nullable=True),
            sa.Column('metadata', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index('ix_document_chunks_document_id', 'document_chunks', ['document_id'], unique=False)

    if not insp.has_table('projects'):
        op.create_table(
            'projects',
            sa.Column('id', sa.UUID(), primary_key=True),
            sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('name', sa.String(150), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index('ix_projects_user_id', 'projects', ['user_id'], unique=False)

    if not insp.has_table('project_repositories'):
        op.create_table(
            'project_repositories',
            sa.Column('id', sa.UUID(), primary_key=True),
            sa.Column('project_id', sa.UUID(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
            sa.Column('repo_url', sa.String(500), nullable=False),
            sa.Column('repo_name', sa.String(150), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index('ix_project_repositories_project_id', 'project_repositories', ['project_id'], unique=False)

    if not insp.has_table('project_conversations'):
        op.create_table(
            'project_conversations',
            sa.Column('id', sa.UUID(), primary_key=True),
            sa.Column('project_id', sa.UUID(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
            sa.Column('conversation_id', sa.UUID(), sa.ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index('ix_project_conversations_project_id', 'project_conversations', ['project_id'], unique=False)
        op.create_index('ix_project_conversations_conversation_id', 'project_conversations', ['conversation_id'], unique=False)

    if not insp.has_table('scheduled_tasks'):
        op.create_table(
            'scheduled_tasks',
            sa.Column('id', sa.UUID(), primary_key=True),
            sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('title', sa.String(200), nullable=False),
            sa.Column('prompt', sa.Text(), nullable=False),
            sa.Column('schedule', sa.String(100), nullable=False),
            sa.Column('timezone', sa.String(50), default='UTC'),
            sa.Column('enabled', sa.Boolean(), default=True),
            sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('metadata', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index('ix_scheduled_tasks_user_id', 'scheduled_tasks', ['user_id'], unique=False)

    if not insp.has_table('scheduled_task_runs'):
        op.create_table(
            'scheduled_task_runs',
            sa.Column('id', sa.UUID(), primary_key=True),
            sa.Column('task_id', sa.UUID(), sa.ForeignKey('scheduled_tasks.id', ondelete='CASCADE'), nullable=False),
            sa.Column('status', sa.String(50), default='RUNNING'),
            sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('error', sa.Text(), nullable=True),
            sa.Column('output', sa.Text(), nullable=True),
            sa.Column('duration_ms', sa.Integer(), default=0),
        )
        op.create_index('ix_scheduled_task_runs_task_id', 'scheduled_task_runs', ['task_id'], unique=False)

    if not insp.has_table('user_integrations'):
        op.create_table(
            'user_integrations',
            sa.Column('id', sa.UUID(), primary_key=True),
            sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('provider', sa.String(50), nullable=False),
            sa.Column('account_name', sa.String(150), nullable=True),
            sa.Column('connected', sa.Boolean(), default=False),
            sa.Column('config', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index('ix_user_integrations_user_id', 'user_integrations', ['user_id'], unique=False)

    if not insp.has_table('repository_workspaces'):
        op.create_table(
            'repository_workspaces',
            sa.Column('id', sa.UUID(), primary_key=True),
            sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('name', sa.String(150), nullable=False),
            sa.Column('repository_url', sa.String(500), nullable=True),
            sa.Column('workspace_path', sa.String(500), nullable=False),
            sa.Column('active_branch', sa.String(100), default='main'),
            sa.Column('base_commit', sa.String(64), nullable=True),
            sa.Column('status', sa.String(50), default='READY'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index('ix_repository_workspaces_user_id', 'repository_workspaces', ['user_id'], unique=False)

    if not insp.has_table('coding_tasks'):
        op.create_table(
            'coding_tasks',
            sa.Column('id', sa.UUID(), primary_key=True),
            sa.Column('workspace_id', sa.UUID(), sa.ForeignKey('repository_workspaces.id', ondelete='CASCADE'), nullable=False),
            sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('title', sa.String(255), nullable=False),
            sa.Column('objective', sa.Text(), nullable=False),
            sa.Column('status', sa.String(50), default='QUEUED'),
            sa.Column('files_modified', sa.JSON(), nullable=True),
            sa.Column('verification_summary', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index('ix_coding_tasks_workspace_id', 'coding_tasks', ['workspace_id'], unique=False)
        op.create_index('ix_coding_tasks_user_id', 'coding_tasks', ['user_id'], unique=False)

    if not insp.has_table('tool_executions'):
        op.create_table(
            'tool_executions',
            sa.Column('id', sa.UUID(), primary_key=True),
            sa.Column('coding_task_id', sa.UUID(), sa.ForeignKey('coding_tasks.id', ondelete='CASCADE'), nullable=False),
            sa.Column('tool_name', sa.String(100), nullable=False),
            sa.Column('arguments', sa.JSON(), nullable=True),
            sa.Column('status', sa.String(50), default='SUCCESS'),
            sa.Column('stdout_preview', sa.Text(), nullable=True),
            sa.Column('stderr_preview', sa.Text(), nullable=True),
            sa.Column('exit_code', sa.Integer(), nullable=True),
            sa.Column('duration_ms', sa.Integer(), default=0),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index('ix_tool_executions_coding_task_id', 'tool_executions', ['coding_task_id'], unique=False)

    if not insp.has_table('conversation_shares'):
        op.create_table(
            'conversation_shares',
            sa.Column('id', sa.UUID(), primary_key=True),
            sa.Column('conversation_id', sa.UUID(), sa.ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False),
            sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('token', sa.String(100), unique=True, nullable=False),
            sa.Column('is_active', sa.Boolean(), default=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index('ix_conversation_shares_conversation_id', 'conversation_shares', ['conversation_id'], unique=False)
        op.create_index('ix_conversation_shares_user_id', 'conversation_shares', ['user_id'], unique=False)
        op.create_index('ix_conversation_shares_token', 'conversation_shares', ['token'], unique=True)

    if not insp.has_table('generated_images'):
        op.create_table(
            'generated_images',
            sa.Column('id', sa.UUID(), primary_key=True),
            sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('conversation_id', sa.UUID(), sa.ForeignKey('conversations.id', ondelete='CASCADE'), nullable=True),
            sa.Column('document_id', sa.UUID(), sa.ForeignKey('documents.id', ondelete='SET NULL'), nullable=True),
            sa.Column('parent_image_id', sa.UUID(), nullable=True),
            sa.Column('prompt', sa.Text(), nullable=False),
            sa.Column('negative_prompt', sa.Text(), nullable=True),
            sa.Column('pipeline', sa.String(50), default='ANIME'),
            sa.Column('style', sa.String(50), default='shinkai'),
            sa.Column('aspect_ratio', sa.String(20), default='1:1'),
            sa.Column('width', sa.Integer(), default=1024),
            sa.Column('height', sa.Integer(), default=1024),
            sa.Column('seed', sa.BigInteger(), nullable=True),
            sa.Column('model_used', sa.String(100), nullable=True),
            sa.Column('generation_time_ms', sa.Integer(), default=0),
            sa.Column('storage_path', sa.String(510), nullable=False),
            sa.Column('filename', sa.String(255), nullable=False),
            sa.Column('mime_type', sa.String(50), default='image/png'),
            sa.Column('file_size', sa.Integer(), default=0),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index('ix_generated_images_conversation_id', 'generated_images', ['conversation_id'], unique=False)
        op.create_index('ix_generated_images_user_id', 'generated_images', ['user_id'], unique=False)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table('users'):
        _create_baseline_tables(insp)
        return

    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('coding_tasks', schema=None) as batch_op:
        batch_op.alter_column('id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.alter_column('workspace_id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.alter_column('user_id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)

    with op.batch_alter_table('conversation_shares', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_active', sa.Boolean(), nullable=True))
        batch_op.alter_column('id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.alter_column('conversation_id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.alter_column('user_id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)

    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.alter_column('id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.alter_column('user_id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.create_index(batch_op.f('ix_conversations_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('document_chunks', schema=None) as batch_op:
        batch_op.alter_column('id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.alter_column('document_id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.alter_column('embedding',
               existing_type=sa.NUMERIC(precision=1536),
               type_=sa.JSON(none_as_null=1536),
               existing_nullable=True)
        batch_op.create_index(batch_op.f('ix_document_chunks_document_id'), ['document_id'], unique=False)

    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.alter_column('id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.alter_column('user_id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.create_index(batch_op.f('ix_documents_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('generated_images', schema=None) as batch_op:
        batch_op.alter_column('id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.alter_column('user_id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.alter_column('conversation_id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=True)
        batch_op.alter_column('document_id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=True)
        batch_op.alter_column('parent_image_id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=True)
        batch_op.create_index(batch_op.f('ix_generated_images_conversation_id'), ['conversation_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_generated_images_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('message_feedbacks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('comment', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('category', sa.String(length=100), nullable=True))
        batch_op.alter_column('id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.alter_column('message_id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.alter_column('user_id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.alter_column('rating',
               existing_type=sa.INTEGER(),
               type_=sa.String(length=50),
               existing_nullable=False)

    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.alter_column('id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.alter_column('conversation_id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.create_index(batch_op.f('ix_messages_conversation_id'), ['conversation_id'], unique=False)

    with op.batch_alter_table('project_conversations', schema=None) as batch_op:
        batch_op.alter_column('id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.alter_column('project_id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.alter_column('conversation_id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)

    with op.batch_alter_table('project_files', schema=None) as batch_op:
        batch_op.alter_column('id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.alter_column('project_id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.alter_column('document_id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)

    with op.batch_alter_table('project_repositories', schema=None) as batch_op:
        batch_op.alter_column('id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.alter_column('project_id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)

    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.alter_column('id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.alter_column('user_id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)

    with op.batch_alter_table('repository_workspaces', schema=None) as batch_op:
        batch_op.alter_column('id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.alter_column('user_id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)

    with op.batch_alter_table('scheduled_task_runs', schema=None) as batch_op:
        batch_op.alter_column('id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.alter_column('task_id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)

    with op.batch_alter_table('scheduled_tasks', schema=None) as batch_op:
        batch_op.alter_column('id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.alter_column('user_id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)

    with op.batch_alter_table('tool_executions', schema=None) as batch_op:
        batch_op.alter_column('id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.alter_column('coding_task_id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)

    with op.batch_alter_table('user_integrations', schema=None) as batch_op:
        batch_op.alter_column('id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.alter_column('user_id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)

    with op.batch_alter_table('user_memories', schema=None) as batch_op:
        batch_op.alter_column('id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.alter_column('user_id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)
        batch_op.create_index(batch_op.f('ix_user_memories_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('id',
               existing_type=sa.NUMERIC(),
               type_=sa.UUID(),
               existing_nullable=False)

    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema to empty base."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = [
        'scheduled_task_runs', 'scheduled_tasks', 'tool_executions',
        'coding_tasks', 'repository_workspaces', 'project_conversations',
        'project_repositories', 'projects', 'document_chunks',
        'documents', 'memories', 'user_memories', 'user_integrations',
        'messages', 'conversations', 'characters', 'users'
    ]
    for t in tables:
        if insp.has_table(t):
            op.drop_table(t)
