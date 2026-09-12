from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select, update

from app.modules.accounts.models import Account
from app.modules.users.models import User
from tests.conftest import TestSessionLocal
from tests.test_auth import login, register


def _fake_convert(rate=Decimal("2")):
    """Deterministic stand-in for app.core.exchange_rate_client.convert —
    avoids a real network call to Frankfurter in tests, and makes the
    converted amount predictable to assert on. Same-currency pairs still
    short-circuit to a 1:1 rate, matching the real implementation."""
    async def _convert(amount, from_currency, to_currency):
        if from_currency.upper() == to_currency.upper():
            return amount, Decimal("1")
        return amount * rate, rate
    return _convert


async def _verified_auth(client, email="payout-user@test.dev", full_name="Payout User"):
    await register(client, email=email, full_name=full_name)
    async with TestSessionLocal() as session:
        await session.execute(update(User).where(User.email == email).values(is_verified=True))
        await session.commit()
    login_response = await login(client, email=email)
    return login_response.json()["access_token"]


async def _fund(email: str, amount: str):
    async with TestSessionLocal() as session:
        result = await session.execute(
            select(Account).join(User, User.id == Account.user_id).where(User.email == email)
        )
        account = result.scalar_one()
        account.balance = Decimal(amount)
        await session.commit()


async def _get_balance(email: str) -> Decimal:
    async with TestSessionLocal() as session:
        result = await session.execute(
            select(Account).join(User, User.id == Account.user_id).where(User.email == email)
        )
        return result.scalar_one().balance


# --- M-Pesa B2C payouts --------------------------------------------------

async def test_mpesa_payout_requires_verified_email(client):
    await register(client, email="unverified-payout@test.dev", full_name="Unverified")
    login_response = await login(client, email="unverified-payout@test.dev")
    token = login_response.json()["access_token"]
    await _fund("unverified-payout@test.dev", "500.00")

    response = await client.post(
        "/api/v1/payouts/mpesa",
        headers={"Authorization": f"Bearer {token}"},
        json={"phone_number": "0712345678", "recipient_email": "someone@test.dev", "amount": "100.00"},
    )
    assert response.status_code == 403


async def test_mpesa_payout_rejects_insufficient_funds_before_calling_gateway(client, monkeypatch):
    gateway_called = []
    monkeypatch.setattr(
        "app.modules.payouts.service.get_access_token",
        lambda: _async_return("fake-token"),
    )
    monkeypatch.setattr(
        "app.modules.payouts.service.generate_security_credential",
        lambda: (gateway_called.append(1), "fake-cred")[1],
    )

    token = await _verified_auth(client, email="poor-user@test.dev")
    await _fund("poor-user@test.dev", "10.00")

    response = await client.post(
        "/api/v1/payouts/mpesa",
        headers={"Authorization": f"Bearer {token}"},
        json={"phone_number": "0712345678", "recipient_email": "someone@test.dev", "amount": "500.00"},
    )
    assert response.status_code == 400
    assert len(gateway_called) == 0  # never even reached the gateway call

    balance = await _get_balance("poor-user@test.dev")
    assert balance == Decimal("10.00")  # untouched


async def test_mpesa_payout_deducts_immediately_then_reverses_on_sync_gateway_failure(client, monkeypatch):
    monkeypatch.setattr(
        "app.modules.payouts.service.get_access_token", lambda: _async_return("fake-token")
    )
    monkeypatch.setattr(
        "app.modules.payouts.service.generate_security_credential", lambda: "fake-cred"
    )
    monkeypatch.setattr(
        "app.modules.payouts.service.httpx.AsyncClient",
        lambda: _FakeAsyncClient(_FakeResponse(500, {"error": "gateway down"})),
    )

    token = await _verified_auth(client, email="gw-fail-user@test.dev")
    await _fund("gw-fail-user@test.dev", "500.00")

    response = await client.post(
        "/api/v1/payouts/mpesa",
        headers={"Authorization": f"Bearer {token}"},
        json={"phone_number": "0712345678", "recipient_email": "someone@test.dev", "amount": "200.00"},
    )
    assert response.status_code == 502

    # Balance was deducted THEN reversed — should be back to the original.
    balance = await _get_balance("gw-fail-user@test.dev")
    assert balance == Decimal("500.00")


