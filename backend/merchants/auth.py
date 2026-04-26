"""
merchants/auth.py

Maps authenticated Django users to Playto merchants.

Key design decisions:
  - JWT authenticates the Django user; merchant ownership is resolved by user email.
  - Views call this helper before returning merchant-owned money or bank-account data.
"""

from rest_framework.exceptions import PermissionDenied

from merchants.models import Merchant


def merchant_for_user(user):
    """
    Resolve the authenticated request user to a Merchant row.

    Args:
        user: Django user authenticated by Simple JWT.

    Returns:
        Merchant matching the user's email.

    Raises:
        PermissionDenied: No merchant is attached to the authenticated user.
    """
    try:
        # Email is unique on Merchant and set on seed JWT users, giving a stable mapping.
        return Merchant.objects.get(email=user.email)
    except Merchant.DoesNotExist as exc:
        # A valid Django user without a merchant must not see merchant-owned resources.
        raise PermissionDenied("Authenticated user is not linked to a merchant.") from exc
