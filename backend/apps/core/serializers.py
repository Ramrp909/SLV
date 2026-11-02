"""Serializers for core app."""

import re
from decimal import Decimal

from rest_framework import serializers

from apps.core.models import AppSettings, GstRate
from apps.core.services import series_start_locked

PREFIX_RE = re.compile(r"^[A-Za-z0-9]{1,4}$")


class AppSettingsSerializer(serializers.ModelSerializer):
    """Serializer for AppSettings - single row settings."""

    class Meta:
        model = AppSettings
        fields = [
            "id",
            "shop_name",
            "logo_url",
            "address",
            "phone",
            "email",
            "gstin",
            "state",
            "state_code",
            "invoice_prefix",
            "series_start_number",
            "invoice_footer",
            "terms_text",
            "prices_include_gst",
            "default_manual_line_gst_rate",
            "purchase_gst_recoverable_default",
            "commission_default_percent",
            "commission_override_allowed",
            "allow_negative_stock",
            "allow_future_invoice_dates",
            "block_prior_fy_backdating",
            "financial_year_start_month",
            "salary_basis",
            "attendance_weights",
            "overdue_days",
            "discount_warn_percent",
            "idle_logout_minutes",
            "print_format",
            "theme",
        ]
        read_only_fields = ["id"]

    def validate_financial_year_start_month(self, value):
        if not (1 <= value <= 12):
            raise serializers.ValidationError("Must be between 1 and 12.")
        return value

    def validate_invoice_prefix(self, value):
        """Validate invoice_prefix: 1-4 alphanumeric characters, stored uppercase."""
        if not value:
            raise serializers.ValidationError("invoice_prefix is required.")
        upper = value.upper()
        if not PREFIX_RE.match(upper):
            raise serializers.ValidationError("invoice_prefix must be 1-4 alphanumeric characters")
        return upper

    def validate_series_start_number(self, value):
        if value < 1:
            raise serializers.ValidationError("Must be at least 1.")
        # Check if series_start_number is locked (any INV number issued)
        if series_start_locked():
            raise serializers.ValidationError(
                "series_start_number cannot be changed after the first invoice number has been issued."
            )
        return value

    def validate_commission_default_percent(self, value):
        if not (Decimal("0") <= value <= Decimal("100")):
            raise serializers.ValidationError("Must be between 0 and 100.")
        return value

    def validate_discount_warn_percent(self, value):
        if value < 0:
            raise serializers.ValidationError("Must be non-negative.")
        return value

    def validate_overdue_days(self, value):
        if value < 1:
            raise serializers.ValidationError("Must be at least 1.")
        return value

    def validate_idle_logout_minutes(self, value):
        if value < 1:
            raise serializers.ValidationError("Must be at least 1.")
        return value

    def update(self, instance, validated_data):
        # TODO: Write audit entry for settings change (T-104)
        return super().update(instance, validated_data)


class GstRateSerializer(serializers.ModelSerializer):
    """Serializer for GstRate."""

    class Meta:
        model = GstRate
        fields = ["id", "rate", "label", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "rate", "created_at", "updated_at"]

    def validate_rate(self, value):
        """Ensure rate is between 0 and 100."""
        if not (Decimal("0") <= value <= Decimal("100")):
            raise serializers.ValidationError("Rate must be between 0 and 100.")
        return value

    def update(self, instance, validated_data):
        # Only allow updating label and is_active
        # rate is read-only so it won't be in validated_data
        # TODO: Write audit entry for GST rate change (T-104)
        return super().update(instance, validated_data)


class GstRateCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating GstRate - rate is writable on create."""

    class Meta:
        model = GstRate
        fields = ["id", "rate", "label", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_rate(self, value):
        """Ensure rate is between 0 and 100 and not duplicate."""
        if not (Decimal("0") <= value <= Decimal("100")):
            raise serializers.ValidationError("Rate must be between 0 and 100.")
        if GstRate.objects.filter(rate=value).exists():
            raise serializers.ValidationError("This GST rate already exists.")
        return value

    def create(self, validated_data):
        # TODO: Write audit entry for GST rate creation (T-104)
        return super().create(validated_data)
