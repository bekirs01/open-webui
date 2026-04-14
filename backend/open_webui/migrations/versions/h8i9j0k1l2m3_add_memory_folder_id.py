"""Add folder_id to memory for folder-scoped shared LTM

Revision ID: h8i9j0k1l2m3
Revises: f5a6b7c8d9e0
Create Date: 2026-04-13

"""

from alembic import op
import sqlalchemy as sa

revision = 'h8i9j0k1l2m3'
down_revision = 'f5a6b7c8d9e0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('memory', sa.Column('folder_id', sa.Text(), nullable=True))
    op.create_index('memory_folder_id_idx', 'memory', ['folder_id'])


def downgrade():
    op.drop_index('memory_folder_id_idx', table_name='memory')
    op.drop_column('memory', 'folder_id')
