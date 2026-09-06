import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.deposits.models import DepositProvider, DepositStatus


class StripeDepositCreate(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: str = Field(default="usd", min_length=3, max_length=3)
    idempotency_key: str | None = Field(default=None, max_length=255)


class StripeDepositResponse(BaseModel):
    client_secret: str
    deposit_id: uuid.UUID


class MpesaDepositCreate(BaseModel):
    phone_number: str = Field(description="Kenyan mobile number, any common format")
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    idempotency_key: str | None = Field(default=None, max_length=255)


class MpesaDepositResponse(BaseModel):
    deposit_id: uuid.UUID
    message: str = "STK push sent — check your phone to enter your M-Pesa PIN"


class DepositResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: DepositProvider
    status: DepositStatus
    amount: Decimal
    currency: str
    failure_reason: str | None
    created_at: datetime
    completed_at: datetime | None


class DepositListResponse(BaseModel):
    items: list[DepositResponse]
    total: int
    page: int
    page_size: int
