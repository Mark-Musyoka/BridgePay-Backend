"""add airtel to deposit_provider and payout_provider enums

Revision ID: 80c1f211d9e4
Revises: a876b09fb223
Create Date: 2026-09-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '80c1f211d9e4'
down_revision: Union[str, None] = 'a876b09fb223'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Postgres 12+ allows ALTER TYPE ... ADD VALUE inside a transaction,
    # as long as the new value isn't also used within that same
    # transaction — this migration only adds it, so that's fine.
    op.execute("ALTER TYPE deposit_provider ADD VALUE IF NOT EXISTS 'airtel'")
    op.execute("ALTER TYPE payout_provider ADD VALUE IF NOT EXISTS 'airtel'")


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE — removing a value means
    # recreating the type without it. This fails loudly (by design) if
    # any row still has provider = 'airtel', since there's no value to
    # cast those rows to; such rows would need to be dealt with before
    # this downgrade could run.
    op.execute("ALTER TYPE deposit_provider RENAME TO deposit_provider_old")
    op.execute("CREATE TYPE deposit_provider AS ENUM ('stripe', 'mpesa')")
    op.execute(
        "ALTER TABLE deposits ALTER COLUMN provider TYPE deposit_provider "
        "USING provider::text::deposit_provider"
    )
    op.execute("DROP TYPE deposit_provider_old")

    op.execute("ALTER TYPE payout_provider RENAME TO payout_provider_old")
    op.execute("CREATE TYPE payout_provider AS ENUM ('mpesa', 'stripe')")
    op.execute(
        "ALTER TABLE payouts ALTER COLUMN provider TYPE payout_provider "
        "USING provider::text::payout_provider"
    )
    op.execute("DROP TYPE payout_provider_old")
