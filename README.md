# BridgePay Backend

FastAPI backend for BridgePay — a PayPal-style payments
platform (auth, wallets, transfers, admin). See [PLAN.md](./PLAN.md) for the
full architecture and original phased build order.

## Team
| Name | GitHub | Role |
|---|---|---|
| Mark Musyoka | [@Mark-Musyoka](https://github.com/Mark-Musyoka) | Owner |
| Abednego Ndimu | [@abednegoingplaces](https://github.com/abednegoingplaces) | Collaborator |
| Franklin Tumaini | [@Antony-debug-jpg](https://github.com/Antony-debug-jpg) | Collaborator — database and frontend |

## Tech stack
| Layer | Choice |
|---|---|
| Framework | FastAPI (async) + Pydantic |
| ORM / migrations | SQLAlchemy 2.0 (async) + Alembic |
| Database | Postgres (Neon) |
| Background jobs | Celery + Redis |
| Auth | JWT (python-jose), bcrypt for password hashing |
| Rate limiting | slowapi, Redis-backed |
| Payments | Stripe (cards) + M-Pesa Daraja (STK Push, B2C) |
| OAuth | Google (Sign in with Google) |
| Deployment | Render |
| Paired with | [BridgePay-Frontend](https://github.com/Mark-Musyoka/BridgePay-Frontend) (Next.js) |

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

| Module | What it owns |
|---|---|
| `users` | User model/profile, `PATCH /users/me`, change password, `GET /countries` |
| `auth` | Register/login/refresh/logout, email verification, password reset, Google OAuth |
| `accounts` | Wallet balance |
| `transactions` | The shared immutable ledger (read by transfers, deposits, payouts) |
| `transfers` | Internal user-to-user transfers, row-locking logic |
| `notifications` | In-app + mocked email notifications, `notify()` called from every other module |
| `payment_methods` | Real Stripe card linking, real M-Pesa phone linking |
| `deposits` | Real Stripe + M-Pesa deposits, webhook-driven crediting |
| `payouts` | Real M-Pesa B2C + Stripe card payouts, deduct-first/reverse-on-failure |
| `webhooks` | Stripe + M-Pesa webhook endpoints (no models of its own) |
| `admin` | Admin-only transaction/audit-log views |
| `audit` | The audit log, `log_action()` called from every other module |

Cross-cutting auth dependencies (`get_current_user`, `get_current_admin_user`,
`get_current_verified_user`) live in `app/core/dependencies.py` — used by
nearly every module, so they don't belong to any single one. `app/core/`
also holds config, security (JWT/password hashing), rate limiting, the
country list, and the shared Stripe/M-Pesa/Google client primitives that
`payment_methods`/`deposits`/`payouts`/`auth` all build on; `app/db/`
holds the SQLAlchemy base and session setup. See PLAN.md section 9 for
the full tree.

To find how a feature works end-to-end: open its module folder — e.g.
everything about transfers (the model, the locking logic, the endpoint,
the confirmation email task) is in `app/modules/transfers/`.

## Timeline
Started as a learning project with no fixed deadline — now targeting a
launch by **Friday, September 18, 2026**. The backend is functionally
complete (see Status below); real Stripe/M-Pesa/Google credentials are
configured locally. Remaining work between now and launch is mostly
frontend (which is being rebuilt to match everything the backend now
supports) plus deployment.

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
versioning, email verification/password reset (Phase 8), a modular
codebase reorganization with a bug-fix pass (Phase 9),
production-readiness fixes (Phase 10), country/notifications/settings/
real Stripe+M-Pesa payments (Phase 11), and Google OAuth (Phase 12).**
Every
endpoint has been tested against a
real running Postgres + Redis + Celery stack — registered users, executed
real transfers, triggered rate limits, confirmed worker output — not just
written and assumed to work.

### Phase 1 — Scaffolding
| Item | Detail |
|---|---|
| Folder structure | FastAPI app boots (`GET /` health check) |
| Migrations | Alembic wired to an async DB engine |

### Phase 2 — User + Auth
| Item | Detail |
|---|---|
| Model + migration | `User` model + `users` table migration |
| Endpoints | `POST /auth/register`, `POST /auth/login` → JWT, `GET /users/me` |
| Password hashing | Via `bcrypt` directly, **not** `passlib` — `passlib` is unmaintained and its bcrypt backend breaks on bcrypt >=4.1 (a version-detection bug); calling `bcrypt.hashpw` / `bcrypt.checkpw` directly avoids this entirely |

### Phase 3 — Accounts + Transactions
| Item | Detail |
|---|---|
| Account model | Auto-created for every user at registration, balance starts at 0.00 |
| Transaction model | Immutable ledger, enums for status/type |
| Endpoints | `GET /accounts/me`, `GET /transactions` (paginated) |
| `POST /transfers` | The core feature. `transfer_service.py` locks both accounts with `SELECT ... FOR UPDATE`, in a fixed order by account id, *before* checking the balance — so two simultaneous transfers can't both pass a stale balance check, and two transfers in opposite directions between the same accounts can't deadlock each other. Verified against: successful transfer, insufficient funds, self-transfer, nonexistent recipient, invalid (negative) amount |

### Phase 4 — Security hardening
| Item | Detail |
|---|---|
| Rate limiting (IP-keyed) | `/auth/register` 5/min, `/auth/login` 10/min, `/transfers` 20/min |
| Audit log | `audit_logs` table — separate from the transaction ledger on purpose: transactions record money movement, audit logs record *who did what*, including failed attempts that never touch the ledger at all. Tracks register, login success/failure, transfer success/failure, with IP address |

### Phase 5 — Celery background job
| Item | Detail |
|---|---|
| Transfer confirmation task | Mocked, queued after a successful transfer via `.delay()`, wrapped in try/except so a broker outage never breaks a transfer that's already succeeded and committed |

### Phase 6 — Admin view
| Item | Detail |
|---|---|
| `is_admin` flag | On `users`, defaults `false` — no signup flow grants it. Promote a user directly in the DB for local dev (see below) |
| Endpoints | `GET /admin/transactions` (optional `?user_email=` filter) and `GET /admin/audit-logs` (optional `?action=` filter) — both admin-only, a non-admin token gets `403`, no token gets `401` |

```sql
UPDATE users SET is_admin = true WHERE email = 'you@example.com';
```

### Phase 7 — Refresh tokens (post-plan addition)
The original plan called for "JWT short expiry + refresh token pattern" but
only shipped the short-expiry access token. This closes that gap:

| Item | Detail |
|---|---|
| `refresh_tokens` table | Tokens stored **hashed** (SHA-256), never raw |
| Login | Now returns both `access_token` and `refresh_token` |
| `POST /auth/refresh` | Single-use rotation: presenting a refresh token issues a new access + refresh token pair and immediately revokes the one used |
| Reuse detection | Presenting an already-revoked refresh token (i.e. a token that's already been rotated once) is treated as a signal of theft — every refresh token for that user is revoked immediately, forcing re-login on all devices. Verified: rotate once (works), replay the original token (401 + full revocation), then confirm the *second* (previously valid) token is also dead |
| `POST /auth/logout` | Revokes a specific refresh token |

### Deployment readiness (hardening pass)
Reviewed against a more mature sibling project's backend to catch gaps
before deploying:

| Item | Detail |
|---|---|
| CORS middleware | Explicit `ALLOWED_ORIGINS` allow-list for the deployed frontend, plus a regex allowing any `localhost`/`127.0.0.1` port for local dev (so `npm run dev`'s random port never breaks CORS). Verified: allowed origin gets `access-control-allow-origin` back, `evil-site.com` does not |
| Global exception handler | Any unhandled exception returns a generic `{"detail": "Internal server error"}` to the client, while the real traceback goes to the server log. Verified by forcing a real DB failure mid-request: client got the generic message, server log had the full traceback. Deliberately does **not** echo `str(exc)` to the client — that leaks internal details (file paths, query fragments) |
| `render.yaml` | Declarative Blueprint for both the web service and the Celery worker, so deployment isn't manual dashboard clicking. Secrets (`DATABASE_URL`, `JWT_SECRET_KEY`, etc.) are marked `sync: false` so Render prompts for them rather than storing them in the repo |
| `Dockerfile` | Containerized entrypoint, not just "run uvicorn directly" |
| Automated test suite | `pytest` + `httpx.AsyncClient`, 21 tests — covers register/login/refresh/logout (including the token-reuse attack scenario), transfers (success, insufficient funds, self-transfer, nonexistent recipient, negative amount), and admin access control. Everything previously verified by hand via curl is now a regression test. Uses a dedicated `bridgepay_test` database with a fresh schema per test. Run with the commands below. Fixed a real bug while wiring this up: the test DB engine was reused across tests with a connection pool, but pytest-asyncio gives each test its own event loop — a pooled connection from one loop is invalid in the next, causing `InterfaceError: another operation is in progress`. Fixed by using `NullPool` for the test engine (fresh connection per use, never reused across loops) |

```bash
pip install -r requirements-dev.txt
pytest
```

### API versioning
| Item | Detail |
|---|---|
| All endpoints | Now live under `/api/v1` (e.g. `/api/v1/auth/register`). The root health check (`/`) stays unversioned — `render.yaml`'s `healthCheckPath` and most infra tooling expect that. This was a breaking URL change; the frontend's PLAN.md contract was updated to match |

### Phase 8 — Email verification + password reset (post-plan addition)
Closes a gap found when reviewing the backend for missing standard flows.

| Item | Detail |
|---|---|
| `is_verified` flag + `EmailVerificationToken` | Flag on `User` (defaults `false`); token model hashed, single-use, same pattern as `RefreshToken` |
| Registration | Issues a verification token and queues a mocked "send verification email" Celery task (logs the raw token; the raw token is never stored, only its hash) |
| `POST /auth/verify-email` | Verified end-to-end: register → Celery logs the token → verify → `is_verified` flips to `true` → reusing the same token afterward correctly fails (single-use enforced) |
| Transfers gated behind verification | A real business rule for a payments app, via a `get_current_verified_user` dependency (mirrors `get_current_admin_user`). Unverified users can register and log in, but `POST /transfers` returns `403` until they verify. Covered by its own test (`test_unverified_user_cannot_send_transfer`) |
| `POST /auth/password-reset-request` / `-confirm` | `PasswordResetToken` model, same hashed/single-use pattern. The request endpoint returns an identical `204` whether or not the email is registered (user-enumeration protection) — verified the Celery log only actually fires for real accounts, not fake ones |
| Reset revokes all refresh tokens | A reset is a signal the account may have been compromised, so any existing session (stolen or not) is killed. Verified live: logged in before the reset, confirmed that pre-reset refresh token is dead afterward — not just asserted in a comment |

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

| Item | Detail |
|---|---|
| Missing audit logging on 3 failure modes | `transfer_service.py` raised `HTTPException` directly for self-transfer / recipient-not-found / account-not-found, which meant those attempts were **never audit-logged** (only `InsufficientFundsError` was, since the router's `try/except` only caught that one case). Fixed by raising domain exceptions (`SelfTransferError`, `RecipientNotFoundError`, `AccountNotFoundError`) that the router now catches and logs individually. Verified live: all three failure modes now appear in `audit_logs` where two previously didn't |
| No audit trail on logout | `POST /auth/logout` had no audit trail at all, unlike every other auth action. Added a `log_action` call. Verified live |
| Missing rate limiting on 2 endpoints | `POST /auth/verify-email` and `POST /auth/logout` were also missing rate limiting entirely (no `@limiter.limit`), unlike every other auth endpoint. Fixed — verified live that the 11th rapid request to `verify-email` correctly gets `429` |
| Silent audit gaps on 3 failure paths | Failed attempts on `verify-email`, `refresh` (the plain invalid/expired case, not just reuse-detection), and `password-reset-confirm` were silently not written to the audit log — only successes and the reuse-detection case were. Fixed to match the pattern already used for `login_failed` |

Also found and fixed, unrelated to the reorg itself:

| Item | Detail |
|---|---|
| Schema drift on `AuditLog.ip_address` | Declared `String(64)` in the model, but the actual migration/DB column was `String(45)` (the correct max length for an IPv6 address string) — the two had been out of sync since Phase 4 and nobody had re-run autogenerate to catch it. Fixed by aligning the model to the DB |
| `UserResponse` missing `is_verified` | The only way a frontend could learn a user's verification status was to get a `403` on a transfer attempt. Added the field |

### Phase 10 — Production-readiness fixes
| Item | Detail |
|---|---|
| Redis-backed rate limiting | The limiter previously used in-memory storage (per-process, resets on restart, and wouldn't correctly enforce limits if Render ever runs multiple instances). Switched to Redis (reusing `CELERY_BROKER_URL`, no new dependency needed). Verified the storage is genuinely Redis, not just configured: confirmed real keys exist in Redis (`LIMITS:LIMITER/...`) after hitting a limit, and confirmed `limiter.reset()` (used between tests) actually clears Redis state via `RedisStorage.reset()`, not silently no-op-ing |
| `POST /auth/resend-verification` | Closes a real gap: if a verification token expired or the (mocked) email never "arrived," there was previously no way for a user to get a new one short of someone manually flipping `is_verified` in the database. Requires auth (the user can already log in, since verification only gates transfers, not login) — this sidesteps needing the user-enumeration precautions the password-reset-request flow needs. Rejects with `400` if already verified. 6 new tests added, closing a pre-existing gap where verify-email/resend had **zero** automated coverage. One test's original assumption was wrong and got corrected rather than "fixed" in the app: resending does *not* revoke the previously issued token, and that's fine — unlike refresh tokens, a stale verification link carries no real risk, so letting an old link keep working is reasonable, not a bug |
| `python-jose` deprecation warning | Every test run showed a `datetime.utcnow()` deprecation warning from inside the library, not our code. Checked whether a newer release fixed it before assuming a library swap was needed: `python-jose` 3.5.0 (up from the pinned 3.3.0) already uses `datetime.now(UTC)` internally — confirmed by downloading and grepping its source before bumping the version. Also set `asyncio_default_fixture_loop_scope = function` in `pytest.ini` to silence an unrelated pytest-asyncio config warning noticed along the way. Full suite now runs with **zero warnings** |

### Phase 11 — Country, notifications, settings, and real payments (Stripe + M-Pesa)
The biggest addition since the initial 6-phase plan — a `country` field,
an in-app+email notification system, account settings, and genuinely
real (not mocked) Stripe and M-Pesa integration for linking payment
methods, depositing funds, and sending real external payouts.

| Feature | Detail |
|---|---|
| `country` | ISO 3166-1 alpha-2, required + validated at registration, nullable at the DB level for backward compatibility. A public `GET /countries` (249 entries) backs the signup dropdown |
| Notifications (`app/modules/notifications/`) | A single `notify()` entry point every other module calls into. Always creates the in-app row first (the source of truth), then queues a mocked email alongside it. Wired into transfers, deposits, and payouts |
| Settings | `PATCH /users/me` (changing email resets `is_verified` and re-triggers the verification flow to the NEW address; rejects a duplicate email), `POST /users/me/change-password` (requires the current password, revokes every refresh token afterward — a password change is a signal worth killing existing sessions over, whether it was the user's own doing or they're locking down a compromised account) |
| `PaymentMethod` (`app/modules/payment_methods/`) | Real Stripe card linking via SetupIntent (the card number itself never touches this backend — Stripe holds it, we store only its `pm_...` id and masked display details) and real M-Pesa phone linking (no gateway call needed for linking itself — Daraja has no "saved payment method" concept, the phone number is used directly at deposit/payout time) |
| Deposits (`app/modules/deposits/`) | Real Stripe PaymentIntents and real M-Pesa STK Push. The account balance is **only ever credited when a webhook confirms success**, never optimistically at request time, since both providers are asynchronous. Both webhook handlers are idempotent (checked against `deposit.status` before crediting), so a redelivered webhook is a safe no-op, not a double-credit. A client-supplied idempotency key means a retried deposit request returns the same PaymentIntent rather than creating a second charge |
| External payouts (`app/modules/payouts/`) | Real M-Pesa B2C and real Stripe card payouts. Money genuinely leaves the platform here, per an explicit product decision. The sender's balance is deducted **up front**, before the external API call, using the same locking discipline as transfers — and reversed (credited back, via a second immutable Transaction, never editing the original) if the payout then fails, whether discovered synchronously or asynchronously (a result callback / `payout.failed` webhook) |

| Note | Detail |
|---|---|
| Untested against live endpoints | None of the above Stripe/M-Pesa integration has been exercised against real sandbox credentials — I don't have any. External SDK/HTTP calls are mocked via monkeypatch in tests; what IS verified for real is everything around those calls: locking, balance math, idempotency, webhook redelivery safety, and the deduct-then-reverse payout logic. The one piece flagged as most likely to need adjustment once real credentials are available: Stripe's `method="instant"` card payout requires the account to have Instant Payouts capability enabled, which isn't automatic |
| Deliberately scoped out, not overlooked | Raw bank-account-number payouts (as opposed to a card token) — the required fields (routing number, account type, etc.) vary by country and weren't specified, so this was left out rather than guessed at. Airtel Money was mentioned early on as a "nice to have" alongside M-Pesa but was never chosen as a gateway to actually build |


### Phase 12 — Google OAuth (Sign in with Google)
The standard [authorization-code flow](https://developers.google.com/identity/protocols/oauth2/web-server),
with one deliberate addition: `GET /auth/google/callback` never puts a
real access/refresh token in its redirect URL (that would end up in
browser history, server logs, and `Referer` headers) — it issues a
short-lived (60s), single-use handoff code instead, and the frontend
exchanges that via `POST /auth/google/exchange` for real tokens over a
request body. Same hashed, single-use token pattern used everywhere
else in this codebase.

| Item | Detail |
|---|---|
| Nullable password | `User.hashed_password` is now nullable (a Google-only account has none at all) — `login()` explicitly checks for `None` before calling `verify_password`, rather than crashing |
| Account linking | Signing in with Google on an email that already has a password-based account **links** Google onto it and upgrades `is_verified` to true — safe to do without extra steps, since Google has already proven the person controls that email via its own consent screen |
| New Google sign-in | Creates an account with no password, `is_verified=true` immediately, and `country` left `null` (Google doesn't reliably provide this — filled in later via `PATCH /users/me`) |
| CSRF protection | Short-lived httpOnly state cookie set on `/auth/google/login` and checked on `/auth/google/callback` |
| Email verification check | Rejects Google accounts reporting `email_verified: false` |

No real Google OAuth credentials available to test against Google's
actual endpoints — the two HTTP calls (`exchange_code_for_tokens`,
`get_google_user_info`) are mocked via monkeypatch. What IS verified for
real: a live boot test confirming `GET /auth/google/login` produces a
correctly-formed, complete authorization URL. 8 tests cover the rest:
state-mismatch rejection, new-account creation, unverified-email
rejection, account linking (verification upgraded, original password
untouched), handoff code exchange (and that it's genuinely single-use —
a second exchange attempt correctly fails), and the specific crash this
could have caused — password login against a Google-only account —
correctly returning 401 instead of a 500.


### Phase 13 — Multi-currency deposit/payout conversion
One of the three items previously deferred out of Phase 11 (see that
phase's "Deliberately scoped out" note). A deposit or payout made in a
currency other than the destination account's own currency (KES by
default) is now converted before it touches the balance, instead of
crediting or deducting the raw foreign-currency number as if it were
already KES. Not suitable for anything requiring real-time FX
precision — adequate for a wallet's conversion, not a trading system.

| Component | What changed |
|---|---|
| `app/core/exchange_rate_client.py` | New client for the [Frankfurter API](https://www.frankfurter.dev/) (free, no key, ECB rates). Hourly per-pair cache; same-currency pairs short-circuit to 1:1, no network call |
| Deposits | `_credit_account_and_record` converts into the account's currency before crediting; rate + converted amount persisted on `Deposit` (`NULL` when no conversion needed); `Transaction` records the account-currency amount that actually moved |
| Payouts | `_deduct_balance_and_record` converts the same way before deducting; `_reverse_deduction` credits back the **converted** amount on failure, not the original |
| Rate unavailable | Deposit marked failed (no funds move), depositor notified; payout rejected with `503` before any external gateway call |

### Phase 14 — Consistent router/schema/service/repository layer
Prompted by a mentor code review flagging module inconsistency. Full
audit found no missing business logic or stub code anywhere — but
several routers reached into another module's repository directly
instead of going through their own service layer. See PLAN.md § 10 for
the per-module file matrix and the reasoning behind what's deliberately
still missing.

| Module | Added | Why |
|---|---|---|
| `accounts`, `transactions` | `service.py` | Router no longer calls the repository directly |
| `transfers` | `repository.py` | Extracted the account-locking + ledger-write logic out of `service.py`, which now owns just the business rules |
| `admin` | `repository.py`, `service.py`, `schemas.py` | Composes accounts/users/transactions/audit repositories in one place instead of the router importing four other modules; schemas re-export the response shapes it reuses |
| `webhooks` | `service.py`, `schemas.py` | Signature verification and event dispatch moved out of the router; typed ack responses (`WebhookAckResponse`, `DarajaAckResponse`) replace raw dicts |

Pure structural refactor — reviewed diff-by-diff against the original
logic (locking order, balance re-check after lock, signature check
before dispatch, empty-result-on-no-match). Full suite: 81/81 passing,
same 43 routes registered before and after.

### Phase 15 — Airtel Money integration
The last of the three items deferred out of Phase 11 (Airtel Money,
bank-account payouts, multi-currency conversion — see that phase's
"Deliberately scoped out" note; multi-currency shipped in Phase 13).
Same shape as the M-Pesa module — Collections for deposits (USSD push),
Disbursement for payouts — against Airtel's real Open API
(`developers.airtel.africa`), scoped to Kenya only, matching M-Pesa and
the account currency default.

| Component | Detail |
|---|---|
| `app/core/airtel_client.py` | OAuth2 client-credentials token fetch/cache (same pattern as M-Pesa's), Kenyan phone normalization (Airtel's format has no country code, unlike Daraja's), disbursement PIN encryption (RSA against Airtel's public key — same shape as M-Pesa B2C's certificate-based `generate_security_credential`), and callback signature verification |
| Deposits (Collections) | `POST /deposits/airtel` — USSD push to the subscriber's phone, same async-then-webhook-confirms pattern as M-Pesa STK Push. Only credits the account once `POST /webhooks/airtel/collection-callback` reports `status_code: "TS"` |
| Payouts (Disbursement) | `POST /payouts/airtel` — same deduct-first-then-reverse-on-failure discipline as every other payout provider. `POST /webhooks/airtel/disbursement-callback` confirms or triggers a reversal |
| Callback signing | Unlike M-Pesa's Daraja (which signs nothing at all), Airtel callbacks are signature-verified via `X-Signature` (HMAC-SHA256, shared secret) — a bad or missing signature is rejected with `400` before the payload is even parsed |

| Note | Detail |
|---|---|
| Untested against live endpoints | Same caveat as Phase 11's Stripe/M-Pesa integration — no real Airtel developer-portal credentials available. External HTTP calls are mocked via monkeypatch in tests |
| Signing scheme confidence | Airtel doesn't publish one single, universally-documented callback-signing spec the way Stripe does. The `X-Signature`/HMAC-SHA256 scheme implemented here matches common integration patterns seen in the wild, but should be re-confirmed against the developer portal's callback-signing docs once real credentials are available — flagged the same way, not assumed correct |

### Phase 16 — Bank-account payouts
The last of the three items deferred out of Phase 11 (Airtel Money,
bank-account payouts, multi-currency conversion — Airtel shipped in
Phase 15, multi-currency in Phase 13). Adds a real destination kind
alongside cards and mobile money: a Kenyan local bank account (account
number + bank code) or an international one (IBAN + SWIFT/BIC), via
Stripe.

| Component | Detail |
|---|---|
| `POST /payouts/bank-account` | Same deduct-first/reverse-on-failure discipline as every other payout provider, `method="standard"` rather than `"instant"` (bank transfers settle over days; there's no faster tier to ask for the way there is for cards) |
| `BankAccountPayoutCreate` schema | Its own schema rather than folded into the card payout's, since a bank destination needs a `country` the card flow doesn't |
| PCI-adjacent handling | Same as the card flow: the bank account token (`btok_...`) must be created client-side via Stripe.js — raw account numbers, IBANs, bank codes, and SWIFT/BIC are never accepted by this backend at all. Stripe.js's tokenization already absorbs the field differences between a Kenyan local account and an international one, so this backend never needs to branch on them |
| `country` field | Not sent to Stripe (it's already baked into the token) — validated against the existing ISO 3166-1 country list and surfaced in the confirmation notification, since a Kenyan payout and a US one carry different real-world settlement expectations worth telling the user about |
| Provider | Reuses `PayoutProvider.stripe` rather than a new enum value — both card and bank payouts are Stripe-mediated; the distinction lives in `destination_reference`'s token prefix (`tok_...` vs `btok_...`), not in a separate provider |

Same untested-against-live-endpoints caveat as every other Stripe/M-Pesa/
Airtel integration in this project — no real Stripe bank-account payout
has been exercised, `stripe.Payout.create` is mocked in tests. The
"requires the relevant payout capability enabled" caveat from the card
flow (Phase 11) applies here too, likely more so — bank payout support
varies more by country than card payout support does.

## Explicitly not built
| Item | Why |
|---|---|
| Production deployment | Backend is deploy-ready; the actual deployment hasn't happened yet |

See PLAN.md § 8 (Way forward) for what's left.
