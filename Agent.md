# AGENT.md — Playto Payout Engine

> This file is the operating manual for any AI agent building this project.
> Read it completely before writing a single line of code.
> Re-read the relevant section before starting each phase.
> When in doubt about any decision: stop, search, verify, then act.

---

## What You Are Building

A production-grade payout engine for Playto — a service that helps Indian freelancers
and agencies collect international payments. Money flows one direction only:

```
International customer (USD) → Playto collects → Merchant paid out (INR)
```

Your job is the engine in the middle: merchant balance tracking, payout requests,
background settlement simulation, and a React dashboard. Every decision you make
must be defensible against the question: *"Would Stripe ship this?"*

---

## Agent Behaviour Rules

These govern how you operate during the build — not what you build.

### Rule 1 — Search before you assume

If you are about to write code that uses a library API, a Django ORM method,
a Celery configuration key, a PostgreSQL feature, or a React hook — and you are
not 100% certain of the exact current API — **search first**.

Do not guess method signatures. Do not recall from training data if there is any
chance the API has changed. Search, read the docs, then write the code.

Triggers that must always produce a search before code is written:
- Any Django version-specific ORM behaviour (e.g. `select_for_update(of=...)`, `aselect_for_update`)
- Any Celery configuration key or beat schedule format
- Any `djangorestframework-simplejwt` setting or view name
- Any PostgreSQL partial index syntax in Django migrations
- Any React 18 hook that did not exist in React 16 (e.g. `useDeferredValue`, `useId`)
- Any Vite configuration option
- Railway deployment environment variable names and service linking syntax
- Any Python package version constraint you are not certain about

### Rule 2 — Verify versions before installing

Before writing `requirements.txt` or `package.json`, search for the current stable
versions of every dependency. Do not hardcode versions from memory.

Packages to always verify:
- `Django` — check djangoproject.com for current LTS
- `djangorestframework` — check pypi.org/project/djangorestframework
- `celery` — check docs.celeryq.dev for current stable
- `redis` (python client) — check pypi.org/project/redis
- `djangorestframework-simplejwt` — check pypi.org/project/djangorestframework-simplejwt
- `psycopg2-binary` — check pypi.org/project/psycopg2-binary
- `react` and `react-dom` — check npmjs.com
- `@vitejs/plugin-react` — check npmjs.com
- `axios` — check npmjs.com
- `tailwindcss` — check tailwindcss.com for current version and PostCSS config

### Rule 3 — One phase at a time, runnable at each boundary

Complete Phase 1 fully before starting Phase 2.
At the end of every phase, the project must be in a runnable state:
- `python manage.py migrate` runs without errors
- `python manage.py seed_merchants` runs without errors
- `python manage.py runserver` starts without errors
- All previously written tests still pass

Do not proceed to the next phase if the current one is not runnable.

### Rule 4 — Comment as you write, not after

Every function, method, and endpoint gets its comment at the time of writing —
not as a cleanup pass at the end. If you are writing a function and find yourself
thinking "I'll comment this later" — stop and write the comment now.

The commenting standard is defined in full in `PLAYTO_BUILD_PROMPT.md`.
Short version: module docstring + function docstring with Args/Returns/Raises
+ inline comment on every non-obvious line, especially anything touching money,
locks, or state transitions.

### Rule 5 — Never write money logic without a transaction boundary

If you are writing any code that reads a balance, creates a ledger entry,
changes a payout state, or refunds funds — wrap it in `transaction.atomic()`
before writing anything else inside it. The transaction boundary is not an
afterthought. It is the first line.

### Rule 6 — When something feels wrong, stop and reason out loud

If you are about to implement something that feels like it might have a race
condition, a stale read, a missing lock, or a non-atomic operation — write a
comment block first explaining the concern, then reason through the correct
approach, then write the code. Do not suppress the concern.

---

## Reference Docs — Search These During the Build

