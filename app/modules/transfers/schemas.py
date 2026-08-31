from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field


class TransferCreate(BaseModel):
    to_email: EmailStr
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    reference_note: str | None = Field(default=None, max_length=255)