async def test_mpesa_payout_succeeds_and_stays_deducted_until_result_callback(client, monkeypatch):
    monkeypatch.setattr(
        "app.modules.payouts.service.get_access_token", lambda: _async_return("fake-token")
    )
    monkeypatch.setattr(
        "app.modules.payouts.service.generate_security_credential", lambda: "fake-cred"
    )
    monkeypatch.setattr(
        "app.modules.payouts.service.httpx.AsyncClient",
        lambda: _FakeAsyncClient(_FakeResponse(200, {"ConversationID": "AG_conv_123"})),
    )

    token = await _verified_auth(client, email="b2c-success@test.dev")
    await _fund("b2c-success@test.dev", "500.00")

    response = await client.post(
        "/api/v1/payouts/mpesa",
        headers={"Authorization": f"Bearer {token}"},
        json={"phone_number": "0712345678", "recipient_email": "someone@test.dev", "amount": "150.00"},
    )
    assert response.status_code == 201
    assert response.json()["status"] == "pending"

    balance = await _get_balance("b2c-success@test.dev")
    assert balance == Decimal("350.00")  # deducted immediately, awaiting result

    result_payload = {
        "Result": {
            "ConversationID": "AG_conv_123",
            "ResultCode": 0,
            "ResultDesc": "The service request has been accepted successfully.",
        }
    }
    result_response = await client.post("/api/v1/webhooks/mpesa/b2c-result", json=result_payload)
    assert result_response.status_code == 200

    final_balance = await _get_balance("b2c-success@test.dev")
    assert final_balance == Decimal("350.00")  # still deducted — payout succeeded for real


async def test_mpesa_payout_b2c_result_failure_reverses_deduction(client, monkeypatch):
    monkeypatch.setattr(
        "app.modules.payouts.service.get_access_token", lambda: _async_return("fake-token")
    )
    monkeypatch.setattr(
        "app.modules.payouts.service.generate_security_credential", lambda: "fake-cred"
    )
    monkeypatch.setattr(
        "app.modules.payouts.service.httpx.AsyncClient",
        lambda: _FakeAsyncClient(_FakeResponse(200, {"ConversationID": "AG_conv_fail"})),
    )

    token = await _verified_auth(client, email="b2c-async-fail@test.dev")
    await _fund("b2c-async-fail@test.dev", "500.00")

    await client.post(
        "/api/v1/payouts/mpesa",
        headers={"Authorization": f"Bearer {token}"},
        json={"phone_number": "0712345678", "recipient_email": "someone@test.dev", "amount": "150.00"},
    )
    assert await _get_balance("b2c-async-fail@test.dev") == Decimal("350.00")

    result_payload = {
        "Result": {
            "ConversationID": "AG_conv_fail",
            "ResultCode": 2001,
            "ResultDesc": "The initiator information is invalid.",
        }
    }
    await client.post("/api/v1/webhooks/mpesa/b2c-result", json=result_payload)

    final_balance = await _get_balance("b2c-async-fail@test.dev")
    assert final_balance == Decimal("500.00")  # reversed back to original


async def test_mpesa_payout_idempotency_key_prevents_double_deduction(client, monkeypatch):
    call_count = []
    monkeypatch.setattr(
        "app.modules.payouts.service.get_access_token", lambda: _async_return("fake-token")
    )
    monkeypatch.setattr(
        "app.modules.payouts.service.generate_security_credential", lambda: "fake-cred"
    )

    def fake_client_factory():
        call_count.append(1)
        return _FakeAsyncClient(_FakeResponse(200, {"ConversationID": f"AG_conv_{len(call_count)}"}))

    monkeypatch.setattr("app.modules.payouts.service.httpx.AsyncClient", fake_client_factory)

    token = await _verified_auth(client, email="idem-payout@test.dev")
    await _fund("idem-payout@test.dev", "500.00")

    body = {
        "phone_number": "0712345678",
        "recipient_email": "someone@test.dev",
        "amount": "100.00",
        "idempotency_key": "payout-key-1",
    }
    first = await client.post(
        "/api/v1/payouts/mpesa", headers={"Authorization": f"Bearer {token}"}, json=body
    )
    second = await client.post(
        "/api/v1/payouts/mpesa", headers={"Authorization": f"Bearer {token}"}, json=body
    )
    assert first.json()["id"] == second.json()["id"]
    assert len(call_count) == 1  # gateway only ever called once

    balance = await _get_balance("idem-payout@test.dev")
    assert balance == Decimal("400.00")  # deducted exactly once, not twice


