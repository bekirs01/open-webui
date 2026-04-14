"""merge dual heads scim and memory folder

Revision ID: 253d22966a8c
Revises: b2c3d4e5f6a7, h8i9j0k1l2m3
Create Date: 2026-04-15 04:22:32.835613

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import open_webui.internal.db


# revision identifiers, used by Alembic.
revision: str = '253d22966a8c'
down_revision: Union[str, None] = ('b2c3d4e5f6a7', 'h8i9j0k1l2m3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
