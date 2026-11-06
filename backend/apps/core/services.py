"""Services for core app."""

import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.core.models import AppSettings, AuditLog, NumberSeries, get_financial_year

PREFIX_RE = re.compile(r"^[A-Za-z0-9]{1,4}$")

# Keys that should be redacted in audit logs (case-insensitive)
REDACTED_KEYS = {
    "password",
    "old_password",
    "new_password",
    "old-password",
    "new-password",
    "token",
    "access",
    "refresh",
    "secret",
    "authorization",
}


def _json_safe(value: Any) -> Any:
    """Convert a value to JSON-safe representation."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_json_safe(v) for v in value]
    return value


def _redact_secrets(data: Any) -> Any:
    """Recursively redact sensitive keys in data structures."""
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            if key.lower() in REDACTED_KEYS:
                result[key] = "[REDACTED]"
            else:
                result[key] = _redact_secrets(value)
        return result
    if isinstance(data, list | tuple | set):
        return [_redact_secrets(v) for v in data]
    return data


def _get_client_ip(request) -> str:
    """Extract client IP from request - uses REMOTE_ADDR only, never X-Forwarded-For."""
    if request is None:
        return "127.0.0.1"
    return request.META.get("REMOTE_ADDR", "127.0.0.1")


class AuditService:
    """Service for recording audit log entries."""

    @staticmethod
    def record(
        action: str,
        entity_type: str,
        entity_id: str,
        summary: str,
        before: dict | None = None,
        after: dict | None = None,
        request=None,
        actor=None,
    ) -> AuditLog:
        """
        Record an audit log entry.

        Runs in the caller's transaction so it commits/rolls back with the action.

        Args:
            action: Action name (e.g., "auth.login", "settings.updated")
            entity_type: Type of entity (e.g., "User", "AppSettings")
            entity_id: Entity identifier as string
            summary: Human-readable summary (truncated to 500 chars)
            before: State before change (dict, optional)
            after: State after change (dict, optional)
            request: HTTP request object (for IP address)
            actor: User model instance (for actor_id and actor_username)

        Returns:
            The created AuditLog entry.
        """
        # Convert to JSON-safe and redact secrets
        before_safe = _redact_secrets(_json_safe(before)) if before is not None else None
        after_safe = _redact_secrets(_json_safe(after)) if after is not None else None

        # Truncate summary to 500 characters
        summary = summary[:500] if summary else ""

        # Get IP address
        ip_address = _get_client_ip(request)

        # Get actor info
        actor_id = actor.id if actor else None
        actor_username = actor.username[:150] if actor and actor.username else None

        entry = AuditLog.objects.create(
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            summary=summary,
            before_json=before_safe,
            after_json=after_safe,
            ip_address=ip_address,
            actor_id=actor_id,
            actor_username=actor_username,
        )
        return entry


def next_number(series_code: str, document_date: date) -> str:
    """
    Generate the next number in the series.

    Args:
        series_code: One of "INV", "CN", "PUR", "RCT", "PR"
        document_date: The document date (not current date)

    Returns:
        Formatted number string like "INV/261105/0042"

    Raises:
        ValidationError: If series_code is invalid, prefix is invalid,
                         number would exceed 16 chars, or prefix contains
                         invalid characters.
        RuntimeError: If called outside a transaction.atomic() block.
        IntegrityError: If a concurrent creation race persists after 5 retries.
    """
    # Must be called inside a transaction
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("next_number must be called inside transaction.atomic()")

    # Validate series code
    if series_code not in NumberSeries.SERIES_CODES:
        raise ValidationError(f"Invalid series code: {series_code}")

    # Get settings for prefix and financial year start month
    settings = AppSettings.get_settings()

    # Determine prefix for new row creation
    if series_code == "INV":
        prefix = settings.invoice_prefix.upper()
        # Validate prefix before using it
        if not PREFIX_RE.match(prefix):
            raise ValidationError("invoice_prefix must be 1-4 alphanumeric characters")
    else:
        prefix = NumberSeries.SERIES_CODES[series_code]

    # Calculate financial year from document date
    financial_year = get_financial_year(document_date, settings.financial_year_start_month)

    # Format date part as YYMMDD
    date_part = document_date.strftime("%y%m%d")

    # Lock the series row and get/create the counter
    # Use a loop to handle race condition on new financial year creation, max 5 retries
    last_error = None
    for _ in range(5):
        try:
            with transaction.atomic():
                series, created = NumberSeries.objects.select_for_update().get_or_create(
                    series_code=series_code,
                    financial_year=financial_year,
                    defaults={
                        "prefix": prefix,
                        "last_number": 0,
                        "padding": 4,
                    },
                )

                # Handle race condition: if another transaction created it between get and create
                if not created:
                    # Re-fetch with lock
                    series = NumberSeries.objects.select_for_update().get(
                        series_code=series_code, financial_year=financial_year
                    )

                # Determine starting number for newly created row
                if created:
                    if series_code == "INV":
                        # Check if this is the very first INV series ever (across all financial years)
                        # Use exclude to not count the row we just created
                        other_inv_exists = (
                            NumberSeries.objects.filter(series_code="INV")
                            .exclude(pk=series.pk)
                            .exists()
                        )
                        if not other_inv_exists:  # This is the first INV series row
                            series.last_number = settings.series_start_number - 1
                        else:
                            # Not the first INV series - start at 0
                            series.last_number = 0
                    else:
                        # All other series start at 0
                        series.last_number = 0
                    series.padding = 4
                    series.prefix = prefix
                    series.save()

                # Compute next serial WITHOUT saving yet
                next_serial = series.last_number + 1

                # Build the full number using the STORED prefix on the row
                serial_str = str(next_serial).zfill(series.padding)
                result = f"{series.prefix}/{date_part}/{serial_str}"

                # Validate length (max 16 characters per GST rules)
                if len(result) > 16:
                    raise ValidationError(f"Generated number exceeds 16 characters: {result}")

                # Validate allowed characters (letters, digits, slash)
                if not re.match(r"^[A-Za-z0-9/]+$", result):
                    raise ValidationError(f"Generated number contains invalid characters: {result}")

                # Validation passed - now save the incremented counter
                series.last_number = next_serial
                series.save()

            # Success - break out of retry loop
            break

        except IntegrityError as e:
            # Another transaction created the row concurrently; retry
            last_error = e
            continue
    else:
        # All 5 retries exhausted
        raise last_error

    # TODO: Write audit entry for number generation (T-104)

    return result


def series_start_locked() -> bool:
    """
    Check if the INV series start number is locked.

    Once any INV number has been issued, the series_start_number
    in settings can no longer be changed.
    """
    return NumberSeries.objects.filter(series_code="INV").exists()
