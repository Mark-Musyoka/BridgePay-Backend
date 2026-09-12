import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PayoutProvider(str, enum.Enum):
    mpesa = "mpesa"
    stripe = "stripe"


class PayoutStatus(str, enum.Enum):
    pending = "pending"
    completed = "completed"
    failed = "failed"
    reversed = "reversed"


class Payout(Base):
    """
    A real external payout — money leaving BridgePay entirely, to a
    non-BridgePay phone (M-Pesa B2C) or card (Stripe). Unlike deposits,
    the sender's balance is deducted UP FRONT, before the external API
    call, because the money must be reserved the instant we commit to
    sending it — see app/modules/payouts/service.py for exactly why and
    how a failure after that point gets reversed.

    recipient_email is always required (per product decision) purely for
    confirmation/notification purposes — it plays no role in actually
    routing the money, which goes to destination_reference alone.
    """
    __tablename__ = "payouts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    provider: Mapped[PayoutProvider] = mapped_column(Enum(PayoutProvider, name="payout_provider"), nullable=False)
    status: Mapped[PayoutStatus] = mapped_column(
        Enum(PayoutStatus, name="payout_status"), default=PayoutStatus.pending, nullable=False
    )
    # M-Pesa: the normalized recipient phone number. Stripe: the card
    # token/PaymentMethod id used as the payout destination. Never a raw
    # card or account number — see service.py's docstring.
    destination_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # Populated only when currency differs from the source account's
    # currency (see _deduct_balance_and_record in service.py). exchange_rate
    # is units of account currency per unit of `currency`; converted_amount
    # is amount * exchange_rate, i.e. what actually gets deducted from (and,
    # on reversal, credited back to) the account, and recorded on the
    # Transaction. Both stay NULL for a payout made directly in the
    # account's own currency — nothing was converted.
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    converted_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    # M-Pesa: ConversationID from the B2C request. Stripe: Payout id
    # (po_...). How an async result/webhook finds its way back here.
    external_reference: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
