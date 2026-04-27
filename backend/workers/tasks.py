"""
workers/tasks.py

Celery workers for payout settlement and maintenance.

Key design decisions:
  - Every task re-locks and re-checks state because Celery delivery can duplicate work.
  - Payout failure refunds use PayoutRequest.transition_to(), which writes state and CREDIT atomically.
  - Stuck payout detection treats updated_at as a worker heartbeat for processing payouts.
"""

import logging
import random
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from idempotency.models import IdempotencyKey
from payouts.models import InvalidStateTransition, PayoutRequest


logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, ignore_result=True, acks_late=True,
             soft_time_limit=90, time_limit=120)
def process_payout(self, payout_id):
    """
    Simulate bank settlement for a payout.

    Stripe P8: The task locks the payout row and re-checks state before doing work.
    Stripe P4: State changes go through PayoutRequest.transition_to().
    Stripe P10: Failed settlement refunds are created in the same DB transaction as failure.

    soft_time_limit=90 / time_limit=120: A real bank API that hangs indefinitely would
    block the worker forever without these guards. SoftTimeLimitExceeded is caught by
    Celery and the task exits cleanly; the hard limit terminates the process as a last resort.
    retry_stuck_payouts then detects the payout via the updated_at heartbeat and re-enqueues it.

    Args:
        self: Bound Celery task instance, used for broker-level retries on unexpected errors.
        payout_id: PayoutRequest UUID string to settle.

    Returns:
        None. The payout row and ledger record the durable result.

    Raises:
        self.retry: Unexpected infrastructure errors are retried by Celery with backoff.
    """
    try:
        with transaction.atomic():
            # Step 1: Acquire lock and re-check state.
            # The lock makes duplicate worker deliveries serialize on this payout row before acting. (P8)
            payout = PayoutRequest.objects.select_for_update().get(pk=payout_id)
            if payout.state == PayoutRequest.PENDING:
                # Step 2: pending -> processing is delegated to the model state machine. (P4)
                payout = payout.transition_to(PayoutRequest.PROCESSING)
                logger.info("process_payout: payout=%s moved to processing", payout_id)
            elif payout.state == PayoutRequest.PROCESSING:
                # Re-enqueued stuck payouts may already be processing; they can make one more settlement attempt.
                logger.info("process_payout: payout=%s retrying from processing", payout_id)
            else:
                # Terminal payouts mean another worker already settled this delivery, so the duplicate exits.
                logger.info("process_payout: payout=%s already %s, skipping", payout_id, payout.state)
                return
    except PayoutRequest.DoesNotExist:
        # Missing payout IDs are non-retryable; retrying cannot create the row.
        logger.warning("process_payout: payout=%s not found, skipping", payout_id)
        return
    except Exception as exc:
        # Unexpected DB or broker-side failures are retried with explicit countdown seconds per Celery docs.
        logger.exception("process_payout: setup failed for payout=%s", payout_id)
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)

    # Step 3: Simulate bank settlement.
    # < 0.70 succeeds, 0.70-0.90 fails and refunds, >= 0.90 hangs so retry_stuck_payouts catches it.
    settlement_roll = random.random()
    logger.info("process_payout: payout=%s settlement_roll=%.4f", payout_id, settlement_roll)

    if settlement_roll < 0.70:
        _complete_payout(payout_id)
        return

    if settlement_roll < 0.90:
        _fail_payout_with_refund(payout_id, "bank_settlement_failed")
        return

    # The >= 0.90 branch simulates a bank hang by returning without settling.
    # The payout stays in PROCESSING with an old updated_at heartbeat.
    # retry_stuck_payouts detects it after 30 s and re-enqueues or fails atomically.
    # Previously this used time.sleep(60), which blocked the whole worker process and
    # starved all other tasks — including retry_stuck_payouts itself.
    logger.warning("process_payout: payout=%s simulated bank hang — returning without settling", payout_id)


def _complete_payout(payout_id):
    """
    Complete a processing payout if it has not already reached a terminal state.

    Args:
        payout_id: PayoutRequest UUID string to complete.

    Returns:
        None. Duplicate deliveries exit after re-checking the locked row.
    """
    try:
        with transaction.atomic():
            # Lock before the terminal transition so two workers cannot both finish the payout. (P8)
            payout = PayoutRequest.objects.select_for_update().get(pk=payout_id)
            if payout.state != PayoutRequest.PROCESSING:
                # Another worker already completed or failed this payout; no money action is needed.
                logger.info("_complete_payout: payout=%s is %s, skipping", payout_id, payout.state)
                return
            # Step 4a: processing -> completed through the model state machine. (P4)
            payout.transition_to(PayoutRequest.COMPLETED)
            logger.info("_complete_payout: payout=%s completed", payout_id)
    except PayoutRequest.DoesNotExist:
        # A missing row cannot be safely settled, so the worker records and exits.
        logger.warning("_complete_payout: payout=%s not found", payout_id)
    except InvalidStateTransition:
        # Illegal transitions are internal correctness failures and should be visible in logs.
        logger.exception("_complete_payout: illegal transition for payout=%s", payout_id)
        raise


