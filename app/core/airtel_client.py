"""
Shared Airtel Money Open API primitives: OAuth2 client-credentials token
fetching (with the same simple in-memory cache pattern as M-Pesa's),
phone number normalization, and callback signature verification. Used
by both deposits (Collections — USSD push) and payouts (Disbursements).

Airtel's Open API is pan-African (14+ countries) but this integration
is scoped to Kenya only, matching M-Pesa and the account currency
default (KES) — see PLAN.md § 8.

Docs: https://developers.airtel.africa/
Sandbox base URL: https://openapiuat.airtel.africa
Production base URL: https://openapi.airtel.africa

NOTE on callback signing: unlike Stripe, Airtel does not publish one
single, universally-documented signing scheme for callbacks the way
Stripe does — integrations in the wild commonly verify an `X-Signature`
header as HMAC-SHA256 over the raw request body, keyed by a shared
secret configured in the developer portal, and that's what
verify_callback_signature implements here. This should be re-confirmed
against the callback-signing section of the developer portal once real
credentials are available — flagged the same way M-Pesa's genuinely
unsigned callbacks are flagged, rather than assumed correct.
"""

import base64
import hashlib
import hmac
import time

import httpx

from app.core.config import settings

_BASE_URLS = {
    "sandbox": "https://openapiuat.airtel.africa",
    "production": "https://openapi.airtel.africa",
}

# Same reasoning as M-Pesa's token cache in mpesa_client.py: good enough
# for a single-instance deployment, a multi-instance one would want this
# in Redis instead.
_token_cache: dict = {}


def get_base_url() -> str:
    return _BASE_URLS.get(settings.AIRTEL_ENV, _BASE_URLS["sandbox"])


async def get_access_token() -> str:
    now = time.time()
    if _token_cache.get("token") and _token_cache.get("expires_at", 0) > now:
        return _token_cache["token"]

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{get_base_url()}/auth/oauth2/token",
            json={
                "client_id": settings.AIRTEL_CLIENT_ID,
                "client_secret": settings.AIRTEL_CLIENT_SECRET,
                "grant_type": "client_credentials",
            },
            headers={"Content-Type": "application/json", "Accept": "*/*"},
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


def standard_headers(access_token: str) -> dict:
    """Headers Airtel's Collections/Disbursement endpoints require on
    every write call, beyond plain Bearer auth — country/currency scope
    every transaction explicitly rather than inferring it from the
    account."""
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "*/*",
        "X-Country": "KE",
        "X-Currency": "KES",
    }


def normalize_kenyan_phone(phone: str) -> str:
    """
    Airtel's Open API expects the subscriber MSISDN without the country
    code or leading zero (e.g. '733123456', not '+254733123456') —
    different from Daraja's format. Accepts the same common input shapes
    M-Pesa's normalizer does and converts them to Airtel's expected
    shape. Raises ValueError for anything that doesn't look like a
    Kenyan mobile number after normalization.
    """
    digits = "".join(ch for ch in phone if ch.isdigit())

    if digits.startswith("254") and len(digits) == 12:
        digits = digits[3:]
    elif digits.startswith("0") and len(digits) == 10:
        digits = digits[1:]
    elif len(digits) == 9:
        pass

    if len(digits) != 9:
        raise ValueError(f"'{phone}' does not look like a valid Kenyan mobile number")

    return digits


def verify_callback_signature(raw_body: bytes, signature: str | None) -> bool:
    """See the module docstring's note on callback signing. Returns
    False (never raises) on a missing signature or secret, so the
    caller always gets a clean reject rather than an exception."""
    if not signature or not settings.AIRTEL_CALLBACK_SECRET:
        return False

    expected = hmac.new(settings.AIRTEL_CALLBACK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def encrypt_disbursement_pin() -> str:
    """
    Disbursement requires the disburser account's PIN, RSA-encrypted
    with Airtel's public encryption key (fetched via their Encryption
    Keys endpoint and cached/rotated per their docs — a real integration
    would fetch and cache this key the same way get_access_token caches
    a token; that fetch-and-cache step isn't implemented here since
    there's no real key to fetch against). Same shape as M-Pesa B2C's
    generate_security_credential: a fixed platform-level credential, not
    anything belonging to the payout recipient.

    Needs settings.AIRTEL_ENCRYPTION_PUBLIC_KEY_PATH pointing at the
    PEM public key file and settings.AIRTEL_DISBURSEMENT_PIN set. This
    is the one piece of the Airtel integration that genuinely cannot be
    exercised without real portal-issued credentials in place — flagged
    the same way M-Pesa B2C's certificate requirement is flagged.
    """
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    if not settings.AIRTEL_ENCRYPTION_PUBLIC_KEY_PATH or not settings.AIRTEL_DISBURSEMENT_PIN:
        raise RuntimeError(
            "AIRTEL_ENCRYPTION_PUBLIC_KEY_PATH / AIRTEL_DISBURSEMENT_PIN are not configured — "
            "disbursements need Airtel's public encryption key and a disburser PIN. See "
            "https://developers.airtel.africa for how to obtain both."
        )

    with open(settings.AIRTEL_ENCRYPTION_PUBLIC_KEY_PATH, "rb") as f:
        public_key = load_pem_public_key(f.read())

    encrypted = public_key.encrypt(settings.AIRTEL_DISBURSEMENT_PIN.encode(), padding.PKCS1v15())
    return base64.b64encode(encrypted).decode()
