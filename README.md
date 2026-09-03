# BridgePay Backend

FastAPI backend for BridgePay — a learning-project PayPal-style payments
platform (auth, wallets, transfers, admin). See [PLAN.md](./PLAN.md) for the
full architecture and original phased build order.

## Team
- **Mark Musyoka** ([@Mark-Musyoka](https://github.com/Mark-Musyoka)) — owner
- **Abednego Ndimu** ([@abednegoingplaces](https://github.com/abednegoingplaces)) — collaborator
- **Franklin Tumaini** ([@Antony-debug-jpg](https://github.com/Antony-debug-jpg)) — collaborator, handling the database and frontend

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

## Codebase organization
The app is organized by domain module, not by file type — everything about
one feature lives together:

```
app/modules/<domain>/
  models.py       # SQLAlchemy models for this domain
  repository.py   # raw DB queries — the only place that talks to SQLAlchemy directly
  schemas.py      # Pydantic request/response shapes
  service.py       # business logic (only where there's real logic beyond CRUD)
  router.py        # FastAPI routes — thin, calls repository/service
  tasks.py          # Celery background tasks (auth, transfers only)
```

Modules: `users`, `auth`, `accounts`, `transactions`, `transfers`, `admin`,
`audit`. Cross-cutting auth dependencies (`get_current_user`,
`get_current_admin_user`, `get_current_verified_user`) live in
`app/core/dependencies.py` — they're used by nearly every module, so they
don't belong to any single one. `app/core/` also holds config, security
(JWT/password hashing), and rate limiting; `app/db/` holds the SQLAlchemy
base and session setup. See PLAN.md section 9 for the full tree.

To find how a feature works end-to-end: open its module folder — e.g.
everything about transfers (the model, the locking logic, the endpoint,
the confirmation email task) is in `app/modules/transfers/`.

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

**All 6 planned phases complete, plus refresh tokens (Phase 7), API
versioning, email verification/password reset (Phase 8), and a modular
codebase reorganization with a real bug-fix pass (Phase 9).** Every
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

### Deployment readiness (hardening pass)
Reviewed against a more mature sibling project's backend to catch gaps
before deploying:
- [x] CORS middleware — explicit `ALLOWED_ORIGINS` allow-list for the
  deployed frontend, plus a regex allowing any `localhost`/`127.0.0.1`
  port for local dev (so `npm run dev`'s random port never breaks CORS).
  Verified: allowed origin gets `access-control-allow-origin` back,
  `evil-site.com` does not.
- [x] Global exception handler — any unhandled exception returns a generic
  `{"detail": "Internal server error"}` to the client, while the real
  traceback goes to the server log. Verified by forcing a real DB failure
  mid-request: client got the generic message, server log had the full
  traceback. Deliberately does **not** echo `str(exc)` to the client —
  that leaks internal details (file paths, query fragments).
- [x] `render.yaml` — declarative Blueprint for both the web service and
  the Celery worker, so deployment isn't manual dashboard clicking.
  Secrets (`DATABASE_URL`, `JWT_SECRET_KEY`, etc.) are marked `sync: false`
  so Render prompts for them rather than storing them in the repo.
- [x] `Dockerfile` — containerized entrypoint, not just "run uvicorn
  directly."
- [x] Automated test suite (`pytest` + `httpx.AsyncClient`, 21 tests) —
  covers register/login/refresh/logout (including the token-reuse attack
  scenario), transfers (success, insufficient funds, self-transfer,
  nonexistent recipient, negative amount), and admin access control.
  Everything previously verified by hand via curl is now a regression test.
  Uses a dedicated `bridgepay_test` database with a fresh schema per test.
  Run with:
  ```bash
  pip install -r requirements-dev.txt
  pytest
  ```
  Fixed a real bug while wiring this up: the test DB engine was reused
  across tests with a connection pool, but pytest-asyncio gives each test
  its own event loop — a pooled connection from one loop is invalid in the
  next, causing `InterfaceError: another operation is in progress`. Fixed
  by using `NullPool` for the test engine (fresh connection per use,
  never reused across loops).

### API versioning
- [x] All endpoints now live under `/api/v1` (e.g. `/api/v1/auth/register`).
  The root health check (`/`) stays unversioned — `render.yaml`'s
  `healthCheckPath` and most infra tooling expect that. This was a breaking
  URL change; the frontend's PLAN.md contract was updated to match.

### Phase 8 — Email verification + password reset (post-plan addition)
Closes a gap found when reviewing the backend for missing standard flows.

- [x] `is_verified` flag on `User` (defaults `false`), `EmailVerificationToken`
  model — hashed, single-use, same pattern as `RefreshToken`
- [x] Registration issues a verification token and queues a mocked
  "send verification email" Celery task (logs the raw token; the raw
  token is never stored, only its hash)
- [x] `POST /auth/verify-email` — verified end-to-end: register → Celery
  logs the token → verify → `is_verified` flips to `true` → reusing the
  same token afterward correctly fails (single-use enforced)
- [x] **Transfers are gated behind verification** — a real business rule
  for a payments app, via a `get_current_verified_user` dependency
  (mirrors `get_current_admin_user`). Unverified users can register and
  log in, but `POST /transfers` returns `403` until they verify. Covered
  by its own test (`test_unverified_user_cannot_send_transfer`).
- [x] `POST /auth/password-reset-request` / `POST /auth/password-reset-confirm`
  — `PasswordResetToken` model, same hashed/single-use pattern. The
  request endpoint returns an identical `204` whether or not the email is
  registered (user-enumeration protection) — verified the Celery log only
  actually fires for real accounts, not fake ones.
- [x] **Resetting a password revokes every refresh token for that user** —
  a reset is a signal the account may have been compromised, so any
  existing session (stolen or not) is killed. Verified live: logged in
  before the reset, confirmed that pre-reset refresh token is dead
  afterward — not just asserted in a comment.

### Phase 9 — Modular reorganization + audit review (post-plan addition)
The codebase was flat (`app/api/`, `app/models/`, `app/schemas/`,
`app/repositories/`, `app/services/`, `app/tasks/` — each holding one file
per *feature* across all domains). Reorganized into
`app/modules/{users,auth,accounts,transactions,transfers,admin,audit}/`,
each holding its own `models.py`, `repository.py`, `schemas.py`, and
`router.py` (plus `service.py`/`tasks.py` where there's real business
logic beyond CRUD) — so a new dev can open one folder and see everything
about that domain, instead of hunting across five top-level folders for
the pieces of one feature. Cross-cutting auth dependencies
(`get_current_user`, `get_current_admin_user`, `get_current_verified_user`)
live in `app/core/dependencies.py` since they don't belong to any single
module.

This was a pure reorganization — no behavior change — verified by:
running all 22 tests unchanged after the move, and confirming
`alembic revision --autogenerate` produces an **empty** migration
(zero schema drift) after relocating every model.

Two real bugs were found and fixed during this review, both about missing
audit coverage:
- [x] `transfer_service.py` raised `HTTPException` directly for
  self-transfer / recipient-not-found / account-not-found, which meant
  those attempts were **never audit-logged** (only `InsufficientFundsError`
  was, since the router's `try/except` only caught that one case). Fixed
  by raising domain exceptions (`SelfTransferError`,
  `RecipientNotFoundError`, `AccountNotFoundError`) that the router now
  catches and logs individually. Verified live: all three failure modes
  now appear in `audit_logs` where two previously didn't.
- [x] `POST /auth/logout` had no audit trail at all, unlike every other
  auth action. Added a `log_action` call. Verified live.
- [x] `POST /auth/verify-email` and `POST /auth/logout` were also missing
  rate limiting entirely (no `@limiter.limit`), unlike every other auth
  endpoint. Fixed — verified live that the 11th rapid request to
  `verify-email` correctly gets `429`.
- [x] Failed attempts on `verify-email`, `refresh` (the plain
  invalid/expired case, not just reuse-detection), and
  `password-reset-confirm` were silently not written to the audit log —
  only successes and the reuse-detection case were. Fixed to match the
  pattern already used for `login_failed`.

Also found and fixed, unrelated to the reorg itself:
- [x] Schema drift: `AuditLog.ip_address` was declared `String(64)` in the
  model, but the actual migration/DB column was `String(45)` (the correct
  max length for an IPv6 address string) — the two had been out of sync
  since Phase 4 and nobody had re-run autogenerate to catch it. Fixed by
  aligning the model to the DB.
- [x] `UserResponse` didn't expose `is_verified` at all — the only way a
  frontend could learn a user's verification status was to get a `403` on
  a transfer attempt. Added the field.

## Explicitly not built
- **PaymentMethod** (mocked card/bank linking) — out of scope for now, see PLAN.md
- Real payment rail integration (Stripe/Paystack sandbox)
- Multi-currency conversion
- Production deployment
- OAuth/social login (email+password only)
- Rate limiting on `/auth/password-reset-request` and `/auth/verify-email`
  uses the same in-memory (per-process) limiter as everything else — see
  the note in Phase 4 about swapping to Redis-backed limits for a
  multi-instance deployment
