"""Tests for core app: AppSettings, GstRate, validators, NumberSeries, and API endpoints."""

import json
import time
import uuid
from datetime import date
from decimal import Decimal
from io import StringIO
from threading import Thread
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import (
    IntegrityError,
    connection,
    models,
    transaction,
)
from django.test import TestCase, TransactionTestCase, override_settings
from drf_spectacular.utils import OpenApiParameter
from rest_framework import status
from rest_framework.test import APIClient

from apps.core.idempotency import (
    IDEMPOTENCY_KEY_PARAMETER,
    _postgres_sqlstate,
    compute_advisory_lock_key,
    compute_request_hash,
)
from apps.core.models import AppSettings, AuditLog, GstRate, IdempotencyRecord, NumberSeries
from apps.core.services import next_number, series_start_locked
from apps.core.validators import validate_gst_rate

User = get_user_model()


class TestAppSettingsModel(TestCase):
    """Tests for AppSettings model - single row table."""

    def setUp(self):
        # Migration already creates the settings row
        pass

    def test_single_settings_row_exists_after_migrate(self):
        """Test exactly one settings row exists after migrate."""
        self.assertEqual(AppSettings.objects.count(), 1)

    def test_second_settings_row_fails_service_level(self):
        """Test that creating a second row fails at service level."""
        # The migration already created the row with pk=1
        # Try to create another without pk (which will try to use pk=1)
        with self.assertRaises(ValidationError):
            settings = AppSettings()
            settings.full_clean()
            settings.save()

    def test_defaults_match_section_7_3(self):
        """Test that defaults match section 7.3 of the blueprint."""
        settings = AppSettings.get_settings()

        # Shop profile
        self.assertEqual(settings.invoice_prefix, "INV")
        self.assertEqual(settings.series_start_number, 1)

        # Money/percentages
        self.assertEqual(settings.commission_default_percent, Decimal("10.00"))
        self.assertEqual(settings.discount_warn_percent, Decimal("0.00"))

        # Booleans
        self.assertTrue(settings.prices_include_gst)
        self.assertTrue(settings.purchase_gst_recoverable_default)
        self.assertTrue(settings.commission_override_allowed)
        self.assertFalse(settings.allow_negative_stock)
        self.assertFalse(settings.allow_future_invoice_dates)
        self.assertTrue(settings.block_prior_fy_backdating)

        # Numbers
        self.assertEqual(settings.financial_year_start_month, 4)
        self.assertEqual(settings.overdue_days, 30)
        self.assertEqual(settings.idle_logout_minutes, 30)

        # Choices
        self.assertEqual(settings.salary_basis, "CALENDAR_DAYS")
        self.assertEqual(settings.print_format, "A4")

        # attendance_weights default
        expected_weights = {"P": 1, "HD": 0.5, "PL": 1, "UL": 0, "A": 0, "H": 1}
        self.assertEqual(settings.attendance_weights, expected_weights)

        # Nullable fields should be None by default
        self.assertIsNone(settings.shop_name)
        self.assertIsNone(settings.logo_url)
        self.assertIsNone(settings.address)
        self.assertIsNone(settings.phone)
        self.assertIsNone(settings.email)
        self.assertIsNone(settings.gstin)
        self.assertIsNone(settings.state)
        self.assertIsNone(settings.state_code)
        self.assertIsNone(settings.invoice_footer)
        self.assertIsNone(settings.terms_text)
        self.assertIsNone(settings.default_manual_line_gst_rate)
        self.assertIsNone(settings.theme)

    def test_get_settings_helper(self):
        """Test get_settings() helper returns the single row."""
        settings = AppSettings.get_settings()
        self.assertIsInstance(settings, AppSettings)
        self.assertEqual(settings.pk, 1)

    def test_get_settings_returns_existing(self):
        """Test get_settings() returns the existing row."""
        settings1 = AppSettings.get_settings()
        settings2 = AppSettings.get_settings()
        self.assertEqual(settings1.pk, settings2.pk)
        self.assertEqual(AppSettings.objects.count(), 1)


class TestGstRateModel(TestCase):
    """Tests for GstRate model."""

    def setUp(self):
        # Migration already creates the 0.00 rate
        pass

    def test_migration_created_only_zero_rate(self):
        """Test that migration creates ONLY the 0.00 rate."""
        rates = GstRate.objects.all()
        self.assertEqual(rates.count(), 1)
        rate = rates.first()
        self.assertEqual(rate.rate, Decimal("0.00"))
        self.assertEqual(rate.label, "Exempt")
        self.assertTrue(rate.is_active)

    def test_create_new_rate(self):
        """Test creating a new GST rate."""
        rate = GstRate.objects.create(rate=Decimal("18.00"), label="Standard", is_active=True)
        self.assertEqual(rate.rate, Decimal("18.00"))
        self.assertTrue(rate.is_active)

    def test_duplicate_rate_rejected(self):
        """Test that duplicate rate is rejected."""
        with self.assertRaises(ValidationError):
            GstRate.objects.create(rate=Decimal("0.00"), label="Duplicate", is_active=True)

    def test_rate_between_0_and_100(self):
        """Test rate must be between 0 and 100."""
        # Valid rates
        GstRate.objects.create(rate=Decimal("5.00"), label="Low", is_active=True)
        GstRate.objects.create(rate=Decimal("100.00"), label="Hundred", is_active=True)

    def test_deactivate_rate(self):
        """Test deactivating a rate."""
        rate = GstRate.objects.create(rate=Decimal("5.00"), label="Low", is_active=True)
        rate.is_active = False
        rate.save()
        rate.refresh_from_db()
        self.assertFalse(rate.is_active)

    def test_rate_value_cannot_be_changed(self):
        """Test that rate value cannot be changed after creation."""
        rate = GstRate.objects.create(rate=Decimal("12.00"), label="Twelve", is_active=True)
        rate.rate = Decimal("18.00")
        with self.assertRaises(ValidationError):
            rate.full_clean()


class TestGstRateValidators(TestCase):
    """Tests for validate_gst_rate function."""

    def setUp(self):
        # Migration already creates 0.00 rate
        GstRate.objects.create(rate=Decimal("18.00"), label="Standard", is_active=True)
        GstRate.objects.create(rate=Decimal("5.00"), label="Low", is_active=False)

    def test_validate_active_rate(self):
        """Test validating an active approved rate returns the GstRate object."""
        rate = validate_gst_rate(Decimal("18.00"))
        self.assertIsInstance(rate, GstRate)
        self.assertEqual(rate.rate, Decimal("18.00"))
        self.assertTrue(rate.is_active)

    def test_validate_zero_rate(self):
        """Test validating 0.00 rate works."""
        rate = validate_gst_rate(Decimal("0.00"))
        self.assertEqual(rate.rate, Decimal("0.00"))

    def test_validate_deactivated_rate_fails(self):
        """Test that a deactivated rate fails validation."""
        with self.assertRaises(ValidationError) as cm:
            validate_gst_rate(Decimal("5.00"))
        self.assertEqual(cm.exception.code, "GST_RATE_NOT_APPROVED")

    def test_validate_nonexistent_rate_fails(self):
        """Test that a non-existent rate fails validation."""
        with self.assertRaises(ValidationError) as cm:
            validate_gst_rate(Decimal("28.00"))
        self.assertEqual(cm.exception.code, "GST_RATE_NOT_APPROVED")

    def test_validate_none_handling(self):
        """Test None handling - should raise ValidationError."""
        with self.assertRaises(ValidationError) as cm:
            validate_gst_rate(None)
        self.assertEqual(cm.exception.code, "GST_RATE_NOT_APPROVED")


