"""Shared validators: GSTIN format and phone format.

Reusable by customers, purchases and any other party master data.
Format validation only - no GSTIN checksum, no hard-coded state names.
"""

import re

from django.core.exceptions import ValidationError

# GSTIN: 15 characters
#   2 digits, 5 letters, 4 digits, 1 letter, 1 letter or digit 1-9,
#   the letter Z, 1 letter or digit
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z1-9]Z[A-Z0-9]$")

# Phone: optional leading +91 or 0, then exactly 10 digits
PHONE_RE = re.compile(r"^(?:\+91|0)?(\d{10})$")


def normalize_gstin(value: str) -> str:
    """Uppercase and remove all spaces from a GSTIN."""
    return "".join(str(value).upper().split())


def validate_gstin(value) -> str | None:
    """
    Validate GSTIN format.

    Args:
        value: GSTIN string (None and empty string are allowed).

    Returns:
        Normalised GSTIN (uppercase, no spaces), or None/empty for empty input.

    Raises:
        ValidationError: If the value does not match the GSTIN format.
    """
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return ""
    normalized = normalize_gstin(value)
    if not GSTIN_RE.match(normalized):
        raise ValidationError("Invalid GSTIN format.")
    return normalized


def normalize_phone(value: str) -> str:
    """Return the 10-digit phone number after removing spaces and a leading +91 or 0."""
    digits = "".join(str(value).split())
    match = PHONE_RE.match(digits)
    if not match:
        raise ValidationError("Phone must be 10 digits (optional leading +91 or 0).")
    return match.group(1)


def validate_phone(value) -> str | None:
    """
    Validate and normalise a phone number.

    Args:
        value: Phone string (None and empty string are allowed).

    Returns:
        Normalised 10-digit phone number, or None/empty for empty input.

    Raises:
        ValidationError: If the value is not a valid 10-digit phone number.
    """
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return ""
    return normalize_phone(value)
