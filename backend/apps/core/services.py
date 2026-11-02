"""Services for core app."""

import re
from datetime import date

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.core.models import AppSettings, NumberSeries, get_financial_year

PREFIX_RE = re.compile(r"^[A-Za-z0-9]{1,4}$")


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
