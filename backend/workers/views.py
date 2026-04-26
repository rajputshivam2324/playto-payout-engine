"""
workers/views.py

Exposes a secret-token-protected endpoint that triggers periodic Celery tasks.

This replaces celery-beat and Render cron jobs — a free external cron service
(e.g. cron-job.org) pings this endpoint on a schedule instead.
"""

import os

from django.http import JsonResponse
from django.views import View

from workers.tasks import purge_expired_idempotency_keys, retry_stuck_payouts


class TriggerScheduledTasksView(View):
    """
    GET /ops/cron/?token=<CRON_SECRET>

    Dispatches all periodic maintenance tasks. Protected by a shared secret
    so only the external cron service can trigger it.
    """

    def get(self, request):
        expected = os.environ.get("CRON_SECRET", "")
        provided = request.GET.get("token", "")

        if not expected or provided != expected:
            return JsonResponse({"error": "forbidden"}, status=403)

        retry_stuck_payouts.delay()
        purge_expired_idempotency_keys.delay()

        return JsonResponse({"status": "dispatched"})
