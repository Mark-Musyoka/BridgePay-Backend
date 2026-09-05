async def register(client, email="alice@test.dev", password="testpass123", full_name="Alice", country="KE"):
    return await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": full_name, "country": country},
    )


async def login(client, email="alice@test.dev", password="testpass123"):
    return await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password},
    )


async def test_register_creates_user_and_account(client):
    response = await register(client)
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "alice@test.dev"
    assert body["is_active"] is True


async def test_register_duplicate_email_rejected(client):
    await register(client)
    response = await register(client)
    assert response.status_code == 400


async def test_register_with_invalid_country_code_rejected(client):
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "bad-country@test.dev", "password": "testpass123", "full_name": "Bad", "country": "ZZ"},
    )
    assert response.status_code == 422


async def test_register_lowercases_country_code(client):
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "lower@test.dev", "password": "testpass123", "full_name": "Lower", "country": "ke"},
    )
    assert response.status_code == 201
    assert response.json()["country"] == "KE"


async def test_public_countries_endpoint_requires_no_auth(client):
    response = await client.get("/api/v1/countries")
    assert response.status_code == 200
    body = response.json()
    assert len(body) > 100  # sanity check it's the real ~249-entry list, not empty
    assert {"code": "KE", "name": "Kenya"} in body


async def test_login_wrong_password_rejected(client):
    await register(client)
    response = await login(client, password="wrongpassword")
    assert response.status_code == 401


async def test_login_success_returns_both_tokens(client):
    await register(client)
    response = await login(client)
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"


async def test_me_requires_valid_token(client):
    response = await client.get("/api/v1/users/me")
    assert response.status_code == 401


async def test_me_returns_current_user_with_valid_token(client):
    await register(client)
    login_response = await login(client)
    token = login_response.json()["access_token"]

    response = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == "alice@test.dev"


async def test_refresh_rotates_tokens(client):
    await register(client)
    login_response = await login(client)
    old_refresh = login_response.json()["refresh_token"]

    refresh_response = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert refresh_response.status_code == 200
    new_tokens = refresh_response.json()
    assert new_tokens["refresh_token"] != old_refresh


async def test_refresh_token_reuse_is_detected_and_revokes_session(client):
    await register(client)
    login_response = await login(client)
    original_refresh = login_response.json()["refresh_token"]

    first_refresh = await client.post("/api/v1/auth/refresh", json={"refresh_token": original_refresh})
    assert first_refresh.status_code == 200
    rotated_refresh = first_refresh.json()["refresh_token"]

    # Replaying the already-used original token should be rejected...
    replay_response = await client.post("/api/v1/auth/refresh", json={"refresh_token": original_refresh})
    assert replay_response.status_code == 401

    # ...and should have revoked the legitimately-rotated token too, since
    # a replay is treated as a signal the session may be compromised.
    followup_response = await client.post("/api/v1/auth/refresh", json={"refresh_token": rotated_refresh})
    assert followup_response.status_code == 401


async def test_logout_revokes_refresh_token(client):
    await register(client)
    login_response = await login(client)
    refresh_token = login_response.json()["refresh_token"]

    logout_response = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})
    assert logout_response.status_code == 204

    reuse_response = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert reuse_response.status_code == 401


def _capture_verification_token(monkeypatch):
    """Verification emails are mocked (queued to Celery, never actually
    sent) — this captures the raw token from the task call args instead,
    so tests can complete the verify-email flow without a running worker."""
    captured = {}

    def fake_delay(to_email, raw_token):
        captured["token"] = raw_token
        captured["to_email"] = to_email

    monkeypatch.setattr("app.modules.auth.router.send_verification_email.delay", fake_delay)
    return captured


async def test_verify_email_with_valid_token(client, monkeypatch):
    captured = _capture_verification_token(monkeypatch)
    await register(client)

    response = await client.post("/api/v1/auth/verify-email", json={"token": captured["token"]})
    assert response.status_code == 204

    login_response = await login(client)
    me_response = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {login_response.json()['access_token']}"},
    )
    assert me_response.json()["is_verified"] is True


async def test_verify_email_with_invalid_token_rejected(client):
    response = await client.post("/api/v1/auth/verify-email", json={"token": "not-a-real-token"})
    assert response.status_code == 400


async def test_verify_email_token_is_single_use(client, monkeypatch):
    captured = _capture_verification_token(monkeypatch)
    await register(client)
    token = captured["token"]

    first = await client.post("/api/v1/auth/verify-email", json={"token": token})
    assert first.status_code == 204

    second = await client.post("/api/v1/auth/verify-email", json={"token": token})
    assert second.status_code == 400


async def test_resend_verification_requires_auth(client):
    response = await client.post("/api/v1/auth/resend-verification")
    assert response.status_code == 401


async def test_resend_verification_issues_a_new_usable_token(client, monkeypatch):
    captured = _capture_verification_token(monkeypatch)
    await register(client)
    original_token = captured["token"]

    login_response = await login(client)
    access_token = login_response.json()["access_token"]

    resend_response = await client.post(
        "/api/v1/auth/resend-verification", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert resend_response.status_code == 204
    new_token = captured["token"]
    assert new_token != original_token

    # Unlike refresh tokens, resending a verification email does NOT
    # revoke the previously issued one — there's no real risk in an old
    # verification link staying valid (it can only idempotently confirm
    # the same account, not escalate privilege or leak anything), and
    # letting old links keep working is reasonable UX. Both the original
    # and the resent token should work.
    stale_attempt = await client.post("/api/v1/auth/verify-email", json={"token": original_token})
    assert stale_attempt.status_code == 204

    # The new token is now moot (account is already verified), but the
    # endpoint should still respond successfully rather than error.
    fresh_attempt = await client.post("/api/v1/auth/verify-email", json={"token": new_token})
    assert fresh_attempt.status_code == 204


async def test_resend_verification_rejected_once_already_verified(client, monkeypatch):
    captured = _capture_verification_token(monkeypatch)
    await register(client)
    await client.post("/api/v1/auth/verify-email", json={"token": captured["token"]})

    login_response = await login(client)
    access_token = login_response.json()["access_token"]

    response = await client.post(
        "/api/v1/auth/resend-verification", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert response.status_code == 400