The agent must fetch these URLs at the relevant phase. Do not rely on memory
for any of these. Fetch the page, read the relevant section, then implement.

### Django + DRF

> Django 5.2 LTS is the target. All URLs point to 5.2 docs.
> Django 6.0 released Dec 2025 but 5.2 is the stable LTS choice for production.

| Topic | URL |
|---|---|
| Django transactions | https://docs.djangoproject.com/en/5.2/topics/db/transactions/ |
| select_for_update | https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update |
| Django aggregation | https://docs.djangoproject.com/en/5.2/topics/db/aggregation/ |
| Custom model managers | https://docs.djangoproject.com/en/5.2/topics/db/managers/ |
| Django signals | https://docs.djangoproject.com/en/5.2/topics/signals/ |
| Management commands | https://docs.djangoproject.com/en/5.2/howto/custom-management-commands/ |
| Django migrations (constraints) | https://docs.djangoproject.com/en/5.2/ref/models/constraints/ |
| Partial unique index (Django) | https://docs.djangoproject.com/en/5.2/ref/models/indexes/#django.db.models.Index |
| Django 5.2 release notes | https://docs.djangoproject.com/en/5.2/releases/5.2/ |
| DRF serializers | https://www.django-rest-framework.org/api-guide/serializers/ |
| DRF generic views | https://www.django-rest-framework.org/api-guide/generic-views/ |
| DRF authentication | https://www.django-rest-framework.org/api-guide/authentication/ |
| DRF exception handling | https://www.django-rest-framework.org/api-guide/exceptions/ |
| DRF throttling | https://www.django-rest-framework.org/api-guide/throttling/ |
| simplejwt quickstart | https://django-rest-framework-simplejwt.readthedocs.io/en/latest/getting_started.html |

### Celery

> Celery 5.6.x is the current stable. Docs at celeryq.dev/en/stable point to 5.6.

| Topic | URL |
|---|---|
| Celery first steps with Django | https://docs.celeryq.dev/en/stable/django/first-steps-with-django.html |
| Celery beat periodic tasks | https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html |
| Celery task retries | https://docs.celeryq.dev/en/stable/userguide/tasks.html#retrying |
| Celery canvas (chains, chords) | https://docs.celeryq.dev/en/stable/userguide/canvas.html |
| Celery configuration reference | https://docs.celeryq.dev/en/stable/userguide/configuration.html |
| Redis as Celery broker | https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html |
| What's new in Celery 5.6 | https://docs.celeryq.dev/en/stable/whatsnew-5.6.html |

### PostgreSQL

| Topic | URL |
|---|---|
| PostgreSQL row-level locking | https://www.postgresql.org/docs/current/explicit-locking.html#LOCKING-ROWS |
| PostgreSQL partial indexes | https://www.postgresql.org/docs/current/indexes-partial.html |
| PostgreSQL BIGINT | https://www.postgresql.org/docs/current/datatype-numeric.html |

### React + Frontend

| Topic | URL |
|---|---|
| React 18 hooks reference | https://react.dev/reference/react |
| useEffect + cleanup | https://react.dev/reference/react/useEffect |
| Tailwind CSS utility classes | https://tailwindcss.com/docs/utility-first |
| Tailwind CSS installation (Vite) | https://tailwindcss.com/docs/guides/vite |
| Axios instance + interceptors | https://axios-http.com/docs/instance |
| Axios request config | https://axios-http.com/docs/req_config |
| uuid npm package | https://www.npmjs.com/package/uuid |
| Vite env variables | https://vitejs.dev/guide/env-and-mode |

### Deployment

| Topic | URL |
|---|---|
| Railway docs | https://docs.railway.app |
| Railway services + networking | https://docs.railway.app/reference/services |
| Railway environment variables | https://docs.railway.app/reference/variables |
| Railway Nixpacks (Django) | https://docs.railway.app/guides/django |
| Docker Compose health checks | https://docs.docker.com/compose/compose-file/05-services/#healthcheck |
| Gunicorn config | https://docs.gunicorn.org/en/stable/configure.html |

