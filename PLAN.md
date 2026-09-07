# BridgePay — Backend Plan

**Status: all 6 original phases + Phases 7-12 (refresh tokens, versioning,
email verification/password reset, modular reorg, production-readiness
fixes, real Stripe+M-Pesa payments, Google OAuth) — see README.md for
verified detail.** This file is the original design plus a running
contract reference; README.md tracks what's actually running and tested.

## 1. What this is
A learning-project payments platform (PayPal-style) built by Abednego, Mark
& Franklin (see README.md's Team section for roles).
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

## 4. Data models (v1, now well beyond v1 — see README Phases 7-12)
- **User** — id, email, hashed_password (nullable — null for Google-only
  accounts), full_name, country (ISO alpha-2, nullable), is_active,
  is_admin, is_verified, google_id (nullable), stripe_customer_id
  (nullable), created_at
- **Account** — id, user_id (FK), balance (cached, derived), currency
- **Transaction** — id, from_account_id, to_account_id, amount, currency,
  status (pending/completed/failed), type (transfer/deposit/withdrawal),
  created_at, reference_note
- **AuditLog** — id, user_id (nullable), action, detail, ip_address, created_at
  — records who-did-what (including failed attempts), separate from the
  money-movement ledger above
- **RefreshToken / EmailVerificationToken / PasswordResetToken /
  OAuthHandoffCode** — all hashed, single-use tokens, same pattern
- **Notification** — id, user_id, type, title, body, is_read, created_at
- **PaymentMethod** — id, user_id, provider (stripe/mpesa), type
  (card/mobile_wallet), external_reference, masked_details, is_default
- **Deposit** — id, user_id, account_id, provider, status, amount,
  currency, external_reference, idempotency_key, failure_reason
- **Payout** — id, user_id, account_id, provider, destination_reference,
  recipient_email, amount, currency, status (pending/completed/failed/
  reversed), external_reference, idempotency_key, failure_reason

Built: **PaymentMethod** — real Stripe card linking + real M-Pesa phone
linking. See README Phase 11 for full detail; no longer out of scope.

## 5. API surface — all implemented, see README for status/testing detail
**Auth**
- `POST /auth/register` (now requires `country`)
- `POST /auth/login` → JWT access + refresh token
- `POST /auth/refresh`, `POST /auth/logout`
- `POST /auth/verify-email`, `POST /auth/resend-verification`
- `POST /auth/password-reset-request`, `POST /auth/password-reset-confirm`
- `GET /auth/google/login`, `GET /auth/google/callback`,
  `POST /auth/google/exchange` — Sign in with Google

**Users / settings**
- `GET /users/me`, `PATCH /users/me`, `POST /users/me/change-password`
- `GET /countries` (public, unauthenticated — for the signup dropdown)

**Money**
- `GET /accounts/me` → balance + account info
- `POST /transfers` → internal transfer between two BridgePay users
- `GET /transactions` → paginated history for logged-in user
- `GET /payment-methods`, `POST /payment-methods/stripe/setup-intent`,
  `POST /payment-methods/stripe/confirm`, `POST /payment-methods/mpesa`,
  `DELETE /payment-methods/{id}`
- `POST /deposits/stripe`, `POST /deposits/mpesa`, `GET /deposits`
- `POST /payouts/mpesa`, `POST /payouts/stripe-card`, `GET /payouts`
  (real external payouts — money leaves the platform)
- `POST /webhooks/stripe`, `POST /webhooks/mpesa/stk-callback`,
  `POST /webhooks/mpesa/b2c-result`, `POST /webhooks/mpesa/b2c-timeout`

**Other**
- `GET /notifications`, `POST /notifications/{id}/read`,
  `POST /notifications/read-all`
- `GET /admin/transactions` (optional `?user_email=`),
  `GET /admin/audit-logs` (optional `?action=`)

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
- Refresh tokens: hashed at rest, single-use with rotation, reuse
  detection revokes every session for that user
- Stripe webhook signatures verified; M-Pesa callbacks processed
  idempotently (Daraja doesn't sign callbacks at all — documented
  limitation, see README Phase 11)
- External payouts: balance deducted before the external API call
  (locked, same discipline as transfers), reversed via a second
  immutable transaction if the payout fails at any point
- Idempotency keys on deposits/payouts prevent a retried request from
  double-charging or double-deducting
- OAuth CSRF protection (state cookie) on the Google sign-in flow;
  OAuth handoff codes are single-use and never appear as real tokens in
  a redirect URL

## 7. Build order (phased, one small task at a time)
1. [x] **Scaffolding** — folder structure, FastAPI app boots, `.env`/.gitignore,
   Postgres connection via Neon, first Alembic migration (empty)
2. [x] **User + Auth** — register/login, JWT issuing, password hashing
3. [x] **Accounts + Transactions models** — migrations for `accounts` and
   `transactions`, seed a couple of test accounts
4. [x] **Transfer endpoint** — the core feature: move money between two accounts
   safely (this is where the ledger principle gets tested)
5. [x] **Transaction history endpoint** — paginated, filterable
6. [x] **Security hardening pass** — rate limiting, audit log, input edge cases
7. [x] **Celery integration** — background task for e.g. "send transfer
   confirmation" (mocked, no real email needed yet)
8. [x] **Admin view** — simple endpoint(s) to see all transactions, flag
   suspicious ones (great spot to build a basic fraud-detection rule later)

Phases 7-12 (refresh tokens, API versioning, email verification/password
reset, the modular reorg, production-readiness fixes, and the full
country/notifications/settings/payments/Google-OAuth feature set) all
happened after this original 8-item build order — see README.md for the
complete, dated history of each.

## 8. Explicitly out of scope for now
- Real bank-account-number payouts (card token + M-Pesa phone payouts
  are built; raw bank routing/account number flow is not — format
  varies by country and wasn't specified)
- Airtel Money integration
- Multi-currency conversion logic (each payout method stays in its own
  native currency)
- Production deployment / real user data

## 9. Folder structure (as built — reorganized into modules in Phase 9,
see README.md for the full rationale and the audit-review bug fixes that
came out of it)
```
BridgePay-Backend/
  app/
    core/
      config.py          # settings, env vars
      security.py         # JWT, password hashing, shared token generate/hash helpers
      limiter.py           # rate limiting (slowapi, Redis-backed)
      dependencies.py      # get_current_user, get_current_admin_user,
                            # get_current_verified_user — cross-cutting,
                            # used by nearly every module
      countries.py          # static ISO 3166-1 country list
      stripe_client.py       # shared Stripe SDK config
      mpesa_client.py         # shared Daraja OAuth/STK/B2C primitives
      google_client.py         # shared Google OAuth primitives
    db/
      base.py
      session.py
    modules/
      users/
        models.py           # User (now incl. country, google_id, stripe_customer_id)
        repository.py
        schemas.py
        service.py            # profile update, change password
        router.py              # /users/me (GET/PATCH), /change-password, /countries
      auth/
        models.py           # RefreshToken, EmailVerificationToken,
                             # PasswordResetToken, OAuthHandoffCode
        repository.py
        schemas.py
        service.py            # refresh rotation + reuse detection, email
                               # verification, password reset, Google
                               # find-or-create, OAuth handoff codes
        tasks.py               # mocked send_verification_email, send_password_reset_email
        router.py               # /auth/register, /login, /refresh, /logout,
                                 # /verify-email, /resend-verification,
                                 # /password-reset-*, /google/*
      accounts/
        models.py           # Account
        repository.py
        schemas.py
        router.py            # GET /accounts/me
      transactions/
        models.py           # Transaction (shared with transfers/deposits/payouts)
        repository.py
        schemas.py
        router.py            # GET /transactions
      transfers/
        schemas.py
        service.py            # execute_transfer — the row-locking logic
        tasks.py               # mocked send_transfer_confirmation
        router.py               # POST /transfers
      notifications/
        models.py           # Notification
        repository.py
        schemas.py
        service.py            # notify() — single entry point every other
                               # module calls into
        tasks.py               # mocked send_notification_email
        router.py               # GET /notifications, mark-read endpoints
      payment_methods/
        models.py           # PaymentMethod
        repository.py
        schemas.py
        service.py            # real Stripe SetupIntent flow, M-Pesa phone linking
        router.py            # /payment-methods/*
      deposits/
        models.py           # Deposit
        repository.py
        schemas.py
        service.py            # real Stripe PaymentIntent + M-Pesa STK Push,
                               # webhook-driven crediting, idempotent
        router.py             # /deposits/*
      payouts/
        models.py           # Payout
        repository.py
        schemas.py
        service.py            # real M-Pesa B2C + Stripe card payouts,
                               # deduct-first/reverse-on-failure
        router.py             # /payouts/*
      webhooks/
        router.py            # /webhooks/stripe, /webhooks/mpesa/*
                              # (no models/service of its own — calls into
                              # deposits/payouts services)
      admin/
        router.py            # GET /admin/transactions, /admin/audit-logs
                              # (reads across accounts/transactions/audit/users,
                              # no models of its own)
      audit/
        models.py           # AuditLog
        repository.py
        schemas.py
        service.py            # log_action — called from every other module
    main.py
  alembic/
  tests/
  celery_app.py
  requirements.txt
  requirements-dev.txt
  pytest.ini
  Dockerfile
  render.yaml
  .env.example
  PLAN.md
  README.md
```