# --- Stripe card payouts ---------------------------------------------------

def _fake_stripe_payout(id="po_fake123", status="pending"):
    return SimpleNamespace(id=id, status=status)


async def test_stripe_card_payout_success(client, monkeypatch):
    monkeypatch.setattr(
        "app.modules.payouts.service.stripe.Payout.create", lambda **kw: _fake_stripe_payout()
    )
    monkeypatch.setattr("app.modules.payouts.service.convert", _fake_convert(rate=Decimal("2")))

    token = await _verified_auth(client, email="stripe-payout@test.dev")
    await _fund("stripe-payout@test.dev", "500.00")

    response = await client.post(
        "/api/v1/payouts/stripe-card",
        headers={"Authorization": f"Bearer {token}"},
        json={"card_token": "tok_visa", "recipient_email": "someone@test.dev", "amount": "100.00"},
    )
    assert response.status_code == 201
    assert response.json()["status"] == "completed"

    # Payout currency defaults to USD, account is KES — 100.00 USD * rate 2
    # = 200.00 KES actually deducted, not the raw 100.00.
    balance = await _get_balance("stripe-payout@test.dev")
    assert balance == Decimal("300.00")


async def test_stripe_card_payout_reverses_on_immediate_failure(client, monkeypatch):
    monkeypatch.setattr(
        "app.modules.payouts.service.stripe.Payout.create",
        lambda **kw: _fake_stripe_payout(status="failed"),
    )
    monkeypatch.setattr("app.modules.payouts.service.convert", _fake_convert(rate=Decimal("2")))

    token = await _verified_auth(client, email="stripe-payout-fail@test.dev")
    await _fund("stripe-payout-fail@test.dev", "500.00")

    response = await client.post(
        "/api/v1/payouts/stripe-card",
        headers={"Authorization": f"Bearer {token}"},
        json={"card_token": "tok_chargeDeclined", "recipient_email": "someone@test.dev", "amount": "100.00"},
    )
    assert response.status_code == 201  # the API call itself succeeded, the payout just failed
    assert response.json()["status"] == "reversed"

    balance = await _get_balance("stripe-payout-fail@test.dev")
    assert balance == Decimal("500.00")  # reversed


async def test_stripe_card_payout_reverses_on_stripe_exception(client, monkeypatch):
    import stripe as stripe_sdk

    def raise_error(**kw):
        raise stripe_sdk.error.CardError("Card declined", None, "card_declined")

    monkeypatch.setattr("app.modules.payouts.service.stripe.Payout.create", raise_error)
    monkeypatch.setattr("app.modules.payouts.service.convert", _fake_convert(rate=Decimal("2")))

    token = await _verified_auth(client, email="stripe-payout-exc@test.dev")
    await _fund("stripe-payout-exc@test.dev", "500.00")

    response = await client.post(
        "/api/v1/payouts/stripe-card",
        headers={"Authorization": f"Bearer {token}"},
        json={"card_token": "tok_bad", "recipient_email": "someone@test.dev", "amount": "100.00"},
    )
    assert response.status_code == 502

    balance = await _get_balance("stripe-payout-exc@test.dev")
    assert balance == Decimal("500.00")  # reversed