---

## Search Triggers by Phase

When you start each phase, fetch the listed URLs before writing code.
These are the minimum; fetch more if you encounter anything unfamiliar.

### Phase 1 — Models + Seed
- Fetch: Django transactions, Django migrations (constraints), Partial unique index
- Search for: current stable versions of all Python dependencies
- Search for: `BigIntegerField` vs `PositiveBigIntegerField` Django 4.2 — verify which to use
- Search for: Django `UniqueConstraint` with `condition` parameter syntax (partial index)

### Phase 2 — API Endpoints
- Fetch: DRF serializers, DRF generic views, DRF exception handling, simplejwt quickstart
- Fetch: select_for_update, Django aggregation
- Search for: DRF custom exception handler — how to return `{"error": {...}}` shape globally
- Search for: `get_or_create` atomicity guarantees in PostgreSQL with Django — verify it uses INSERT ON CONFLICT
- Search for: how to set `updated_at` manually when `auto_now=True` is set (use `queryset.update()`)

### Phase 3 — Celery Workers
- Fetch: Celery first steps with Django, Celery beat periodic tasks, Celery task retries
- Fetch: Redis as Celery broker
- Search for: Celery `bind=True` + `self.retry()` with `countdown` — verify current API
- Search for: how to prevent Celery from swallowing exceptions silently — verify `task_acks_late` setting
- Search for: Celery beat `CELERY_BEAT_SCHEDULE` vs `beat_schedule` — verify which key Django uses in settings

### Phase 4 — Tests
- Fetch: Django test client docs — https://docs.djangoproject.com/en/4.2/topics/testing/tools/
- Search for: Django `TestCase` vs `TransactionTestCase` — critical for concurrency tests
  (regular `TestCase` wraps each test in a transaction, which breaks `select_for_update` testing)
- Search for: `threading.Barrier` Python docs — verify constructor and `wait()` API
- Search for: Celery task testing with `CELERY_TASK_ALWAYS_EAGER` — verify current setting name

### Phase 5 — React Frontend
- Fetch: React 18 hooks reference, useEffect + cleanup, Tailwind CSS installation (Vite)
- Fetch: Axios instance + interceptors, uuid npm package, Vite env variables
- Search for: current Tailwind CSS v3 vs v4 — verify which version and PostCSS config applies
- Search for: `crypto.randomUUID()` browser support vs `uuid` npm package — decide which to use for idempotency key generation

### Phase 6 — Deployment
- Fetch: Railway docs, Railway services + networking, Railway environment variables, Railway Nixpacks (Django)
- Fetch: Docker Compose health checks, Gunicorn config
- Search for: Railway Celery worker deployment pattern — how to run worker + beat as separate Railway services
- Search for: Railway Redis plugin — current setup steps and `REDIS_URL` env var name

---

## Forbidden Patterns

These patterns are banned. If you find yourself writing any of them, stop immediately,
delete the code, search for the correct approach, and start again.

### Money and data integrity

```python
# BANNED — Python arithmetic on a fetched value. Stale by the time you act on it.
merchant = Merchant.objects.get(pk=id)
if merchant.balance >= amount:   # merchant.balance is a snapshot, not locked
    merchant.balance -= amount
    merchant.save()

# BANNED — FloatField or DecimalField for money
amount = models.FloatField()
amount = models.DecimalField(max_digits=10, decimal_places=2)

# BANNED — Direct state assignment bypassing the state machine
payout.state = 'completed'
payout.save()

# BANNED — Updating a ledger entry
LedgerEntry.objects.filter(pk=entry.pk).update(amount_paise=new_amount)

# BANNED — Deleting a ledger entry
LedgerEntry.objects.filter(merchant=m).delete()

# BANNED — Creating a DEBIT entry outside the balance-check transaction
with transaction.atomic():
    balance = get_balance(merchant)
    if balance >= amount:
        payout = PayoutRequest.objects.create(...)
# ^ transaction commits here — DEBIT not yet written
LedgerEntry.objects.create(entry_type='DEBIT', ...)  # NOT ATOMIC WITH BALANCE CHECK
```

