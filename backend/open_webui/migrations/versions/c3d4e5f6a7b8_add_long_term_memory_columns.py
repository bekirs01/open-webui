"""Add long-term memory columns to memory table

Revision ID: c3d4e5f6a7b8
Revises: 018012973d35
Create Date: 2026-04-12

"""

from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a7b8'
down_revision = '018012973d35'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('memory', sa.Column('chat_id', sa.Text(), nullable=True))
    op.add_column('memory', sa.Column('category', sa.Text(), nullable=True))
    op.add_column('memory', sa.Column('normalized_content', sa.Text(), nullable=True))
    op.add_column('memory', sa.Column('source_excerpt', sa.Text(), nullable=True))
    op.add_column('memory', sa.Column('confidence_score', sa.Float(), nullable=True))
    op.add_column('memory', sa.Column('importance_score', sa.Float(), nullable=True))
    op.add_column('memory', sa.Column('last_accessed_at', sa.BigInteger(), nullable=True))
    op.add_column('memory', sa.Column('access_count', sa.BigInteger(), nullable=True))
    op.add_column('memory', sa.Column('status', sa.Text(), nullable=True))
    op.add_column('memory', sa.Column('source_type', sa.Text(), nullable=True))
    op.add_column('memory', sa.Column('ltm_extra', sa.Text(), nullable=True))

    op.execute("UPDATE memory SET status = 'active' WHERE status IS NULL")
    op.execute("UPDATE memory SET access_count = 0 WHERE access_count IS NULL")
    op.execute("UPDATE memory SET category = 'custom' WHERE category IS NULL")
    op.execute("UPDATE memory SET source_type = 'manual' WHERE source_type IS NULL")


def downgrade():
    op.drop_column('memory', 'ltm_extra')
    op.drop_column('memory', 'source_type')
    op.drop_column('memory', 'status')
    op.drop_column('memory', 'access_count')
    op.drop_column('memory', 'last_accessed_at')
    op.drop_column('memory', 'importance_score')
    op.drop_column('memory', 'confidence_score')
    op.drop_column('memory', 'source_excerpt')
    op.drop_column('memory', 'normalized_content')
    op.drop_column('memory', 'category')
    op.drop_column('memory', 'chat_id')
