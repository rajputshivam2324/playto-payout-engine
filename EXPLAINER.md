# Playto Payout Engine — Technical Explainer

---

## Section 1 — The Ledger

### The Balance Calculation Query

```python
from django.db.models import Sum, Q

def get_merchant_balance(merchant_id):
    result = LedgerEntry.objects.filter(merchant_id=merchant_id).aggregate(
        credits=Sum('amount_paise', filter=Q(entry_type='CREDIT')),
        debits=Sum('amount_paise', filter=Q(entry_type='DEBIT')),
    )
    return (result['credits'] or 0) - (result['debits'] or 0)
```

### Why Credits and Debits Are Separate Rows

Every money movement is represented as its own immutable row. A collection from a customer is a `CREDIT` row. A payout hold is a `DEBIT` row. A failed payout refund is a new `CREDIT` row. No row is ever updated or deleted — the `LedgerEntry.save()` override raises `ImmutableLedgerEntryError` on update, and `delete()` always raises.

Balance is derived at query time: `SUM(credits) - SUM(debits)`. This means:

1. **Full audit trail** — You can reconstruct the merchant's balance at any point in history by replaying rows up to a timestamp.
2. **Structurally impossible to violate** — There is no mutable balance column that can drift out of sync with reality.
3. **Concurrent safety** — Two transactions inserting new rows cannot corrupt each other's view of the balance as long as the balance check runs inside a locked transaction (see Section 2).

### What Breaks If You Store Balance as a Column

If balance were a mutable column (`merchant.balance = merchant.balance - amount`), then:

- Two concurrent requests could both read `balance = 10000`, both compute `10000 - 6000 = 4000`, and both write `balance = 4000`. The merchant loses ₹60 but only got charged ₹60 once — the other ₹60 disappeared into the void.
- Balance could go negative if a bug writes a wrong number and there is no compensating ledger row to catch it during audit.
- Historical balance reconstruction requires storing snapshots or change logs, duplicating the work that the ledger already does.

---

## Section 2 — The Lock

### The SELECT FOR UPDATE Code Block

```python
with transaction.atomic():
    # SELECT FOR UPDATE: acquires a PostgreSQL row-level lock on this merchant row.
    # No other transaction can read-for-update or modify this row until we commit or rollback.
    # This is the primitive that prevents two concurrent 60-rupee payouts from both
    # passing the balance check when the merchant only has 100 rupees. (P5)
    locked_merchant = Merchant.objects.select_for_update().get(pk=merchant.pk)

    # Compute available balance via DB aggregate — runs inside the locked transaction
    ledger_balance = get_merchant_balance(locked_merchant.id)

    if amount_paise > ledger_balance:
        # Rollback: return error, merchant row lock is released
        return error_response("insufficient_funds", ...)

    # Create PayoutRequest + DEBIT LedgerEntry inside the same transaction
    payout = PayoutRequest.objects.create(...)
    LedgerEntry.objects.create(entry_type='DEBIT', ...)
    # Commit: both writes are durable, lock is released
```

### PostgreSQL Primitive

This relies on **PostgreSQL row-level locks** (`FOR UPDATE` clause in SQL). When `select_for_update()` runs, PostgreSQL places an exclusive lock on the merchant row. Any other transaction that tries to `SELECT FOR UPDATE` on the same row will **block** until the first transaction commits or rolls back.

### What Happens to the Second Concurrent Request

1. Thread A acquires the lock on merchant row, reads balance = ₹100, begins creating a ₹60 payout.
2. Thread B tries to `SELECT FOR UPDATE` on the same merchant row — it **blocks** at the database level.
3. Thread A writes the DEBIT entry (₹60 hold) and commits. The balance is now ₹40. Lock is released.
4. Thread B's `SELECT FOR UPDATE` unblocks. It reads balance = ₹40. It tries to create a ₹60 payout — but ₹40 < ₹60, so it returns `insufficient_funds`.

This is why SQLite cannot be used for development — SQLite silently ignores `select_for_update()`, making the lock a no-op and allowing both threads to succeed (double-spend).

---

## Section 3 — Idempotency

### How the System Recognizes a Previously Seen Key

The `IdempotencyKey` model has a `UniqueConstraint` on `(merchant, key)`. When a payout creation request arrives:

1. The view queries `IdempotencyKey.objects.filter(merchant=merchant, key=key_value).first()`.
2. If found and `status=done` and not expired → return the stored `response_body` verbatim (Case B).
3. If found and `status=in_flight` → return 409 `request_in_progress` (Case C).
4. If found but `expires_at < now` → delete the old key, treat as new (Case D).
5. If not found → create with `status=in_flight`, proceed to create the payout (Case A).

