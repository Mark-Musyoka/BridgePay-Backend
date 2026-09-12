import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DepositProvider(str, enum.Enum):
    stripe = "stripe"
    mpesa = "mpesa"


class DepositStatus(str, enum.Enum):
    pending = "pending"
    completed = "completed"
    failed = "failed"


class Deposit(Base):
    """
    Tracks a deposit request from creation through the async gateway
    round-trip to completion. The account balance is ONLY ever credited
    when the corresponding webhook confirms success (see
    app/modules/deposits/service.py) — never optimistically at request
    time, since both Stripe and M-Pesa are asynchronous: the money isn't
    actually there yet when this row is first created.
    """
    __tablename__ = "deposits"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    provider: Mapped[DepositProvider] = mapped_column(Enum(DepositProvider, name="deposit_provider"), nullable=False)
    status: Mapped[DepositStatus] = mapped_column(
        Enum(DepositStatus, name="deposit_status"), default=DepositStatus.pending, nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # Populated only when currency differs from the destination account's
    # currency (see _credit_account_and_record in service.py). exchange_rate
    # is units of account currency per unit of `currency`; converted_amount
    # is amount * exchange_rate, i.e. what actually gets credited to the
    # account and recorded on the Transaction. Both stay NULL for a deposit
    # made directly in the account's own currency — nothing was converted.
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    converted_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    # Stripe: PaymentIntent id (pi_...). M-Pesa: CheckoutRequestID. This is
    # how the webhook, arriving with no other context, finds its way back
    # to this row.
    external_reference: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    # Client-supplied, optional. Prevents a network retry (e.g. a double
    # tap on "Deposit") from creating two separate gateway charges for
    # the same intended deposit — see get_or_create logic in service.py.
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
