from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select

from app.modules.accounts.models import Account
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


async def _auth(client, email="dep-user@test.dev", full_name="Dep User"):
    await register(client, email=email, full_name=full_name)
    login_response = await login(client, email=email)
    return login_response.json()["access_token"]


async def _get_balance(email: str) -> Decimal:
    async with TestSessionLocal() as session:
        from app.modules.users.models import User

        result = await session.execute(
            select(Account).join(User, User.id == Account.user_id).where(User.email == email)
        )
        return result.scalar_one().balance


# --- Stripe deposits ---------------------------------------------------

def _fake_customer(id="cus_dep123"):
    return SimpleNamespace(id=id)


def _fake_payment_intent(id="pi_fake123", client_secret="pi_fake123_secret"):
    return SimpleNamespace(id=id, client_secret=client_secret)


async def test_create_stripe_deposit_returns_client_secret(client, monkeypatch):
    monkeypatch.setattr(
        "app.modules.payment_methods.service.stripe.Customer.create", lambda **kw: _fake_customer()
    )
    monkeypatch.setattr(
        "app.modules.deposits.service.stripe.PaymentIntent.create", lambda **kw: _fake_payment_intent()
    )

    token = await _auth(client)
    response = await client.post(
        "/api/v1/deposits/stripe",
        headers={"Authorization": f"Bearer {token}"},
        json={"amount": "50.00", "currency": "usd"},
    )
    assert response.status_code == 200
    assert response.json()["client_secret"] == "pi_fake123_secret"


