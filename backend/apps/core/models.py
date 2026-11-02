"""Models for core app: AppSettings and GstRate."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


def get_default_attendance_weights():
    """Default attendance weights."""
    return {"P": 1, "HD": 0.5, "PL": 1, "UL": 0, "A": 0, "H": 1}


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
