import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.transaction import TransactionStatus, TransactionType


class TransferCreate(BaseModel):
    to_email: EmailStr
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    reference_note: str | None = Field(default=None, max_length=255)


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    from_account_id: uuid.UUID | None
    to_account_id: uuid.UUID | None
    amount: Decimal
    currency: str
    status: TransactionStatus
    type: TransactionType
    reference_note: str | None
    created_at: datetime


class TransactionListResponse(BaseModel):
    items: list[TransactionResponse]
    total: int
    page: int
    page_size: int
