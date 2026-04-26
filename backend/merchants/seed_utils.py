"""
merchants/seed_utils.py

Provides reusable seed logic to generate mock data personas.
"""
import random
from django.utils import timezone
from ledger.models import LedgerEntry
from merchants.models import BankAccount
from payouts.models import PayoutRequest

SEED_PERSONAS = {
    1: {
        "name": "Boutique E-commerce",
        "accounts": [("E-commerce Ops", "501000111111", "HDEF0001", True), ("E-commerce Reserve", "9182736111", "ICIC0001", False)],
        "credit_range": (50_000, 500_000), "credit_desc": "Customer cart checkout",
        "tx_count": 25,
    },
    2: {
        "name": "Freelance Developer",
        "accounts": [("Freelance Dev", "501000222222", "SBIN0002", True)],
        "credit_range": (150_000, 300_000), "credit_desc": "Upwork milestone payment",
        "tx_count": 12,
    },
    3: {
        "name": "SaaS Startup",
        "accounts": [("SaaS Operating", "501000333333", "HDEF0003", True), ("SaaS Payroll", "9182736333", "ICIC0003", False)],
        "credit_range": (10_000, 50_000), "credit_desc": "Monthly subscription renewal",
        "tx_count": 45,
    },
    4: {
        "name": "Design Agency",
        "accounts": [("Agency Main", "501000444444", "UTIB0004", True)],
        "credit_range": (200_000, 800_000), "credit_desc": "Client retainer fee",
        "tx_count": 8,
    },
    5: {
        "name": "Consulting Firm",
        "accounts": [("Consulting Corp", "501000555555", "YESB0005", True)],
        "credit_range": (500_000, 1_500_000), "credit_desc": "Corporate strategy consultation",
        "tx_count": 5,
    },
}

def clear_merchant_data(merchant):
    """Remove existing ledger entries and bank accounts to allow re-seeding."""
    PayoutRequest.objects.filter(merchant=merchant).delete()
    LedgerEntry.objects.filter(merchant=merchant).delete()
    BankAccount.objects.filter(merchant=merchant).delete()

def apply_seed_persona(merchant, persona_id):
    """
    Apply a specific seed persona to the given merchant.
    Args:
        merchant: The Merchant instance
        persona_id: Integer 1-5
    """
    persona = SEED_PERSONAS.get(int(persona_id))
    if not persona:
        raise ValueError("Invalid persona ID")

    # Only clean if seeding
    clear_merchant_data(merchant)
    
    bank_accounts = []
    for holder, number, ifsc, is_default in persona["accounts"]:
        bank_accounts.append(
            BankAccount.objects.create(
                merchant=merchant,
                account_holder=holder,
                account_number=number,
                ifsc_code=ifsc,
                is_default=is_default,
            )
        )

    # Credits
    for index in range(persona["tx_count"]):
        LedgerEntry.objects.create(
            merchant=merchant,
            entry_type=LedgerEntry.CREDIT,
            amount_paise=random.randint(*persona["credit_range"]),
            reference_id=f"SEED-{merchant.id}-{index}",
            description=persona["credit_desc"],
            created_at=timezone.now() - timezone.timedelta(days=random.randint(0, 60)),
        )

    # Payouts
    completed_count = random.randint(2, max(2, persona["tx_count"] // 5))
    for index in range(completed_count):
        amount_paise = random.randint(5_000, persona["credit_range"][1] // 2)
        bank_account = random.choice(bank_accounts)
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
        payout.transition_to(PayoutRequest.PROCESSING, reason="seed payout processing")
        payout.transition_to(PayoutRequest.COMPLETED, reason="seed payout completed")
