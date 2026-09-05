from tests.test_auth import login, register


async def test_update_profile_full_name_and_country(client):
    await register(client, email="dana@test.dev", full_name="Dana")
    login_response = await login(client, email="dana@test.dev")
    token = login_response.json()["access_token"]

    response = await client.patch(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"full_name": "Dana Updated", "country": "NG"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["full_name"] == "Dana Updated"
    assert body["country"] == "NG"


async def test_changing_email_resets_verification_and_notifies(client, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "app.modules.users.service.send_verification_email.delay",
        lambda to_email, raw_token: captured.update(to_email=to_email, token=raw_token),
    )

    await register(client, email="ethan@test.dev", full_name="Ethan")
    login_response = await login(client, email="ethan@test.dev")
    token = login_response.json()["access_token"]

    response = await client.patch(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "ethan-new@test.dev"},
    )
    assert response.status_code == 200
    assert response.json()["email"] == "ethan-new@test.dev"
    assert response.json()["is_verified"] is False
    assert captured["to_email"] == "ethan-new@test.dev"

    notifs = await client.get("/api/v1/notifications", headers={"Authorization": f"Bearer {token}"})
    assert notifs.json()["items"][0]["type"] == "account_update"


async def test_cannot_change_email_to_one_already_taken(client):
    await register(client, email="felix@test.dev", full_name="Felix")
    await register(client, email="gabby@test.dev", full_name="Gabby")
    login_response = await login(client, email="felix@test.dev")
    token = login_response.json()["access_token"]

    response = await client.patch(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "gabby@test.dev"},
    )
    assert response.status_code == 400


async def test_change_password_with_wrong_current_password_rejected(client):
    await register(client, email="hana@test.dev", full_name="Hana")
    login_response = await login(client, email="hana@test.dev")
    token = login_response.json()["access_token"]

    response = await client.post(
        "/api/v1/users/me/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "wrongpass", "new_password": "newpass456"},
    )
    assert response.status_code == 400


async def test_change_password_revokes_existing_sessions(client):
    await register(client, email="ivan@test.dev", full_name="Ivan")
    login_response = await login(client, email="ivan@test.dev")
    access_token = login_response.json()["access_token"]
    old_refresh_token = login_response.json()["refresh_token"]

    change_response = await client.post(
        "/api/v1/users/me/change-password",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"current_password": "testpass123", "new_password": "newpass456"},
    )
    assert change_response.status_code == 204

    old_login = await client.post(
        "/api/v1/auth/login", data={"username": "ivan@test.dev", "password": "testpass123"}
    )
    assert old_login.status_code == 401

    new_login = await client.post(
        "/api/v1/auth/login", data={"username": "ivan@test.dev", "password": "newpass456"}
    )
    assert new_login.status_code == 200

    refresh_attempt = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh_token})
    assert refresh_attempt.status_code == 401