async def test_stripe_deposit_idempotency_key_prevents_duplicate_charge(client, monkeypatch):
    create_calls = []
    monkeypatch.setattr(
        "app.modules.payment_methods.service.stripe.Customer.create", lambda **kw: _fake_customer()
    )
    monkeypatch.setattr(
        "app.modules.deposits.service.stripe.PaymentIntent.create",
        lambda **kw: (create_calls.append(1), _fake_payment_intent())[1],
    )
    monkeypatch.setattr(
        "app.modules.deposits.service.stripe.PaymentIntent.retrieve",
        lambda pi_id: _fake_payment_intent(id=pi_id),
    )

    token = await _auth(client, email="idem-user@test.dev")
    body = {"amount": "50.00", "currency": "usd", "idempotency_key": "same-key-123"}

    first = await client.post(
        "/api/v1/deposits/stripe", headers={"Authorization": f"Bearer {token}"}, json=body
    )
    second = await client.post(
        "/api/v1/deposits/stripe", headers={"Authorization": f"Bearer {token}"}, json=body
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["deposit_id"] == second.json()["deposit_id"]
    assert len(create_calls) == 1  # only ONE real PaymentIntent was ever created


async def test_stripe_webhook_credits_account_on_success(client, monkeypatch):
    monkeypatch.setattr(
        "app.modules.payment_methods.service.stripe.Customer.create", lambda **kw: _fake_customer()
    )
    monkeypatch.setattr(
        "app.modules.deposits.service.stripe.PaymentIntent.create",
        lambda **kw: _fake_payment_intent(id="pi_webhook_test"),
    )
    monkeypatch.setattr(
        "app.modules.webhooks.service.stripe.Webhook.construct_event",
        lambda payload, sig, secret: {
            "type": "payment_intent.succeeded",
            "data": {"object": {"id": "pi_webhook_test"}},
        },
    )
    monkeypatch.setattr("app.modules.deposits.service.convert", _fake_convert(rate=Decimal("2")))

    token = await _auth(client, email="webhook-user@test.dev")
    await client.post(
        "/api/v1/deposits/stripe",
        headers={"Authorization": f"Bearer {token}"},
        json={"amount": "75.00", "currency": "usd"},
    )

    balance_before = await _get_balance("webhook-user@test.dev")
    assert balance_before == Decimal("0.00")

    webhook_response = await client.post(
        "/api/v1/webhooks/stripe", headers={"stripe-signature": "fake"}, json={}
    )
    assert webhook_response.status_code == 200

    # Account is KES by default, deposit was USD — credited amount is the
    # converted (75.00 * rate 2 = 150.00) figure, not the raw 75.00.
    balance_after = await _get_balance("webhook-user@test.dev")
    assert balance_after == Decimal("150.00")


async def test_stripe_webhook_is_idempotent_on_redelivery(client, monkeypatch):
    monkeypatch.setattr(
        "app.modules.payment_methods.service.stripe.Customer.create", lambda **kw: _fake_customer()
    )
    monkeypatch.setattr(
        "app.modules.deposits.service.stripe.PaymentIntent.create",
        lambda **kw: _fake_payment_intent(id="pi_redelivered"),
    )
    monkeypatch.setattr(
        "app.modules.webhooks.service.stripe.Webhook.construct_event",
        lambda payload, sig, secret: {
            "type": "payment_intent.succeeded",
            "data": {"object": {"id": "pi_redelivered"}},
        },
    )
    monkeypatch.setattr("app.modules.deposits.service.convert", _fake_convert(rate=Decimal("2")))

    token = await _auth(client, email="redelivery-user@test.dev")
    await client.post(
        "/api/v1/deposits/stripe",
        headers={"Authorization": f"Bearer {token}"},
        json={"amount": "20.00", "currency": "usd"},
    )

    await client.post("/api/v1/webhooks/stripe", headers={"stripe-signature": "fake"}, json={})
    await client.post("/api/v1/webhooks/stripe", headers={"stripe-signature": "fake"}, json={})  # redelivered

    balance = await _get_balance("redelivery-user@test.dev")
    assert balance == Decimal("40.00")  # 20.00 * rate 2 — NOT 80.00, the second delivery must be a no-op


async def test_stripe_webhook_rejects_bad_signature(client, monkeypatch):
    import stripe as stripe_sdk

    def raise_sig_error(payload, sig, secret):
        raise stripe_sdk.error.SignatureVerificationError("bad sig", sig)

    monkeypatch.setattr("app.modules.webhooks.service.stripe.Webhook.construct_event", raise_sig_error)

    response = await client.post(
        "/api/v1/webhooks/stripe", headers={"stripe-signature": "wrong"}, json={}
    )
    assert response.status_code == 400


# --- M-Pesa deposits -----------------------------------------------------

class _FakeMpesaResponse:
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


async def test_create_mpesa_deposit_returns_deposit_id(client, monkeypatch):
    monkeypatch.setattr("app.modules.deposits.service.get_access_token", lambda: _async_return("fake-token"))
    monkeypatch.setattr(
        "app.modules.deposits.service.httpx.AsyncClient",
        lambda: _FakeAsyncClient(_FakeMpesaResponse(200, {"CheckoutRequestID": "ws_CO_test123"})),
    )

    token = await _auth(client, email="mpesa-dep@test.dev")
    response = await client.post(
        "/api/v1/deposits/mpesa",
        headers={"Authorization": f"Bearer {token}"},
        json={"phone_number": "0712345678", "amount": "100"},
    )
    assert response.status_code == 200
    assert "deposit_id" in response.json()


async def test_mpesa_deposit_invalid_phone_rejected(client, monkeypatch):
    monkeypatch.setattr("app.modules.deposits.service.get_access_token", lambda: _async_return("fake-token"))

    token = await _auth(client, email="mpesa-bad-phone@test.dev")
    response = await client.post(
        "/api/v1/deposits/mpesa",
        headers={"Authorization": f"Bearer {token}"},
        json={"phone_number": "123", "amount": "100"},
    )
    assert response.status_code == 422


async def test_mpesa_callback_credits_account_on_success(client, monkeypatch):
    monkeypatch.setattr("app.modules.deposits.service.get_access_token", lambda: _async_return("fake-token"))
    monkeypatch.setattr(
        "app.modules.deposits.service.httpx.AsyncClient",
        lambda: _FakeAsyncClient(_FakeMpesaResponse(200, {"CheckoutRequestID": "ws_CO_callback_test"})),
    )

    token = await _auth(client, email="mpesa-callback@test.dev")
    await client.post(
        "/api/v1/deposits/mpesa",
        headers={"Authorization": f"Bearer {token}"},
        json={"phone_number": "0712345678", "amount": "250"},
    )

    callback_payload = {
        "Body": {
            "stkCallback": {
                "MerchantRequestID": "merchant-123",
                "CheckoutRequestID": "ws_CO_callback_test",
                "ResultCode": 0,
                "ResultDesc": "The service request is processed successfully.",
                "CallbackMetadata": {
                    "Item": [
                        {"Name": "Amount", "Value": 250},
                        {"Name": "MpesaReceiptNumber", "Value": "ABC123XYZ"},
                        {"Name": "PhoneNumber", "Value": 254712345678},
                    ]
                },
            }
        }
    }
    callback_response = await client.post("/api/v1/webhooks/mpesa/stk-callback", json=callback_payload)
    assert callback_response.status_code == 200

    balance = await _get_balance("mpesa-callback@test.dev")
    assert balance == Decimal("250.00")


async def test_mpesa_callback_marks_failed_on_cancellation(client, monkeypatch):
    monkeypatch.setattr("app.modules.deposits.service.get_access_token", lambda: _async_return("fake-token"))
    monkeypatch.setattr(
        "app.modules.deposits.service.httpx.AsyncClient",
        lambda: _FakeAsyncClient(_FakeMpesaResponse(200, {"CheckoutRequestID": "ws_CO_cancelled"})),
    )

    token = await _auth(client, email="mpesa-cancel@test.dev")
    await client.post(
        "/api/v1/deposits/mpesa",
        headers={"Authorization": f"Bearer {token}"},
        json={"phone_number": "0712345678", "amount": "100"},
    )

    callback_payload = {
        "Body": {
            "stkCallback": {
                "MerchantRequestID": "merchant-456",
                "CheckoutRequestID": "ws_CO_cancelled",
                "ResultCode": 1032,
                "ResultDesc": "Request cancelled by user",
            }
        }
    }
    response = await client.post("/api/v1/webhooks/mpesa/stk-callback", json=callback_payload)
    assert response.status_code == 200

    balance = await _get_balance("mpesa-cancel@test.dev")
    assert balance == Decimal("0.00")  # not credited


async def test_create_airtel_deposit_returns_deposit_id(client, monkeypatch):
    monkeypatch.setattr("app.modules.deposits.service.get_airtel_access_token", lambda: _async_return("fake-token"))
    monkeypatch.setattr(
        "app.modules.deposits.service.httpx.AsyncClient",
        lambda: _FakeAsyncClient(_FakeMpesaResponse(200, {"status": {"success": True}})),
    )

    token = await _auth(client, email="airtel-dep@test.dev")
    response = await client.post(
        "/api/v1/deposits/airtel",
        headers={"Authorization": f"Bearer {token}"},
        json={"phone_number": "0733123456", "amount": "100"},
    )
    assert response.status_code == 200
    assert "deposit_id" in response.json()


async def test_airtel_deposit_invalid_phone_rejected(client, monkeypatch):
    monkeypatch.setattr("app.modules.deposits.service.get_airtel_access_token", lambda: _async_return("fake-token"))

    token = await _auth(client, email="airtel-bad-phone@test.dev")
    response = await client.post(
        "/api/v1/deposits/airtel",
        headers={"Authorization": f"Bearer {token}"},
        json={"phone_number": "123", "amount": "100"},
    )
    assert response.status_code == 422


async def test_airtel_callback_credits_account_on_success(client, monkeypatch):
    monkeypatch.setattr("app.modules.deposits.service.get_airtel_access_token", lambda: _async_return("fake-token"))
    monkeypatch.setattr(
        "app.modules.deposits.service.httpx.AsyncClient",
        lambda: _FakeAsyncClient(_FakeMpesaResponse(200, {"status": {"success": True}})),
    )
    monkeypatch.setattr("app.modules.webhooks.service.verify_airtel_signature", lambda raw_body, signature: True)

    token = await _auth(client, email="airtel-callback@test.dev")
    create_response = await client.post(
        "/api/v1/deposits/airtel",
        headers={"Authorization": f"Bearer {token}"},
        json={"phone_number": "0733123456", "amount": "300"},
    )
    deposit_id = create_response.json()["deposit_id"]

    from app.modules.deposits.models import Deposit

    async with TestSessionLocal() as session:
        deposit = (await session.execute(select(Deposit).where(Deposit.id == deposit_id))).scalar_one()
        transaction_id = deposit.external_reference  # generated internally, not returned by the mocked API

    callback_payload = {"transaction": {"id": transaction_id, "airtel_money_id": "MP123456", "status_code": "TS"}}
    callback_response = await client.post(
        "/api/v1/webhooks/airtel/collection-callback",
        headers={"x-signature": "fake-sig"},
        json=callback_payload,
    )
    assert callback_response.status_code == 200

    balance = await _get_balance("airtel-callback@test.dev")
    assert balance == Decimal("300.00")


async def test_airtel_callback_marks_failed_on_failure_status(client, monkeypatch):
    monkeypatch.setattr("app.modules.deposits.service.get_airtel_access_token", lambda: _async_return("fake-token"))
    monkeypatch.setattr(
        "app.modules.deposits.service.httpx.AsyncClient",
        lambda: _FakeAsyncClient(_FakeMpesaResponse(200, {"status": {"success": True}})),
    )
    monkeypatch.setattr("app.modules.webhooks.service.verify_airtel_signature", lambda raw_body, signature: True)

    token = await _auth(client, email="airtel-callback-fail@test.dev")
    create_response = await client.post(
        "/api/v1/deposits/airtel",
        headers={"Authorization": f"Bearer {token}"},
        json={"phone_number": "0733123456", "amount": "100"},
    )
    deposit_id = create_response.json()["deposit_id"]

    from app.modules.deposits.models import Deposit

    async with TestSessionLocal() as session:
        deposit = (await session.execute(select(Deposit).where(Deposit.id == deposit_id))).scalar_one()
        transaction_id = deposit.external_reference

    callback_payload = {"transaction": {"id": transaction_id, "status_code": "TF"}}
    response = await client.post(
        "/api/v1/webhooks/airtel/collection-callback",
        headers={"x-signature": "fake-sig"},
        json=callback_payload,
    )
    assert response.status_code == 200

    balance = await _get_balance("airtel-callback-fail@test.dev")
    assert balance == Decimal("0.00")  # not credited


async def test_airtel_callback_rejects_invalid_signature(client, monkeypatch):
    monkeypatch.setattr("app.modules.webhooks.service.verify_airtel_signature", lambda raw_body, signature: False)

    response = await client.post(
        "/api/v1/webhooks/airtel/collection-callback",
        headers={"x-signature": "bad-sig"},
        json={"transaction": {"id": "whatever", "status_code": "TS"}},
    )
    assert response.status_code == 400


async def _async_return(value):
    return value


# --- Multi-currency conversion -------------------------------------------

async def test_stripe_deposit_records_exchange_rate_and_converted_amount(client, monkeypatch):
    """A deposit made in a currency other than the account's (KES by
    default) should be converted before crediting, and the applied rate
    plus the converted figure should be persisted on the Deposit row."""
    monkeypatch.setattr(
        "app.modules.payment_methods.service.stripe.Customer.create", lambda **kw: _fake_customer()
    )
    monkeypatch.setattr(
        "app.modules.deposits.service.stripe.PaymentIntent.create",
        lambda **kw: _fake_payment_intent(id="pi_convert_test"),
    )
    monkeypatch.setattr(
        "app.modules.webhooks.service.stripe.Webhook.construct_event",
        lambda payload, sig, secret: {
            "type": "payment_intent.succeeded",
            "data": {"object": {"id": "pi_convert_test"}},
        },
    )
    monkeypatch.setattr("app.modules.deposits.service.convert", _fake_convert(rate=Decimal("130")))

    token = await _auth(client, email="convert-user@test.dev")
    create_response = await client.post(
        "/api/v1/deposits/stripe",
        headers={"Authorization": f"Bearer {token}"},
        json={"amount": "10.00", "currency": "usd"},
    )
    deposit_id = create_response.json()["deposit_id"]

    await client.post("/api/v1/webhooks/stripe", headers={"stripe-signature": "fake"}, json={})

    balance = await _get_balance("convert-user@test.dev")
    assert balance == Decimal("1300.00")  # 10.00 USD * rate 130

    from app.modules.deposits.models import Deposit

    async with TestSessionLocal() as session:
        deposit = (await session.execute(select(Deposit).where(Deposit.id == deposit_id))).scalar_one()
        assert deposit.exchange_rate == Decimal("130")
        assert deposit.converted_amount == Decimal("1300.00")
        assert deposit.amount == Decimal("10.00")  # original figure preserved, untouched


async def test_deposit_marked_failed_when_exchange_rate_unavailable(client, monkeypatch):
    """If the conversion rate can't be fetched, the deposit must not
    silently credit the wrong amount (or crash) — it's marked failed and
    no funds move."""
    from app.core.exchange_rate_client import ExchangeRateUnavailable

    async def _broken_convert(amount, from_currency, to_currency):
        raise ExchangeRateUnavailable("rate service down")

    monkeypatch.setattr(
        "app.modules.payment_methods.service.stripe.Customer.create", lambda **kw: _fake_customer()
    )
    monkeypatch.setattr(
        "app.modules.deposits.service.stripe.PaymentIntent.create",
        lambda **kw: _fake_payment_intent(id="pi_rate_down"),
    )
    monkeypatch.setattr(
        "app.modules.webhooks.service.stripe.Webhook.construct_event",
        lambda payload, sig, secret: {
            "type": "payment_intent.succeeded",
            "data": {"object": {"id": "pi_rate_down"}},
        },
    )
    monkeypatch.setattr("app.modules.deposits.service.convert", _broken_convert)

    token = await _auth(client, email="rate-down-user@test.dev")
    create_response = await client.post(
        "/api/v1/deposits/stripe",
        headers={"Authorization": f"Bearer {token}"},
        json={"amount": "10.00", "currency": "usd"},
    )
    deposit_id = create_response.json()["deposit_id"]

    webhook_response = await client.post(
        "/api/v1/webhooks/stripe", headers={"stripe-signature": "fake"}, json={}
    )
    assert webhook_response.status_code == 200  # webhook itself still ack's cleanly

    balance = await _get_balance("rate-down-user@test.dev")
    assert balance == Decimal("0.00")  # nothing credited

    from app.modules.deposits.models import Deposit, DepositStatus

    async with TestSessionLocal() as session:
        deposit = (await session.execute(select(Deposit).where(Deposit.id == deposit_id))).scalar_one()
        assert deposit.status == DepositStatus.failed
        assert "Currency conversion failed" in deposit.failure_reason

