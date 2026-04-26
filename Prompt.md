# Playto Payout Engine — Master Build Prompt

> You are a senior payments engineer building a production-grade payout engine for Playto,
> a service that helps Indian freelancers and agencies collect international payments.
> Money flows one way: international customer pays in USD → Playto collects → merchant gets paid in INR.
> Your job is to build the payout engine in the middle.
>
> **Every line of code you write must follow Stripe engineering principles.**
> These are not suggestions. They are invariants. They are listed in full below.
> **Every endpoint, every function, every background task must contain inline comments
> explaining what it is doing and why — especially around money, locks, and state transitions.**

---

## Stripe Engineering Principles (Non-Negotiable)

Apply every one of these to every phase. When in doubt, ask: *"What would Stripe do here?"*

**P1 — Correctness over speed**
Every operation that touches money runs inside a database transaction.
Never optimistically update and reconcile later.
If anything fails mid-flight, the DB rolls back. No half-states. No cleanup jobs.

**P2 — Idempotency is a first-class API primitive**
Every mutation endpoint requires an `Idempotency-Key` header.
The key stores the full serialized response body so replays are byte-perfect —
same payout ID, same timestamp, same status code. Not just "similar". Identical.

**P3 — Immutable ledger as source of truth**
Money rows are append-only. Never UPDATE an amount. Never DELETE a ledger entry.
Balance is always derived: `SUM(credits) - SUM(debits)` at query time.
This is the only model where the invariant is structurally impossible to violate.

**P4 — Explicit state machines; illegal transitions are hard errors**
Every stateful object has a documented state machine encoded at the model layer.
Backward transitions raise an exception — they do not silently fail or return a 400.
No code path anywhere in the system can bypass the state machine.

**P5 — Lock before you read, always**
Never do check-then-act on money without holding a DB lock across both steps.
`SELECT FOR UPDATE` is a correctness requirement, not a performance decision.
Lock the merchant row before computing available balance. Hold it until commit.

**P6 — APIs are stable contracts**
Response shapes never change shape mid-build.
Errors are structured: always `{ "error": { "code": "...", "message": "...", "param": "..." } }`.
No naked 500s with stack traces. Clients program against error codes, not strings.

**P7 — Observability is built in, not bolted on**
Every state transition records a timestamp and a reason.
Stuck payout detection works because `updated_at` is written on every transition.
Log every meaningful event with enough context to debug without a debugger.

**P8 — Background workers are suspects**
Every Celery task is written to be idempotent.
The first thing every task does: acquire a lock and re-check current state.
A duplicate invocation must do nothing harmful. Assume it will happen.

**P9 — Money amounts are integers, always**
Store everything in paise (smallest INR unit). `BigIntegerField` in Django. `BIGINT` in Postgres.
No `FloatField`. No `DecimalField` unless you can justify a rounding rule.
Display logic converts paise → rupees only at the serializer or frontend layer.

**P10 — Fail loudly, recover atomically**
On payout failure, funds return to the merchant in the same DB transaction as the state transition.
There is no separate "refund step". If the state transition commits, the refund has committed too.
If anything raises, both roll back. There is no in-between.

---

## Stack

| Layer | Technology | Version |
|---|---|---|
| Backend | Django + Django REST Framework | Django 5.2 LTS (current LTS, supported until 2028) |
| Database | PostgreSQL | 16+ |
| Background jobs | Celery + Redis | Celery 5.6.x |
| Frontend | React + Tailwind CSS | React 19.x · Tailwind CSS v4.x |
| Auth | djangorestframework-simplejwt | latest |
| Deployment | Railway | Django + Celery worker + Celery beat + Postgres + Redis |

> **Version policy:** Always install the latest stable patch of each version listed above.
> Do not pin to a specific minor unless a breaking change requires it.
> Verify current versions at install time — do not hardcode from memory.

---

## Repository Structure