def _fail_payout_with_refund(payout_id, reason):
    """
    Fail a processing payout and refund the ledger hold atomically.

    Args:
        payout_id: PayoutRequest UUID string to fail.
        reason: Failure reason stored on the payout for operator debugging.

    Returns:
        None. Duplicate deliveries exit after re-checking the locked row.
    """
    try:
        with transaction.atomic():
            # Lock before failure so a concurrent success cannot race the refund path. (P8, P10)
            payout = PayoutRequest.objects.select_for_update().get(pk=payout_id)
            if payout.state != PayoutRequest.PROCESSING:
                # A terminal state means the hold was already resolved by another worker.
                logger.info("_fail_payout_with_refund: payout=%s is %s, skipping", payout_id, payout.state)
                return
            # The CREDIT refund is created inside transition_to() in the same transaction as failed.
            # Splitting those writes would allow a failed payout without returned funds, which breaks P10.
            payout.transition_to(PayoutRequest.FAILED, reason=reason)
            logger.info("_fail_payout_with_refund: payout=%s failed with reason=%s", payout_id, reason)
    except PayoutRequest.DoesNotExist:
        # A missing row cannot be refunded because there is no authoritative payout amount.
        logger.warning("_fail_payout_with_refund: payout=%s not found", payout_id)
    except InvalidStateTransition:
        # Illegal transitions indicate a code path bypassed the documented payout lifecycle.
        logger.exception("_fail_payout_with_refund: illegal transition for payout=%s", payout_id)
        raise


@shared_task(ignore_result=True)
def retry_stuck_payouts():
    """
    Re-enqueue or fail payouts that have been processing too long.

    Stripe P7: updated_at is the heartbeat written on every transition/retry.
    Stripe P8: Each candidate is locked and re-checked before action.
    Stripe P10: Exhausted stuck payouts fail and refund in one atomic transition.

    Returns:
        Dict with counts for observability in worker logs.
    """
    # Snapshot cutoff once before the scan so both the initial query filter and the
    # per-row re-check inside the lock use the same timestamp. Computing cutoff inside
    # the loop would allow a payout whose updated_at is refreshed during a long loop to
    # slip through the guard on a later iteration with a different cutoff value.
    cutoff = timezone.now() - timedelta(seconds=30)
    scanned = retried = failed = skipped = 0

    # updated_at is the heartbeat: processing rows older than 30s likely belong to a hung worker.
    stuck_ids = list(
        PayoutRequest.objects.filter(
            state=PayoutRequest.PROCESSING,
            updated_at__lt=cutoff,
        ).values_list("id", flat=True)
    )

    for payout_id in stuck_ids:
        scanned += 1
        with transaction.atomic():
            # Lock each stuck payout before deciding whether it still qualifies. (P8)
            payout = PayoutRequest.objects.select_for_update().get(pk=payout_id)
            if payout.state != PayoutRequest.PROCESSING or payout.updated_at >= cutoff:
                # A live worker may have completed or refreshed the row since the scan query.
                skipped += 1
                continue

            if payout.attempt_count >= 3:
                # Maxed-out stuck payouts fail through the model so the refund CREDIT is atomic. (P10)
                payout.transition_to(PayoutRequest.FAILED, reason="stuck_payout_retry_limit_exceeded")
                failed += 1
                logger.error("retry_stuck_payouts: payout=%s failed after retries", payout_id)
                continue

            payout.attempt_count += 1
            # Manually write updated_at as the retry heartbeat while still inside the lock.
            payout.updated_at = timezone.now()
            payout.save(update_fields=["attempt_count", "updated_at"])
            # Exponential backoff uses the post-increment attempt count, per Phase 3 requirements.
            countdown = 2 ** payout.attempt_count
            # Enqueue only after the retry heartbeat commits so the next worker sees the fresh attempt_count.
            transaction.on_commit(
                lambda payout_id=str(payout.id), retry_countdown=countdown: process_payout.apply_async(
                    args=[payout_id],
                    countdown=retry_countdown,
                )
            )
            retried += 1
            logger.warning(
                "retry_stuck_payouts: payout=%s retry=%s countdown=%s",
                payout_id,
                payout.attempt_count,
                countdown,
            )

    logger.info(
        "retry_stuck_payouts: scanned=%s retried=%s failed=%s skipped=%s",
        scanned,
        retried,
        failed,
        skipped,
    )
    return {"scanned": scanned, "retried": retried, "failed": failed, "skipped": skipped}


@shared_task(ignore_result=True)
def purge_expired_idempotency_keys():
    """
    Delete idempotency keys after their 24-hour replay window.

    Returns:
        Number of rows deleted, including any cascaded rows reported by Django.
    """
    # Expired keys are already treated as absent by API lookup, so cleanup is safe at any time.
    deleted, _ = IdempotencyKey.objects.filter(expires_at__lt=timezone.now()).delete()
    logger.info("purge_expired_idempotency_keys: deleted=%s", deleted)
    return deleted