### Locking

```python
# BANNED — Reading balance without a lock
balance = LedgerEntry.objects.filter(merchant=m).aggregate(...)['balance']
# Another request can pass this check simultaneously

# BANNED — Using update() on PayoutRequest without select_for_update
PayoutRequest.objects.filter(pk=payout_id).update(state='processing')
# No lock held — two workers can both do this simultaneously

# BANNED — select_for_update outside a transaction.atomic() block
merchant = Merchant.objects.select_for_update().get(pk=id)
# select_for_update has no effect outside an atomic block in autocommit mode
```

### API responses

```python
# BANNED — Naked exception response
except Exception as e:
    return Response({'detail': str(e)}, status=500)

# BANNED — Non-structured error
return Response({'message': 'insufficient funds'}, status=400)

# REQUIRED shape — always
return Response({
    'error': {
        'code': 'insufficient_funds',
        'message': 'Available balance of ₹150.00 is less than requested ₹600.00',
        'param': 'amount_paise',
    }
}, status=402)
```

### Background workers

```python
# BANNED — Task that does not re-check state at entry
@shared_task
def process_payout(payout_id):
    payout = PayoutRequest.objects.get(pk=payout_id)
    # ^ No lock. No state check. If this runs twice, both proceed.
    simulate_bank_settlement(payout)

# REQUIRED pattern
@shared_task(bind=True)
def process_payout(self, payout_id):
    with transaction.atomic():
        # Re-acquire lock and re-check state — P8, workers are suspects
        payout = PayoutRequest.objects.select_for_update().get(pk=payout_id)
        if payout.state != 'pending':
            # Already processed by another worker or a retry — exit cleanly
            logger.info(f"process_payout: payout {payout_id} is {payout.state}, skipping")
            return
        payout.transition_to('processing')
    # ... rest of task
```

### Frontend

```javascript
// BANNED — Sending rupees to the API
const response = await api.post('/payouts/', { amount: rupeesValue });

// REQUIRED — Always convert to paise before sending
const amountPaise = Math.round(parseFloat(rupeesValue) * 100);
// Note: integer multiplication, not float division on the receive side

// BANNED — Exposing or logging the full idempotency key in console
console.log('Sending with key:', idempotencyKey);

// BANNED — Reusing the same idempotency key across different form submissions
// Each submit generates a fresh UUID. Store it in component state per submission.
```

---

## Self-Check Checklist (Run Before Each Phase Commit)

Before marking a phase complete, verify every item. Do not skip items.

### After Phase 1
- [ ] `python manage.py migrate` runs clean on a fresh DB
- [ ] `python manage.py seed_merchants` creates exactly 3 merchants
- [ ] Each merchant has 2 bank accounts and 20–30 CREDIT ledger entries
- [ ] `LedgerEntry` has no `updated_at` field (immutable — no auto_now)
- [ ] `IdempotencyKey` has `UniqueConstraint` on `(merchant, key)` in migration
- [ ] `BankAccount` has partial unique index on `is_default=True` in migration
- [ ] `PayoutRequest.updated_at` uses `auto_now=True`
- [ ] All models registered in Django admin
- [ ] No `FloatField` or `DecimalField` anywhere in models.py files

### After Phase 2
- [ ] `POST /api/v1/payouts/` returns 400 if `Idempotency-Key` header is missing
- [ ] `POST /api/v1/payouts/` with the same key twice returns identical responses
- [ ] `POST /api/v1/payouts/` uses `select_for_update()` before balance check
- [ ] `GET /api/v1/bank-accounts/` never returns `account_number` — only `account_number_masked`
- [ ] `POST /api/v1/payouts/` with another merchant's `bank_account_id` returns 403
- [ ] All error responses have `error.code`, `error.message`, `error.param`
- [ ] All views are authenticated — unauthenticated requests return 401
- [ ] `GET /api/v1/merchants/me/` returns both `available_balance_paise` and `held_balance_paise`

