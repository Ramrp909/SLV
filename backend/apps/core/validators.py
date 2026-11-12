"""Validators for core app."""

from decimal import Decimal

from common.errors import GST_RATE_NOT_APPROVED
from django.core.exceptions import ValidationError

from apps.core.models import GstRate


def validate_gst_rate(value: Decimal | None) -> GstRate:
    """
    Validate that a GST rate is an active approved rate.

    Args:
        value: The GST rate value to validate (Decimal or None)

    Returns:
        GstRate: The matching active GstRate object

    Raises:
        ValidationError: If the rate is None, not found, or not active
            with code GST_RATE_NOT_APPROVED
    """
    if value is None:
        raise ValidationError("GST rate is required.", code=GST_RATE_NOT_APPROVED)

    try:
        rate = GstRate.objects.get(rate=value, is_active=True)
    except GstRate.DoesNotExist:
        raise ValidationError(
            f"GST rate {value} is not an approved active rate.",
            code=GST_RATE_NOT_APPROVED,
        ) from None

    return rate
