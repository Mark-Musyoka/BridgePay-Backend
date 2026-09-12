"""add currency conversion columns to deposits and payouts

Revision ID: a876b09fb223
Revises: 647324fe3116
Create Date: 2026-09-12 10:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a876b09fb223'
down_revision: Union[str, None] = '647324fe3116'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('deposits', sa.Column('exchange_rate', sa.Numeric(precision=18, scale=8), nullable=True))
    op.add_column('deposits', sa.Column('converted_amount', sa.Numeric(precision=18, scale=2), nullable=True))
    op.add_column('payouts', sa.Column('exchange_rate', sa.Numeric(precision=18, scale=8), nullable=True))
    op.add_column('payouts', sa.Column('converted_amount', sa.Numeric(precision=18, scale=2), nullable=True))


def downgrade() -> None:
    op.drop_column('payouts', 'converted_amount')
    op.drop_column('payouts', 'exchange_rate')
    op.drop_column('deposits', 'converted_amount')
    op.drop_column('deposits', 'exchange_rate')