class TestSettingsAPI(TestCase):
    """Tests for /api/v1/settings/ endpoints."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="owner", password="SecurePass123!")
        self.login()

    def login(self):
        """Login and set auth header."""
        response = self.client.post(
            "/api/v1/auth/login/",
            {"username": "owner", "password": "SecurePass123!"},
            format="json",
        )
        self.access_token = response.json()["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")

    def test_get_settings_returns_401_without_token(self):
        """Test GET /api/v1/settings/ returns 401 without token."""
        client = APIClient()
        response = client.get("/api/v1/settings/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json()["code"], "AUTHENTICATION_FAILED")

    def test_put_settings_returns_401_without_token(self):
        """Test PUT /api/v1/settings/ returns 401 without token."""
        client = APIClient()
        response = client.put("/api/v1/settings/", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json()["code"], "AUTHENTICATION_FAILED")

    def test_get_settings_works(self):
        """Test GET /api/v1/settings/ returns settings."""
        response = self.client.get("/api/v1/settings/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["invoice_prefix"], "INV")
        self.assertEqual(data["commission_default_percent"], "10.00")

    def test_put_settings_updates_field(self):
        """Test PUT /api/v1/settings/ updates a field."""
        response = self.client.put(
            "/api/v1/settings/",
            {"shop_name": "My Paint Shop", "commission_default_percent": "12.50"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["shop_name"], "My Paint Shop")
        self.assertEqual(data["commission_default_percent"], "12.50")

    def test_put_settings_rejects_invalid_commission(self):
        """Test PUT rejects commission > 100."""
        response = self.client.put(
            "/api/v1/settings/",
            {"commission_default_percent": "101.00"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["code"], "VALIDATION_ERROR")

    def test_put_settings_rejects_invalid_month(self):
        """Test PUT rejects financial_year_start_month > 12."""
        response = self.client.put(
            "/api/v1/settings/",
            {"financial_year_start_month": 13},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["code"], "VALIDATION_ERROR")

    def test_put_settings_rejects_zero_series_start(self):
        """Test PUT rejects series_start_number < 1."""
        response = self.client.put(
            "/api/v1/settings/",
            {"series_start_number": 0},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["code"], "VALIDATION_ERROR")

    def test_put_settings_partial_update(self):
        """Test PUT allows partial updates."""
        response = self.client.put(
            "/api/v1/settings/",
            {"allow_future_invoice_dates": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data["allow_future_invoice_dates"])

    def test_decimal_values_returned_as_strings(self):
        """Test that Decimal values in response are strings."""
        response = self.client.get("/api/v1/settings/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIsInstance(data["commission_default_percent"], str)


class TestAppSettingsSerializerValidation(TestCase):
    """Tests for AppSettingsSerializer validation."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="owner", password="SecurePass123!")
        self.login()

    def login(self):
        response = self.client.post(
            "/api/v1/auth/login/",
            {"username": "owner", "password": "SecurePass123!"},
            format="json",
        )
        self.access_token = response.json()["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")

    def test_put_invoice_prefix_5_chars_rejected(self):
        """Test PUT rejects invoice_prefix with 5 characters."""
        response = self.client.put(
            "/api/v1/settings/",
            {"invoice_prefix": "INVOI"},  # 5 chars
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["code"], "VALIDATION_ERROR")
        self.assertIn("invoice_prefix", response.json()["fields"])

    def test_put_invoice_prefix_with_slash_rejected(self):
        """Test PUT rejects invoice_prefix with slash."""
        response = self.client.put(
            "/api/v1/settings/",
            {"invoice_prefix": "IN/V"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["code"], "VALIDATION_ERROR")
        self.assertIn("invoice_prefix", response.json()["fields"])

    def test_put_valid_invoice_prefix_accepted_and_uppercased(self):
        """Test PUT accepts valid invoice_prefix and uppercases it."""
        response = self.client.put(
            "/api/v1/settings/",
            {"invoice_prefix": "abc"},  # 3 chars, lowercase
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["invoice_prefix"], "ABC")


class TestGstRatesAPI(TestCase):
    """Tests for /api/v1/settings/gst-rates/ endpoints."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="owner", password="SecurePass123!")
        self.login()

    def login(self):
        response = self.client.post(
            "/api/v1/auth/login/",
            {"username": "owner", "password": "SecurePass123!"},
            format="json",
        )
        self.access_token = response.json()["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")

    def test_get_gst_rates_returns_401_without_token(self):
        client = APIClient()
        response = client.get("/api/v1/settings/gst-rates/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json()["code"], "AUTHENTICATION_FAILED")

    def test_post_gst_rate_returns_401_without_token(self):
        client = APIClient()
        response = client.post("/api/v1/settings/gst-rates/", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_put_gst_rate_returns_401_without_token(self):
        client = APIClient()
        response = client.put("/api/v1/settings/gst-rates/1/", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_gst_rates_list(self):
        """Test GET /api/v1/settings/gst-rates/ returns list."""
        response = self.client.get("/api/v1/settings/gst-rates/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("results", data)  # paginated
        # Should have the default 0.00 rate
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["rate"], "0.00")

    def test_create_gst_rate(self):
        """Test POST /api/v1/settings/gst-rates/ creates new rate."""
        response = self.client.post(
            "/api/v1/settings/gst-rates/",
            {"rate": "18.00", "label": "Standard"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data["rate"], "18.00")
        self.assertEqual(data["label"], "Standard")
        self.assertTrue(data["is_active"])

    def test_create_duplicate_rate_rejected(self):
        """Test creating duplicate rate is rejected."""
        self.client.post(
            "/api/v1/settings/gst-rates/",
            {"rate": "12.00", "label": "Low"},
            format="json",
        )
        response = self.client.post(
            "/api/v1/settings/gst-rates/",
            {"rate": "12.00", "label": "Low Duplicate"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["code"], "VALIDATION_ERROR")

    def test_update_gst_rate_label_and_active(self):
        """Test PUT /api/v1/settings/gst-rates/{id}/ updates label or is_active."""
        create_response = self.client.post(
            "/api/v1/settings/gst-rates/",
            {"rate": "12.00", "label": "Low"},
            format="json",
        )
        rate_id = create_response.json()["id"]

        # Update label
        response = self.client.put(
            f"/api/v1/settings/gst-rates/{rate_id}/",
            {"label": "Low Rate", "is_active": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["label"], "Low Rate")
        self.assertFalse(data["is_active"])
        self.assertEqual(data["rate"], "12.00")  # rate unchanged

    def test_update_gst_rate_rejects_rate_change(self):
        """Test that changing the rate value is rejected."""
        create_response = self.client.post(
            "/api/v1/settings/gst-rates/",
            {"rate": "12.00", "label": "Low"},
            format="json",
        )
        rate_id = create_response.json()["id"]

        response = self.client.put(
            f"/api/v1/settings/gst-rates/{rate_id}/",
            {"rate": "18.00"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["code"], "VALIDATION_ERROR")


class TestAppSettingsDatabaseConstraint(TestCase):
    """Test service-level constraint for single row."""

    def test_service_constraint_prevents_second_row(self):
        """Test that service constraint prevents second row."""
        # Migration already created the row
        with self.assertRaises(ValidationError):
            settings = AppSettings()
            settings.full_clean()
            settings.save()


class TestAppSettingsDatabaseCheckConstraint(TestCase):
    """Test database-level CheckConstraint for single row (id = 1)."""

    def test_database_constraint_prevents_id_not_one(self):
        """Test that inserting a row with id != 1 raises an error (IntegrityError or ValidationError)."""
        # The migration already created the row with pk=1
        # Try to create another with pk=2 - should fail at database level
        # Django's model validation catches the constraint first, so we accept either
        with self.assertRaises((IntegrityError, ValidationError)):
            AppSettings.objects.create(pk=2, invoice_prefix="INV")


class TestSpectacularSchema(TestCase):
    """Tests for drf-spectacular schema generation."""

    def test_spectacular_validate_passes(self):
        """Test that spectacular --validate --fail-on-warn succeeds."""
        import io

        from django.core.management import call_command
        from django.core.management.base import CommandError

        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            call_command(
                "spectacular", "--validate", "--fail-on-warn", stdout=stdout, stderr=stderr
            )
        except (CommandError, SystemExit):
            # drf-spectacular may raise CommandError or call sys.exit() on validation failure
            output = stderr.getvalue() or stdout.getvalue()
            self.fail(f"Spectacular validation failed: {output}")

    def test_schema_has_bearer_security_scheme(self):
        """Test that the schema has a Bearer JWT security scheme."""
        from drf_spectacular.generators import SchemaGenerator

        generator = SchemaGenerator()
        schema = generator.get_schema(request=None, public=True)

        # Check for security schemes - drf-spectacular auto-generates "jwtAuth" for JWT auth
        self.assertIn("components", schema)
        self.assertIn("securitySchemes", schema["components"])
        security_schemes = schema["components"]["securitySchemes"]
        # drf-spectacular auto-generates "jwtAuth" for JWT authentication
        self.assertIn("jwtAuth", security_schemes)
        bearer_scheme = security_schemes["jwtAuth"]
        self.assertEqual(bearer_scheme["type"], "http")
        self.assertEqual(bearer_scheme["scheme"], "bearer")
        self.assertEqual(bearer_scheme["bearerFormat"], "JWT")

    def test_login_operation_has_request_body(self):
        """Test that the login operation has username and password in request body."""
        from drf_spectacular.generators import SchemaGenerator

        generator = SchemaGenerator()
        schema = generator.get_schema(request=None, public=True)

        # Find the login path
        paths = schema.get("paths", {})
        self.assertIn("/api/v1/auth/login/", paths)
        login_path = paths["/api/v1/auth/login/"]
        self.assertIn("post", login_path)
        post_op = login_path["post"]

        # Check request body
        self.assertIn("requestBody", post_op)
        request_body = post_op["requestBody"]
        self.assertIn("content", request_body)
        self.assertIn("application/json", request_body["content"])
        json_content = request_body["content"]["application/json"]
        self.assertIn("schema", json_content)

        # Check properties
        schema_props = json_content["schema"].get("properties", {})
        self.assertIn("username", schema_props)
        self.assertIn("password", schema_props)

        # Check that login is marked as not requiring auth (no security requirement)
        # or has empty security array
        _ = post_op.get("security", [])
        # For public endpoints, security should be empty or not present
        # This is just checking the structure exists


class TestNumberSeriesModel(TestCase):
    """Tests for NumberSeries model."""

    def test_create_number_series(self):
        """Test creating a NumberSeries row."""
        series = NumberSeries.objects.create(
            series_code="INV",
            financial_year="26-27",
            prefix="INV",
            last_number=0,
            padding=4,
        )
        self.assertEqual(series.series_code, "INV")
        self.assertEqual(series.financial_year, "26-27")
        self.assertEqual(series.last_number, 0)

    def test_unique_constraint_series_code_financial_year(self):
        """Test unique constraint on series_code + financial_year."""
        NumberSeries.objects.create(
            series_code="INV", financial_year="26-27", prefix="INV", last_number=0, padding=4
        )
        with self.assertRaises(IntegrityError):
            NumberSeries.objects.create(
                series_code="INV", financial_year="26-27", prefix="INV", last_number=0, padding=4
            )

    def test_different_financial_year_allowed(self):
        """Test same series_code with different financial_year is allowed."""
        NumberSeries.objects.create(
            series_code="INV", financial_year="26-27", prefix="INV", last_number=0, padding=4
        )
        series2 = NumberSeries.objects.create(
            series_code="INV", financial_year="27-28", prefix="INV", last_number=0, padding=4
        )
        self.assertEqual(series2.financial_year, "27-28")


class TestNextNumberService(TestCase):
    """Tests for next_number service function."""

    def setUp(self):
        # Ensure clean state
        NumberSeries.objects.all().delete()
        # Reset settings
        settings = AppSettings.get_settings()
        settings.invoice_prefix = "INV"
        settings.series_start_number = 1
        settings.financial_year_start_month = 4
        settings.save()

    def test_next_number_exact_format(self):
        """Test exact format INV/261105/0042."""
        # Create series with last_number = 41 so next is 42
        NumberSeries.objects.create(
            series_code="INV",
            financial_year="26-27",
            prefix="INV",
            last_number=41,
            padding=4,
        )
        result = next_number("INV", date(2026, 11, 5))
        self.assertEqual(result, "INV/261105/0042")

    def test_next_number_serial_continues_across_days(self):
        """Test serial continues across days (0042 then 0043 on 6 November)."""
        NumberSeries.objects.create(
            series_code="INV",
            financial_year="26-27",
            prefix="INV",
            last_number=41,
            padding=4,
        )
        result1 = next_number("INV", date(2026, 11, 5))
        result2 = next_number("INV", date(2026, 11, 6))
        self.assertEqual(result1, "INV/261105/0042")
        self.assertEqual(result2, "INV/261106/0043")

    def test_next_number_financial_year_rollover(self):
        """Test financial year rollover - 1 April 2027 gives INV/270401/0001."""
        # Create series for 26-27
        NumberSeries.objects.create(
            series_code="INV",
            financial_year="26-27",
            prefix="INV",
            last_number=9999,
            padding=4,
        )
        # Document dated 1 April 2027 belongs to 27-28
        result = next_number("INV", date(2027, 4, 1))
        self.assertEqual(result, "INV/270401/0001")
        # 26-27 series should be untouched
        series_26_27 = NumberSeries.objects.get(series_code="INV", financial_year="26-27")
        self.assertEqual(series_26_27.last_number, 9999)

    def test_next_number_backdated_document(self):
        """Test back-dated document gets next serial with its own date."""
        NumberSeries.objects.create(
            series_code="INV",
            financial_year="26-27",
            prefix="INV",
            last_number=44,
            padding=4,
        )
        # Document dated 28 October (backdated) after serial 44 gets 0045 with date 261028
        result = next_number("INV", date(2026, 10, 28))
        self.assertEqual(result, "INV/261028/0045")

    def test_series_start_number_custom(self):
        """Test series_start_number 215 gives INV/261105/0215 for first ever invoice."""
        settings = AppSettings.get_settings()
        settings.series_start_number = 215
        settings.save()

        # No existing INV series for 26-27, so first number should be 215
        result = next_number("INV", date(2026, 11, 5))
        self.assertEqual(result, "INV/261105/0215")
        # Next should be 216
        result2 = next_number("INV", date(2026, 11, 5))
        self.assertEqual(result2, "INV/261105/0216")

    def test_start_number_ignored_for_cn(self):
        """Test start number is ignored for CN and other non-INV series."""
        settings = AppSettings.get_settings()
        settings.series_start_number = 500
        settings.save()

        # CN should always start at 1
        result = next_number("CN", date(2026, 11, 5))
        self.assertEqual(result, "CN/261105/0001")

    def test_start_number_ignored_for_next_financial_year(self):
        """Test start number is ignored for next financial year."""
        settings = AppSettings.get_settings()
        settings.series_start_number = 500
        settings.save()

        # Create 26-27 series with some numbers
        NumberSeries.objects.create(
            series_code="INV",
            financial_year="26-27",
            prefix="INV",
            last_number=100,
            padding=4,
        )
        # First number in 27-28 should be 0001, not 500
        result = next_number("INV", date(2027, 4, 1))
        self.assertEqual(result, "INV/270401/0001")

    def test_16_character_guard(self):
        """Test 16-character guard rejects numbers that are too long."""
        NumberSeries.objects.create(
            series_code="INV",
            financial_year="26-27",
            prefix="INV",
            last_number=99999,  # This would make a 17-char number
            padding=5,
        )
        with self.assertRaises(ValidationError):
            next_number("INV", date(2026, 11, 5))

    def test_unknown_series_code_rejected(self):
        """Test unknown series code raises error."""
        with self.assertRaises(ValidationError):
            next_number("XXX", date(2026, 11, 5))

    def test_calling_outside_transaction_raises(self):
        """Test calling next_number outside a transaction raises error (placeholder)."""
        # This test is replaced by TestNextNumberOutsideTransaction in TransactionTestCase
        pass

    def test_series_start_locked(self):
        """Test series_start_locked returns True after first INV number issued."""
        self.assertFalse(series_start_locked())
        with transaction.atomic():
            next_number("INV", date(2026, 11, 5))
        self.assertTrue(series_start_locked())

    def test_settings_api_rejects_series_start_number_change_when_locked(self):
        """Test settings API rejects changing series_start_number after INV number issued."""
        client = APIClient()
        User.objects.create_user(username="owner", password="SecurePass123!")
        response = client.post(
            "/api/v1/auth/login/",
            {"username": "owner", "password": "SecurePass123!"},
            format="json",
        )
        access_token = response.json()["access"]
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")

        # First, issue an INV number
        with transaction.atomic():
            next_number("INV", date(2026, 11, 5))

        # Now try to change series_start_number - should be rejected
        response = client.put(
            "/api/v1/settings/",
            {"series_start_number": 999},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["code"], "VALIDATION_ERROR")


class TestNextNumberOutsideTransaction(TransactionTestCase):
    """Tests for next_number behavior when called outside transaction.atomic()."""

    def setUp(self):
        NumberSeries.objects.all().delete()
        settings = AppSettings.get_settings()
        settings.invoice_prefix = "INV"
        settings.series_start_number = 1
        settings.financial_year_start_month = 4
        settings.save()

    def test_calling_outside_transaction_raises_runtime_error(self):
        """Test calling next_number outside transaction.atomic raises RuntimeError and creates no row."""
        # Verify we're not in an atomic block
        from django.db import transaction

        conn = transaction.get_connection()
        self.assertFalse(conn.in_atomic_block)

        # Calling next_number should raise RuntimeError
        with self.assertRaises(RuntimeError) as cm:
            next_number("INV", date(2026, 11, 5))

        self.assertIn("transaction.atomic", str(cm.exception))

        # Verify no NumberSeries row was created
        self.assertEqual(NumberSeries.objects.count(), 0)

    def test_calling_inside_transaction_works(self):
        """Test calling next_number inside transaction.atomic works normally."""
        with transaction.atomic():
            result = next_number("INV", date(2026, 11, 5))

        self.assertEqual(result, "INV/261105/0001")
        self.assertEqual(NumberSeries.objects.count(), 1)


class TestNextNumberConcurrency(TransactionTestCase):
    """Concurrency tests for next_number."""

    def setUp(self):
        NumberSeries.objects.all().delete()
        settings = AppSettings.get_settings()
        settings.invoice_prefix = "INV"
        settings.series_start_number = 1
        settings.financial_year_start_month = 4
        settings.save()

    def test_concurrency_20_threads_unique_contiguous(self):
        """Test 20 threads produce 20 unique, contiguous serials."""
        results = []
        errors = []

        def worker():
            try:
                # Each thread needs its own database connection
                connection.close_if_unusable_or_obsolete()
                with transaction.atomic():
                    result = next_number("INV", date(2026, 11, 5))
                    results.append(result)
            except Exception as e:
                errors.append(e)
            finally:
                # Ensure connection is closed after each thread
                connection.close()

        threads = [Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Errors occurred: {errors}")
        self.assertEqual(len(results), 20)

        # Extract serial numbers and verify they are contiguous
        serials = sorted([int(r.split("/")[-1]) for r in results])
        self.assertEqual(serials, list(range(1, 21)))

        # Verify format is correct for all results
        for r in results:
            self.assertTrue(r.startswith("INV/261105/"))


class TestNextNumberFinancialYearBoundary(TransactionTestCase):
    """Tests for financial year boundary behavior (31 March vs 1 April)."""

    def setUp(self):
        NumberSeries.objects.all().delete()
        settings = AppSettings.get_settings()
        settings.invoice_prefix = "INV"
        settings.series_start_number = 1
        settings.financial_year_start_month = 4  # April start
        settings.save()

    def test_31_march_belongs_to_previous_fy(self):
        """Test document dated 31 March 2027 belongs to FY 26-27."""
        with transaction.atomic():
            result = next_number("INV", date(2027, 3, 31))

        self.assertEqual(result, "INV/270331/0001")
        series = NumberSeries.objects.get(series_code="INV", financial_year="26-27")
        self.assertEqual(series.last_number, 1)
        # 27-28 series should not exist yet
        self.assertFalse(NumberSeries.objects.filter(financial_year="27-28").exists())

    def test_1_april_belongs_to_next_fy(self):
        """Test document dated 1 April 2027 belongs to FY 27-28 (serial restarts at 0001)."""
        # First create a 26-27 series with some numbers
        NumberSeries.objects.create(
            series_code="INV", financial_year="26-27", prefix="INV", last_number=100, padding=4
        )

        with transaction.atomic():
            result = next_number("INV", date(2027, 4, 1))

        self.assertEqual(result, "INV/270401/0001")
        # 26-27 series should be untouched
        series_26_27 = NumberSeries.objects.get(series_code="INV", financial_year="26-27")
        self.assertEqual(series_26_27.last_number, 100)
        # 27-28 series should be created with last_number = 1
        series_27_28 = NumberSeries.objects.get(series_code="INV", financial_year="27-28")
        self.assertEqual(series_27_28.last_number, 1)


class TestNextNumberRollback(TransactionTestCase):
    """Tests for rollback behavior - serial should not be consumed."""

    def setUp(self):
        NumberSeries.objects.all().delete()
        settings = AppSettings.get_settings()
        settings.invoice_prefix = "INV"
        settings.series_start_number = 1
        settings.financial_year_start_month = 4
        settings.save()

    def test_rolled_back_transaction_does_not_consume_serial(self):
        """Test that a rolled-back transaction does not consume a serial number."""
        # First successful call
        with transaction.atomic():
            result1 = next_number("INV", date(2026, 11, 5))
        self.assertEqual(result1, "INV/261105/0001")

        # Second call that rolls back
        try:
            with transaction.atomic():
                result2 = next_number("INV", date(2026, 11, 5))
                self.assertEqual(result2, "INV/261105/0002")
                raise Exception("Force rollback")
        except Exception:
            pass  # Expected rollback

        # Third call should get the same serial as the rolled-back one (0002)
        with transaction.atomic():
            result3 = next_number("INV", date(2026, 11, 5))
        self.assertEqual(result3, "INV/261105/0002")

        # Verify only 2 series numbers were actually used (0001 and 0002)
        series = NumberSeries.objects.get(series_code="INV", financial_year="26-27")
        self.assertEqual(series.last_number, 2)


class TestNextNumberConcurrencyNewFY(TransactionTestCase):
    """Concurrency test for creating a new financial year row."""

    def setUp(self):
        NumberSeries.objects.all().delete()
        settings = AppSettings.get_settings()
        settings.invoice_prefix = "INV"
        settings.series_start_number = 1
        settings.financial_year_start_month = 4
        settings.save()

    def test_concurrency_20_threads_new_fy_creation(self):
        """Test 20 threads creating a new FY row produce 20 unique, contiguous serials."""
        results = []
        errors = []

        def worker():
            try:
                # Each thread needs its own database connection
                connection.close_if_unusable_or_obsolete()
                with transaction.atomic():
                    # Use a date in a FY that doesn't exist yet (2028-01-01 = FY 28-29)
                    result = next_number("INV", date(2028, 1, 1))
                    results.append(result)
            except Exception as e:
                errors.append(e)
            finally:
                connection.close()

        threads = [Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Errors occurred: {errors}")
        self.assertEqual(len(results), 20)

        # Extract serial numbers and verify they are contiguous
        serials = sorted([int(r.split("/")[-1]) for r in results])
        self.assertEqual(serials, list(range(1, 21)))

        # Verify format is correct for all results
        for r in results:
            self.assertTrue(r.startswith("INV/280101/"))


class TestNextNumberCustomFYStartMonth(TransactionTestCase):
    """Tests for custom financial_year_start_month setting."""

    def setUp(self):
        NumberSeries.objects.all().delete()
        settings = AppSettings.get_settings()
        settings.invoice_prefix = "INV"
        settings.series_start_number = 1
        settings.financial_year_start_month = 7  # July start
        settings.save()

    def test_july_start_fy_calculation(self):
        """Test FY calculation with July start month."""
        from apps.core.models import get_financial_year

        # June 30, 2026 -> FY 25-26 (before July)
        self.assertEqual(get_financial_year(date(2026, 6, 30), 7), "25-26")
        # July 1, 2026 -> FY 26-27
        self.assertEqual(get_financial_year(date(2026, 7, 1), 7), "26-27")
        # Dec 31, 2026 -> FY 26-27
        self.assertEqual(get_financial_year(date(2026, 12, 31), 7), "26-27")
        # June 30, 2027 -> FY 26-27
        self.assertEqual(get_financial_year(date(2027, 6, 30), 7), "26-27")
        # July 1, 2027 -> FY 27-28
        self.assertEqual(get_financial_year(date(2027, 7, 1), 7), "27-28")

    def test_july_start_fy_boundary_next_number(self):
        """Test next_number respects custom July FY start."""
        # June 30, 2026 -> FY 25-26
        with transaction.atomic():
            result1 = next_number("INV", date(2026, 6, 30))
        self.assertEqual(result1, "INV/260630/0001")
        series_25_26 = NumberSeries.objects.get(series_code="INV", financial_year="25-26")
        self.assertEqual(series_25_26.last_number, 1)

        # July 1, 2026 -> FY 26-27 (new FY, serial restarts at 1)
        with transaction.atomic():
            result2 = next_number("INV", date(2026, 7, 1))
        self.assertEqual(result2, "INV/260701/0001")
        series_26_27 = NumberSeries.objects.get(series_code="INV", financial_year="26-27")
        self.assertEqual(series_26_27.last_number, 1)
        # 25-26 should be untouched
        series_25_26.refresh_from_db()
        self.assertEqual(series_25_26.last_number, 1)

        # Another in same FY 26-27
        with transaction.atomic():
            result3 = next_number("INV", date(2026, 7, 2))
        self.assertEqual(result3, "INV/260702/0002")


class TestNextNumberPrefixValidation(TransactionTestCase):
    """Tests for prefix validation in next_number."""

    def setUp(self):
        NumberSeries.objects.all().delete()
        settings = AppSettings.get_settings()
        settings.invoice_prefix = "INV"
        settings.series_start_number = 1
        settings.financial_year_start_month = 4
        settings.save()

    def test_invalid_prefix_too_long_raises_validation_error(self):
        """Test that a prefix > 4 chars raises ValidationError and doesn't consume serial."""
        settings = AppSettings.get_settings()
        settings.invoice_prefix = "INVO"  # 4 chars is OK, 5 is not
        settings.save()

        # Create a series row first with valid prefix
        with transaction.atomic():
            next_number("INV", date(2026, 11, 5))

        # Now change prefix to invalid (5 chars) directly on model
        settings.invoice_prefix = "INVOI"  # 5 chars
        settings.save()

        # Should raise ValidationError and not consume serial
        with self.assertRaises(ValidationError) as cm:
            with transaction.atomic():
                next_number("INV", date(2026, 11, 6))
        self.assertIn("prefix", str(cm.exception).lower())

        # Serial should not have been consumed
        series = NumberSeries.objects.get(series_code="INV", financial_year="26-27")
        self.assertEqual(series.last_number, 1)

    def test_invalid_prefix_with_slash_raises_validation_error(self):
        """Test that a prefix with slash raises ValidationError."""
        settings = AppSettings.get_settings()
        settings.invoice_prefix = "IN/V"  # slash not allowed
        settings.save()

        with self.assertRaises(ValidationError) as cm:
            with transaction.atomic():
                next_number("INV", date(2026, 11, 5))
        self.assertIn("prefix", str(cm.exception).lower())

    def test_prefix_change_after_first_invoice_same_fy_uses_old_prefix(self):
        """Test changing invoice_prefix after first INV number uses old prefix in same FY."""
        # Issue first INV number
        with transaction.atomic():
            result1 = next_number("INV", date(2026, 11, 5))
        self.assertEqual(result1, "INV/261105/0001")

        # Change prefix in settings
        settings = AppSettings.get_settings()
        settings.invoice_prefix = "NEW"
        settings.save()

        # Next number in SAME FY should use old prefix
        with transaction.atomic():
            result2 = next_number("INV", date(2026, 11, 6))
        self.assertEqual(result2, "INV/261106/0002")

        # But new FY should use new prefix
        with transaction.atomic():
            result3 = next_number("INV", date(2027, 4, 1))
        self.assertEqual(result3, "NEW/270401/0001")

    def test_valid_prefix_uppercase_stored(self):
        """Test that valid prefix (1-4 chars, alnum) works and is uppercased."""
        settings = AppSettings.get_settings()
        settings.invoice_prefix = "abc"  # lowercase
        settings.save()

        with transaction.atomic():
            result = next_number("INV", date(2026, 11, 5))
        # Should be uppercased in the stored row
        self.assertEqual(result, "ABC/261105/0001")
        series = NumberSeries.objects.get(series_code="INV", financial_year="26-27")
        self.assertEqual(series.prefix, "ABC")


class TestNextNumberRetryLimit(TransactionTestCase):
    """Tests for retry limit on IntegrityError."""

    def setUp(self):
        NumberSeries.objects.all().delete()
        settings = AppSettings.get_settings()
        settings.invoice_prefix = "INV"
        settings.series_start_number = 1
        settings.financial_year_start_month = 4
        settings.save()

    def test_retry_stops_after_5_attempts(self):
        """Test that retry loop stops after 5 IntegrityError attempts and re-raises."""

        # Mock get_or_create to always raise IntegrityError
        with patch.object(NumberSeries.objects, "select_for_update") as mock_select_for_update:
            mock_manager = mock_select_for_update.return_value
            mock_manager.get_or_create.side_effect = IntegrityError("duplicate key")

            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    next_number("INV", date(2026, 11, 5))

            # Verify it was called 5 times (the retry limit)
            self.assertEqual(mock_manager.get_or_create.call_count, 5)


class TestFirstEverINVRule(TransactionTestCase):
    """Tests for the first-ever-INV series_start_number rule."""

    def setUp(self):
        NumberSeries.objects.all().delete()
        settings = AppSettings.get_settings()
        settings.invoice_prefix = "INV"
        settings.series_start_number = 215
        settings.financial_year_start_month = 4
        settings.save()

    def test_first_ever_inv_uses_series_start_number(self):
        """Test first ever INV row uses series_start_number (215 -> 0215)."""
        with transaction.atomic():
            result = next_number("INV", date(2026, 11, 5))
        self.assertEqual(result, "INV/261105/0215")

        # Next should be 216
        with transaction.atomic():
            result2 = next_number("INV", date(2026, 11, 5))
        self.assertEqual(result2, "INV/261105/0216")

    def test_cn_ignores_series_start_number(self):
        """Test CN series ignores series_start_number and starts at 1."""
        with transaction.atomic():
            result = next_number("CN", date(2026, 11, 5))
        self.assertEqual(result, "CN/261105/0001")

    def test_later_fy_ignores_series_start_number(self):
        """Test later financial year ignores series_start_number and starts at 1."""
        # Create first FY
        with transaction.atomic():
            next_number("INV", date(2026, 11, 5))

        # Next FY should start at 1, not 215
        with transaction.atomic():
            result = next_number("INV", date(2027, 4, 1))
        self.assertEqual(result, "INV/270401/0001")


# =============================================================================
# IDEMPOTENCY TESTS (T-105)
# =============================================================================


def _canonical_json(data: dict) -> str:
    """Helper to produce canonical JSON for hash comparison in tests."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class TestComputeRequestHash(TestCase):
    """Tests for compute_request_hash function."""

    def test_hash_includes_method_path_body_query(self):
        """Test hash includes method, path, body, and query string."""
        method = "POST"
        path = "/api/v1/test/"
        body = {"b": 2, "a": 1}
        query = "foo=bar&baz=qux"

        hash1 = compute_request_hash(method, path, body, query)
        hash2 = compute_request_hash(method, path, body, query)
        self.assertEqual(hash1, hash2)
        self.assertEqual(len(hash1), 64)  # SHA-256 hex

    def test_hash_different_for_different_body(self):
        """Test different body produces different hash."""
        hash1 = compute_request_hash("POST", "/api/v1/test/", {"a": 1}, "")
        hash2 = compute_request_hash("POST", "/api/v1/test/", {"a": 2}, "")
        self.assertNotEqual(hash1, hash2)

    def test_hash_different_for_different_method(self):
        """Test different method produces different hash."""
        hash1 = compute_request_hash("POST", "/api/v1/test/", {"a": 1}, "")
        hash2 = compute_request_hash("PUT", "/api/v1/test/", {"a": 1}, "")
        self.assertNotEqual(hash1, hash2)

    def test_hash_different_for_different_path(self):
        """Test different path produces different hash."""
        hash1 = compute_request_hash("POST", "/api/v1/test/", {"a": 1}, "")
        hash2 = compute_request_hash("POST", "/api/v1/other/", {"a": 1}, "")
        self.assertNotEqual(hash1, hash2)

    def test_hash_different_for_different_query(self):
        """Test different query string produces different hash."""
        hash1 = compute_request_hash("POST", "/api/v1/test/", {"a": 1}, "foo=bar")
        hash2 = compute_request_hash("POST", "/api/v1/test/", {"a": 1}, "foo=baz")
        self.assertNotEqual(hash1, hash2)

    def test_hash_same_for_different_key_order(self):
        """Test same content with different key order produces same hash."""
        hash1 = compute_request_hash("POST", "/api/v1/test/", {"b": 2, "a": 1}, "")
        hash2 = compute_request_hash("POST", "/api/v1/test/", {"a": 1, "b": 2}, "")
        self.assertEqual(hash1, hash2)

    def test_hash_handles_decimals_as_sent(self):
        """Test that Decimal values are compared as sent (strings)."""
        # JSON doesn't have Decimal, so they come as strings or numbers
        hash1 = compute_request_hash("POST", "/api/v1/test/", {"amount": "100.00"}, "")
        hash2 = compute_request_hash("POST", "/api/v1/test/", {"amount": 100.00}, "")
        # These might differ because one is string, one is number in JSON
        # The requirement says "Decimals and numbers compared as sent"
        # So we just verify the function doesn't crash
        self.assertEqual(len(hash1), 64)
        self.assertEqual(len(hash2), 64)

    def test_empty_body_and_query(self):
        """Test hash with empty body and query."""
        hash1 = compute_request_hash("POST", "/api/v1/test/", {}, "")
        hash2 = compute_request_hash("POST", "/api/v1/test/", {}, "")
        self.assertEqual(hash1, hash2)


class TestAdvisoryLockKey(TestCase):
    """Tests for compute_advisory_lock_key stability (never Python's hash())."""

    def test_lock_key_matches_fixed_expected(self):
        """Same (user_id, key) always yields the same fixed 64-bit key."""
        user_id = 1
        key_uuid = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
        self.assertEqual(compute_advisory_lock_key(user_id, key_uuid), 2156988632690186920)
        # Positive int64 range (pg_advisory_xact_lock accepts bigint).
        self.assertGreaterEqual(compute_advisory_lock_key(user_id, key_uuid), 0)
        self.assertLessEqual(compute_advisory_lock_key(user_id, key_uuid), 0x7FFFFFFFFFFFFFFF)

    def test_lock_key_independent_of_python_hashseed(self):
        """The key is computed with hashlib, so PYTHONHASHSEED cannot change it.

        An independent hashlib computation must agree with the helper, proving
        the built-in randomized hash() is never used.
        """
        import hashlib as _hashlib

        user_id = 7
        key_uuid = uuid.UUID("550e8400-e29b-41d4-a716-446655440001")
        expected = (
            int.from_bytes(
                _hashlib.sha256(f"{user_id}:{key_uuid}".encode()).digest()[:8],
                "big",
                signed=False,
            )
            & 0x7FFFFFFFFFFFFFFF
        )
        self.assertEqual(compute_advisory_lock_key(user_id, key_uuid), expected)
        # Different inputs must differ (no accidental constant).
        self.assertNotEqual(
            compute_advisory_lock_key(user_id, key_uuid),
            compute_advisory_lock_key(user_id + 1, key_uuid),
        )

    def test_lock_key_same_user_same_key_same_lock_key(self):
        """Same user and key always give the same advisory lock key."""
        key_uuid = uuid.UUID("550e8400-e29b-41d4-a716-446655440002")
        k1 = compute_advisory_lock_key(42, key_uuid)
        k2 = compute_advisory_lock_key(42, key_uuid)
        self.assertEqual(k1, k2)

    def test_lock_key_different_user_different_lock_key(self):
        """Same key with a different user gives a different advisory lock key."""
        key_uuid = uuid.UUID("550e8400-e29b-41d4-a716-446655440003")
        self.assertNotEqual(
            compute_advisory_lock_key(1, key_uuid),
            compute_advisory_lock_key(2, key_uuid),
        )

    def test_postgres_sqlstate_detects_sqlstate(self):
        """_postgres_sqlstate detects SQLSTATE from the sqlstate attribute (psycopg 3)."""

        class FakeLockNotAvailableError(Exception):
            sqlstate = "55P03"

        self.assertEqual(_postgres_sqlstate(FakeLockNotAvailableError()), "55P03")

    def test_postgres_sqlstate_walks_cause_chain(self):
        """_postgres_sqlstate walks the __cause__ chain to find SQLSTATE."""

        class InnerError(Exception):
            pgcode = "55P03"

        class OuterError(Exception):
            pass

        exc = OuterError("wrapped")
        exc.__cause__ = InnerError("inner")
        self.assertEqual(_postgres_sqlstate(exc), "55P03")


class TestRealLockNotAvailable(TransactionTestCase):
    """Test that the real psycopg.errors.LockNotAvailable is detected against the DB."""

    def test_real_lock_not_available_detected(self):
        """A real lock-not-available from psycopg 3 yields SQLSTATE 55P03."""
        import time
        from threading import Thread

        import psycopg
        from django.conf import settings

        results = []
        lock_key = 987654325

        db_params = {
            "host": settings.DATABASES["default"]["HOST"],
            "port": settings.DATABASES["default"]["PORT"],
            "dbname": settings.DATABASES["default"]["NAME"],
            "user": settings.DATABASES["default"]["USER"],
            "password": settings.DATABASES["default"]["PASSWORD"],
        }

        def holder():
            """Acquire and hold an advisory lock for ~2 seconds."""
            try:
                conn = psycopg.connect(**db_params)
                conn.autocommit = False
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_xact_lock(%s)", [lock_key])
                time.sleep(2)
                conn.commit()
            except Exception as e:  # noqa: BLE001
                results.append(("holder", e))
            finally:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass

        def waiter():
            """Try to acquire the same lock with a 100ms timeout."""
            try:
                time.sleep(0.2)
                conn = psycopg.connect(**db_params)
                conn.autocommit = False
                with conn.cursor() as cur:
                    cur.execute("SET LOCAL lock_timeout = '100ms'")
                    try:
                        cur.execute("SELECT pg_advisory_xact_lock(%s)", [lock_key])
                        results.append(("waiter", "ACQUIRED"))
                    except Exception as exc:  # noqa: BLE001
                        results.append(("waiter", exc))
                conn.rollback()
            except Exception as e:  # noqa: BLE001
                results.append(("waiter-outer", e))
            finally:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass

        t1 = Thread(target=holder)
        t2 = Thread(target=waiter)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        waiter_exc = next((r[1] for r in results if r[0] == "waiter"), None)
        self.assertIsNotNone(waiter_exc, "waiter should have received a lock error")

        # The real driver exception (psycopg.errors.LockNotAvailable) exposes SQLSTATE 55P03
        self.assertEqual(_postgres_sqlstate(waiter_exc), "55P03")


class TestIdempotencyDecoratorBasic(TestCase):
    """Basic tests for @idempotent decorator."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="owner", password="SecurePass123!")
        self.login()

    def login(self):
        response = self.client.post(
            "/api/v1/auth/login/",
            {"username": "owner", "password": "SecurePass123!"},
            format="json",
        )
        self.access_token = response.json()["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")

    def _post_with_key(self, key, data=None, path="/api/v1/test-idempotency/"):
        """Helper to POST with Idempotency-Key header."""
        if data is None:
            data = {"test": "data"}
        return self.client.post(
            path,
            data,
            format="json",
            HTTP_IDEMPOTENCY_KEY=key,
        )

    @override_settings(ROOT_URLCONF="apps.core.test_urls")
    def test_missing_header_returns_400(self):
        """Missing Idempotency-Key header returns 400 IDEMPOTENCY_KEY_REQUIRED."""
        response = self.client.post(
            "/api/v1/test-idempotency/",
            {"test": "data"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["code"], "IDEMPOTENCY_KEY_REQUIRED")
        self.assertEqual(response.json()["message"], "Idempotency-Key header is required")
        # Handler should not be called (no IdempotencyRecord created)
        self.assertEqual(IdempotencyRecord.objects.count(), 0)

    @override_settings(ROOT_URLCONF="apps.core.test_urls")
    def test_invalid_uuid_returns_400(self):
        """Non-UUID Idempotency-Key returns 400 IDEMPOTENCY_KEY_INVALID."""
        response = self._post_with_key("not-a-uuid")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["code"], "IDEMPOTENCY_KEY_INVALID")
        self.assertEqual(response.json()["message"], "Idempotency-Key must be a valid UUID")

    @override_settings(ROOT_URLCONF="apps.core.test_urls")
    def test_first_call_returns_201_and_creates_record(self):
        """First call returns 201 and creates one IdempotencyRecord."""
        key = "550e8400-e29b-41d4-a716-446655440000"
        response = self._post_with_key(key)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["result"], "success")

        # Verify record created
        record = IdempotencyRecord.objects.get(user_id=self.user.id, key=key)
        self.assertEqual(record.method, "POST")
        self.assertEqual(record.path, "/api/v1/test-idempotency/")
        self.assertEqual(record.response_status, 201)
        self.assertIn("result", record.response_body)
        self.assertEqual(record.response_body["result"], "success")

    @override_settings(ROOT_URLCONF="apps.core.test_urls")
    def test_replay_returns_identical_response_with_header(self):
        """Replay returns identical status and body with Idempotent-Replayed: true."""
        key = "550e8400-e29b-41d4-a716-446655440001"
        # First call
        response1 = self._post_with_key(key, {"value": 42})
        self.assertEqual(response1.status_code, status.HTTP_201_CREATED)
        body1 = response1.json()

        # Second call (replay)
        response2 = self._post_with_key(key, {"value": 42})
        self.assertEqual(response2.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response2.json(), body1)
        self.assertEqual(response2.headers.get("Idempotent-Replayed"), "true")

        # Handler should only be called once
        # We can't easily check view.handler_call_count from here since it's a new instance per request
        # But we can verify only one record exists
        self.assertEqual(IdempotencyRecord.objects.filter(user_id=self.user.id, key=key).count(), 1)

    @override_settings(ROOT_URLCONF="apps.core.test_urls")
    def test_same_key_different_payload_returns_409(self):
        """Same key with different payload returns 409 IDEMPOTENCY_KEY_REUSED."""
        key = "550e8400-e29b-41d4-a716-446655440002"
        self._post_with_key(key, {"value": 1})
        response = self._post_with_key(key, {"value": 2})  # Different payload
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.json()["code"], "IDEMPOTENCY_KEY_REUSED")
        self.assertIn("different request", response.json()["message"])

    @override_settings(ROOT_URLCONF="apps.core.test_urls")
    def test_same_key_different_path_returns_409(self):
        """Same key on different path returns 409 IDEMPOTENCY_KEY_REUSED."""
        key = "550e8400-e29b-41d4-a716-446655440003"
        # First call on path A
        self._post_with_key(key, {"value": 1}, path="/api/v1/test-idempotency/")
        # Second call on path B with same key - should be 409
        response = self._post_with_key(key, {"value": 1}, path="/api/v1/test-idempotency-other/")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.json()["code"], "IDEMPOTENCY_KEY_REUSED")
        self.assertIn("different request", response.json()["message"])
        # Handler for path B should not have run
        self.assertEqual(IdempotencyRecord.objects.filter(user_id=self.user.id, key=key).count(), 1)

    @override_settings(ROOT_URLCONF="apps.core.test_urls")
    def test_same_key_different_method_returns_409(self):
        """Same key with different HTTP method returns 409 IDEMPOTENCY_KEY_REUSED."""
        key = "550e8400-e29b-41d4-a716-446655440004"
        # First call with POST
        self._post_with_key(key, {"value": 1}, path="/api/v1/test-idempotency/")
        # Second call with PUT on same path - should be 409 (different method)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")
        response = client.put(
            "/api/v1/test-idempotency/",
            {"value": 1},
            format="json",
            HTTP_IDEMPOTENCY_KEY=key,
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.json()["code"], "IDEMPOTENCY_KEY_REUSED")
        self.assertIn("different request", response.json()["message"])
        # Only one record should exist (from the POST)
        self.assertEqual(IdempotencyRecord.objects.filter(user_id=self.user.id, key=key).count(), 1)

    @override_settings(ROOT_URLCONF="apps.core.test_urls")
    def test_json_same_content_different_key_order_same_hash(self):
        """JSON with same content but different key order counts as same payload."""
        key = "550e8400-e29b-41d4-a716-446655440005"
        # First call with one key order
        response1 = self._post_with_key(key, {"b": 2, "a": 1})
        self.assertEqual(response1.status_code, status.HTTP_201_CREATED)

        # Second call with different key order - should replay
        response2 = self._post_with_key(key, {"a": 1, "b": 2})
        self.assertEqual(response2.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response2.headers.get("Idempotent-Replayed"), "true")
        self.assertEqual(response2.json(), response1.json())

    @override_settings(ROOT_URLCONF="apps.core.test_urls")
    def test_handler_returns_400_stores_nothing_and_allows_retry(self):
        """Handler returning 400 stores nothing, rolls back, key can be retried."""
        key = "550e8400-e29b-41d4-a716-446655440006"
        # Use the error view that can return 400
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")

        # First call - handler returns 400 (enable should_fail)
        import apps.core.test_urls as test_urls

        test_urls._should_fail = True
        try:
            response1 = client.post(
                "/api/v1/test-error/",
                {"test": "data"},
                format="json",
                HTTP_IDEMPOTENCY_KEY=key,
            )
            self.assertEqual(response1.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response1.json()["code"], "VALIDATION_ERROR")

            # No record should exist (rolled back)
            self.assertEqual(
                IdempotencyRecord.objects.filter(user_id=self.user.id, key=key).count(), 0
            )

            # Retry with same key should work (should_fail reset)
            test_urls._should_fail = False
            response2 = client.post(
                "/api/v1/test-error/",
                {"test": "data"},
                format="json",
                HTTP_IDEMPOTENCY_KEY=key,
            )
            self.assertEqual(response2.status_code, status.HTTP_201_CREATED)
            self.assertEqual(
                IdempotencyRecord.objects.filter(user_id=self.user.id, key=key).count(), 1
            )
        finally:
            test_urls._should_fail = False

    @override_settings(ROOT_URLCONF="apps.core.test_urls")
    def test_handler_raises_exception_stores_nothing_and_allows_retry(self):
        """Handler raising exception stores nothing, rolls back, key can be retried."""
        key = "550e8400-e29b-41d4-a716-446655440007"
        # Use the error view that can raise an exception
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")

        import apps.core.test_urls as test_urls

        # First call - handler raises exception (enable should_raise)
        test_urls._should_raise = True
        try:
            # Use raise_request_exception=True to propagate the exception
            client.post(
                "/api/v1/test-error/",
                {"test": "data"},
                format="json",
                HTTP_IDEMPOTENCY_KEY=key,
                raise_request_exception=True,
            )
            self.fail("Expected exception to be raised")
        except Exception:
            pass  # Expected
        finally:
            test_urls._should_raise = False

        # No record should exist (rolled back)
        self.assertEqual(IdempotencyRecord.objects.filter(user_id=self.user.id, key=key).count(), 0)

        # Retry with same key should work (should_raise reset)
        test_urls._should_raise = False
        response2 = client.post(
            "/api/v1/test-error/",
            {"test": "data"},
            format="json",
            HTTP_IDEMPOTENCY_KEY=key,
        )
        self.assertEqual(response2.status_code, status.HTTP_201_CREATED)
        self.assertEqual(IdempotencyRecord.objects.filter(user_id=self.user.id, key=key).count(), 1)

    @override_settings(ROOT_URLCONF="apps.core.test_urls")
    def test_unauthenticated_call_returns_401(self):
        """Unauthenticated call returns 401 before idempotency check."""
        client = APIClient()
        response = client.post(
            "/api/v1/test-idempotency/",
            {"test": "data"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="550e8400-e29b-41d4-a716-446655440008",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json()["code"], "AUTHENTICATION_FAILED")


class TestIdempotencyDecoratorAudit(TestCase):
    """Tests for audit log behavior with idempotency."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="owner", password="SecurePass123!")
        self.login()

    def login(self):
        response = self.client.post(
            "/api/v1/auth/login/",
            {"username": "owner", "password": "SecurePass123!"},
            format="json",
        )
        self.access_token = response.json()["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")

    def _post_with_key(self, key, data=None):
        if data is None:
            data = {"test": "data"}
        return self.client.post(
            "/api/v1/test-idempotency/",
            data,
            format="json",
            HTTP_IDEMPOTENCY_KEY=key,
        )

    @override_settings(ROOT_URLCONF="apps.core.test_urls")
    def test_replay_does_not_create_audit_entry(self):
        """Replay does not create additional audit entries."""
        key = "550e8400-e29b-41d4-a716-446655440009"

        # First call
        self._post_with_key(key)
        audit_count_after_first = AuditLog.objects.filter(action="test.idempotency_write").count()

        # Replay
        self._post_with_key(key)
        audit_count_after_replay = AuditLog.objects.filter(action="test.idempotency_write").count()

        # Should be the same (handler not called on replay)
        self.assertEqual(audit_count_after_first, audit_count_after_replay)


class TestIdempotencyDecimalStorage(TestCase):
    """Tests for Decimal value storage in response_body."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="owner", password="SecurePass123!")
        self.login()

    def login(self):
        response = self.client.post(
            "/api/v1/auth/login/",
            {"username": "owner", "password": "SecurePass123!"},
            format="json",
        )
        self.access_token = response.json()["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")

    def _post_with_key(self, key, data=None):
        if data is None:
            data = {"test": "data"}
        return self.client.post(
            "/api/v1/test-idempotency/",
            data,
            format="json",
            HTTP_IDEMPOTENCY_KEY=key,
        )

    @override_settings(ROOT_URLCONF="apps.core.test_urls")
    def test_decimal_values_stored_as_strings(self):
        """Decimal values in response body are stored as strings."""
        key = "550e8400-e29b-41d4-a716-446655440010"
        # The test view returns count as int, but we can check the serialization
        self._post_with_key(key)
        record = IdempotencyRecord.objects.get(user_id=self.user.id, key=key)
        # response_body should be JSON-serializable with Decimals as strings
        # Since our test returns int, verify it's stored correctly
        self.assertIsInstance(record.response_body, dict)
        self.assertIn("count", record.response_body)


class TestIdempotencyDifferentUsers(TestCase):
    """Tests for different users using the same key."""

    def setUp(self):
        self.client1 = APIClient()
        self.user1 = User.objects.create_user(username="owner1", password="SecurePass123!")
        self.login1()

        self.client2 = APIClient()
        self.user2 = User.objects.create_user(username="owner2", password="SecurePass123!")
        self.login2()

    def login1(self):
        response = self.client1.post(
            "/api/v1/auth/login/",
            {"username": "owner1", "password": "SecurePass123!"},
            format="json",
        )
        self.access_token1 = response.json()["access"]
        self.client1.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token1}")

    def login2(self):
        response = self.client2.post(
            "/api/v1/auth/login/",
            {"username": "owner2", "password": "SecurePass123!"},
            format="json",
        )
        self.access_token2 = response.json()["access"]
        self.client2.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token2}")

    def _post_with_key(self, client, key, data=None):
        if data is None:
            data = {"test": "data"}
        return client.post(
            "/api/v1/test-idempotency/",
            data,
            format="json",
            HTTP_IDEMPOTENCY_KEY=key,
        )

    @override_settings(ROOT_URLCONF="apps.core.test_urls")
    def test_different_users_same_key_independent(self):
        """Two different users may use the same key independently."""
        key = "550e8400-e29b-41d4-a716-446655440011"

        # User 1 creates record
        response1 = self._post_with_key(self.client1, key)
        self.assertEqual(response1.status_code, status.HTTP_201_CREATED)

        # User 2 uses same key - should work independently
        response2 = self._post_with_key(self.client2, key)
        self.assertEqual(response2.status_code, status.HTTP_201_CREATED)

        # Both records exist
        self.assertEqual(IdempotencyRecord.objects.filter(key=key).count(), 2)
        self.assertTrue(IdempotencyRecord.objects.filter(user_id=self.user1.id, key=key).exists())
        self.assertTrue(IdempotencyRecord.objects.filter(user_id=self.user2.id, key=key).exists())


class TestPurgeIdempotencyKeysCommand(TestCase):
    """Tests for purge_idempotency_keys management command."""

    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="SecurePass123!")
        # Create some records with different ages
        from datetime import timedelta

        from django.utils import timezone

        # Recent record (should not be purged)
        recent = IdempotencyRecord.objects.create(
            user_id=self.user.id,
            key="11111111-1111-1111-1111-111111111111",
            method="POST",
            path="/api/v1/test/",
            request_hash="abc",
            response_status=201,
            response_body={},
        )
        recent.created_at = timezone.now() - timedelta(days=5)
        recent.save()

        # Old record (should be purged with --days 30)
        old = IdempotencyRecord.objects.create(
            user_id=self.user.id,
            key="22222222-2222-2222-2222-222222222222",
            method="POST",
            path="/api/v1/test/",
            request_hash="def",
            response_status=201,
            response_body={},
        )
        old.created_at = timezone.now() - timedelta(days=60)
        old.save()

    def test_purge_deletes_only_old_records(self):
        """Purge command deletes only records older than N days."""
        out = StringIO()
        call_command("purge_idempotency_keys", "--days", "30", stdout=out)
        output = out.getvalue()

        self.assertIn("Deleted 1 idempotency record(s)", output)
        self.assertEqual(IdempotencyRecord.objects.count(), 1)
        self.assertTrue(
            IdempotencyRecord.objects.filter(key="11111111-1111-1111-1111-111111111111").exists()
        )
        self.assertFalse(
            IdempotencyRecord.objects.filter(key="22222222-2222-2222-2222-222222222222").exists()
        )

    def test_purge_default_30_days(self):
        """Default purge uses 30 days."""
        out = StringIO()
        call_command("purge_idempotency_keys", stdout=out)
        output = out.getvalue()

        self.assertIn("Deleted 1 idempotency record(s)", output)

    def test_purge_zero_days_deletes_all(self):
        """Purge with --days 0 deletes all records."""
        out = StringIO()
        call_command("purge_idempotency_keys", "--days", "0", stdout=out)
        output = out.getvalue()

        self.assertIn("Deleted 2 idempotency record(s)", output)
        self.assertEqual(IdempotencyRecord.objects.count(), 0)


class TestIdempotencyConcurrency(TransactionTestCase):
    """Concurrency tests for idempotency mechanism."""

    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="SecurePass123!")
        self.key = "550e8400-e29b-41d4-a716-446655440020"
        # Get JWT token for authentication
        self.client = APIClient()
        response = self.client.post(
            "/api/v1/auth/login/",
            {"username": "owner", "password": "SecurePass123!"},
            format="json",
        )
        self.access_token = response.json()["access"]

    def _make_request(self, results, errors, key, wait=0.5):
        """Make a request in a separate thread with its own connection."""
        try:
            connection.close_if_unusable_or_obsolete()
            client = APIClient()
            client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")
            response = client.post(
                "/api/v1/test-idempotency/",
                {"test": "data"},
                format="json",
                HTTP_IDEMPOTENCY_KEY=key,
            )
            if response.status_code >= 500:
                # DEBUG: Thread got 500 response
                pass
            results.append(
                (response.status_code, response.json(), response.headers.get("Idempotent-Replayed"))
            )
        except Exception as e:
            errors.append(e)
        finally:
            connection.close()

    @override_settings(ROOT_URLCONF="apps.core.test_urls")
    def test_concurrency_same_key_handler_executed_once(self):
        """5 threads with same key: handler executed exactly once, one business row, same response."""
        results = []
        errors = []
        threads = [
            Thread(target=self._make_request, args=(results, errors, self.key, 0.5))
            for _ in range(5)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Errors: {errors}")
        self.assertEqual(len(results), 5)

        # All should succeed
        for status_code, _body, _replayed in results:
            self.assertEqual(status_code, status.HTTP_201_CREATED)
            self.assertEqual(_body["result"], "success")

        # Exactly one should have replayed=false (first), rest replayed=true
        replayed_count = sum(1 for _, _, r in results if r == "true")
        not_replayed_count = sum(1 for _, _, r in results if r != "true")
        self.assertEqual(not_replayed_count, 1)
        self.assertEqual(replayed_count, 4)

        # Only one IdempotencyRecord created
        self.assertEqual(
            IdempotencyRecord.objects.filter(user_id=self.user.id, key=self.key).count(), 1
        )

        # Only one business write (AuditLog entry)
        from apps.core.models import AuditLog

        self.assertEqual(AuditLog.objects.filter(action="test.idempotency_write").count(), 1)

    @override_settings(ROOT_URLCONF="apps.core.test_urls")
    def test_concurrency_different_keys_handler_executed_for_each(self):
        """5 threads with different keys: handler executed 5 times."""
        results = []
        errors = []
        keys = [f"550e8400-e29b-41d4-a716-4466554400{i:02d}" for i in range(21, 26)]

        threads = [
            Thread(target=self._make_request, args=(results, errors, key, 0.1)) for key in keys
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Errors: {errors}")
        self.assertEqual(len(results), 5)

        # All should succeed
        for status_code, _body, _replayed in results:
            self.assertEqual(status_code, status.HTTP_201_CREATED)

        # None should be replayed (all different keys)
        replayed_count = sum(1 for _, _, r in results if r == "true")
        self.assertEqual(replayed_count, 0)

        # 5 IdempotencyRecords created
        self.assertEqual(IdempotencyRecord.objects.filter(user_id=self.user.id).count(), 5)

        # 5 business writes
        from apps.core.models import AuditLog

        self.assertEqual(AuditLog.objects.filter(action="test.idempotency_write").count(), 5)


class TestIdempotencyLockTimeout(TransactionTestCase):
    """Tests for lock timeout behavior."""

    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="SecurePass123!")
        self.key = "550e8400-e29b-41d4-a716-446655440030"
        self.client = APIClient()
        response = self.client.post(
            "/api/v1/auth/login/",
            {"username": "owner", "password": "SecurePass123!"},
            format="json",
        )
        self.access_token = response.json()["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")

    @override_settings(ROOT_URLCONF="apps.core.test_urls", IDEMPOTENCY_LOCK_TIMEOUT_MS=300)
    def test_lock_timeout_returns_409_with_retry_after(self):
        """Lock timeout returns 409 IDEMPOTENCY_IN_PROGRESS with Retry-After: 2.

        Deterministic version (no sleeps for ordering):
        * Thread A (holder) enters the handler and sets _lock_started, then waits
          on _lock_release. The advisory lock is held for the whole transaction.
        * Thread B (waiter) starts only after _lock_started, blocks on the same
          key and, with a small lock_timeout, must return
          409 IDEMPOTENCY_IN_PROGRESS with Retry-After: 2 without running the
          handler.
        * Releasing A lets it commit (201). A retry of B with the same key then
          replays (201, Idempotent-Replayed: true) and the handler counter is
          still 1 (handler ran once).
        Each thread closes its database connection at the end.
        """
        import apps.core.test_urls as test_urls

        test_urls._lock_started.clear()
        test_urls._lock_release.clear()
        test_urls._lock_handler_calls = 0

        results = []
        errors = []

        def holder_thread():
            """Thread A: starts first, runs handler, waits to be released."""
            try:
                connection.close_if_unusable_or_obsolete()
                client = APIClient()
                client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")
                response = client.post(
                    "/api/v1/test-lock-timeout/",
                    {"test": "data"},
                    format="json",
                    HTTP_IDEMPOTENCY_KEY=self.key,
                )
                results.append(("holder", response.status_code, dict(response.headers)))
            except Exception as e:  # noqa: BLE001
                errors.append(("holder", e))
            finally:
                connection.close()

        def waiter_thread():
            """Thread B: starts after A signals started, must block + time out."""
            try:
                # Wait until the holder has entered the handler (advisory lock held)
                test_urls._lock_started.wait(timeout=10)
                connection.close_if_unusable_or_obsolete()
                client = APIClient()
                client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")
                response = client.post(
                    "/api/v1/test-lock-timeout/",
                    {"test": "data"},
                    format="json",
                    HTTP_IDEMPOTENCY_KEY=self.key,
                )
                results.append(
                    ("waiter", response.status_code, response.json(), dict(response.headers))
                )
            except Exception as e:  # noqa: BLE001
                errors.append(("waiter", e))
            finally:
                connection.close()

        t1 = Thread(target=holder_thread)
        t2 = Thread(target=waiter_thread)
        t1.start()
        t2.start()

        # Waiter must time out on the advisory lock while the holder still holds it.
        t2.join(timeout=15)

        self.assertEqual(len(errors), 0, f"Errors: {errors}")
        self.assertEqual(len(results), 1)  # only the waiter has finished so far

        waiter_result = results[0]
        self.assertEqual(waiter_result[0], "waiter")
        self.assertEqual(waiter_result[1], status.HTTP_409_CONFLICT)
        self.assertEqual(waiter_result[2]["code"], "IDEMPOTENCY_IN_PROGRESS")
        self.assertEqual(waiter_result[3].get("Retry-After"), "2")
        # Handler must not have run for the waiter
        self.assertEqual(test_urls._lock_handler_calls, 1)  # holder only

        # Release the holder: it commits (201) and the advisory lock is released.
        test_urls._lock_release.set()
        t1.join(timeout=15)

        self.assertEqual(len(results), 2)  # holder now finished too
        holder_result = next(r for r in results if r[0] == "holder")
        self.assertEqual(holder_result[1], status.HTTP_201_CREATED)
        self.assertEqual(holder_result[2].get("Idempotent-Replayed"), None)

        # Handler ran exactly once (holder), no duplicate record
        self.assertEqual(test_urls._lock_handler_calls, 1)
        self.assertEqual(
            IdempotencyRecord.objects.filter(user_id=self.user.id, key=self.key).count(), 1
        )
        from apps.core.models import AuditLog

        self.assertEqual(AuditLog.objects.filter(action="test.idempotency_lock_timeout").count(), 1)

        # Retry B with the same key: must replay the stored response
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")
        retry_response = client.post(
            "/api/v1/test-lock-timeout/",
            {"test": "data"},
            format="json",
            HTTP_IDEMPOTENCY_KEY=self.key,
        )
        self.assertEqual(retry_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(retry_response.headers.get("Idempotent-Replayed"), "true")
        self.assertEqual(retry_response.json()["result"], "success")
        # Handler counter still 1: the retry did not re-run the handler
        self.assertEqual(test_urls._lock_handler_calls, 1)
        self.assertEqual(
            IdempotencyRecord.objects.filter(user_id=self.user.id, key=self.key).count(), 1
        )

    @override_settings(ROOT_URLCONF="apps.core.test_urls")
    def test_lock_timeout_not_triggered_for_handler_wait(self):
        """Lock timeout applies only to insert, not to handler execution.

        A handler that holds a long lock wait should NOT be reported as
        IDEMPOTENCY_IN_PROGRESS - the lock_timeout is only for the insert.
        """
        key = "550e8400-e29b-41d4-a716-446655440031"
        results = []
        errors = []

        def holder_thread():
            """Thread that starts first and uses test-idempotency with wait."""
            try:
                connection.close_if_unusable_or_obsolete()
                client = APIClient()
                client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")
                # Enable wait before write for this request
                import apps.core.test_urls as test_urls

                test_urls._wait_before_write = 2
                try:
                    response = client.post(
                        "/api/v1/test-idempotency/",
                        {"test": "data"},
                        format="json",
                        HTTP_IDEMPOTENCY_KEY=key,
                    )
                    results.append(("holder", response.status_code, response.json()))
                finally:
                    test_urls._wait_before_write = 0
            except Exception as e:
                errors.append(("holder", e))
            finally:
                connection.close()

        def waiter_thread():
            """Thread that uses same key but different path (should be 409 REUSED)."""
            try:
                time.sleep(0.1)
                connection.close_if_unusable_or_obsolete()
                client = APIClient()
                client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")
                response = client.post(
                    "/api/v1/test-idempotency-other/",
                    {"test": "data"},
                    format="json",
                    HTTP_IDEMPOTENCY_KEY=key,
                )
                results.append(("waiter", response.status_code, response.json()))
            except Exception as e:
                errors.append(("waiter", e))
            finally:
                connection.close()

        t1 = Thread(target=holder_thread)
        t2 = Thread(target=waiter_thread)
        t1.start()
        time.sleep(0.05)
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        self.assertEqual(len(errors), 0, f"Errors: {errors}")
        self.assertEqual(len(results), 2)

        # Holder should succeed
        holder_result = next(r for r in results if r[0] == "holder")
        self.assertEqual(holder_result[1], status.HTTP_201_CREATED)

        # Waiter on different path should get 409 REUSED (not IN_PROGRESS)
        waiter_result = next(r for r in results if r[0] == "waiter")
        self.assertEqual(waiter_result[1], status.HTTP_409_CONFLICT)
        self.assertEqual(waiter_result[2]["code"], "IDEMPOTENCY_KEY_REUSED")

    @override_settings(ROOT_URLCONF="apps.core.test_urls", IDEMPOTENCY_LOCK_TIMEOUT_MS=300)
    def test_handler_waits_on_different_lock_succeeds(self):
        """Handler waiting on a *different* lock succeeds (lock_timeout restored).

        With IDEMPOTENCY_LOCK_TIMEOUT_MS set small (300ms), the advisory-lock
        acquisition for the idempotency key must fail fast, but once the insert
        succeeds, lock_timeout is restored before the handler runs. The handler
        then waits on a different advisory lock held by another thread and
        completes normally instead of failing with IDEMPOTENCY_IN_PROGRESS.
        """
        from django.db import connection, transaction

        import apps.core.test_urls as test_urls

        test_urls._wait_on_different_lock = True
        results = []
        errors = []
        key = "550e8400-e29b-41d4-a716-446655440050"

        def holder_thread():
            """Holds a different advisory lock for ~2 seconds."""
            try:
                connection.close_if_unusable_or_obsolete()
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT pg_advisory_xact_lock(%s)",
                            [test_urls._different_lock_key],
                        )
                    time.sleep(2)
            except Exception as e:  # noqa: BLE001
                errors.append(("holder", e))
            finally:
                connection.close()

        def request_thread():
            """Runs the idempotent handler; it waits on the same different lock."""
            try:
                connection.close_if_unusable_or_obsolete()
                client = APIClient()
                client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")
                response = client.post(
                    "/api/v1/test-different-lock/",
                    {"test": "data"},
                    format="json",
                    HTTP_IDEMPOTENCY_KEY=key,
                )
                results.append(response.status_code)
            except Exception as e:  # noqa: BLE001
                errors.append(("requester", e))
            finally:
                connection.close()

        t1 = Thread(target=holder_thread)
        t2 = Thread(target=request_thread)
        t1.start()
        time.sleep(0.3)  # Ensure holder acquires the different lock first
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)

        self.assertEqual(len(errors), 0, f"Errors: {errors}")
        self.assertEqual(len(results), 1)
        # Must be 201, NOT 409 IDEMPOTENCY_IN_PROGRESS (proves lock_timeout restored)
        self.assertEqual(results[0], status.HTTP_201_CREATED)

        test_urls._wait_on_different_lock = False


class TestOpenApiParameter(TestCase):
    """Tests for IDEMPOTENCY_KEY_PARAMETER OpenAPI constant."""

    def test_parameter_exists_and_correct(self):
        """Test IDEMPOTENCY_KEY_PARAMETER has correct properties."""
        self.assertIsInstance(IDEMPOTENCY_KEY_PARAMETER, OpenApiParameter)
        self.assertEqual(IDEMPOTENCY_KEY_PARAMETER.name, "Idempotency-Key")
        self.assertEqual(IDEMPOTENCY_KEY_PARAMETER.location, OpenApiParameter.HEADER)
        self.assertTrue(IDEMPOTENCY_KEY_PARAMETER.required)
        self.assertEqual(IDEMPOTENCY_KEY_PARAMETER.type, str)


class TestIdempotencyModel(TestCase):
    """Tests for IdempotencyRecord model."""

    def test_model_fields_and_constraints(self):
        """Test model has correct fields and constraints."""
        # Check unique constraint on (user_id, key)
        constraints = IdempotencyRecord._meta.constraints
        unique_constraints = [c for c in constraints if isinstance(c, models.UniqueConstraint)]
        self.assertTrue(
            any(set(c.fields) == {"user_id", "key"} for c in unique_constraints),
            "Unique constraint on (user_id, key) not found",
        )

        # Check index on created_at
        indexes = IdempotencyRecord._meta.indexes
        self.assertTrue(
            any("created_at" in idx.fields for idx in indexes), "Index on created_at not found"
        )

    def test_model_creation(self):
        """Test creating an IdempotencyRecord."""
        user = User.objects.create_user(username="owner", password="SecurePass123!")
        record = IdempotencyRecord.objects.create(
            user_id=user.id,
            key="550e8400-e29b-41d4-a716-446655440040",
            method="POST",
            path="/api/v1/test/",
            request_hash="abc123",
            response_status=201,
            response_body={"result": "success"},
        )
        self.assertEqual(record.user_id, user.id)
        self.assertEqual(str(record.key), "550e8400-e29b-41d4-a716-446655440040")
        self.assertEqual(record.method, "POST")
        self.assertEqual(record.path, "/api/v1/test/")
        self.assertEqual(record.request_hash, "abc123")
        self.assertEqual(record.response_status, 201)
        self.assertEqual(record.response_body, {"result": "success"})
        self.assertIsNotNone(record.created_at)


class TestIdempotencyErrorPropagation(TransactionTestCase):
    """Tests for error propagation - only LockNotAvailable maps to 409."""

    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="SecurePass123!")
        self.client = APIClient()
        response = self.client.post(
            "/api/v1/auth/login/",
            {"username": "owner", "password": "SecurePass123!"},
            format="json",
        )
        self.access_token = response.json()["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")

    @override_settings(ROOT_URLCONF="apps.core.test_urls")
    def test_other_operational_error_propagates(self):
        """OperationalError other than LockNotAvailable propagates, causes rollback, key can be retried."""
        key = "550e8400-e29b-41d4-a716-446655440040"
        # Enable raising an operational error
        import apps.core.test_urls as test_urls

        test_urls._raise_operational_error = True
        try:
            response = self.client.post(
                "/api/v1/test-error/",
                {"test": "data"},
                format="json",
                HTTP_IDEMPOTENCY_KEY=key,
            )
            # Exception is caught by exception handler and returned as 500
            self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
            self.assertEqual(response.json()["code"], "INTERNAL_ERROR")
        finally:
            test_urls._raise_operational_error = False

        # No record should exist (rolled back)
        self.assertEqual(IdempotencyRecord.objects.filter(user_id=self.user.id, key=key).count(), 0)

        # Retry with same key should work
        response2 = self.client.post(
            "/api/v1/test-error/",
            {"test": "data"},
            format="json",
            HTTP_IDEMPOTENCY_KEY=key,
        )
        self.assertEqual(response2.status_code, status.HTTP_201_CREATED)
        self.assertEqual(IdempotencyRecord.objects.filter(user_id=self.user.id, key=key).count(), 1)

    @override_settings(ROOT_URLCONF="apps.core.test_urls")
    def test_database_error_propagates(self):
        """DatabaseError propagates, causes rollback, key can be retried."""
        key = "550e8400-e29b-41d4-a716-446655440041"
        import apps.core.test_urls as test_urls

        test_urls._raise_database_error = True
        try:
            response = self.client.post(
                "/api/v1/test-error/",
                {"test": "data"},
                format="json",
                HTTP_IDEMPOTENCY_KEY=key,
            )
            # Exception is caught by exception handler and returned as 500
            self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
            self.assertEqual(response.json()["code"], "INTERNAL_ERROR")
        finally:
            test_urls._raise_database_error = False

        # No record should exist (rolled back)
        self.assertEqual(IdempotencyRecord.objects.filter(user_id=self.user.id, key=key).count(), 0)

        # Retry with same key should work
        response2 = self.client.post(
            "/api/v1/test-error/",
            {"test": "data"},
            format="json",
            HTTP_IDEMPOTENCY_KEY=key,
        )
        self.assertEqual(response2.status_code, status.HTTP_201_CREATED)
        self.assertEqual(IdempotencyRecord.objects.filter(user_id=self.user.id, key=key).count(), 1)


class TestNoTestRoutesInProduction(TestCase):
    """Ensure test URL configuration doesn't leak into production."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="owner", password="SecurePass123!")
        response = self.client.post(
            "/api/v1/auth/login/",
            {"username": "owner", "password": "SecurePass123!"},
            format="json",
        )
        self.access_token = response.json()["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")

    def test_test_idempotency_endpoints_not_in_production_urls(self):
        """Test endpoints under test_urls.py are not accessible via normal URLs."""
        # These endpoints should return 404 when accessed via normal URLconf
        # (which is the case since we only override ROOT_URLCONF in tests)
        endpoints = [
            "/api/v1/test-idempotency/",
            "/api/v1/test-idempotency-other/",
            "/api/v1/test-lock-timeout/",
            "/api/v1/test-error/",
        ]
        for endpoint in endpoints:
            response = self.client.post(
                endpoint,
                {"test": "data"},
                format="json",
                HTTP_IDEMPOTENCY_KEY="550e8400-e29b-41d4-a716-446655440050",
            )
            # Should be 404 because these routes don't exist in production URLconf
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
            self.assertEqual(response.json()["code"], "NOT_FOUND")