```
playto/
├── backend/
│   ├── config/                  # Django settings, urls, wsgi, asgi
│   ├── merchants/               # Merchant model, bank accounts
│   ├── ledger/                  # LedgerEntry model, balance queries
│   ├── payouts/                 # PayoutRequest model, state machine, API views
│   ├── idempotency/             # IdempotencyKey model + middleware
│   ├── workers/                 # Celery tasks: process_payout, retry_stuck
│   ├── tests/                   # concurrency test, idempotency test
│   └── manage.py
├── frontend/
│   ├── src/
│   │   ├── components/          # BalanceCard, PayoutForm, PayoutTable, LedgerFeed
│   │   ├── hooks/               # useBalance, usePayouts, useLedger (polling)
│   │   ├── api/                 # axios client with idempotency key generation
│   │   └── App.jsx
│   └── package.json
├── docker-compose.yml
├── README.md
└── EXPLAINER.md
```

---

## Data Models (Design these exactly as described)

### Merchant
```
id              UUID primary key
name            CharField
email           EmailField unique
created_at      DateTimeField auto
```

### BankAccount
```
id              UUID primary key
merchant        ForeignKey(Merchant)
account_number  CharField
ifsc_code       CharField
account_holder  CharField
is_default      BooleanField
```

**BankAccount security rules (enforce at every layer — model, serializer, view):**
- A merchant may only read, use, or reference their own bank accounts.
  Any request that supplies a `bank_account_id` belonging to a different merchant
  must be rejected with `403` and error code `bank_account_not_owned`.
- Never expose raw `account_number` in API responses. Mask it: last 4 digits only.
  Store full number in DB; the serializer always emits `"account_number": "••••••1234"`.
- `is_default` must be enforced as a true singleton per merchant at the DB level:
  use a partial unique index `WHERE is_default = true` so only one default can exist.
  When setting a new default, clear the old one inside a transaction (P1).
- The payout form dropdown must call `GET /api/v1/bank-accounts/` and render
  `account_holder — ••••1234 (IFSC)` so the merchant can distinguish accounts
  without ever seeing the full number in the UI.

**BankAccount API endpoints (add in Phase 2 alongside payout endpoints):**

```
GET    /api/v1/bank-accounts/          List merchant's own accounts (masked numbers)
POST   /api/v1/bank-accounts/          Add a new bank account
PATCH  /api/v1/bank-accounts/{id}/     Update account_holder or set is_default
DELETE /api/v1/bank-accounts/{id}/     Soft-delete (set is_active=False); reject if
                                        any pending/processing payout references it
```

`BankAccount` serializer output shape (stable contract — P6):
```json
{
  "id": "uuid",
  "account_holder": "Rahul Sharma",
  "account_number_masked": "••••••1234",
  "ifsc_code": "HDFC0001234",
  "is_default": true,
  "created_at": "2024-01-15T10:30:00Z"
}
```

