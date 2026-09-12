from pydantic import BaseModel


class WebhookAckResponse(BaseModel):
    """Generic ack for our own consumers (Stripe doesn't parse the
    response body — it only cares about the 2xx status code)."""

    received: bool = True


class DarajaAckResponse(BaseModel):
    """Daraja (M-Pesa) expects exactly this shape acknowledging receipt,
    regardless of what we did with the callback internally — it wants
    confirmation the callback arrived, not a description of our
    processing. ResultCode 0 means "accepted"; anything else and Daraja
    will retry the callback."""

    ResultCode: int = 0
    ResultDesc: str = "Accepted"


class AirtelAckResponse(BaseModel):
    """Airtel's callback ack — a simple success/message pair, distinct
    from Daraja's ResultCode/ResultDesc shape."""

    status: str = "success"
    message: str = "Callback received"
