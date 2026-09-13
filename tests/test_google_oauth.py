from sqlalchemy import select

from app.modules.users.models import User
from tests.conftest import TestSessionLocal
from tests.test_auth import register


def _fake_google_user_info(email="googler@test.dev", name="Googler", sub="google-sub-123", verified=True):
    return {"email": email, "email_verified": verified, "name": name, "sub": sub}


async def _get_user(email: str) -> User:
    async with TestSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == email))
        return result.scalar_one()


async def test_google_login_redirects_to_google_with_state_cookie(client):
    response = await client.get("/api/v1/auth/google/login", follow_redirects=False)
    assert response.status_code == 302
    assert "accounts.google.com" in response.headers["location"]
    assert "bp_oauth_state" in response.cookies


async def test_google_callback_rejects_mismatched_state(client):
    client.cookies.set("bp_oauth_state", "correct")
    response = await client.get(
        "/api/v1/auth/google/callback?code=fake&state=wrong",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "error=invalid_state" in response.headers["location"]


async def test_google_callback_creates_new_verified_user_and_redirects_with_handoff_code(client, monkeypatch):
    monkeypatch.setattr(
        "app.modules.auth.router.exchange_code_for_tokens",
        lambda code: _async_return({"access_token": "fake-google-access-token"}),
    )
    monkeypatch.setattr(
        "app.modules.auth.router.get_google_user_info",
        lambda token: _async_return(_fake_google_user_info(email="newgoogler@test.dev")),
    )

    client.cookies.set("bp_oauth_state", "matching-state")
    response = await client.get(
        "/api/v1/auth/google/callback?code=fake-code&state=matching-state",
        follow_redirects=False,
    )
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("http://testserver/auth/google/complete?code=") or "code=" in location

    user = await _get_user("newgoogler@test.dev")
    assert user.is_verified is True
    assert user.hashed_password is None
    assert user.google_id == "google-sub-123"
    assert user.country is None  # Google doesn't provide this — left for the user to fill in later


async def test_google_callback_rejects_unverified_google_email(client, monkeypatch):
    monkeypatch.setattr(
        "app.modules.auth.router.exchange_code_for_tokens",
        lambda code: _async_return({"access_token": "fake-token"}),
    )
    monkeypatch.setattr(
        "app.modules.auth.router.get_google_user_info",
        lambda token: _async_return(_fake_google_user_info(email="unverified@test.dev", verified=False)),
    )

    client.cookies.set("bp_oauth_state", "s")
    response = await client.get(
        "/api/v1/auth/google/callback?code=fake-code&state=s",
        follow_redirects=False,
    )
    assert "error=email_not_verified" in response.headers["location"]


async def test_google_login_links_to_existing_password_account_and_verifies_it(client, monkeypatch):
    await register(client, email="linkme@test.dev", full_name="Link Me")
    # Confirm it starts unverified, as normal registration leaves it.
    user_before = await _get_user("linkme@test.dev")
    assert user_before.is_verified is False

    monkeypatch.setattr(
        "app.modules.auth.router.exchange_code_for_tokens",
        lambda code: _async_return({"access_token": "fake-token"}),
    )
    monkeypatch.setattr(
        "app.modules.auth.router.get_google_user_info",
        lambda token: _async_return(_fake_google_user_info(email="linkme@test.dev", sub="linked-sub")),
    )

    client.cookies.set("bp_oauth_state", "s")
    await client.get(
        "/api/v1/auth/google/callback?code=fake-code&state=s",
        follow_redirects=False,
    )

    user_after = await _get_user("linkme@test.dev")
    assert user_after.is_verified is True  # upgraded
    assert user_after.google_id == "linked-sub"
    assert user_after.hashed_password is not None  # the original password is untouched


async def test_google_exchange_issues_real_tokens_and_code_is_single_use(client, monkeypatch):
    monkeypatch.setattr(
        "app.modules.auth.router.exchange_code_for_tokens",
        lambda code: _async_return({"access_token": "fake-token"}),
    )
    monkeypatch.setattr(
        "app.modules.auth.router.get_google_user_info",
        lambda token: _async_return(_fake_google_user_info(email="exchange-test@test.dev")),
    )

    client.cookies.set("bp_oauth_state", "s")
    callback_response = await client.get(
        "/api/v1/auth/google/callback?code=fake-code&state=s",
        follow_redirects=False,
    )
    location = callback_response.headers["location"]
    handoff_code = location.split("code=")[1]

    exchange_response = await client.post("/api/v1/auth/google/exchange", json={"code": handoff_code})
    assert exchange_response.status_code == 200
    body = exchange_response.json()
    assert "access_token" in body
    assert "refresh_token" in body

    # Single-use — the same handoff code can't be exchanged twice.
    second_attempt = await client.post("/api/v1/auth/google/exchange", json={"code": handoff_code})
    assert second_attempt.status_code == 400


async def test_google_exchange_rejects_garbage_code(client):
    response = await client.post("/api/v1/auth/google/exchange", json={"code": "not-a-real-code"})
    assert response.status_code == 400


async def test_password_login_rejected_for_google_only_account(client, monkeypatch):
    monkeypatch.setattr(
        "app.modules.auth.router.exchange_code_for_tokens",
        lambda code: _async_return({"access_token": "fake-token"}),
    )
    monkeypatch.setattr(
        "app.modules.auth.router.get_google_user_info",
        lambda token: _async_return(_fake_google_user_info(email="googleonly@test.dev", sub="only-sub")),
    )
    client.cookies.set("bp_oauth_state", "s")
    await client.get(
        "/api/v1/auth/google/callback?code=fake-code&state=s",
        follow_redirects=False,
    )

    # No password was ever set for this account — attempting a normal
    # password login must fail cleanly (401), not crash (500).
    response = await client.post(
        "/api/v1/auth/login", data={"username": "googleonly@test.dev", "password": "anything123"}
    )
    assert response.status_code == 401


async def _async_return(value):
    return value