### What Happens When the First Request Is Still In-Flight

If the first request's `IdempotencyKey` has `status=in_flight` (meaning the payout creation is still processing), the second request sees Case C and returns:

```json
{
  "error": {
    "code": "request_in_progress",
    "message": "A request with this key is already being processed.",
    "param": "Idempotency-Key"
  }
}
```

This tells the client to wait and retry. It is expected behavior, not a bug. The unique constraint also handles the race where two requests try to create the key simultaneously — the loser gets an `IntegrityError` and returns the same 409.

### What `response_body` Contains and Why It Is Stored Verbatim

`response_body` is a `JSONField` containing the exact serialized payout response that the API returned on the first successful creation — including the payout `id`, `amount_paise`, `state`, `created_at`, and `updated_at`.

It is stored verbatim so that replays are **byte-perfect**: the second request with the same key returns the exact same payout ID, the exact same timestamp, the exact same status code. The client cannot tell whether it is receiving a fresh response or a replay. This matches Stripe's behavior.

Additionally, `request_params` stores a fingerprint of the original request body (`amount_paise` and `bank_account_id`). If a client reuses the same key with different parameters, the system rejects with `idempotency_key_conflict` (409) — preventing accidental reuse.

---

## Section 4 — The State Machine

### The `transition_to()` Method

```python
def transition_to(self, new_state, reason=None):
    with transaction.atomic():
        locked = type(self).objects.select_for_update().get(pk=self.pk)
        allowed_states = self.LEGAL_TRANSITIONS[locked.state]
        if new_state not in allowed_states:
            raise InvalidStateTransition(
                f"Cannot transition payout {locked.id} from {locked.state} to {new_state}."
            )
        locked.state = new_state
        locked.updated_at = timezone.now()
        if reason:
            locked.failure_reason = reason
        locked.save(update_fields=["state", "updated_at", "failure_reason"])

        if previous_state == self.PROCESSING and new_state == self.FAILED:
            LedgerEntry.objects.create(
                merchant=locked.merchant,
                entry_type=LedgerEntry.CREDIT,
                amount_paise=locked.amount_paise,
                reference_id=str(locked.id),
                description=f"Payout refund after failure - {reason or 'unspecified failure'}",
            )
        return locked
```

### The `VALID_TRANSITIONS` Dict

```python
LEGAL_TRANSITIONS = {
    PENDING: {PROCESSING},
    PROCESSING: {COMPLETED, FAILED},
    COMPLETED: set(),     # Terminal — no outgoing transitions
    FAILED: set(),        # Terminal — no outgoing transitions
}
```

### Where `failed → completed` Is Blocked

It is blocked by **absence**: `FAILED` maps to `set()` — an empty set of allowed next states. The code does not check `if new_state == 'completed' and current_state == 'failed': reject`. Instead, a `failed → completed` transition simply fails the `new_state not in allowed_states` check because `'completed' not in set()` is `True`. This means adding a new illegal transition requires no code change — it is illegal by default because it is not in the allow list.

### Why the State Machine Lives in the Model Layer

If the state machine were in the view or the Celery task, there would be multiple code paths that could change payout state. A new developer adding a management command or admin action could bypass the state machine by writing `payout.state = 'completed'` directly.

By encoding transitions in `PayoutRequest.transition_to()`, the model is the **single source of truth** for what transitions are legal. The method also handles locking and atomic refund creation. No code path — view, task, management command, or admin — can bypass it unless they directly write SQL.

---

## Section 5 — The AI Audit

### Bug: AI Used Float Division for Paise-to-Rupees Conversion

**Wrong code (AI-generated):**

```python
def rupees_from_paise(amount_paise):
    return f"₹{amount_paise / 100:.2f}"
```

**What the bug was:**

Float division can introduce IEEE 754 rounding artifacts. For example, `100007 / 100` evaluates to `1000.0699999999999` in Python, which would format as `₹1000.07` instead of `₹1,000.07`. More critically, using `/ 100` in a financial context establishes a pattern where money values are routinely converted to floats, inviting downstream comparisons like `amount >= 0.01` that are undefined in floating-point arithmetic.

**Corrected code:**

```python
def rupees_from_paise(amount_paise):
    # Integer arithmetic only — float division can introduce IEEE 754 rounding artifacts
    # on certain paise values, which violates the money-as-integers invariant. (P9)
    whole = amount_paise // 100
    fractional = abs(amount_paise) % 100
    return f"₹{whole:,}.{fractional:02d}"
```

The corrected version uses floor division (`//`) and modulo (`%`) — both integer operations — so no floating-point value is ever created. The same pattern is applied in the frontend `formatRupees()` function, which uses `Math.trunc()` and `%` instead of `/ 100`.
