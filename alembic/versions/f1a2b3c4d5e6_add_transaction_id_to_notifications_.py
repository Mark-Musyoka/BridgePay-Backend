"""add transaction_id to notifications and payouts

Revision ID: f1a2b3c4d5e6
Revises: 80c1f211d9e4
Create Date: 2026-10-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = '80c1f211d9e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable on both - most notifications genuinely have no related
    # transaction (security_alert, account_update, deposit_failed,
    # payout_failed), and existing rows obviously have nothing to
    # backfill this with. Lets the frontend deep-link a "money
    # received"/"payout sent" notification straight to its transaction.
    op.add_column('notifications', sa.Column('transaction_id', sa.UUID(), nullable=True))
    op.create_index(
        op.f('ix_notifications_transaction_id'), 'notifications', ['transaction_id'], unique=False
    )
    op.create_foreign_key(
        'fk_notifications_transaction_id_transactions',
        'notifications', 'transactions', ['transaction_id'], ['id'],
    )

    # On Payout, not just exposed via notify() calls: the "payout sent"
    # success notification fires from an async provider callback/webhook
    # that only has the Payout row to work with, not the original
    # request's local variables - this is how it finds its way back to
    # the withdrawal Transaction written at deduction time.
    op.add_column('payouts', sa.Column('transaction_id', sa.UUID(), nullable=True))
    op.create_index(
        op.f('ix_payouts_transaction_id'), 'payouts', ['transaction_id'], unique=False
    )
    op.create_foreign_key(
        'fk_payouts_transaction_id_transactions',
        'payouts', 'transactions', ['transaction_id'], ['id'],
    )


def downgrade() -> None:
    op.drop_constraint('fk_payouts_transaction_id_transactions', 'payouts', type_='foreignkey')
    op.drop_index(op.f('ix_payouts_transaction_id'), table_name='payouts')
    op.drop_column('payouts', 'transaction_id')

    op.drop_constraint('fk_notifications_transaction_id_transactions', 'notifications', type_='foreignkey')
    op.drop_index(op.f('ix_notifications_transaction_id'), table_name='notifications')
    op.drop_column('notifications', 'transaction_id')
