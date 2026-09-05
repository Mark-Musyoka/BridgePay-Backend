import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PaymentMethodProvider(str, enum.Enum):
    stripe = "stripe"
    mpesa = "mpesa"


class PaymentMethodType(str, enum.Enum):
    card = "card"
    mobile_wallet = "mobile_wallet"


class PaymentMethod(Base):
    """
    A linked way to move money in or out. For Stripe cards,
    external_reference is the Stripe PaymentMethod id (pm_...) — the
    actual card number is never touched or stored by this backend at
    all, Stripe holds it. For M-Pesa, there's no real "saved payment
    method" concept on Daraja's side — external_reference is just the
    normalized phone number itself, used directly at STK Push/B2C time.
    """
    __tablename__ = "payment_methods"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    provider: Mapped[PaymentMethodProvider] = mapped_column(
        Enum(PaymentMethodProvider, name="payment_method_provider"), nullable=False
    )
    type: Mapped[PaymentMethodType] = mapped_column(
        Enum(PaymentMethodType, name="payment_method_type"), nullable=False
    )
    external_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    # Display-only, e.g. "Visa •••• 4242" or "M-Pesa •••• 5678" — never a
    # full card/account number.
    masked_details: Mapped[str] = mapped_column(String(100), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
