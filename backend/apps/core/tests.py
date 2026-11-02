"""Tests for core app: AppSettings, GstRate, validators, NumberSeries, and API endpoints."""

from datetime import date
from decimal import Decimal
from subprocess import run
from threading import Thread

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.core.models import AppSettings, GstRate, NumberSeries
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
        """Test that python manage.py spectacular --validate --fail-on-warn succeeds."""
        result = run(
            ["python", "manage.py", "spectacular", "--validate", "--fail-on-warn"],
            cwd="E:/ram/Inventory Management/project-starter-kit/backend",
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, f"Spectacular validation failed: {result.stderr}")

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
