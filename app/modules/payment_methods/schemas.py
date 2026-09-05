import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.payment_methods.models import PaymentMethodProvider, PaymentMethodType


class PaymentMethodResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: PaymentMethodProvider
    type: PaymentMethodType
    masked_details: str
    is_default: bool
    created_at: datetime


class StripeSetupIntentResponse(BaseModel):
    client_secret: str


class StripeConfirmCardRequest(BaseModel):
    payment_method_id: str = Field(description="Stripe PaymentMethod id (pm_...) from the confirmed SetupIntent")
    set_as_default: bool = False


class LinkMpesaRequest(BaseModel):
    phone_number: str = Field(description="Kenyan mobile number, any common format")
    set_as_default: bool = False
