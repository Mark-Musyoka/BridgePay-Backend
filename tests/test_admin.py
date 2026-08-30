from sqlalchemy import select

from app.models.user import User

from tests.test_auth import login, register


async def _make_admin(db_session, email: str):
    result = await db_session.execute(select(User).where(User.email == email))
    user = result.scalar_one()
    user.is_admin = True
    await db_session.commit()


async def test_non_admin_gets_403(client):
    await register(client, email="regular@test.dev", full_name="Regular")
    token = (await login(client, email="regular@test.dev")).json()["access_token"]

    response = await client.get("/api/v1/admin/transactions", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


async def test_no_token_gets_401(client):
    response = await client.get("/api/v1/admin/transactions")
    assert response.status_code == 401


async def test_admin_can_access_transactions(client, db_session):
    await register(client, email="root@test.dev", full_name="Root")
    await _make_admin(db_session, "root@test.dev")
    token = (await login(client, email="root@test.dev")).json()["access_token"]

    response = await client.get("/api/v1/admin/transactions", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["total"] == 0


async def test_admin_can_access_audit_logs(client, db_session):
    await register(client, email="root2@test.dev", full_name="Root")
    await _make_admin(db_session, "root2@test.dev")
    token = (await login(client, email="root2@test.dev")).json()["access_token"]

    response = await client.get("/api/v1/admin/audit-logs", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["total"] >= 1  # at least the register/login events above
