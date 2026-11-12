"""Models for core app: AppSettings, GstRate, NumberSeries, and AuditLog."""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


def get_default_attendance_weights():
    """Default attendance weights."""
    return {"P": 1, "HD": 0.5, "PL": 1, "UL": 0, "A": 0, "H": 1}


class AuditLogManager(models.Manager):
    """Manager that blocks update, delete, and bulk_update."""

    def get_queryset(self):
        return AuditLogQuerySet(self.model, using=self._db)


class AuditLogQuerySet(models.QuerySet):
    """QuerySet that blocks update, delete, and bulk_update."""

    def update(self, *args, **kwargs):
        raise ValidationError("Audit log is append-only; updates are not allowed.")

    def delete(self):
        raise ValidationError("Audit log is append-only; deletes are not allowed.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Audit log is append-only; bulk updates are not allowed.")


class AuditLog(models.Model):
    """
    Append-only audit log.

    Records are never updated or deleted. Corrections are new rows.
    Enforced at three layers:
    1. Model save()/delete() raise ValidationError on existing rows
    2. Custom manager/queryset block update()/delete()/bulk_update()
    3. PostgreSQL trigger blocks raw SQL UPDATE/DELETE (allows TRUNCATE for tests)
    """

    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    action = models.CharField(max_length=100, db_index=True)
    entity_type = models.CharField(max_length=100)
    entity_id = models.TextField()
    summary = models.TextField()
    before_json = models.JSONField(null=True, blank=True)
    after_json = models.JSONField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    actor_id = models.BigIntegerField(null=True, blank=True)
    actor_username = models.CharField(max_length=150, null=True, blank=True)

    objects = AuditLogManager()

    class Meta:
        ordering = ["-timestamp", "-id"]
        indexes = [
            models.Index(fields=["entity_type", "entity_id"]),
        ]
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"

    def __str__(self):
        return f"{self.timestamp} - {self.action} - {self.entity_type}:{self.entity_id}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError("Audit log is append-only; existing entries cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Audit log is append-only; entries cannot be deleted.")


