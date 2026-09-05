from decimal import Decimal

from tests.test_transfers import _fund_account, _register_and_login
from tests.test_auth import register


async def test_transfer_notifies_both_sender_and_recipient(client, db_session):
    sender_token = await _register_and_login(client, "wendy@test.dev", "Wendy")
    await register(client, email="xavier@test.dev", full_name="Xavier")
    await _fund_account(db_session, "wendy@test.dev", "200.00")

    await client.post(
        "/api/v1/transfers",
        headers={"Authorization": f"Bearer {sender_token}"},
        json={"to_email": "xavier@test.dev", "amount": "30.00"},
    )

    sender_notifs = await client.get(
        "/api/v1/notifications", headers={"Authorization": f"Bearer {sender_token}"}
    )
    assert sender_notifs.status_code == 200
    body = sender_notifs.json()
    assert body["total"] == 1
    assert body["items"][0]["type"] == "transfer_sent"
    assert body["unread_count"] == 1

    recipient_login = await client.post(
        "/api/v1/auth/login", data={"username": "xavier@test.dev", "password": "testpass123"}
    )
    recipient_token = recipient_login.json()["access_token"]

    recipient_notifs = await client.get(
        "/api/v1/notifications", headers={"Authorization": f"Bearer {recipient_token}"}
    )
    assert recipient_notifs.status_code == 200
    r_body = recipient_notifs.json()
    assert r_body["total"] == 1
    assert r_body["items"][0]["type"] == "transfer_received"


async def test_mark_notification_read(client, db_session):
    token = await _register_and_login(client, "yusuf@test.dev", "Yusuf")
    await register(client, email="zara@test.dev", full_name="Zara")
    await _fund_account(db_session, "yusuf@test.dev", "100.00")
    await client.post(
        "/api/v1/transfers",
        headers={"Authorization": f"Bearer {token}"},
        json={"to_email": "zara@test.dev", "amount": "10.00"},
    )

    notifs = await client.get("/api/v1/notifications", headers={"Authorization": f"Bearer {token}"})
    notif_id = notifs.json()["items"][0]["id"]

    read_response = await client.post(
        f"/api/v1/notifications/{notif_id}/read", headers={"Authorization": f"Bearer {token}"}
    )
    assert read_response.status_code == 204

    after = await client.get("/api/v1/notifications", headers={"Authorization": f"Bearer {token}"})
    assert after.json()["unread_count"] == 0


async def test_mark_read_for_nonexistent_notification_returns_404(client):
    token = await _register_and_login(client, "amir@test.dev", "Amir")
    response = await client.post(
        "/api/v1/notifications/00000000-0000-0000-0000-000000000000/read",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


async def test_notifications_require_auth(client):
    response = await client.get("/api/v1/notifications")
    assert response.status_code == 401