**Inline comment requirement:**
The masking logic in the serializer must have a comment explaining why the full number
is never sent over the wire even though it is stored in the DB.
The ownership check in the payout creation view must have a comment explaining
what attack it prevents (a merchant referencing another merchant's bank account).

### LedgerEntry  ← SOURCE OF TRUTH. APPEND ONLY. NEVER UPDATE.
```
id              UUID primary key
merchant        ForeignKey(Merchant)
entry_type      CharField  choices=['CREDIT', 'DEBIT']
amount_paise    BigIntegerField  (always positive)
reference_id    CharField  (payout ID for debits, "SEED" for credits)
description     CharField
created_at      DateTimeField auto  (immutable — no updated_at on this model)
```

### PayoutRequest
```
id              UUID primary key
merchant        ForeignKey(Merchant)
bank_account    ForeignKey(BankAccount)
amount_paise    BigIntegerField
state           CharField  choices=['pending','processing','completed','failed']
idempotency_key CharField  (indexed)
attempt_count   IntegerField default=0
failure_reason  CharField null=True
created_at      DateTimeField auto
updated_at      DateTimeField auto_now  (used by stuck-payout detection)
```

### IdempotencyKey
```
id              UUID primary key
merchant        ForeignKey(Merchant)
key             CharField
status          CharField  choices=['in_flight','done']
request_params  JSONField   (fingerprint of original request body — see below)
response_status IntegerField null=True
response_body   JSONField null=True
created_at      DateTimeField auto
expires_at      DateTimeField  (created_at + 24 hours)

UniqueConstraint on (merchant, key)
Index on expires_at  (used by the expiry cleanup task)
```

**Stale idempotency key handling — implement all four cases explicitly:**

```
Case A — Key not found
  → Create IdempotencyKey with status=in_flight, store request_params fingerprint
  → Proceed to create payout
  → On completion: update status=done, store response_status + response_body

Case B — Key found, status=done, not expired
  → Return response_body verbatim with stored response_status (byte-perfect replay)
  → Do NOT touch the DB. Do NOT enqueue any task.
  → Log: "idempotency replay: key=<k> merchant=<id>"

Case C — Key found, status=in_flight (first request still processing)
  → Return 409 with error code=request_in_progress
  → Body: { "error": { "code": "request_in_progress",
                        "message": "A request with this key is already being processed.",
                        "param": "Idempotency-Key" } }
  → Client must retry after a short delay. This is expected behaviour, not a bug.

Case D — Key found, status=done OR in_flight, but expires_at < now (expired)
  → Delete the old key row
  → Treat as Case A (brand new key)
  → This allows a merchant to reuse a key after 24 hours for a logically new request
```

**Parameter mismatch detection (Stripe does this — so do we):**
When a key is found with `status=done`, compare the incoming request body against
`request_params` stored on the key. If `amount_paise` or `bank_account_id` differ,
reject with `409` and error code `idempotency_key_conflict`:
```json
{
  "error": {
    "code": "idempotency_key_conflict",
    "message": "This idempotency key was used with different request parameters.",
    "param": "Idempotency-Key"
  }
}
```
This prevents a merchant from accidentally reusing a UUID for a different payout amount.

**Expiry cleanup — add to Celery beat schedule:**
```python
# Runs once per hour. Deletes expired keys to keep the table lean.
# Safe to run at any time — expired keys are already treated as absent by the lookup logic.
@shared_task
def purge_expired_idempotency_keys():
    deleted, _ = IdempotencyKey.objects.filter(expires_at__lt=now()).delete()
    logger.info(f"Purged {deleted} expired idempotency keys")
```

**Inline comment requirement:**
Each of the four cases in the idempotency lookup must have a comment labelling it
(Case A / B / C / D) and explaining the client behaviour it is designed to produce.
The `request_params` fingerprint storage must have a comment explaining why it is
needed (conflict detection) and what fields it includes.

---

## State Machine (Encode at model layer — not in views, not in tasks)

```
pending ──► processing ──► completed
                    └────► failed
```

Legal transitions:
- `pending → processing`
- `processing → completed`
- `processing → failed`

Every other transition is illegal and must raise `InvalidStateTransition`.
The `transition_to(new_state, reason=None)` method on `PayoutRequest` is the only
place state is ever changed. Nothing calls `payout.state = 'x'` directly anywhere.

---

## Balance Calculation (Always DB-level aggregation — never Python arithmetic on fetched rows)

```python
# Correct pattern — single DB query, no Python math on stale values
from django.db.models import Sum, Q

def get_merchant_balance(merchant_id):
    result = LedgerEntry.objects.filter(merchant_id=merchant_id).aggregate(
        credits=Sum('amount_paise', filter=Q(entry_type='CREDIT')),
        debits=Sum('amount_paise', filter=Q(entry_type='DEBIT')),
    )
    credits = result['credits'] or 0
    debits  = result['debits']  or 0
    return credits - debits  # paise

def get_held_balance(merchant_id):
    # Held = sum of pending + processing payout amounts
    return PayoutRequest.objects.filter(
        merchant_id=merchant_id,
        state__in=['pending', 'processing']
    ).aggregate(held=Sum('amount_paise'))['held'] or 0
```

---

## Phase 1 — Django Foundation

**What to build:**
- Django project scaffold with all apps created
- All models defined and migrated (Merchant, BankAccount, LedgerEntry, PayoutRequest, IdempotencyKey)
- Admin registered for all models
- Management command: `python manage.py seed_merchants`
  - Creates 3 merchants with realistic names
  - Each merchant gets 2 bank accounts
  - Each merchant gets 20–30 CREDIT ledger entries (random amounts 5000–500000 paise, seeded over past 60 days)
  - 2–3 completed payouts per merchant (with matching DEBIT entries)
- JWT auth configured (login endpoint returns access + refresh)
- Settings split: `base.py`, `local.py`, `production.py`
- `requirements.txt` pinned

**Inline comment requirement for this phase:**
Every model field must have a comment explaining why it is that type.
Every model method must have a docstring.
The seed command must have step-by-step comments explaining what it seeds and why.

**Stripe principles active this phase:** P3, P9

---

## Phase 2 — Payout Request API

**What to build:**
`POST /api/v1/payouts/`

This is the most critical endpoint. Build it with the following exact flow, in order:

```
1. Authenticate merchant from JWT
2. Parse and validate request body (amount_paise, bank_account_id)
3. Read Idempotency-Key header — reject with 400 if missing
4. Check IdempotencyKey table:
   a. If found + status=done + not expired → return stored response immediately
   b. If found + status=in_flight → return 409 (request in progress)
   c. If found + expired → treat as new (delete old, create new)
   d. If not found → create with status=in_flight, proceed
5. Open DB transaction:
   a. SELECT FOR UPDATE on merchant row (P5 — lock before read)
   b. Compute available balance via DB aggregate (P3 — never Python arithmetic)
   c. Subtract held balance (pending + processing payouts)
   d. If amount > available → rollback, return 402 with structured error (P6)
   e. Create PayoutRequest in 'pending' state
   f. Create DEBIT LedgerEntry (this is the hold — P3, P10)
   g. Commit
6. Enqueue process_payout.delay(payout_id) to Celery
7. Serialize response
8. Update IdempotencyKey: store response body + status=done
9. Return 201
```

**Also build:**
- `GET /api/v1/payouts/` — list payouts for authenticated merchant, ordered by created_at desc
- `GET /api/v1/payouts/{id}/` — single payout detail (for frontend polling)
- `GET /api/v1/merchants/me/` — merchant profile + available_balance_paise + held_balance_paise
- `GET /api/v1/ledger/` — paginated ledger entries for authenticated merchant

**Error response format (Stripe-style, P6):**
```json
{
  "error": {
    "code": "insufficient_funds",
    "message": "Available balance of ₹150.00 is less than requested ₹600.00",
    "param": "amount_paise"
  }
}
```

Error codes to implement:
- `insufficient_funds` — balance too low
- `invalid_bank_account` — bank account not owned by merchant
- `idempotency_key_missing` — header not provided
- `idempotency_key_conflict` — same key, different params
- `invalid_state_transition` — illegal state move (internal, logged not exposed)
- `payout_not_found` — 404

**Inline comment requirement for this phase:**
Every step in the POST /payouts view must have a comment matching the numbered steps above.
The `SELECT FOR UPDATE` line must have a comment explaining exactly what it prevents.
Every error return must have a comment explaining what client behavior it is designed to drive.

**Stripe principles active this phase:** P1, P2, P3, P5, P6, P9

---

## Phase 3 — Background Workers

**What to build:**

### Task 1: `process_payout(payout_id)`

```python
@shared_task(bind=True, max_retries=3)
def process_payout(self, payout_id):
    # Step 1: Acquire lock and re-check state (P8 — workers are suspects)
    # Step 2: Transition pending → processing (P4 — state machine only)
    # Step 3: Simulate bank settlement:
    #   - random() < 0.70 → success path
    #   - 0.70 ≤ random() < 0.90 → failure path
    #   - random() ≥ 0.90 → hang (sleep 60s, let stuck-payout detector catch it)
    # Step 4a (success): transition processing → completed (P4)
    # Step 4b (failure): in ONE atomic transaction (P10):
    #   - transition processing → failed
    #   - create CREDIT LedgerEntry to reverse the hold
    #   - record failure_reason
```

### Task 2: `retry_stuck_payouts()` — Celery beat, every 30 seconds

```python
@shared_task
def retry_stuck_payouts():
    # Find all payouts in 'processing' state untouched for > 30 seconds
    # For each stuck payout:
    #   - If attempt_count >= 3: mark failed, refund atomically (P10)
    #   - Else: increment attempt_count, re-enqueue with exponential backoff
    #     backoff = 2 ** attempt_count seconds
```

**Celery beat schedule:**
```python
CELERY_BEAT_SCHEDULE = {
    'retry-stuck-payouts': {
        'task': 'workers.tasks.retry_stuck_payouts',
        'schedule': 30.0,  # every 30 seconds
    },
}
```

**Inline comment requirement for this phase:**
The randomness block must have a comment explaining each probability bucket.
The refund CREDIT creation must have a comment explaining why it is in the same transaction as the state transition and what breaks if it is not.
The stuck-payout detector must have a comment explaining how `updated_at` is used as the heartbeat.

**Stripe principles active this phase:** P1, P3, P4, P7, P8, P10

---

## Phase 4 — Tests

### Test 1 — Concurrency (required)

```python
def test_concurrent_payout_overdraw():
    """
    Stripe principle P5 — Lock before you read.

    Scenario:
      A merchant has exactly 10000 paise (₹100) of available balance.
      Two threads simultaneously POST /api/v1/payouts/ for 6000 paise (₹60) each.

    Expected outcome:
      - Exactly one response is 201 Created.
      - Exactly one response is 402 with error.code = 'insufficient_funds'.
      - After both threads complete:
          * LedgerEntry DEBIT count for this merchant = 1 (not 2)
          * SUM(CREDIT) - SUM(DEBIT) = 4000 paise (not -2000)
          * PayoutRequest count in ['pending','processing'] = 1 (not 2)

    Implementation notes:
      Use threading.Barrier to ensure both threads reach the POST call
      at the same instant before either fires. Without the barrier,
      thread scheduling means they run sequentially and the test is worthless.

      Use a threading.Barrier(2) set before both threads start,
      then call barrier.wait() inside each thread function immediately
      before the requests.post() call.

    Invariant check (run after threads join):
      credits = LedgerEntry.objects.filter(merchant=m, entry_type='CREDIT')
                  .aggregate(s=Sum('amount_paise'))['s']
      debits  = LedgerEntry.objects.filter(merchant=m, entry_type='DEBIT')
                  .aggregate(s=Sum('amount_paise'))['s']
      assert credits - debits == merchant_available_balance_via_api
    """
```

### Test 2 — Idempotency (required)

```python
def test_idempotency_key_replay():
    """
    Stripe principle P2 — Idempotency is a first-class API primitive.

    Scenario:
      Two sequential POST /api/v1/payouts/ calls with the identical
      Idempotency-Key header value and identical request bodies.

    Expected outcome:
      - Both responses return HTTP 201.
      - response_1.json() == response_2.json()  (byte-for-byte identical)
        Same payout ID. Same created_at. Same amount. Same state.
      - PayoutRequest.objects.filter(merchant=m).count() == 1  (not 2)
      - LedgerEntry DEBIT count = 1  (not 2)
      - IdempotencyKey.objects.filter(merchant=m, key=k).count() == 1

    Also test the mismatch case:
      Third call with same key but different amount_paise
      → must return 409 with error.code = 'idempotency_key_conflict'
    """
```

### Test 3 — State machine (required)

```python
def test_illegal_state_transitions():
    """
    Stripe principle P4 — Illegal transitions are hard errors.

    Each of the following must raise InvalidStateTransition.
    Test them at the model layer (call payout.transition_to() directly —
    no HTTP needed, this is a unit test on the model method).

    Illegal moves to verify:
      - completed → pending
      - completed → processing
      - completed → failed
      - failed → pending
      - failed → processing
      - failed → completed
      - pending → completed   (skips processing)
      - pending → failed      (skips processing)

    Also verify the legal path does NOT raise:
      - pending → processing  (ok)
      - processing → completed (ok)
      - processing → failed    (ok)

    And verify that on processing → failed, a CREDIT LedgerEntry
    is created in the same transaction (the refund is atomic).
    Query LedgerEntry AFTER calling transition_to('failed') and
    assert the CREDIT row exists with the correct amount_paise.
    """
```

### Test 4 — Balance invariant (required)

```python
def test_ledger_invariant_holds_throughout_lifecycle():
    """
    Stripe principle P3 — Immutable ledger as source of truth.

    This test checks the invariant at every stage of a payout lifecycle,
    not just at the end. The invariant must hold even mid-flight.

    Invariant: SUM(CREDIT entries) - SUM(DEBIT entries) == GET /merchants/me available_balance

    Check it at each of these points:
      1. After seed credits are created (baseline)
      2. After payout is created in 'pending' state (DEBIT hold applied)
      3. After payout moves to 'processing' (no ledger change — invariant still holds)
      4a. After payout completes (no ledger change — DEBIT stands, funds gone)
      4b. After payout fails (CREDIT refund applied — available_balance restored)

    Also assert: at no point does any LedgerEntry row get updated or deleted.
    Take a snapshot of all LedgerEntry PKs before and after each stage.
    The set of PKs must be monotonically growing — never shrinking, never changing.
    """
```

### Test 5 — Heartbeat and stuck-payout detection (required)

```python
def test_stuck_payout_retry_and_promotion_to_failed():
    """
    Stripe principle P7 — Observability is built in, not bolted on.
    Stripe principle P8 — Background workers are suspects.

    Scenario:
      A payout is manually placed in 'processing' state with
      updated_at set to 60 seconds ago (simulating a hung worker).

    Part A — Retry:
      Call retry_stuck_payouts() directly (not via beat schedule).
      Assert:
        - payout.attempt_count incremented by 1
        - payout.state remains 'processing' (not yet failed)
        - process_payout task was enqueued (check Celery task queue or use mock)
        - payout.updated_at was refreshed (the heartbeat moved)

    Part B — Promotion to failed after max attempts:
      Set payout.attempt_count = 3 (at the limit), updated_at = 60s ago.
      Call retry_stuck_payouts() again.
      Assert:
        - payout.state == 'failed'
        - payout.failure_reason contains 'max retries exceeded' or similar
        - A CREDIT LedgerEntry was created atomically (refund happened)
        - SUM(CREDIT) - SUM(DEBIT) equals the pre-payout balance (fully restored)

    Part C — Worker idempotency:
      Call process_payout(payout_id) on a payout that is already 'completed'.
      Assert: no exception, no state change, no new ledger entries.
      The task must detect the stale state at entry and exit cleanly. (P8)

    updated_at manipulation:
      Use PayoutRequest.objects.filter(pk=payout.pk).update(updated_at=stale_time)
      (bypass auto_now by using queryset update, which does not trigger auto_now)
    """
```

**Inline comment requirement for this phase:**
Every test must have a docstring explaining the scenario, the exact invariant being
checked, and which Stripe principle it verifies.
Every assertion must have an inline comment explaining what it would catch if it failed
— not just what it checks.
Example:
```python
assert status_codes.count(201) == 1  # catches: both threads succeeded (no lock)
assert status_codes.count(402) == 1  # catches: both threads failed (over-rejection)
assert debit_count == 1              # catches: two DEBIT entries created (double-spend)
assert balance_paise == 4000         # catches: negative balance allowed through
```

---

## Phase 5 — React + Tailwind Frontend

> **Framework versions for this phase:**
> React 19.x · Tailwind CSS v4.x · Vite (latest) · Axios (latest)
>
> **Tailwind CSS v4 is a ground-up rewrite — do not use v3 setup instructions.**
> v4 installation with Vite uses `@tailwindcss/vite` plugin, not PostCSS config.
> There is no `tailwind.config.js` — configuration lives in your CSS file with `@import "tailwindcss"`.
> Content detection is automatic — no `content: []` array needed.
> Install: `npm install tailwindcss @tailwindcss/vite`
> Docs: https://tailwindcss.com/docs/installation/using-vite
>
> **React 19.x notes:**
> Use `use()` hook for data fetching with Suspense where appropriate.
> `useRef()` now requires an initial argument — `useRef(null)` not `useRef()`.
> `useEffectEvent` is now stable for non-reactive effect logic.
> Refs are passed as regular props in React 19 — no `forwardRef` needed.
> All standard hooks (`useState`, `useEffect`, `useCallback`, `useMemo`) unchanged.
> Docs: https://react.dev/reference/react

**What to build:**

### Components

**`BalanceCard`**
- Shows `available_balance` in rupees (paise ÷ 100, formatted as ₹X,XXX.XX)
- Shows `held_balance` separately with a tooltip: "Funds held for pending payouts"
- Polls `GET /api/v1/merchants/me/` every 5 seconds
- Skeleton loader on first load

**`PayoutForm`**
- Amount input — user types in rupees, frontend converts to paise before sending
- Bank account dropdown — populated from merchant's bank accounts
- On submit:
  - Generate UUID v4 as idempotency key (stored in component state)
  - POST to `/api/v1/payouts/` with `Idempotency-Key: <uuid>` header
  - On 201: show success, refresh balance, refresh payout table
  - On 402: show "Insufficient funds" inline error
  - On 409: show "Request in progress, please wait"
  - On any other error: show structured error message from `error.code`

**`PayoutTable`**
- Columns: Date · Amount · Bank Account · Status · Attempts
- Status badges: pending (gray) · processing (blue, pulsing) · completed (green) · failed (red)
- Polls `GET /api/v1/payouts/` every 3 seconds
- Most recent first

**`LedgerFeed`**
- Recent 20 entries
- Credits in green with ↑ arrow
- Debits in red with ↓ arrow
- Amount in rupees, description, date

### API client (`src/api/client.js`)
- Axios instance with base URL from env
- JWT interceptor: attach `Authorization: Bearer <token>` to every request
- 401 interceptor: attempt token refresh, retry once, then redirect to login
- Every mutating request generates a fresh UUID idempotency key if not provided

**Inline comment requirement for this phase:**
The paise-to-rupees conversion utility must have a comment explaining why it is not using floating point division.
The idempotency key generation in the axios client must have a comment explaining its purpose.
Every polling hook must have a comment explaining the interval and what triggers a manual refresh.

---

## Phase 6 — Deployment & Final Files

**What to build:**

### `docker-compose.yml`
Services: `db` (postgres:15), `redis` (redis:7), `api` (Django + Gunicorn), `worker` (Celery), `beat` (Celery beat), `frontend` (Vite dev server or nginx).
Health checks on db and redis. `api`, `worker`, `beat` all depend on db + redis being healthy.

### `README.md` must include:
1. Local setup (docker-compose up — single command)
2. Manual setup (virtualenv, pip install, migrate, seed, runserver)
3. How to run tests
4. How to trigger a payout manually via curl with idempotency key
5. Live deployment URL
6. Architecture overview (one paragraph)

### `EXPLAINER.md` must include:

**Section 1 — The Ledger**
Paste the exact balance calculation query. Explain why credits and debits are separate rows rather than a running balance column. Explain what breaks if you store balance as a column.

**Section 2 — The Lock**
Paste the exact `SELECT FOR UPDATE` code block. Explain which PostgreSQL primitive it relies on (row-level lock). Explain what happens to the second concurrent request while the lock is held.

**Section 3 — Idempotency**
Explain how the system recognizes a key it has seen before (unique constraint + lookup). Explain what happens if the first request is still in-flight when the second arrives (`in_flight` status → 409). Explain what `response_body` contains and why it is stored verbatim.

**Section 4 — The State Machine**
Show the `transition_to()` method. Show the `VALID_TRANSITIONS` dict. Explain where `failed → completed` is blocked (it is not in `VALID_TRANSITIONS` at all — not a conditional, an absence). Explain why the state machine is at the model layer and not in the view or the task.

**Section 5 — The AI Audit**
Document one specific example where AI-generated code was subtly wrong. Show the exact wrong code. Explain what the bug was. Show the corrected version. Common traps to look for:
- AI writes `merchant.balance >= amount` using a Python variable fetched before the lock
- AI uses `payout.state = 'completed'` directly instead of calling `transition_to()`
- AI creates the DEBIT entry outside the transaction that checks the balance
- AI uses `update()` on PayoutRequest without `select_for_update()`
- AI uses `DecimalField` or floats for money amounts

---

## Commenting Standard (Apply to Every File)

Every file must open with a module-level docstring:
```python
"""
payouts/views.py

Handles payout request creation, listing, and retrieval.

The POST /payouts endpoint is the most critical in the system.
It enforces:
  - Idempotency (P2): same key always returns same response
  - Locking (P5): SELECT FOR UPDATE before balance check
  - Atomicity (P1): balance check + debit + payout creation in one transaction
  - Ledger integrity (P3): DEBIT entry written here, never updated
"""
```

Every function or method that touches money must have:
```python
def create_payout(merchant, amount_paise, bank_account, idempotency_key):
    """
    Creates a payout request and holds funds atomically.

    Stripe principle P5: We acquire a row-level lock on the merchant before
    reading the balance. This prevents two simultaneous requests from both
    reading the same balance and both succeeding.

    Stripe principle P10: The DEBIT ledger entry is created in the same
    transaction as the PayoutRequest. If anything fails, both roll back.
    There is no partial state.

    Args:
        merchant: Merchant instance (will be locked with SELECT FOR UPDATE)
        amount_paise: int — amount in paise, must be positive
        bank_account: BankAccount instance — must belong to merchant
        idempotency_key: str — caller-supplied UUID, scoped to merchant

    Returns:
        PayoutRequest instance in 'pending' state

    Raises:
        InsufficientFunds: if available_balance < amount_paise
        InvalidBankAccount: if bank_account.merchant != merchant
    """
```

Inline comments on non-obvious lines:
```python
# SELECT FOR UPDATE: acquires a PostgreSQL row-level lock on this merchant row.
# No other transaction can read or modify this row until we commit or rollback.
# This is the primitive that prevents two concurrent 60-rupee payouts from both
# passing the balance check when the merchant only has 100 rupees. (P5)
merchant = Merchant.objects.select_for_update().get(pk=merchant_id)
```

---

## What Success Looks Like

When the build is complete, the following must all be true:

**Money integrity**
- [ ] `SUM(CREDIT entries) - SUM(DEBIT entries)` equals `GET /merchants/me` balance at all times
- [ ] No LedgerEntry row is ever updated or deleted — PK set is monotonically growing
- [ ] No `FloatField`, no `DecimalField`, no Python arithmetic on fetched money rows

**Concurrency**
- [ ] Two simultaneous 60-rupee payouts on a 100-rupee balance: exactly one succeeds
- [ ] Test uses `threading.Barrier` so threads fire truly simultaneously

**Idempotency**
- [ ] Same `Idempotency-Key` sent twice: exactly one payout row, byte-identical responses
- [ ] Same key with different `amount_paise`: rejected with `idempotency_key_conflict`
- [ ] In-flight key (first request still processing): returns 409 `request_in_progress`
- [ ] Expired key (> 24h old): treated as new, not replayed
- [ ] `purge_expired_idempotency_keys` beat task runs and cleans the table

**State machine**
- [ ] All 8 illegal transitions raise `InvalidStateTransition` at the model layer
- [ ] `payout.state = 'x'` is never called directly anywhere — only `transition_to()`
- [ ] Failed payout refund is atomic: CREDIT entry and state change in one transaction

**Background workers**
- [ ] Celery beat finds stuck payouts within 30 seconds and retries or fails them
- [ ] Exponential backoff: attempt 1 waits 2s, attempt 2 waits 4s, attempt 3 marks failed
- [ ] `process_payout` called on an already-completed payout: exits cleanly, no side effects
- [ ] `updated_at` is refreshed on every retry (heartbeat moves forward)

**Bank accounts**
- [ ] `account_number` is never exposed in any API response — only `account_number_masked`
- [ ] A merchant referencing another merchant's bank account ID returns `403`
- [ ] Only one `is_default=True` per merchant enforced at DB level (partial unique index)
- [ ] Deleting a bank account with a pending/processing payout referencing it is rejected

**API contract**
- [ ] All error responses have `error.code`, `error.message`, `error.param`
- [ ] Every endpoint, model method, and task has inline comments explaining the why

---

## Build Order

```
Phase 1 → Models + Seed
Phase 2 → API Endpoints
Phase 3 → Celery Workers
Phase 4 → Tests
Phase 5 → React Frontend
Phase 6 → Docker + README + EXPLAINER
```

Do not skip phases. Do not build Phase 2 endpoints without Phase 1 models migrated.
Do not build Phase 5 without Phase 2 endpoints returning real data.
At the end of each phase, the work so far must be in a runnable state.
