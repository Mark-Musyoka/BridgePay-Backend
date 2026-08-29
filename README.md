# BridgePay Backend

FastAPI backend for BridgePay, a learning-project payments platform
(PayPal-style). See [PLAN.md](./PLAN.md) for the full architecture and
original phased build order.

## Team
- **Abednego Ndimu** ([@abednegoingplaces](https://github.com/abednegoingplaces)) — collaborator
- **Mark Musyoka** ([@Mark-Musyoka](https://github.com/Mark-Musyoka)) — owner

## Tech stack
- FastAPI (async) + Pydantic
- SQLAlchemy 2.0 (async) + Alembic migrations
- Postgres (Neon)
- Celery + Redis for background jobs
- JWT auth (python-jose), bcrypt for password hashing
- Rate limiting (slowapi)
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

## Run the background worker
Requires Redis running locally (`CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND`
in `.env`). Start the worker separately from the API:

```bash
celery -A celery_app worker --loglevel=info
```

On Windows, add `--pool=solo` (Celery's default prefork pool isn't supported
there).

## Status

**All 6 planned phases complete, plus refresh tokens (Phase 7).** Every
endpoint has been tested against a
real running Postgres + Redis + Celery stack — registered users, executed
real transfers, triggered rate limits, confirmed worker output — not just
written and assumed to work.

### Phase 1 — Scaffolding
- [x] Folder structure, FastAPI app boots (`GET /` health check)
- [x] Alembic wired to an async DB engine

### Phase 2 — User + Auth
- [x] User model + `users` table migration
- [x] `POST /auth/register`, `POST /auth/login` → JWT, `GET /users/me`
- [x] Password hashing via `bcrypt` directly, **not** `passlib` — `passlib`
  is unmaintained and its bcrypt backend breaks on bcrypt >=4.1 (a
  version-detection bug); calling `bcrypt.hashpw` / `bcrypt.checkpw`
  directly avoids this entirely

### Phase 3 — Accounts + Transactions
- [x] Account model — auto-created for every user at registration, balance
  starts at 0.00
- [x] Transaction model — immutable ledger, enums for status/type
- [x] `GET /accounts/me`, `GET /transactions` (paginated)
- [x] `POST /transfers` — the core feature. `transfer_service.py` locks both
  accounts with `SELECT ... FOR UPDATE`, in a fixed order by account id,
  *before* checking the balance — so two simultaneous transfers can't both
  pass a stale balance check, and two transfers in opposite directions
  between the same accounts can't deadlock each other. Verified against:
  successful transfer, insufficient funds, self-transfer, nonexistent
  recipient, invalid (negative) amount.

### Phase 4 — Security hardening
- [x] Rate limiting (IP-keyed): `/auth/register` 5/min, `/auth/login`
  10/min, `/transfers` 20/min
- [x] Audit log (`audit_logs` table) — separate from the transaction
  ledger on purpose: transactions record money movement, audit logs
  record *who did what*, including failed attempts that never touch the
  ledger at all. Tracks register, login success/failure, transfer
  success/failure, with IP address.

### Phase 5 — Celery background job
- [x] Mocked transfer-confirmation task, queued after a successful
  transfer via `.delay()`, wrapped in try/except so a broker outage never
  breaks a transfer that's already succeeded and committed

### Phase 6 — Admin view
- [x] `is_admin` flag on `users`, defaults `false` — no signup flow grants
  it. Promote a user directly in the DB for local dev:
  ```sql
  UPDATE users SET is_admin = true WHERE email = 'you@example.com';
  ```
- [x] `GET /admin/transactions` (optional `?user_email=` filter) and
  `GET /admin/audit-logs` (optional `?action=` filter) — both admin-only,
  a non-admin token gets `403`, no token gets `401`

### Phase 7 — Refresh tokens (post-plan addition)
The original plan called for "JWT short expiry + refresh token pattern" but
only shipped the short-expiry access token. This closes that gap:
- [x] `refresh_tokens` table — tokens stored **hashed** (SHA-256), never raw
- [x] Login now returns both `access_token` and `refresh_token`
- [x] `POST /auth/refresh` — single-use rotation: presenting a refresh token
  issues a new access + refresh token pair and immediately revokes the one
  used
- [x] **Reuse detection**: presenting an already-revoked refresh token (i.e.
  a token that's already been rotated once) is treated as a signal of theft
  — every refresh token for that user is revoked immediately, forcing
  re-login on all devices. Verified: rotate once (works), replay the
  original token (401 + full revocation), then confirm the *second*
  (previously valid) token is also dead.
- [x] `POST /auth/logout` — revokes a specific refresh token

## Explicitly not built
- **PaymentMethod** (mocked card/bank linking) — out of scope for now, see PLAN.md
- Real payment rail integration (Stripe/Paystack sandbox)
- Multi-currency conversion
- Production deployment
