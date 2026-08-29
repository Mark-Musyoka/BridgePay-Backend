# BridgePay Backend

FastAPI backend for BridgePay, a learning-project payments platform
(PayPal-style). See [PLAN.md](./PLAN.md) for the full architecture and
phased build order.

## Team
- **Abednego Ndimu** ([@abednegoingplaces](https://github.com/abednegoingplaces)) — collaborator
- **Mark Musyoka** ([@Mark-Musyoka](https://github.com/Mark-Musyoka)) — owner

## Tech stack
- FastAPI (async) + Pydantic
- SQLAlchemy 2.0 (async) + Alembic migrations
- Postgres (Neon)
- Celery + Redis for background jobs
- JWT auth (python-jose), bcrypt for password hashing
- Deployed on Render
- Paired with [BridgePay-Frontend](https://github.com/Mark-Musyoka/BridgePay-Frontend)
  (Next.js)

## Timeline
This is a learning project, not a race to launch — no fixed deadline. Built
incrementally in phases (see PLAN.md), picked up as time allows.

## Related repo
This is the backend only. The frontend client lives in a separate repo:
[BridgePay-Frontend](https://github.com/Mark-Musyoka/BridgePay-Frontend)

```bash
git clone https://github.com/Mark-Musyoka/BridgePay-Frontend.git
```

## Setup

```bash
git clone https://github.com/Mark-Musyoka/BridgePay-Backend.git
cd BridgePay-Backend
python3 -m venv venv
source venv/bin/activate   # or venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env       # then fill in real values
```

## Run the app

```bash
uvicorn app.main:app --reload
```

Visit `http://127.0.0.1:8000/docs` for the interactive API docs, or
`http://127.0.0.1:8000/` for the health check.

## Run migrations

```bash
alembic upgrade head
```

## Status

**Phase 1 — Scaffolding**
- [x] Folder structure
- [x] FastAPI app boots (`GET /` health check)
- [x] Alembic wired to async DB engine

**Phase 2 — User + Auth**
- [x] User model + `users` table migration
- [x] Password hashing (bcrypt, used directly — see note below)
- [x] `POST /auth/register`
- [x] `POST /auth/login` → JWT access token
- [x] `GET /users/me` (protected route, proves the auth flow end-to-end)

**Phase 3 — Accounts + Transactions**
- [x] Account model (auto-created for every user at registration, balance starts at 0.00)
- [x] Transaction model (immutable ledger, enums for status/type)
- [x] `GET /accounts/me`
- [x] `POST /transfers` — the core feature, row-locked to prevent race conditions
- [x] `GET /transactions` — paginated history

**Phase 4 — Security hardening**
- [x] Rate limiting: `/auth/register` (5/min), `/auth/login` (10/min), `/transfers` (20/min) — keyed by IP
- [x] Audit log (`audit_logs` table) — separate from the transaction ledger,
  tracks register, login success/failure, and transfer success/failure, with
  IP address
- [x] Celery background job for transfer confirmation (Phase 5) — mocked
  notification, queued after a successful transfer, non-blocking
- [x] Admin view — list/flag all transactions (Phase 6)

### Admin access (Phase 6)
`is_admin` is a boolean on `users`, defaulting to `false` — no signup flow
grants it. For local dev, promote a user directly in the DB:

```sql
UPDATE users SET is_admin = true WHERE email = 'you@example.com';
```

`GET /admin/transactions` (optionally filtered by `?user_email=`) and
`GET /admin/audit-logs` (optionally filtered by `?action=`) are both
admin-only — a non-admin token gets `403`, no token gets `401`.

### Running the background worker (Phase 5)
Requires Redis running locally (`CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND`
in `.env`). Start the worker separately from the API:

```bash
celery -A celery_app worker --loglevel=info
```

On Windows, add `--pool=solo` (Celery's default prefork pool isn't supported
there).

### Note on transfer safety
`transfer_service.py` locks both accounts with `SELECT ... FOR UPDATE`, in a
fixed order by account id, before checking the balance — so two simultaneous
transfers can't both pass a stale balance check, and two transfers in
opposite directions between the same accounts can't deadlock each other.
Verified against: successful transfer, insufficient funds, self-transfer,
nonexistent recipient, and invalid (negative) amount.

### Note on password hashing
We use the `bcrypt` library directly rather than `passlib`. `passlib` is
unmaintained and its bcrypt backend breaks on bcrypt >=4.1 (a version-detection
bug). Calling `bcrypt.hashpw` / `bcrypt.checkpw` directly avoids this.
