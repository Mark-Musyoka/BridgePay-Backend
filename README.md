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

## Status: Phase 1 — Scaffolding

- [x] Folder structure
- [x] FastAPI app boots (`GET /` health check)
- [x] Alembic wired to async DB engine
- [ ] User + Auth models (Phase 2)
