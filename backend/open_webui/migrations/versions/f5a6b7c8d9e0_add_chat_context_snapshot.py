"""Add chat_context_snapshot and context_transfer for cross-chat continuity

Revision ID: f5a6b7c8d9e0
Revises: c3d4e5f6a7b8
Create Date: 2026-04-12

"""

from alembic import op
import sqlalchemy as sa

revision = 'f5a6b7c8d9e0'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'chat_context_snapshot',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('chat_id', sa.Text(), nullable=False),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('key_points', sa.Text(), nullable=True),
        sa.Column('preferences', sa.Text(), nullable=True),
        sa.Column('ongoing_tasks', sa.Text(), nullable=True),
        sa.Column('constraints', sa.Text(), nullable=True),
        sa.Column('created_at', sa.BigInteger(), nullable=False),
        sa.Column('updated_at', sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'chat_id', name='uq_snapshot_user_chat'),
    )
    op.create_index('ix_chat_context_snapshot_user_id', 'chat_context_snapshot', ['user_id'])
    op.create_index('ix_chat_context_snapshot_chat_id', 'chat_context_snapshot', ['chat_id'])

    op.create_table(
        'context_transfer',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('source_chat_id', sa.Text(), nullable=False),
        sa.Column('target_chat_id', sa.Text(), nullable=False),
        sa.Column('snapshot_id', sa.Text(), nullable=True),
        sa.Column('transfer_mode', sa.Text(), nullable=True),
        sa.Column('created_at', sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_context_transfer_user_id', 'context_transfer', ['user_id'])


def downgrade():
    op.drop_index('ix_context_transfer_user_id', table_name='context_transfer')
    op.drop_table('context_transfer')
    op.drop_index('ix_chat_context_snapshot_chat_id', table_name='chat_context_snapshot')
    op.drop_index('ix_chat_context_snapshot_user_id', table_name='chat_context_snapshot')
    op.drop_table('chat_context_snapshot')
