# Playto Payout Engine — Explainer

> **Live:** Frontend → [playto-frontend-m4j7.onrender.com](https://playto-frontend-m4j7.onrender.com/) | Backend → [playto-api-550a.onrender.com](https://playto-api-550a.onrender.com)

---

## What This Is

A production-grade payout engine for Indian merchants. Money flows one direction: customers pay → Playto collects → merchant requests an INR payout to their bank account. The system simulates the bank settlement step (70% success, 20% fail, 10% hang) to exercise the full lifecycle — concurrency, retries, refunds, idempotency — without a real banking integration.

---

## Architecture Diagram

![Playto Payout Engine Architecture](./architecture.png)

---

## Tech Stack

| Layer | Tech |
|---|---|
| Frontend | React 19 + Tailwind CSS v4 + Vite + TypeScript |
| Backend | Django 5.2 + Django REST Framework |
| Database | PostgreSQL 16 (row-level locking via `SELECT FOR UPDATE`) |
| Task Queue | Celery 5.6 + Redis 7 (broker + result backend) |
| Auth | JWT via `djangorestframework-simplejwt` (15 min access / 24 hr refresh) |
| Deployment | Render (free tier) — API + Celery worker in one container, static frontend, managed Postgres + Redis |

---

## Project Structure

```
playto-payout-engine/
├── backend/
│   ├── config/          # Django project config (settings, urls, celery, error handler)
│   │   ├── settings/
│   │   │   ├── base.py        # Shared: DRF, JWT, CORS, Celery beat schedules
│   │   │   ├── local.py       # Dev: PostgreSQL + Redis on localhost
│   │   │   └── production.py  # Render: env vars, SSL, WhiteNoise
│   │   ├── urls.py            # All API routes (versioned under /api/v1/)
│   │   ├── celery.py          # Celery app factory
│   │   └── api_errors.py      # Stripe-style {error: {code, message, param}} envelope
│   ├── merchants/       # Merchant model, bank accounts, auth, signup, seed data
│   ├── ledger/          # Append-only LedgerEntry model + balance aggregation
│   ├── payouts/         # PayoutRequest model (state machine) + create/list/detail views
│   ├── idempotency/     # IdempotencyKey model for replay protection
│   ├── workers/         # Celery tasks: process_payout, retry_stuck_payouts, purge keys
│   ├── Dockerfile       # Python 3.12-slim + psycopg2
│   ├── start.sh         # Entrypoint: migrate → seed → celery worker (bg) → gunicorn
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── api/client.ts       # Axios + JWT interceptor + silent refresh + idempotency key gen
│   │   ├── components/         # LandingPage, BalanceCard, PayoutForm, PayoutTable, LedgerFeed, etc.
│   │   ├── hooks/              # usePollingResource (generic), useBalance, usePayouts, useLedger
│   │   ├── types.ts            # TypeScript interfaces mirroring API JSON shapes
│   │   └── formatters.ts       # Paise → Rupees (integer arithmetic only)
│   ├── Dockerfile
│   └── vite.config.ts
├── docker-compose.yml   # Full local stack: postgres, redis, api, worker, beat, frontend
├── render.yaml          # Render IaC: web service, static site, managed DB + Redis
└── .env.example         # Template for local env vars
```

---

## Core Design Principles

These are not abstract. Every one maps to concrete code.

### 1. Ledger Is the Source of Truth (No Balance Column)

`Merchant` has **no** `balance` field. Balance is always:

```python
SUM(CREDIT entries) - SUM(DEBIT entries)
```

`LedgerEntry` is append-only. The model overrides `save()` to reject updates and `delete()` to always raise. You cannot edit history. Balance at any timestamp = replay rows up to that time.

**File:** `ledger/models.py` → `get_merchant_balance()`, `LedgerEntry.save()`, `LedgerEntry.delete()`

### 2. SELECT FOR UPDATE Prevents Double-Spend

When a payout is created, the merchant row is locked with `SELECT FOR UPDATE` inside `transaction.atomic()`. The second concurrent request **blocks** at the DB level until the first commits. It then reads the updated (lower) balance and gets `insufficient_funds`.

SQLite silently ignores `select_for_update()` — that's why PostgreSQL is mandatory even for local dev.

**File:** `payouts/views.py` → `_create_payout_response()` lines 242-292

### 3. Model-Layer State Machine

Payout states and transitions:

```
pending → processing → completed
                     → failed (+ atomic refund CREDIT)
```

`transition_to()` on `PayoutRequest` does everything: acquires row lock, validates allowed transitions, writes state + ledger refund in one atomic transaction. Illegal transitions raise `InvalidStateTransition`. There is no other way to change payout state.

```python
LEGAL_TRANSITIONS = {
    PENDING:    {PROCESSING},
    PROCESSING: {COMPLETED, FAILED},
    COMPLETED:  set(),   # terminal
    FAILED:     set(),   # terminal
}
```

**File:** `payouts/models.py` → `transition_to()`

### 4. Idempotency (Stripe-Style)

Every mutation endpoint requires an `Idempotency-Key` header. The system:

| Case | Condition | Response |
|---|---|---|
| A | New key | Create `in_flight` row → process → store response → `done` |
| B | Same key, same params, `done` | Replay stored response byte-for-byte |
| C | Same key, `in_flight` | 409 `request_in_progress` |
| D | Same key, expired (>24h) | Delete old row, treat as new |
| Conflict | Same key, different params | 409 `idempotency_key_conflict` |

Unique constraint on `(merchant, key)` handles races at the DB level.

**File:** `payouts/views.py` → `_prepare_idempotency_key()`, `idempotency/models.py`

### 5. Atomic Failure Refunds

When a payout fails (bank rejection or retry exhaustion), the `transition_to()` method creates a CREDIT ledger entry **in the same transaction** as the state change to `failed`. If either write fails, both roll back. Funds cannot get stranded.

**File:** `payouts/models.py` lines 100-109

### 6. Celery Workers Are Suspects

Workers assume duplicate delivery. Every task:
1. Acquires `SELECT FOR UPDATE` on the payout row
2. Re-checks current state
3. Exits cleanly if already terminal

The `process_payout` task simulates bank settlement:
- `random() < 0.70` → complete
- `0.70 – 0.90` → fail + refund
- `≥ 0.90` → sleep 60s (simulates bank hang)

**File:** `workers/tasks.py` → `process_payout()`, `_complete_payout()`, `_fail_payout_with_refund()`

### 7. Stuck Payout Detection

`retry_stuck_payouts` runs periodically (every 30s via Celery beat / external cron). It finds processing payouts where `updated_at` is older than 30 seconds (worker heartbeat). For each:

- If `attempt_count < 3`: increment count, refresh heartbeat, re-enqueue with exponential backoff (`2^attempt`)
- If `attempt_count >= 3`: fail + refund atomically

**File:** `workers/tasks.py` → `retry_stuck_payouts()`

### 8. Money Is Integers (Paise)

All amounts are stored as `PositiveBigIntegerField` in paise (1 INR = 100 paise). No floats, no decimals, no `Decimal`. Display conversion uses integer arithmetic only:

```python
# Backend
whole = amount_paise // 100
fractional = abs(amount_paise) % 100
```

```typescript
// Frontend
const whole = Math.trunc(paise / 100)
const fractional = Math.abs(paise % 100)
```

---

## API Endpoints

All under `/api/v1/`. Auth via `Authorization: Bearer <jwt>`.

| Method | Path | What It Does |
|---|---|---|
| POST | `/auth/token/` | Login → JWT pair |
| POST | `/auth/token/refresh/` | Refresh → new access token |
| POST | `/auth/signup/` | Register user + merchant |
| GET | `/merchants/me/` | Profile + available/held balances |
| POST | `/merchants/me/seed/` | Seed demo data (persona 1-5) |
| GET | `/bank-accounts/` | List merchant's bank accounts |
| POST | `/bank-accounts/` | Add bank account (needs Idempotency-Key) |
| PATCH | `/bank-accounts/:id/` | Update holder name or default flag |
| DELETE | `/bank-accounts/:id/` | Soft-delete (rejected if payout active) |
| GET | `/payouts/` | List merchant's payouts |
| POST | `/payouts/` | Create payout (needs Idempotency-Key) |
| GET | `/payouts/:id/` | Single payout detail |
| GET | `/ledger/` | Paginated ledger feed |
| GET | `/ops/cron/?token=<secret>` | Trigger periodic tasks (external cron) |

Every error response follows the same shape:
```json
{"error": {"code": "insufficient_funds", "message": "...", "param": "amount_paise"}}
```

---

## Frontend Flow

1. **Landing Page** — Sign in or create account. Default creds: `rahul` / `playto12345`.
2. **Seed Selection** — First-time users pick a persona (Boutique E-commerce, Freelancer, SaaS, etc.) which seeds bank accounts + ledger credits + sample payouts.
3. **Dashboard** — Balance cards (available + held), payout form, payout history table, ledger feed.
4. **Live Polling** — `usePollingResource` hook polls balance (5s), payouts (3s), ledger (5s) so payout state changes appear without manual refresh.
5. **Silent Token Refresh** — Axios interceptor swaps expired access tokens using the refresh token. Queues concurrent 401s so only one refresh request fires.

---

## Payout Lifecycle (end to end)

```
1. User submits payout form
2. Frontend sends POST /payouts/ with Idempotency-Key header
3. Backend: validate → check idempotency → lock merchant row → check balance → create PayoutRequest (pending) + DEBIT ledger entry → commit → enqueue Celery task
4. Celery worker picks up task → lock payout → pending→processing → simulate bank
5a. 70%: processing→completed (payout done, DEBIT stays)
5b. 20%: processing→failed (refund CREDIT created atomically)
5c. 10%: worker hangs → retry_stuck_payouts detects stale heartbeat → re-enqueue or fail after 3 retries
6. Frontend polls /payouts/ and /merchants/me/ → UI updates in real time
```

---

## Deployment (Render)

Defined in `render.yaml`:

- **playto-api** — Docker web service. `start.sh` runs migrations, seeds, starts Celery worker in background, then Gunicorn. Single container = free tier compatible (no separate worker service).
- **playto-frontend** — Static site. `npm ci && npm run build` → serves `dist/`.
- **playto-db** — Managed PostgreSQL (free tier).
- **playto-redis** — Managed Redis key-value store (free tier).
- **Periodic tasks** — No Celery beat. An external cron service (cron-job.org) hits `GET /ops/cron/?token=<CRON_SECRET>` to trigger `retry_stuck_payouts` and `purge_expired_idempotency_keys`.

---

## Local Dev Setup

```bash
# 1. Start infra
docker compose up -d db redis

# 2. Backend
cd backend
python -m venv ../.venv && source ../.venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_merchants
python manage.py runserver

# 3. Workers (separate terminals)
celery -A config worker -l info
celery -A config beat -l info

# 4. Frontend
cd frontend && npm install && npm run dev
```

Dashboard at `http://localhost:5173`. Login: `rahul` / `playto12345`.

---

## Tests

```bash
cd backend
python manage.py test                # all tests
python manage.py test payouts.tests  # idempotency, state machine, balance, concurrency
python manage.py test workers.tests  # stuck payout retry, cleanup, worker idempotency
```

Key tests:
- **Concurrent overdraw** — Two threads race to create payouts exceeding balance. `SELECT FOR UPDATE` ensures exactly one succeeds, one gets `insufficient_funds`.
- **Idempotency replay** — Same key + same params = same response. Same key + different params = 409 conflict.
- **Balance invariant** — After create, process, complete, and fail+refund stages, API balance always equals `SUM(CREDIT) - SUM(DEBIT)`.
- **Retry exhaustion** — Stuck payout at `attempt_count >= 3` fails atomically with refund.
- **Worker idempotency** — Calling `process_payout` on a terminal payout is a no-op (no state change, no ledger mutation).

Tests use `TransactionTestCase` for concurrency because Django's `TestCase` wraps everything in a transaction, making `SELECT FOR UPDATE` untestable.

---

## The AI Bug That Was Fixed

The AI generated float division for paise-to-rupees:

```python
# WRONG: float division → IEEE 754 rounding artifacts
return f"₹{amount_paise / 100:.2f}"
# 100007 / 100 = 1000.0699999999999 → "₹1000.07" (wrong)
```

Fixed to integer arithmetic:

```python
# CORRECT: no floats involved
whole = amount_paise // 100
fractional = abs(amount_paise) % 100
return f"₹{whole:,}.{fractional:02d}"
```

Same fix applied in frontend `formatRupees()` using `Math.trunc()` and `%`.
