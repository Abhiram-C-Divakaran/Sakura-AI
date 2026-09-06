"""schema_parity_and_occurrence_unique

Revision ID: c3e1a89f4b20
Revises: b1c4e72089fa
Create Date: 2026-09-06 20:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c3e1a89f4b20'
down_revision: Union[str, Sequence[str], None] = 'b1c4e72089fa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 1. user_memories (renamed from memories or created)
    if insp.has_table('memories') and not insp.has_table('user_memories'):
        op.rename_table('memories', 'user_memories')
        # Re-inspect to update index name if necessary
    elif not insp.has_table('user_memories'):
        op.create_table(
            'user_memories',
            sa.Column('id', sa.UUID(), primary_key=True),
            sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('memory_type', sa.String(50), nullable=False, server_default='preference'),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('confidence', sa.Float(), nullable=True, server_default='1.0'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index('ix_user_memories_user_id', 'user_memories', ['user_id'], unique=False)

    # 2. messages: role, content, metadata
    if insp.has_table('messages'):
        msg_cols = [c['name'] for c in insp.get_columns('messages')]
        with op.batch_alter_table('messages', schema=None) as batch_op:
            if 'sender' in msg_cols and 'role' not in msg_cols:
                batch_op.alter_column('sender', new_column_name='role', existing_type=sa.String(50), type_=sa.String(20), nullable=False)
            elif 'role' not in msg_cols:
                batch_op.add_column(sa.Column('role', sa.String(20), nullable=False, server_default='user'))

            if 'text' in msg_cols and 'content' not in msg_cols:
                batch_op.alter_column('text', new_column_name='content', existing_type=sa.Text(), nullable=False)
            elif 'content' not in msg_cols:
                batch_op.add_column(sa.Column('content', sa.Text(), nullable=False, server_default=''))

            if 'metadata' not in msg_cols:
                batch_op.add_column(sa.Column('metadata', sa.JSON(), nullable=True))

            if 'media_url' in msg_cols:
                batch_op.drop_column('media_url')

    # 3. project_repositories: name, repository_url, branch
    if insp.has_table('project_repositories'):
        pr_cols = [c['name'] for c in insp.get_columns('project_repositories')]
        with op.batch_alter_table('project_repositories', schema=None) as batch_op:
            if 'repo_name' in pr_cols and 'name' not in pr_cols:
                batch_op.alter_column('repo_name', new_column_name='name', existing_type=sa.String(150), nullable=False)
            elif 'name' not in pr_cols:
                batch_op.add_column(sa.Column('name', sa.String(150), nullable=False, server_default='repo'))

            if 'repo_url' in pr_cols and 'repository_url' not in pr_cols:
                batch_op.alter_column('repo_url', new_column_name='repository_url', existing_type=sa.String(500), nullable=False)
            elif 'repository_url' not in pr_cols:
                batch_op.add_column(sa.Column('repository_url', sa.String(500), nullable=False, server_default=''))

            if 'branch' not in pr_cols:
                batch_op.add_column(sa.Column('branch', sa.String(100), nullable=True, server_default='main'))

    # 4. conversations: pinned, pinned_at, archived_at
    if insp.has_table('conversations'):
        conv_cols = [c['name'] for c in insp.get_columns('conversations')]
        with op.batch_alter_table('conversations', schema=None) as batch_op:
            if 'pinned' not in conv_cols:
                batch_op.add_column(sa.Column('pinned', sa.Boolean(), nullable=True, server_default=sa.text('0')))
            if 'pinned_at' not in conv_cols:
                batch_op.add_column(sa.Column('pinned_at', sa.DateTime(timezone=True), nullable=True))
            if 'archived_at' not in conv_cols:
                batch_op.add_column(sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True))

    # 5. conversation_shares: share_token, is_active, expires_at, revoked_at
    if not insp.has_table('conversation_shares'):
        op.create_table(
            'conversation_shares',
            sa.Column('id', sa.UUID(), primary_key=True),
            sa.Column('conversation_id', sa.UUID(), sa.ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False),
            sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('share_token', sa.String(64), unique=True, nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=True, server_default=sa.text('1')),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index('ix_conversation_shares_conversation_id', 'conversation_shares', ['conversation_id'], unique=False)
        op.create_index('ix_conversation_shares_user_id', 'conversation_shares', ['user_id'], unique=False)
        op.create_index('ix_conversation_shares_share_token', 'conversation_shares', ['share_token'], unique=True)
    else:
        cs_cols = [c['name'] for c in insp.get_columns('conversation_shares')]
        with op.batch_alter_table('conversation_shares', schema=None) as batch_op:
            if 'token' in cs_cols and 'share_token' not in cs_cols:
                batch_op.alter_column('token', new_column_name='share_token', existing_type=sa.String(64), nullable=False)
            if 'is_active' not in cs_cols:
                batch_op.add_column(sa.Column('is_active', sa.Boolean(), nullable=True, server_default=sa.text('1')))
            if 'expires_at' not in cs_cols:
                batch_op.add_column(sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
            if 'revoked_at' not in cs_cols:
                batch_op.add_column(sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True))

    # 6. project_files table
    if not insp.has_table('project_files'):
        op.create_table(
            'project_files',
            sa.Column('id', sa.UUID(), primary_key=True),
            sa.Column('project_id', sa.UUID(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
            sa.Column('document_id', sa.UUID(), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index('ix_project_files_project_id', 'project_files', ['project_id'], unique=False)
        op.create_index('ix_project_files_document_id', 'project_files', ['document_id'], unique=False)

    # 7. message_feedbacks table
    if not insp.has_table('message_feedbacks'):
        op.create_table(
            'message_feedbacks',
            sa.Column('id', sa.UUID(), primary_key=True),
            sa.Column('message_id', sa.UUID(), sa.ForeignKey('messages.id', ondelete='CASCADE'), nullable=False),
            sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('rating', sa.String(50), nullable=False),
            sa.Column('reason', sa.String(255), nullable=True),
            sa.Column('comment', sa.Text(), nullable=True),
            sa.Column('category', sa.String(100), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index('ix_message_feedbacks_message_id', 'message_feedbacks', ['message_id'], unique=False)
        op.create_index('ix_message_feedbacks_user_id', 'message_feedbacks', ['user_id'], unique=False)
    else:
        mf_cols = [c['name'] for c in insp.get_columns('message_feedbacks')]
        with op.batch_alter_table('message_feedbacks', schema=None) as batch_op:
            if 'comment' not in mf_cols:
                batch_op.add_column(sa.Column('comment', sa.Text(), nullable=True))
            if 'category' not in mf_cols:
                batch_op.add_column(sa.Column('category', sa.String(100), nullable=True))

    # 8. projects: instructions, metadata
    if insp.has_table('projects'):
        proj_cols = [c['name'] for c in insp.get_columns('projects')]
        with op.batch_alter_table('projects', schema=None) as batch_op:
            if 'instructions' not in proj_cols:
                batch_op.add_column(sa.Column('instructions', sa.Text(), nullable=True, server_default=''))
            if 'metadata' not in proj_cols:
                batch_op.add_column(sa.Column('metadata', sa.JSON(), nullable=True))

    # 9. generated_images table and column parity
    if not insp.has_table('generated_images'):
        op.create_table(
            'generated_images',
            sa.Column('id', sa.UUID(), primary_key=True),
            sa.Column('user_id', sa.UUID(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('conversation_id', sa.UUID(), sa.ForeignKey('conversations.id', ondelete='SET NULL'), nullable=True),
            sa.Column('document_id', sa.UUID(), sa.ForeignKey('documents.id', ondelete='SET NULL'), nullable=True),
            sa.Column('prompt', sa.Text(), nullable=False),
            sa.Column('enhanced_prompt', sa.Text(), nullable=True),
            sa.Column('aspect_ratio', sa.String(20), nullable=True, server_default='1:1'),
            sa.Column('width', sa.Integer(), nullable=True, server_default='1024'),
            sa.Column('height', sa.Integer(), nullable=True, server_default='1024'),
            sa.Column('model', sa.String(100), nullable=True, server_default='flux-realism'),
            sa.Column('seed', sa.Integer(), nullable=True),
            sa.Column('workflow', sa.String(50), nullable=True, server_default='TEXT_TO_IMAGE'),
            sa.Column('parent_image_id', sa.UUID(), sa.ForeignKey('generated_images.id', ondelete='SET NULL'), nullable=True),
            sa.Column('lineage_depth', sa.Integer(), nullable=True, server_default='0'),
            sa.Column('storage_path', sa.String(510), nullable=False),
            sa.Column('image_url', sa.String(510), nullable=False),
            sa.Column('metadata', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index('ix_generated_images_user_id', 'generated_images', ['user_id'], unique=False)
        op.create_index('ix_generated_images_conversation_id', 'generated_images', ['conversation_id'], unique=False)
    else:
        gi_cols = [c['name'] for c in insp.get_columns('generated_images')]
        with op.batch_alter_table('generated_images', schema=None) as batch_op:
            if 'filename' in gi_cols:
                batch_op.alter_column('filename', existing_type=sa.String(255), nullable=True)
            if 'enhanced_prompt' not in gi_cols:
                batch_op.add_column(sa.Column('enhanced_prompt', sa.Text(), nullable=True))
            if 'model' not in gi_cols:
                batch_op.add_column(sa.Column('model', sa.String(100), nullable=True, server_default='flux-realism'))
            if 'workflow' not in gi_cols:
                batch_op.add_column(sa.Column('workflow', sa.String(50), nullable=True, server_default='TEXT_TO_IMAGE'))
            if 'lineage_depth' not in gi_cols:
                batch_op.add_column(sa.Column('lineage_depth', sa.Integer(), nullable=True, server_default='0'))
            if 'image_url' not in gi_cols:
                batch_op.add_column(sa.Column('image_url', sa.String(510), nullable=False, server_default=''))
            if 'metadata' not in gi_cols:
                batch_op.add_column(sa.Column('metadata', sa.JSON(), nullable=True))

    # 10. scheduled_task_runs: unique occurrence constraint
    if insp.has_table('scheduled_task_runs'):
        run_indices = [idx['name'] for idx in insp.get_indexes('scheduled_task_runs')]
        with op.batch_alter_table('scheduled_task_runs', schema=None) as batch_op:
            if 'ix_scheduled_task_runs_task_occurrence' in run_indices:
                batch_op.drop_index('ix_scheduled_task_runs_task_occurrence')
            batch_op.create_unique_constraint('uq_scheduled_task_run_occurrence', ['task_id', 'scheduled_for'])
            batch_op.create_index('ix_scheduled_task_runs_task_occurrence', ['task_id', 'scheduled_for'], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table('scheduled_task_runs'):
        with op.batch_alter_table('scheduled_task_runs', schema=None) as batch_op:
            batch_op.drop_index('ix_scheduled_task_runs_task_occurrence')
            batch_op.drop_constraint('uq_scheduled_task_run_occurrence', type_='unique')
            batch_op.create_index('ix_scheduled_task_runs_task_occurrence', ['task_id', 'scheduled_for'], unique=False)

    if insp.has_table('message_feedbacks'):
        op.drop_table('message_feedbacks')

    if insp.has_table('project_files'):
        op.drop_table('project_files')

    if insp.has_table('user_memories') and not insp.has_table('memories'):
        op.rename_table('user_memories', 'memories')
