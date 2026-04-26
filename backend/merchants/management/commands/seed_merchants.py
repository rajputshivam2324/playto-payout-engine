"""
merchants/management/commands/seed_merchants.py

Seeds local development data for the Playto payout engine.

Key design decisions:
  - The command is idempotent enough for local reruns by clearing non-auth seed data first.
  - Ledger rows are created, never updated, so seeded history follows append-only rules.
  - Completed payouts are moved through the model state machine instead of direct mutation.
"""

import random

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from ledger.models import LedgerEntry
from merchants.models import BankAccount, Merchant
from payouts.models import PayoutRequest


class Command(BaseCommand):
    """Create deterministic local merchants, bank accounts, credits, and payouts."""

    help = "Seed three merchants with bank accounts, credit ledger entries, and completed payouts."

    def handle(self, *args, **options):
        """
        Seed Phase 1 development data.

        Args:
            *args: Positional command arguments supplied by Django.
            **options: Parsed command options supplied by Django.

        Returns:
            None. Writes seed records and prints a summary to stdout.
        """
        random.seed(20260425)
        User = get_user_model()

        with transaction.atomic():
            # Step 1: Preserve existing money history on reruns because ledger rows are append-only.
            if Merchant.objects.exists() or LedgerEntry.objects.exists() or PayoutRequest.objects.exists():
                self.stdout.write(self.style.WARNING("Seed data already exists; leaving immutable money history unchanged."))
                return

            merchant_specs = [
                {
                    "username": "rahul",
                    "name": "Rahul Sharma Studio",
                    "email": "rahul@example.com",
                    "accounts": [
                        ("Rahul Sharma", "50100012345678", "HDFC0001234", True),
                        ("Rahul Sharma", "918273645501", "ICIC0000456", False),
                    ],
                },
                {
                    "username": "ananya",
                    "name": "Ananya Design Co",
                    "email": "ananya@example.com",
                    "accounts": [
                        ("Ananya Iyer", "30221100998877", "SBIN0007788", True),
                        ("Ananya Iyer", "771122334455", "KKBK0009012", False),
                    ],
                },
                {
                    "username": "vikram",
                    "name": "Vikram Dev Works",
                    "email": "vikram@example.com",
                    "accounts": [
                        ("Vikram Mehta", "22004400660088", "UTIB0003344", True),
                        ("Vikram Mehta", "445566778899", "YESB0005566", False),
                    ],
                },
            ]

            created_merchants = []
            for spec in merchant_specs:
                # Step 2: Create a Django user for JWT login and a matching Merchant by email.
                user, _ = User.objects.get_or_create(
                    username=spec["username"],
                    defaults={"email": spec["email"]},
                )
                # Password is set explicitly so the documented Phase 1 login always works.
                user.set_password("playto12345")
                user.email = spec["email"]
                user.save(update_fields=["email", "password"])
                merchant = Merchant.objects.create(name=spec["name"], email=spec["email"])
                created_merchants.append(merchant)

                bank_accounts = []
                for holder, number, ifsc, is_default in spec["accounts"]:
                    # Step 3: Give each merchant two payout destinations for Phase 2 dropdowns.
                    bank_accounts.append(
                        BankAccount.objects.create(
                            merchant=merchant,
                            account_holder=holder,
                            account_number=number,
                            ifsc_code=ifsc,
                            is_default=is_default,
                        )
                    )

                credit_count = random.randint(20, 30)
                for index in range(credit_count):
                    # Step 4: Seed realistic incoming collection credits over the last 60 days.
                    # Amounts are integer paise, never rupees or floats. (P9)
                    LedgerEntry.objects.create(
                        merchant=merchant,
                        entry_type=LedgerEntry.CREDIT,
                        amount_paise=random.randint(5_000, 500_000),
                        reference_id=f"SEED-{merchant.id}-{index}",
                        description="Seeded international collection credit",
                        created_at=timezone.now() - timezone.timedelta(days=random.randint(0, 60)),
                    )

                completed_count = random.randint(2, 3)
                for index in range(completed_count):
                    amount_paise = random.randint(5_000, 100_000)
                    bank_account = random.choice(bank_accounts)
                    # Step 5: Create a pending payout and matching DEBIT hold atomically.
                    payout = PayoutRequest.objects.create(
                        merchant=merchant,
                        bank_account=bank_account,
                        amount_paise=amount_paise,
                        idempotency_key=f"seed-{merchant.id}-{index}",
                    )
                    LedgerEntry.objects.create(
                        merchant=merchant,
                        entry_type=LedgerEntry.DEBIT,
                        amount_paise=amount_paise,
                        reference_id=str(payout.id),
                        description=f"Seeded completed payout to ******{bank_account.account_number_last4}",
                    )
                    # Step 6: Move seeded payouts through legal transitions for state-machine safety.
                    payout.transition_to(PayoutRequest.PROCESSING, reason="seed payout processing")
                    payout.transition_to(PayoutRequest.COMPLETED, reason="seed payout completed")

        # Step 7: Print a concise summary so callers know the boundary state is correct.
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(created_merchants)} merchants. "
                "JWT users: rahul/ananya/vikram, password: playto12345"
            )
        )