### After Phase 3
- [ ] `process_payout` task re-checks payout state at entry with a lock
- [ ] `retry_stuck_payouts` correctly identifies payouts where `updated_at < now - 30s`
- [ ] Failed payouts create a CREDIT LedgerEntry in the same `transaction.atomic()` as the state transition
- [ ] `purge_expired_idempotency_keys` is in `CELERY_BEAT_SCHEDULE`
- [ ] `retry_stuck_payouts` is in `CELERY_BEAT_SCHEDULE` with 30-second interval
- [ ] Exponential backoff: `countdown = 2 ** attempt_count`

### After Phase 4
- [ ] Concurrency test uses `threading.Barrier` (not just `threading.Thread`)
- [ ] Concurrency test uses `TransactionTestCase` (not `TestCase`)
- [ ] All 8 illegal state transitions are tested at the model layer
- [ ] Idempotency test checks that `response_1.json() == response_2.json()` exactly
- [ ] Idempotency test checks payout count == 1 and DEBIT entry count == 1
- [ ] Heartbeat test calls `retry_stuck_payouts()` directly and asserts on `updated_at`
- [ ] Balance invariant test checks at every lifecycle stage, not just the end
- [ ] Every test has a docstring naming the Stripe principle it verifies

### After Phase 5
- [ ] Paise-to-rupees conversion uses integer arithmetic, not float division
- [ ] Idempotency key is a fresh UUID per form submission, stored in component state
- [ ] `PayoutTable` status badge for `processing` has a visible pulse animation
- [ ] `BalanceCard` shows `held_balance` separately with a tooltip
- [ ] API client attaches `Idempotency-Key` header on every POST
- [ ] 402 response shows "Insufficient funds" inline in the form, not a toast
- [ ] 409 response shows "Request in progress, please wait" inline

### After Phase 6
- [ ] `docker compose up` starts all 6 services without errors
- [ ] `docker compose up` runs seed automatically on first start
- [ ] `EXPLAINER.md` Section 2 (The Lock) pastes actual code, not pseudocode
- [ ] `EXPLAINER.md` Section 5 (AI Audit) shows real wrong code that was caught
- [ ] `README.md` includes a `curl` example with `Idempotency-Key` header

---

## Error Code Registry

All error codes in the system. Use exactly these strings. Never invent new ones mid-build.

| Code | HTTP Status | Meaning |
|---|---|---|
| `insufficient_funds` | 402 | Available balance < requested amount |
| `invalid_bank_account` | 400 | `bank_account_id` not found |
| `bank_account_not_owned` | 403 | Bank account belongs to different merchant |
| `bank_account_in_use` | 409 | Cannot delete — active payout references it |
| `idempotency_key_missing` | 400 | `Idempotency-Key` header absent |
| `idempotency_key_conflict` | 409 | Same key, different request parameters |
| `request_in_progress` | 409 | Key exists with `in_flight` status |
| `invalid_state_transition` | 500 | Internal — log it, do not expose to client |
| `payout_not_found` | 404 | Payout ID not found or not owned by merchant |
| `amount_must_be_positive` | 400 | `amount_paise` ≤ 0 |
| `amount_exceeds_maximum` | 400 | `amount_paise` > 10,000,000 (₹1 lakh safety cap) |

---

## Commenting Standard (Enforced — Not Optional)

### Module docstring — every file

```python
"""
merchants/models.py

Defines the Merchant and BankAccount models.

Key design decisions:
  - BankAccount.account_number stored in full; masked at serializer layer only (P6)
  - BankAccount.is_default enforced as singleton via partial unique index (P1)
  - No balance column on Merchant — balance is always derived from LedgerEntry (P3)
"""
```

### Function docstring — every function touching money, state, or locks