class AppSettings(models.Model):
    """
    Single-row settings table for the paint shop.

    Enforced as single row via:
    - Service-level check in clean()
    - save() forces pk=1
    - Database CheckConstraint (id = 1)
    """

    # Shop profile
    shop_name = models.CharField(max_length=200, blank=True, null=True)
    logo_url = models.URLField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    gstin = models.CharField(max_length=15, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    state_code = models.CharField(max_length=2, blank=True, null=True)

    # Invoice settings
    invoice_prefix = models.CharField(max_length=10, default="INV")
    series_start_number = models.PositiveIntegerField(default=1)
    invoice_footer = models.TextField(blank=True, null=True)
    terms_text = models.TextField(blank=True, null=True)

    # Tax and billing
    prices_include_gst = models.BooleanField(default=True)
    default_manual_line_gst_rate = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )
    purchase_gst_recoverable_default = models.BooleanField(default=True)
    discount_warn_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00")
    )

    # Commission
    commission_default_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("10.00")
    )
    commission_override_allowed = models.BooleanField(default=True)

    # Stock
    allow_negative_stock = models.BooleanField(default=False)

    # Dates
    allow_future_invoice_dates = models.BooleanField(default=False)
    block_prior_fy_backdating = models.BooleanField(default=True)
    financial_year_start_month = models.PositiveSmallIntegerField(default=4)

    # HR / Salary
    SALARY_BASIS_CHOICES = [
        ("CALENDAR_DAYS", "Calendar Days"),
        ("FIXED_26", "Fixed 26 Days"),
        ("FIXED_30", "Fixed 30 Days"),
    ]
    salary_basis = models.CharField(
        max_length=20, choices=SALARY_BASIS_CHOICES, default="CALENDAR_DAYS"
    )
    attendance_weights = models.JSONField(
        default=get_default_attendance_weights,
        help_text="JSON mapping of attendance status to day weight",
    )

    # Expenses / Dues
    overdue_days = models.PositiveIntegerField(default=30)

    # Security
    idle_logout_minutes = models.PositiveIntegerField(default=30)

    # Printing / UI
    PRINT_FORMAT_CHOICES = [
        ("A4", "A4"),
        ("THERMAL_80", "Thermal 80mm"),
    ]
    print_format = models.CharField(max_length=20, choices=PRINT_FORMAT_CHOICES, default="A4")
    theme = models.CharField(max_length=50, blank=True, null=True)

    class Meta:
        verbose_name = "App Settings"
        verbose_name_plural = "App Settings"
        constraints = [
            models.CheckConstraint(
                check=Q(pk=1),
                name="appsettings_single_row",
            ),
        ]

    def __str__(self):
        return "App Settings"

    def clean(self):
        # Service-level single row enforcement
        if not self.pk and AppSettings.objects.exists():
            raise ValidationError("Only one AppSettings row is allowed.")

        # Validate financial_year_start_month
        if self.financial_year_start_month is not None:
            if not (1 <= self.financial_year_start_month <= 12):
                raise ValidationError({"financial_year_start_month": "Must be between 1 and 12."})

        # Validate series_start_number
        if self.series_start_number is not None and self.series_start_number < 1:
            raise ValidationError({"series_start_number": "Must be at least 1."})

        # Validate commission_default_percent
        if self.commission_default_percent is not None:
            if not (Decimal("0") <= self.commission_default_percent <= Decimal("100")):
                raise ValidationError({"commission_default_percent": "Must be between 0 and 100."})

        # Validate discount_warn_percent
        if self.discount_warn_percent is not None and self.discount_warn_percent < 0:
            raise ValidationError({"discount_warn_percent": "Must be non-negative."})

        # Validate overdue_days
        if self.overdue_days is not None and self.overdue_days < 1:
            raise ValidationError({"overdue_days": "Must be at least 1."})

        # Validate idle_logout_minutes
        if self.idle_logout_minutes is not None and self.idle_logout_minutes < 1:
            raise ValidationError({"idle_logout_minutes": "Must be at least 1."})

    def save(self, *args, **kwargs):
        self.full_clean()
        # Enforce single row by always using pk=1
        if not self.pk:
            self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # Prevent deletion of the settings row
        raise ValidationError("AppSettings row cannot be deleted.")

    @classmethod
    def get_settings(cls) -> "AppSettings":
        """Get or create the single settings row."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class GstRate(models.Model):
    """
    Approved GST rates.

    Rates are never deleted, only deactivated.
    """

    rate = models.DecimalField(max_digits=5, decimal_places=2, unique=True)
    label = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["rate"]
        verbose_name = "GST Rate"
        verbose_name_plural = "GST Rates"

    def __str__(self):
        return f"{self.rate}% - {self.label}"

    def clean(self):
        # Rate must be between 0 and 100
        if self.rate is not None:
            if not (Decimal("0") <= self.rate <= Decimal("100")):
                raise ValidationError({"rate": "Rate must be between 0 and 100."})

        # Prevent changing rate value after creation
        if self.pk:
            original = GstRate.objects.get(pk=self.pk)
            if original.rate != self.rate:
                raise ValidationError({"rate": "Rate value cannot be changed after creation."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class NumberSeries(models.Model):
    """
    Number series for documents (invoices, credit notes, purchases, receipts, purchase returns).

    Each series has a counter per financial year. The serial never restarts daily -
    it continues consecutively within the financial year.

    Format: PREFIX/YYMMDD/NNNN (e.g., INV/261105/0042)
    - Prefix: from settings for INV, fixed for others (CN, PUR, RCT, PR)
    - Date part: document date (not current date), formatted YYMMDD
    - Serial: padded to 4 digits, consecutive per series + financial year
    """

    SERIES_CODES = {
        "INV": "INV",  # Invoice - prefix from settings
        "CN": "CN",  # Credit Note
        "PUR": "PUR",  # Purchase
        "RCT": "RCT",  # Receipt
        "PR": "PR",  # Purchase Return
    }

    series_code = models.CharField(max_length=4, choices=[(k, k) for k in SERIES_CODES.keys()])
    financial_year = models.CharField(max_length=7)  # Format: "26-27"
    prefix = models.CharField(max_length=10)
    last_number = models.PositiveIntegerField(default=0)
    padding = models.PositiveSmallIntegerField(default=4)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [["series_code", "financial_year"]]
        ordering = ["series_code", "financial_year"]
        verbose_name = "Number Series"
        verbose_name_plural = "Number Series"

    def __str__(self):
        return f"{self.series_code}/{self.financial_year} (last: {self.last_number})"


class IdempotencyRecord(models.Model):
    """
    Idempotency record for preventing duplicate request processing.

    A record is created ONLY after a request succeeds (2xx response).
    Failed requests (4xx, 5xx, exceptions) do NOT create a record, allowing retry.

    Unique constraint on (user_id, key) ensures same key from same user
    cannot be used twice with different payloads.
    """

    user_id = models.BigIntegerField(db_index=True)
    key = models.UUIDField()
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=500)
    request_hash = models.CharField(max_length=64)  # SHA-256 hex
    response_status = models.PositiveSmallIntegerField()
    response_body = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user_id", "key"],
                name="idempotency_unique_user_key",
            )
        ]
        indexes = [
            models.Index(fields=["created_at"]),
        ]
        ordering = ["-created_at"]
        verbose_name = "Idempotency Record"
        verbose_name_plural = "Idempotency Records"

    def __str__(self):
        return (
            f"IdempotencyRecord(user={self.user_id}, key={self.key}, status={self.response_status})"
        )


def get_financial_year(document_date: date, start_month: int = 4) -> str:
    """
    Calculate financial year from document date.

    Financial year starts in April (month 4 by default).
    Returns string like "26-27" for 2026-04-01 to 2027-03-31.
    """
    year = document_date.year
    month = document_date.month

    if month >= start_month:
        # Current financial year starts this year
        fy_start = year
        fy_end = year + 1
    else:
        # Current financial year started last year
        fy_start = year - 1
        fy_end = year

    return f"{fy_start % 100:02d}-{fy_end % 100:02d}"


def series_start_locked() -> bool:
    """
    Check if the INV series start number is locked.

    Once any INV number has been issued, the series_start_number
    in settings can no longer be changed.
    """
    return NumberSeries.objects.filter(series_code="INV").exists()
