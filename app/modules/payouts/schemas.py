import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.modules.payouts.models import PayoutProvider, PayoutStatus


class MpesaPayoutCreate(BaseModel):
    phone_number: str = Field(description="Recipient's Kenyan mobile number, any common format")
    recipient_email: EmailStr = Field(description="Required for confirmation, regardless of destination type")
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    idempotency_key: str | None = Field(default=None, max_length=255)


class StripeCardPayoutCreate(BaseModel):
    card_token: str = Field(
        description=(
            "A Stripe card token (tok_...), NOT a raw card number. The "
            "frontend must tokenize the recipient's card via Stripe.js/"
            "Elements before it ever reaches this backend — raw card "
            "numbers are never accepted here, for the same PCI-compliance "
            "reason Stripe itself requires this for any integration."
        )
    )
    recipient_email: EmailStr
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: str = Field(default="usd", min_length=3, max_length=3)
    idempotency_key: str | None = Field(default=None, max_length=255)


class PayoutResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: PayoutProvider
    status: PayoutStatus
    recipient_email: str
    amount: Decimal
    currency: str
    failure_reason: str | None
    created_at: datetime
    completed_at: datetime | None


class PayoutListResponse(BaseModel):
    items: list[PayoutResponse]
    total: int
    page: int
    page_size: int
