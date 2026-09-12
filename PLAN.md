# BridgePay — Backend Plan

**Status: all 6 original phases + Phases 7-13 (refresh tokens, versioning,
email verification/password reset, modular reorg, production-readiness
fixes, real Stripe+M-Pesa payments, Google OAuth, multi-currency
conversion) — see README.md for verified detail.** This file is the
original design plus a running contract reference; README.md tracks
what's actually running and tested.

## 1. What this is
A learning-project payments platform (PayPal-style) built by Abednego, Mark
& Franklin (see README.md's Team section for roles).
Goal: understand how real payment systems work internally — ledgers, transfers,
auth, and fraud/security patterns — not to launch a production product (yet).

## 2. Stack
| Layer | Choice |
|---|---|
| Framework | FastAPI (async, Pydantic-validated request/response models) |
| Background jobs | Celery + Redis (notifications, delayed settlement, fraud checks) |
| Database | Postgres (Neon) |
| ORM / migrations | SQLAlchemy 2.0 (async) + Alembic |
| Auth | JWT-based (OAuth2PasswordBearer), passwords hashed with bcrypt |
| Deploy target | Render |

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

## 4. Data models (v1, now well beyond v1 — see README Phases 7-13)
| Model | Key fields |
|---|---|
| `User` | id, email, hashed_password (nullable — null for Google-only accounts), full_name, country (ISO alpha-2, nullable), is_active, is_admin, is_verified, google_id (nullable), stripe_customer_id (nullable), created_at |
| `Account` | id, user_id (FK), balance (cached, derived), currency |
| `Transaction` | id, from_account_id, to_account_id, amount, currency, status (pending/completed/failed), type (transfer/deposit/withdrawal), created_at, reference_note — the immutable ledger |
| `AuditLog` | id, user_id (nullable), action, detail, ip_address, created_at — who-did-what, including failed attempts, separate from the ledger above |
| `RefreshToken` / `EmailVerificationToken` / `PasswordResetToken` / `OAuthHandoffCode` | All hashed, single-use tokens, same pattern |
| `Notification` | id, user_id, type, title, body, is_read, created_at |
| `PaymentMethod` | id, user_id, provider (stripe/mpesa), type (card/mobile_wallet), external_reference, masked_details, is_default |
| `Deposit` | id, user_id, account_id, provider, status, amount, currency, exchange_rate (nullable), converted_amount (nullable), external_reference, idempotency_key, failure_reason |
| `Payout` | id, user_id, account_id, provider, destination_reference, recipient_email, amount, currency, exchange_rate (nullable), converted_amount (nullable), status (pending/completed/failed/reversed), external_reference, idempotency_key, failure_reason |

Built: **PaymentMethod** — real Stripe card linking + real M-Pesa phone
linking. See README Phase 11 for full detail; no longer out of scope.

## 5. API surface — all implemented, see README for status/testing detail

| Category | Endpoint | Notes |
|---|---|---|
| Auth | `POST /auth/register` | Now requires `country` |
| Auth | `POST /auth/login` | Returns JWT access + refresh token |
| Auth | `POST /auth/refresh` | |
| Auth | `POST /auth/logout` | |
| Auth | `POST /auth/verify-email` | |
| Auth | `POST /auth/resend-verification` | |
| Auth | `POST /auth/password-reset-request` | |
| Auth | `POST /auth/password-reset-confirm` | |
| Auth | `GET /auth/google/login` | Sign in with Google |
| Auth | `GET /auth/google/callback` | |
| Auth | `POST /auth/google/exchange` | |
| Users / settings | `GET /users/me`, `PATCH /users/me` | |
| Users / settings | `POST /users/me/change-password` | |
| Users / settings | `GET /countries` | Public, unauthenticated — for the signup dropdown |
| Money | `GET /accounts/me` | Balance + account info |
| Money | `POST /transfers` | Internal transfer between two BridgePay users |
| Money | `GET /transactions` | Paginated history for logged-in user |
| Money | `GET /payment-methods` | |
| Money | `POST /payment-methods/stripe/setup-intent`, `POST /payment-methods/stripe/confirm` | |
| Money | `POST /payment-methods/mpesa` | |
| Money | `DELETE /payment-methods/{id}` | |
| Money | `POST /deposits/stripe`, `POST /deposits/mpesa`, `GET /deposits` | |
| Money | `POST /payouts/mpesa`, `POST /payouts/stripe-card`, `GET /payouts` | Real external payouts — money leaves the platform |
| Money | `POST /webhooks/stripe` | |
| Money | `POST /webhooks/mpesa/stk-callback`, `POST /webhooks/mpesa/b2c-result`, `POST /webhooks/mpesa/b2c-timeout` | |
| Other | `GET /notifications`, `POST /notifications/{id}/read`, `POST /notifications/read-all` | |
| Other | `GET /admin/transactions` | Optional `?user_email=` filter |
| Other | `GET /admin/audit-logs` | Optional `?action=` filter |

## 6. Security checklist (this is where your cybersecurity focus comes in)
| Measure | Detail |
|---|---|
| Password storage | bcrypt, never plaintext, never logged |
| JWT | Short expiry + refresh token pattern |
| Rate limiting | On `/auth/login` and `/transfers` (prevent brute force / spam) |
| Input validation | Pydantic on every endpoint (amounts must be positive, currency whitelisted, etc.) |
| Money math | Always `Decimal`, never `float` |
| Concurrency safety | Every transfer wrapped in a DB transaction with row-level locking (prevents two simultaneous transfers draining an account below zero) |
| Audit log | Who did what, when — separate from the transaction table |
| Secrets | `.env` never committed; `.gitignore` covers it from commit 1 |
| Refresh tokens | Hashed at rest, single-use with rotation, reuse detection revokes every session for that user |
| Webhooks | Stripe signatures verified; M-Pesa callbacks processed idempotently (Daraja doesn't sign callbacks at all — documented limitation, see README Phase 11) |
| External payouts | Balance deducted before the external API call (locked, same discipline as transfers), reversed via a second immutable transaction if the payout fails at any point |
| Idempotency | Keys on deposits/payouts prevent a retried request from double-charging or double-deducting |
| OAuth | CSRF protection (state cookie) on the Google sign-in flow; handoff codes are single-use and never appear as real tokens in a redirect URL |

## 7. Build order (phased, one small task at a time)
| # | Phase | Status |
|---|---|---|
| 1 | Scaffolding — folder structure, FastAPI app boots, `.env`/.gitignore, Postgres connection via Neon, first Alembic migration (empty) | [x] |
| 2 | User + Auth — register/login, JWT issuing, password hashing | [x] |
| 3 | Accounts + Transactions models — migrations, seed test accounts | [x] |
| 4 | Transfer endpoint — the core feature, ledger principle tested here | [x] |
| 5 | Transaction history endpoint — paginated, filterable | [x] |
| 6 | Security hardening pass — rate limiting, audit log, input edge cases | [x] |
| 7 | Celery integration — background task for "send transfer confirmation" (mocked) | [x] |
| 8 | Admin view — see all transactions, flag suspicious ones | [x] |

Phases 7-13 (refresh tokens, API versioning, email verification/password
reset, the modular reorg, production-readiness fixes, the full
country/notifications/settings/payments/Google-OAuth feature set, and
multi-currency deposit/payout conversion) all happened after this
original 8-item build order — see README.md for the complete, dated
history of each.

## 8. Way forward (next up, in priority order)
The three items originally deferred out of Phase 11 were Airtel Money,
bank-account payouts, and multi-currency conversion — see that phase's
README writeup. Multi-currency conversion (Phase 13) is now done; these
two remain:

| # | Item | Notes |
|---|---|---|
| 1 | Airtel Money integration | STK-style push deposit/payout, same shape as the existing M-Pesa module (`airtel_client.py`, deposit/payout endpoints, webhooks) |
| 2 | Bank-account payouts | Kenyan account number + bank code, and international IBAN/SWIFT — likely via Stripe bank-account tokens; required fields vary by country so this needs its own schema per region rather than reusing the card-token flow |

After those: production deployment (backend is deploy-ready — see
`Dockerfile`/`render.yaml` — the actual deployment hasn't happened yet)
and the frontend rebuild to match everything the backend now supports.
See README's Timeline for the current target date.

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

## 10. Architecture notes: why some modules have fewer files
Every module follows the same layering — `models.py` (table),
`repository.py` (DB queries), `schemas.py` (request/response shapes),
`service.py` (business logic), `router.py` (HTTP layer) — but not every
module needs all five. A module skips a layer only when there's
genuinely nothing to put in it, never as a shortcut:

- **`accounts`, `transactions`** — no `service.py`. Each has exactly one
  read-only endpoint (`GET /accounts/me`, `GET /transactions`) with no
  business logic beyond "fetch and paginate" — the router calls the
  repository directly. A service layer here would just be a pass-through
  wrapper around the repository call.
- **`transfers`** — no `models.py`/`repository.py`. It doesn't own a
  table; it moves money between `Account` rows and writes `Transaction`
  rows, both of which belong to their own modules. Introducing a
  transfers-specific model or repo would mean duplicating the
  accounts/transactions data access instead of reusing it.
- **`admin`** — no `schemas.py`/`service.py`/`repository.py`. It's a
  read-only reporting layer over other modules' data (transactions,
  audit logs), reusing their repositories and response schemas directly.
  No new data or business rule originates here.
- **`webhooks`** — only `router.py`. It's a dispatcher: verify the
  signature, then call into `deposits`/`payouts` services, which own the
  actual state changes. It has no model or business logic of its own.
- **`audit`** — no `router.py`. Audit log rows are written from inside
  other modules' request flows (`log_action()`, called from `transfers`,
  auth failures, etc.) and read back out through `admin`'s endpoints —
  there's no reason for `audit` to expose its own HTTP surface too.

Verified as of Phase 13: every endpoint documented in § 5 (API surface)
exists in code and is registered in `app/main.py`; no stub functions,
`TODO`s, or `NotImplementedError`s anywhere in `app/modules/`.

