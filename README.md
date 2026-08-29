# BridgePay Backend

FastAPI backend for BridgePay. See [PLAN.md](./PLAN.md) for the full
architecture and phased build order.

## Setup

```bash
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
- [ ] Accounts + Transactions models (Phase 3)

### Note on password hashing
We use the `bcrypt` library directly rather than `passlib`. `passlib` is
unmaintained and its bcrypt backend breaks on bcrypt >=4.1 (a version-detection
bug). Calling `bcrypt.hashpw` / `bcrypt.checkpw` directly avoids this.
