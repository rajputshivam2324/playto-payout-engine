"""
workers/management/commands/trigger_scheduled_tasks.py

Fires all periodic Celery tasks that beat would normally schedule.

This command exists because Render free-tier workers spin down after 15 min
of inactivity, making celery-beat unreliable. A Render cron job calls this
command on a fixed schedule instead.
"""

from django.core.management.base import BaseCommand

from workers.tasks import purge_expired_idempotency_keys, retry_stuck_payouts


class Command(BaseCommand):
    """Dispatch periodic maintenance tasks via Celery (beat replacement)."""

    help = "Enqueue all scheduled Celery tasks — replaces beat on Render free tier."

    def handle(self, *args, **options):
        self.stdout.write("Dispatching retry_stuck_payouts …")
        retry_stuck_payouts.delay()

        self.stdout.write("Dispatching purge_expired_idempotency_keys …")
        purge_expired_idempotency_keys.delay()

        self.stdout.write(self.style.SUCCESS("All scheduled tasks dispatched."))
