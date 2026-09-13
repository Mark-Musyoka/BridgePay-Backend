"""
Currency conversion for deposits and payouts made in a currency other
than the destination account's currency (accounts are always held in a
single currency — see app/modules/accounts/models.py, default "KES").

Uses the Frankfurter API (https://www.frankfurter.dev/) — free, no API
key required, backed by European Central Bank reference rates. Not
suitable for anything requiring real-time FX precision, but adequate
for a wallet's deposit/payout conversion.

Rates are cached in-process for an hour per currency pair, same
reasoning as the M-Pesa token cache in app/core/mpesa_client.py: good
enough for a single-instance deployment, a multi-instance one would
want this in Redis instead.
"""

import time
from decimal import Decimal

import httpx

_FRANKFURTER_BASE_URL = "https://api.frankfurter.dev/v1"

_CACHE_TTL_SECONDS = 60 * 60  # 1 hour

# {(from_currency, to_currency): (rate: Decimal, expires_at: float (epoch))}
_rate_cache: dict[tuple[str, str], tuple[Decimal, float]] = {}


class ExchangeRateUnavailable(Exception):
    pass


async def get_exchange_rate(from_currency: str, to_currency: str) -> Decimal:
    """
    Returns how many units of to_currency one unit of from_currency is
    worth. Same-currency pairs short-circuit to 1 without a network
    call, which also means callers never need to special-case that
    themselves.
    """
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()

    if from_currency == to_currency:
        return Decimal(1)

    cache_key = (from_currency, to_currency)
    cached = _rate_cache.get(cache_key)
    if cached is not None:
        rate, expires_at = cached
        if time.time() < expires_at:
            return rate

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{_FRANKFURTER_BASE_URL}/latest",
                params={"base": from_currency, "symbols": to_currency},
                timeout=10.0,
            )
        response.raise_for_status()
        data = response.json()
        rate = Decimal(str(data["rates"][to_currency]))
    except (httpx.HTTPError, KeyError, ValueError) as e:
        raise ExchangeRateUnavailable(
            f"Could not fetch exchange rate {from_currency}->{to_currency}: {e}"
        )

    _rate_cache[cache_key] = (rate, time.time() + _CACHE_TTL_SECONDS)
    return rate


async def convert(amount: Decimal, from_currency: str, to_currency: str) -> tuple[Decimal, Decimal]:
    """
    Converts amount from from_currency to to_currency. Returns
    (converted_amount, exchange_rate) so the caller can persist both —
    converted_amount is what actually moves through the ledger,
    exchange_rate is kept alongside it as a record of the rate applied.
    """
    rate = await get_exchange_rate(from_currency, to_currency)
    converted_amount = amount * rate
    return converted_amount, rate
