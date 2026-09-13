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


class AirtelPayoutCreate(BaseModel):
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


class BankAccountPayoutCreate(BaseModel):
    """
    Like the card flow, the bank account token must be created
    client-side (Stripe.js) before reaching this backend — raw account
    numbers, IBANs, bank codes, and SWIFT/BIC are never accepted here,
    same PCI-adjacent reasoning as StripeCardPayoutCreate. Stripe.js's
    tokenization already handles the field differences between a
    Kenyan local account (account number + bank code) and an
    international one (IBAN + SWIFT/BIC) — this backend never sees
    those raw fields at all.

    `country` isn't sent to Stripe (it's already baked into the token)
    — it's validated against our own ISO 3166-1 list and included in
    the confirmation notification, since a Kenyan bank payout and a US
    one carry different real-world settlement expectations worth
    surfacing to the user. Kept as its own schema rather than folded
    into StripeCardPayoutCreate because a bank payout and a card payout
    are different destination kinds with different context, per
    PLAN.md's own note that this needed its own schema.
    """

    bank_account_token: str = Field(
        description="A Stripe bank account token (btok_...), created client-side via Stripe.js — never a raw account number, IBAN, bank code, or SWIFT/BIC."
    )
    country: str = Field(min_length=2, max_length=2, description="ISO 3166-1 alpha-2, e.g. 'KE', 'US', 'GB'")
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
