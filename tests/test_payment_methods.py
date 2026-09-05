from types import SimpleNamespace

from tests.test_auth import login, register


async def _auth_headers(client, email="pm-user@test.dev", full_name="PM User"):
    await register(client, email=email, full_name=full_name)
    login_response = await login(client, email=email)
    token = login_response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# --- M-Pesa linking (no external API call needed to "link" a phone) --------

async def test_link_mpesa_number_normalizes_and_masks(client):
    headers = await _auth_headers(client)

    response = await client.post(
        "/api/v1/payment-methods/mpesa", headers=headers, json={"phone_number": "0712345678"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["provider"] == "mpesa"
    assert body["type"] == "mobile_wallet"
    assert body["masked_details"] == "M-Pesa •••• 5678"
    assert body["is_default"] is False


async def test_link_invalid_phone_number_rejected(client):
    headers = await _auth_headers(client)
    response = await client.post(
        "/api/v1/payment-methods/mpesa", headers=headers, json={"phone_number": "12345"}
    )
    assert response.status_code == 422


async def test_link_same_mpesa_number_twice_rejected(client):
    headers = await _auth_headers(client)
    await client.post("/api/v1/payment-methods/mpesa", headers=headers, json={"phone_number": "0712345678"})

    response = await client.post(
        "/api/v1/payment-methods/mpesa", headers=headers, json={"phone_number": "+254712345678"}
    )
    assert response.status_code == 400  # same number, different format — still a duplicate


async def test_list_payment_methods(client):
    headers = await _auth_headers(client)
    await client.post("/api/v1/payment-methods/mpesa", headers=headers, json={"phone_number": "0712345678"})

    response = await client.get("/api/v1/payment-methods", headers=headers)
    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_unlink_payment_method(client):
    headers = await _auth_headers(client)
    create_response = await client.post(
        "/api/v1/payment-methods/mpesa", headers=headers, json={"phone_number": "0712345678"}
    )
    method_id = create_response.json()["id"]

    delete_response = await client.delete(f"/api/v1/payment-methods/{method_id}", headers=headers)
    assert delete_response.status_code == 204

    list_response = await client.get("/api/v1/payment-methods", headers=headers)
    assert list_response.json() == []


async def test_cannot_unlink_another_users_payment_method(client):
    headers_a = await _auth_headers(client, email="pm-a@test.dev", full_name="A")
    headers_b = await _auth_headers(client, email="pm-b@test.dev", full_name="B")

    create_response = await client.post(
        "/api/v1/payment-methods/mpesa", headers=headers_a, json={"phone_number": "0712345678"}
    )
    method_id = create_response.json()["id"]

    delete_response = await client.delete(f"/api/v1/payment-methods/{method_id}", headers=headers_b)
    assert delete_response.status_code == 404


async def test_payment_methods_require_auth(client):
    response = await client.get("/api/v1/payment-methods")
    assert response.status_code == 401


# --- Stripe linking (mocked SDK calls — no real Stripe account available) --

def _fake_customer(id="cus_fake123"):
    return SimpleNamespace(id=id)


def _fake_setup_intent(client_secret="seti_fake_secret"):
    return SimpleNamespace(client_secret=client_secret)


def _fake_payment_method(id="pm_fake123", customer=None, brand="visa", last4="4242"):
    return SimpleNamespace(
        id=id,
        customer=customer,
        card=SimpleNamespace(brand=brand, last4=last4),
    )


async def test_stripe_setup_intent_creates_customer_and_returns_secret(client, monkeypatch):
    monkeypatch.setattr(
        "app.modules.payment_methods.service.stripe.Customer.create",
        lambda **kwargs: _fake_customer(),
    )
    monkeypatch.setattr(
        "app.modules.payment_methods.service.stripe.SetupIntent.create",
        lambda **kwargs: _fake_setup_intent(),
    )

    headers = await _auth_headers(client, email="stripe-user@test.dev", full_name="Stripe User")
    response = await client.post("/api/v1/payment-methods/stripe/setup-intent", headers=headers)

    assert response.status_code == 200
    assert response.json()["client_secret"] == "seti_fake_secret"


async def test_stripe_confirm_card_stores_masked_details(client, monkeypatch):
    monkeypatch.setattr(
        "app.modules.payment_methods.service.stripe.Customer.create",
        lambda **kwargs: _fake_customer(id="cus_abc"),
    )
    attached = {}
    monkeypatch.setattr(
        "app.modules.payment_methods.service.stripe.PaymentMethod.retrieve",
        lambda pm_id: _fake_payment_method(id=pm_id, customer=None),
    )
    monkeypatch.setattr(
        "app.modules.payment_methods.service.stripe.PaymentMethod.attach",
        lambda pm_id, customer: attached.update(pm_id=pm_id, customer=customer),
    )

    headers = await _auth_headers(client, email="stripe-confirm@test.dev", full_name="Stripe Confirm")

    response = await client.post(
        "/api/v1/payment-methods/stripe/confirm",
        headers=headers,
        json={"payment_method_id": "pm_fake123", "set_as_default": True},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["masked_details"] == "Visa •••• 4242"
    assert body["is_default"] is True
    assert attached == {"pm_id": "pm_fake123", "customer": "cus_abc"}


async def test_stripe_confirm_rejects_card_belonging_to_another_customer(client, monkeypatch):
    monkeypatch.setattr(
        "app.modules.payment_methods.service.stripe.Customer.create",
        lambda **kwargs: _fake_customer(id="cus_mine"),
    )
    monkeypatch.setattr(
        "app.modules.payment_methods.service.stripe.PaymentMethod.retrieve",
        lambda pm_id: _fake_payment_method(id=pm_id, customer="cus_someone_else"),
    )

    headers = await _auth_headers(client, email="stripe-mismatch@test.dev", full_name="Mismatch")

    response = await client.post(
        "/api/v1/payment-methods/stripe/confirm",
        headers=headers,
        json={"payment_method_id": "pm_stolen"},
    )
    assert response.status_code == 400
