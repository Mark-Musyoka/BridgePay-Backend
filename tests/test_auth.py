async def register(client, email="alice@test.dev", password="testpass123", full_name="Alice"):
    return await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
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
