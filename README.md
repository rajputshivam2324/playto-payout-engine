# Playto Payout Engine

> Production-grade payout engine for Playto — a service that helps Indian freelancers and agencies collect international payments. Money flows one way: USD → Playto collects → merchant gets paid in INR.

Built with Stripe engineering principles: row-level locking for concurrency, an immutable append-only ledger as the money source of truth, model-layer state machines with hard-error illegal transitions, byte-perfect idempotency replay, and atomic failure refunds.

---

## Architecture Overview

The system is a Django REST API backed by PostgreSQL (for `SELECT FOR UPDATE` row-level locking), with Celery + Redis for background payout settlement and stuck-payout detection. The React + Tailwind CSS frontend polls the API for live dashboard updates. Every mutation endpoint requires an `Idempotency-Key` header and stores full serialized responses for replay. Balance is always derived from `SUM(CREDIT entries) - SUM(DEBIT entries)` — there is no mutable balance column anywhere.

---

## Local Setup

### Option 1: Docker Compose (recommended single command)

```bash
# Start PostgreSQL and Redis
docker compose up -d

# Wait for health checks, then set up the backend
cd backend
python -m venv ../.venv && source ../.venv/bin/activate
pip install -r ../requirements.txt
python manage.py migrate
python manage.py seed_merchants

# Run the API server
python manage.py runserver

# In separate terminals:
celery -A config worker -l info
celery -A config beat -l info

# Start the frontend
cd ../frontend
npm install
npm run dev
```

### Option 2: Manual Setup

```bash
# 1. Start PostgreSQL (port 5432)
#    DB: playto, User: playto, Password: playto

# 2. Start Redis (port 6379)

# 3. Backend
cd backend
python -m venv ../.venv && source ../.venv/bin/activate
pip install -r ../requirements.txt
export DJANGO_SETTINGS_MODULE=config.settings.local
python manage.py migrate
python manage.py seed_merchants
python manage.py runserver

# 4. Celery worker (new terminal)
cd backend && source ../.venv/bin/activate
celery -A config worker -l info

# 5. Celery beat (new terminal)
cd backend && source ../.venv/bin/activate
celery -A config beat -l info

# 6. Frontend (new terminal)
cd frontend
npm install
npm run dev
```

The dashboard is available at `http://127.0.0.1:5173`. Login with:
- **rahul** / playto12345
- **ananya** / playto12345
- **vikram** / playto12345

---

## Running Tests

```bash
cd backend

# All tests (requires running PostgreSQL)
python manage.py test

# Specific test modules
python manage.py test payouts.tests       # Concurrency, idempotency, state machine, balance
python manage.py test workers.tests       # Stuck-payout retry, cleanup
```

Tests use `TransactionTestCase` for concurrency coverage because Django's `TestCase` wraps each test in a transaction, making `SELECT FOR UPDATE` testing impossible.

---

## Trigger a Payout via curl

```bash
# 1. Get a JWT token
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/auth/token/ \
  -H 'Content-Type: application/json' \
  -d '{"username": "rahul", "password": "playto12345"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access'])")

# 2. List bank accounts to get a bank_account_id
curl -s http://127.0.0.1:8000/api/v1/bank-accounts/ \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# 3. Create a payout (replace BANK_ACCOUNT_ID)
curl -s -X POST http://127.0.0.1:8000/api/v1/payouts/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{"amount_paise": 50000, "bank_account_id": "BANK_ACCOUNT_ID"}' | python3 -m json.tool

# 4. Check merchant balance
curl -s http://127.0.0.1:8000/api/v1/merchants/me/ \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

---

## Live Deployment

Deployment target: **Railway** (Django + Celery worker + Celery beat + PostgreSQL + Redis).

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Django 5.2 LTS + Django REST Framework |
| Database | PostgreSQL 16+ |
| Background jobs | Celery 5.6.x + Redis 7 |
| Frontend | React 19.x + Tailwind CSS v4.x + Vite |
| Auth | djangorestframework-simplejwt |