async def test_stripe_payout_failed_webhook_reverses_a_completed_payout(client, monkeypatch):
    monkeypatch.setattr(
        "app.modules.payouts.service.stripe.Payout.create",
        lambda **kw: _fake_stripe_payout(id="po_later_fails", status="pending"),
    )
    monkeypatch.setattr(
        "app.modules.webhooks.router.stripe.Webhook.construct_event",
        lambda payload, sig, secret: {
            "type": "payout.failed",
            "data": {"object": {"id": "po_later_fails", "failure_message": "Card closed"}},
        },
    )
    monkeypatch.setattr("app.modules.payouts.service.convert", _fake_convert(rate=Decimal("2")))

    token = await _verified_auth(client, email="stripe-late-fail@test.dev")
    await _fund("stripe-late-fail@test.dev", "500.00")

    create_response = await client.post(
        "/api/v1/payouts/stripe-card",
        headers={"Authorization": f"Bearer {token}"},
        json={"card_token": "tok_visa", "recipient_email": "someone@test.dev", "amount": "100.00"},
    )
    assert create_response.json()["status"] == "completed"
    # 100.00 USD * rate 2 = 200.00 KES actually deducted
    assert await _get_balance("stripe-late-fail@test.dev") == Decimal("300.00")

    webhook_response = await client.post(
        "/api/v1/webhooks/stripe", headers={"stripe-signature": "fake"}, json={}
    )
    assert webhook_response.status_code == 200

    final_balance = await _get_balance("stripe-late-fail@test.dev")
    assert final_balance == Decimal("500.00")  # reversed after the fact, back to the original


# --- Multi-currency conversion -------------------------------------------

async def test_stripe_payout_records_exchange_rate_and_converted_amount(client, monkeypatch):
    """A payout requested in a currency other than the account's (KES by
    default) should be converted before deducting, and the applied rate
    plus the converted figure should be persisted on the Payout row."""
    monkeypatch.setattr(
        "app.modules.payouts.service.stripe.Payout.create", lambda **kw: _fake_stripe_payout()
    )
    monkeypatch.setattr("app.modules.payouts.service.convert", _fake_convert(rate=Decimal("130")))

    token = await _verified_auth(client, email="payout-convert@test.dev")
    await _fund("payout-convert@test.dev", "5000.00")

    response = await client.post(
        "/api/v1/payouts/stripe-card",
        headers={"Authorization": f"Bearer {token}"},
        json={"card_token": "tok_visa", "recipient_email": "someone@test.dev", "amount": "10.00"},
    )
    assert response.status_code == 201
    payout_id = response.json()["id"]

    balance = await _get_balance("payout-convert@test.dev")
    assert balance == Decimal("3700.00")  # 5000.00 - (10.00 USD * rate 130)

    from app.modules.payouts.models import Payout

    async with TestSessionLocal() as session:
        payout = (await session.execute(select(Payout).where(Payout.id == payout_id))).scalar_one()
        assert payout.exchange_rate == Decimal("130")
        assert payout.converted_amount == Decimal("1300.00")
        assert payout.amount == Decimal("10.00")  # original figure preserved, untouched


async def test_payout_rejected_when_exchange_rate_unavailable(client, monkeypatch):
    """If the conversion rate can't be fetched, the payout must not go
    ahead with a wrong deduction — it's rejected before any external
    gateway call, and the sender's balance is untouched."""
    from app.core.exchange_rate_client import ExchangeRateUnavailable

    async def _broken_convert(amount, from_currency, to_currency):
        raise ExchangeRateUnavailable("rate service down")

    gateway_calls = []
    monkeypatch.setattr(
        "app.modules.payouts.service.stripe.Payout.create",
        lambda **kw: (gateway_calls.append(1), _fake_stripe_payout())[1],
    )
    monkeypatch.setattr("app.modules.payouts.service.convert", _broken_convert)

    token = await _verified_auth(client, email="payout-rate-down@test.dev")
    await _fund("payout-rate-down@test.dev", "500.00")

    response = await client.post(
        "/api/v1/payouts/stripe-card",
        headers={"Authorization": f"Bearer {token}"},
        json={"card_token": "tok_visa", "recipient_email": "someone@test.dev", "amount": "100.00"},
    )
    assert response.status_code == 503
    assert len(gateway_calls) == 0  # never even reached the gateway

    balance = await _get_balance("payout-rate-down@test.dev")
    assert balance == Decimal("500.00")  # untouched


class _FakeResponse:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self._data = data

    def json(self):
        return self._data

    @property
    def text(self):
        return str(self._data)


class _FakeAsyncClient:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def post(self, *args, **kwargs):
        return self._response


async def _async_return(value):
    return value
