from decimal import Decimal

from sqlalchemy import select

from app.models.account import Account
from app.models.user import User

from tests.test_auth import login, register


async def _register_and_login(client, email, full_name):
    await register(client, email=email, full_name=full_name)
    login_response = await login(client, email=email)
    return login_response.json()["access_token"]


async def _fund_account(db_session, email: str, amount: str):
    """Directly credit an account for test setup — there's no deposit
    endpoint yet, so this mirrors what one would eventually do."""
    result = await db_session.execute(select(User).where(User.email == email))
    user = result.scalar_one()
    account_result = await db_session.execute(select(Account).where(Account.user_id == user.id))
    account = account_result.scalar_one()
    account.balance = Decimal(amount)
    await db_session.commit()


async def test_new_account_starts_at_zero_balance(client):
    token = await _register_and_login(client, "bob@test.dev", "Bob")
    response = await client.get("/accounts/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["balance"] == "0.00"


async def test_transfer_with_insufficient_funds_rejected(client):
    token = await _register_and_login(client, "carol@test.dev", "Carol")
    await register(client, email="dave@test.dev", full_name="Dave")

    response = await client.post(
        "/transfers",
        headers={"Authorization": f"Bearer {token}"},
        json={"to_email": "dave@test.dev", "amount": "50.00"},
    )
    assert response.status_code == 400


async def test_successful_transfer_moves_correct_balances(client, db_session):
    token = await _register_and_login(client, "eve@test.dev", "Eve")
    await register(client, email="frank@test.dev", full_name="Frank")
    await _fund_account(db_session, "eve@test.dev", "1000.00")

    response = await client.post(
        "/transfers",
        headers={"Authorization": f"Bearer {token}"},
        json={"to_email": "frank@test.dev", "amount": "250.50", "reference_note": "rent"},
    )
    assert response.status_code == 201

    eve_account = await client.get("/accounts/me", headers={"Authorization": f"Bearer {token}"})
    assert eve_account.json()["balance"] == "749.50"

    frank_token = (await login(client, email="frank@test.dev")).json()["access_token"]
    frank_account = await client.get("/accounts/me", headers={"Authorization": f"Bearer {frank_token}"})
    assert frank_account.json()["balance"] == "250.50"


async def test_self_transfer_rejected(client, db_session):
    token = await _register_and_login(client, "gina@test.dev", "Gina")
    await _fund_account(db_session, "gina@test.dev", "100.00")

    response = await client.post(
        "/transfers",
        headers={"Authorization": f"Bearer {token}"},
        json={"to_email": "gina@test.dev", "amount": "10.00"},
    )
    assert response.status_code == 400


async def test_transfer_to_nonexistent_recipient_rejected(client, db_session):
    token = await _register_and_login(client, "hank@test.dev", "Hank")
    await _fund_account(db_session, "hank@test.dev", "100.00")

    response = await client.post(
        "/transfers",
        headers={"Authorization": f"Bearer {token}"},
        json={"to_email": "nobody@test.dev", "amount": "10.00"},
    )
    assert response.status_code == 404


async def test_negative_amount_rejected_by_validation(client, db_session):
    token = await _register_and_login(client, "ivy@test.dev", "Ivy")
    await register(client, email="jack@test.dev", full_name="Jack")
    await _fund_account(db_session, "ivy@test.dev", "100.00")

    response = await client.post(
        "/transfers",
        headers={"Authorization": f"Bearer {token}"},
        json={"to_email": "jack@test.dev", "amount": "-10.00"},
    )
    assert response.status_code == 422


async def test_transaction_appears_in_sender_history(client, db_session):
    token = await _register_and_login(client, "kim@test.dev", "Kim")
    await register(client, email="liam@test.dev", full_name="Liam")
    await _fund_account(db_session, "kim@test.dev", "500.00")

    await client.post(
        "/transfers",
        headers={"Authorization": f"Bearer {token}"},
        json={"to_email": "liam@test.dev", "amount": "75.00"},
    )

    history = await client.get("/transactions", headers={"Authorization": f"Bearer {token}"})
    assert history.status_code == 200
    body = history.json()
    assert body["total"] == 1
    assert body["items"][0]["amount"] == "75.00"
