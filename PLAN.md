# BridgePay — Backend Plan

## 1. What this is
A learning-project payments platform (PayPal-style) built by Abednego & Mark.
Goal: understand how real payment systems work internally — ledgers, transfers,
auth, and fraud/security patterns — not to launch a production product (yet).

## 2. Stack
- **Framework:** FastAPI (async, Pydantic-validated request/response models)
- **Background jobs:** Celery + Redis (for async tasks: notifications, delayed
  settlement, fraud checks)
- **Database:** Postgres (Neon)
- **ORM:** SQLAlchemy 2.0 (async) + Alembic for migrations
- **Auth:** JWT-based (OAuth2PasswordBearer), passwords hashed with bcrypt
- **Deploy target (later):** Render, same as your usual pattern

## 3. Core design principle: the ledger
Never mutate a balance field directly. Every money movement is an **immutable
transaction record**. A user's balance is always the *sum of their transaction
history*, not a stored number you update in place.

- `accounts` — one row per user, holds a cached balance (for fast reads) that
  is only ever updated by writing a new transaction row, inside a single DB
  transaction.
- `transactions` — immutable log: id, from_account, to_account, amount,
  currency, status, type (transfer/deposit/withdrawal), created_at.

This is the single most important lesson of the project — it's how every real
payment system (and accounting system) avoids "money disappearing" bugs.

## 4. Data models (v1)
- **User** — id, email, hashed_password, full_name, created_at, is_active
- **Account** — id, user_id (FK), balance (cached, derived), currency
- **Transaction** — id, from_account_id, to_account_id, amount, currency,
  status (pending/completed/failed), type, created_at, reference_note
- **PaymentMethod** (mocked) — id, user_id, type (card/bank - sandbox only),
  masked_details, is_verified

## 5. API surface (v1)
- `POST /auth/register`
- `POST /auth/login` → returns JWT
- `GET /users/me`
- `GET /accounts/me` → balance + account info
- `POST /transfers` → move money between two accounts (the core feature)
- `GET /transactions` → paginated history for logged-in user
- `GET /admin/transactions` → all transactions (admin-only, for fraud review)

## 6. Security checklist (this is where your cybersecurity focus comes in)
- Passwords: bcrypt, never plaintext, never logged
- JWT: short expiry + refresh token pattern
- Rate limiting on `/auth/login` and `/transfers` (prevent brute force / spam)
- Input validation via Pydantic on every endpoint (amounts must be positive,
  currency whitelisted, etc.)
- All money math in `Decimal`, never `float`
- Every transfer wrapped in a DB transaction with row-level locking to
  prevent race conditions (two simultaneous transfers draining an account
  below zero)
- Audit log: who did what, when — separate from the transaction table
- `.env` for secrets, never committed; `.gitignore` covers it from commit 1

## 7. Build order (phased, one small task at a time)
1. **Scaffolding** — folder structure, FastAPI app boots, `.env`/.gitignore,
   Postgres connection via Neon, first Alembic migration (empty)
2. **User + Auth** — register/login, JWT issuing, password hashing
3. **Accounts + Transactions models** — migrations for `accounts` and
   `transactions`, seed a couple of test accounts
4. **Transfer endpoint** — the core feature: move money between two accounts
   safely (this is where the ledger principle gets tested)
5. **Transaction history endpoint** — paginated, filterable
6. **Security hardening pass** — rate limiting, audit log, input edge cases
7. **Celery integration** — background task for e.g. "send transfer
   confirmation" (mocked, no real email needed yet)
8. **Admin view** — simple endpoint(s) to see all transactions, flag
   suspicious ones (great spot to build a basic fraud-detection rule later)

## 8. Explicitly out of scope for now
- Real payment rail integration (Stripe/Paystack) — sandbox mode only, later
- Multi-currency conversion logic
- Production deployment / real user data

## 9. Folder structure (proposed)
```
backend/
  app/
    api/
      auth.py
      accounts.py
      transfers.py
      transactions.py
      admin.py
    core/
      config.py       # settings, env vars
      security.py      # JWT, password hashing
    db/
      base.py
      session.py
    models/
      user.py
      account.py
      transaction.py
    schemas/          # Pydantic request/response models
      user.py
      account.py
      transaction.py
    services/         # business logic (kept out of route handlers)
      transfer_service.py
    main.py
  alembic/
  celery_app.py
  requirements.txt
  .env.example
  PLAN.md
```
