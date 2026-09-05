"""
Shared M-Pesa Daraja API primitives: OAuth token fetching (with a simple
in-memory cache — Daraja tokens last ~1hr, no need to fetch one per
request), phone number normalization, and the STK Push password Daraja
requires. Used by both deposits (STK Push) and payouts (B2C).

Sandbox docs: https://developer.safaricom.co.ke/APIs
"""

import base64
import time
from datetime import datetime

import httpx

from app.core.config import settings

_BASE_URLS = {
    "sandbox": "https://sandbox.safaricom.co.ke",
    "production": "https://api.safaricom.co.ke",
}

# Simple process-local cache: {"token": str, "expires_at": float (epoch)}.
# Good enough for a single-instance deployment; a multi-instance one would
# want this in Redis instead (same reasoning as the rate limiter — see
# app/core/limiter.py).
_token_cache: dict = {}


def get_base_url() -> str:
    return _BASE_URLS.get(settings.MPESA_ENV, _BASE_URLS["sandbox"])


async def get_access_token() -> str:
    now = time.time()
    if _token_cache.get("token") and _token_cache.get("expires_at", 0) > now:
        return _token_cache["token"]

    credentials = f"{settings.MPESA_CONSUMER_KEY}:{settings.MPESA_CONSUMER_SECRET}"
    encoded = base64.b64encode(credentials.encode()).decode()

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{get_base_url()}/oauth/v1/generate",
            params={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {encoded}"},
            timeout=15.0,
        )
        response.raise_for_status()
        data = response.json()

    token = data["access_token"]
    expires_in = int(data.get("expires_in", 3599))
    # Refresh a minute early rather than exactly on expiry, to avoid a
    # request landing right as a cached token dies mid-flight.
    _token_cache["token"] = token
    _token_cache["expires_at"] = now + expires_in - 60
    return token


def generate_stk_password(timestamp: str) -> str:
    raw = f"{settings.MPESA_SHORTCODE}{settings.MPESA_PASSKEY}{timestamp}"
    return base64.b64encode(raw.encode()).decode()


def current_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


def normalize_kenyan_phone(phone: str) -> str:
    """
    Daraja requires the format 2547XXXXXXXX / 2541XXXXXXXX (no '+', no
    leading '0'). Accepts common input shapes and normalizes them:
    '0712345678', '+254712345678', '254712345678' -> '254712345678'.
    Raises ValueError for anything that doesn't look like a Kenyan
    mobile number after normalization.
    """
    digits = "".join(ch for ch in phone if ch.isdigit())

    if digits.startswith("0") and len(digits) == 10:
        digits = "254" + digits[1:]
    elif digits.startswith("254") and len(digits) == 12:
        pass
    elif len(digits) == 9:
        digits = "254" + digits

    if not (digits.startswith("254") and len(digits) == 12):
        raise ValueError(f"'{phone}' does not look like a valid Kenyan mobile number")

    return digits