```python
def create_payout(merchant, amount_paise, bank_account, idempotency_key):
    """
    Creates a payout and holds funds atomically.

    Stripe P5: Acquires SELECT FOR UPDATE on merchant before balance read.
    Stripe P1: Balance check + DEBIT entry + PayoutRequest creation in one transaction.
    Stripe P10: If anything raises, all three roll back together.

    Args:
        merchant: Merchant — will be locked with SELECT FOR UPDATE
        amount_paise: int — amount in paise, must be > 0
        bank_account: BankAccount — must belong to merchant
        idempotency_key: str — caller-supplied UUID, scoped to merchant

    Returns:
        PayoutRequest in 'pending' state

    Raises:
        InsufficientFunds: available_balance < amount_paise
        InvalidBankAccount: bank_account.merchant_id != merchant.id
    """
```

### Inline comment — every non-obvious line

```python
# SELECT FOR UPDATE: PostgreSQL row-level lock on this merchant row.
# Held until transaction commits or rolls back. The second concurrent
# request blocks here and re-reads the aggregate after the first commits.
# This is the primitive that prevents overdraw. (P5)
merchant = Merchant.objects.select_for_update().get(pk=merchant_id)

# DB-level aggregate — never Python arithmetic on a fetched value.
# Running this inside the locked transaction ensures we see the
# balance as of the lock acquisition, not a stale snapshot. (P3, P5)
result = LedgerEntry.objects.filter(merchant=merchant).aggregate(
    credits=Sum('amount_paise', filter=Q(entry_type='CREDIT')),
    debits=Sum('amount_paise', filter=Q(entry_type='DEBIT')),
)

# Atomically create DEBIT entry in same transaction as PayoutRequest.
# If payout creation fails after this, the DEBIT rolls back too.
# There is no state where a DEBIT exists without a PayoutRequest. (P10)
LedgerEntry.objects.create(
    merchant=merchant,
    entry_type='DEBIT',
    amount_paise=amount_paise,
    reference_id=str(payout.id),
    description=f'Payout hold — {bank_account.ifsc_code} ••••{account_last4}',
)
```

---

## When You Are Stuck

If you cannot figure out the correct implementation for something:

1. **Search the reference docs table above** for the relevant topic.
2. **Search for the specific error or pattern** — e.g. "Django select_for_update outside transaction", "Celery task retry countdown", "DRF custom exception handler".
3. **Read the Stripe engineering blog** for conceptual guidance:
   - https://stripe.com/blog/idempotency
   - https://stripe.com/blog/payment-api-design
4. **Reason out loud in a comment** — write a `# DECISION:` block explaining your options and why you chose one:
   ```python
   # DECISION: Using select_for_update(of=('self',)) rather than locking
   # all related objects. We only need to lock the merchant row because
   # the balance aggregate reads LedgerEntry, which is append-only and
   # does not need locking. Locking LedgerEntry too would cause unnecessary
   # contention between unrelated merchants. Verified against Django docs:
   # https://docs.djangoproject.com/en/4.2/ref/models/querysets/#select-for-update
   ```
5. If still stuck after steps 1–4: implement the simpler correct approach, leave a
   `# TODO(correctness):` comment explaining the concern, and note it in `EXPLAINER.md`.
   Do not implement a wrong approach and hope it works.

---

## Build Order

```
Phase 1 → Models + migrations + seed command
Phase 2 → All API endpoints + bank account endpoints
Phase 3 → Celery worker + beat tasks
Phase 4 → All 5 tests passing
Phase 5 → React frontend connected to real API
Phase 6 → docker-compose.yml + README.md + EXPLAINER.md + deploy
```

Strict rule: **every phase must be in a runnable state before the next phase begins.**
This is not optional. A half-built Phase 2 and a started Phase 3 is worse than a
complete Phase 2 with no Phase 3 — because you cannot test, cannot verify invariants,
and cannot catch bugs at the boundary where they actually live.
