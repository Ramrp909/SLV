"""Tests for audit log functionality."""

import datetime
from decimal import Decimal
from unittest.mock import MagicMock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.core.models import AuditLog
from apps.core.services import AuditService

User = get_user_model()


class TestAuditLogModel(TestCase):
    """Tests for AuditLog model."""

    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="SecurePass123!")

    def test_audit_log_creation(self):
        """Test creating an audit log entry."""
        entry = AuditLog.objects.create(
            action="test.action",
            entity_type="TestModel",
            entity_id="123",
            summary="Test summary",
            before_json={"field": "old"},
            after_json={"field": "new"},
            ip_address="127.0.0.1",
            actor_id=self.user.id,
            actor_username="owner",
        )
        self.assertIsNotNone(entry.id)
        self.assertEqual(entry.action, "test.action")
        self.assertEqual(entry.entity_type, "TestModel")
        self.assertEqual(entry.entity_id, "123")
        self.assertEqual(entry.summary, "Test summary")
        self.assertEqual(entry.before_json, {"field": "old"})
        self.assertEqual(entry.after_json, {"field": "new"})
        self.assertEqual(entry.ip_address, "127.0.0.1")
        self.assertEqual(entry.actor_id, self.user.id)
        self.assertEqual(entry.actor_username, "owner")
        self.assertIsNotNone(entry.timestamp)

    def test_audit_log_nullable_fields(self):
        """Test audit log with nullable fields."""
        entry = AuditLog.objects.create(
            action="test.action",
            entity_type="TestModel",
            entity_id="123",
            summary="Test summary",
            before_json=None,
            after_json=None,
            ip_address=None,
            actor_id=None,
            actor_username=None,
        )
        self.assertIsNone(entry.before_json)
        self.assertIsNone(entry.after_json)
        self.assertIsNone(entry.ip_address)
        self.assertIsNone(entry.actor_id)
        self.assertIsNone(entry.actor_username)

    def test_audit_log_save_raises_on_existing(self):
        """Test that saving an existing audit log entry raises an error."""
        entry = AuditLog.objects.create(
            action="test.action",
            entity_type="TestModel",
            entity_id="123",
            summary="Test summary",
        )
        # Try to save again (should raise)
        entry.summary = "Modified"
        with self.assertRaises(ValidationError):
            entry.save()

    def test_audit_log_delete_raises(self):
        """Test that deleting an audit log entry raises an error."""
        entry = AuditLog.objects.create(
            action="test.action",
            entity_type="TestModel",
            entity_id="123",
            summary="Test summary",
        )
        with self.assertRaises(ValidationError):
            entry.delete()

    def test_audit_log_indexes_exist(self):
        """Test that required indexes exist on the model."""
        indexes = AuditLog._meta.indexes
        index_fields = [tuple(idx.fields) for idx in indexes]
        self.assertIn(("entity_type", "entity_id"), index_fields)
        # timestamp and action indexes are created via db_index=True on the fields
        timestamp_field = AuditLog._meta.get_field("timestamp")
        self.assertTrue(timestamp_field.db_index)
        action_field = AuditLog._meta.get_field("action")
        self.assertTrue(action_field.db_index)


class TestAuditLogQuerysetBlocking(TransactionTestCase):
    """Tests that queryset update, delete, bulk_update are blocked."""

    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="SecurePass123!")
        AuditLog.objects.create(
            action="test.action",
            entity_type="TestModel",
            entity_id="1",
            summary="Entry 1",
        )
        AuditLog.objects.create(
            action="test.action",
            entity_type="TestModel",
            entity_id="2",
            summary="Entry 2",
        )

    def test_queryset_update_blocked(self):
        """Test that queryset.update() is blocked."""
        with self.assertRaises(ValidationError):
            AuditLog.objects.filter(entity_id="1").update(summary="Modified")

    def test_queryset_delete_blocked(self):
        """Test that queryset.delete() is blocked."""
        with self.assertRaises(ValidationError):
            AuditLog.objects.filter(entity_id="1").delete()

    def test_queryset_bulk_update_blocked(self):
        """Test that queryset.bulk_update() is blocked."""
        entries = list(AuditLog.objects.all())
        entries[0].summary = "Modified"
        with self.assertRaises(ValidationError):
            AuditLog.objects.bulk_update(entries, ["summary"])


class TestAuditLogTrigger(TransactionTestCase):
    """Tests that PostgreSQL trigger blocks UPDATE and DELETE."""

    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="SecurePass123!")
        with transaction.atomic():
            self.entry = AuditLog.objects.create(
                action="test.action",
                entity_type="TestModel",
                entity_id="1",
                summary="Test summary",
            )
            self.entry_id = self.entry.id

    def test_raw_sql_update_blocked(self):
        """Test that raw SQL UPDATE is blocked by trigger."""
        with self.assertRaises(Exception) as cm:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE core_auditlog SET summary = 'Modified' WHERE id = %s",
                        [self.entry_id],
                    )
        # Check that the error is from the trigger
        self.assertIn("audit log is append-only", str(cm.exception).lower())

    def test_raw_sql_delete_blocked(self):
        """Test that raw SQL DELETE is blocked by trigger."""
        with self.assertRaises(Exception) as cm:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM core_auditlog WHERE id = %s",
                        [self.entry_id],
                    )
        self.assertIn("audit log is append-only", str(cm.exception).lower())

    def test_truncate_allowed(self):
        """Test that TRUNCATE is allowed (for test cleanup)."""
        # This should not raise - TRUNCATE is allowed
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("TRUNCATE TABLE core_auditlog RESTART IDENTITY CASCADE")
        # Verify table is empty
        self.assertEqual(AuditLog.objects.count(), 0)


class TestAuditService(TestCase):
    """Tests for AuditService.record."""

    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="SecurePass123!")

    def _make_request(self, ip="127.0.0.1", xff=None):
        """Create a mock request with given IP."""
        request = MagicMock()
        request.META = {"REMOTE_ADDR": ip}
        if xff:
            request.META["HTTP_X_FORWARDED_FOR"] = xff
        return request

    def test_record_basic(self):
        """Test basic audit record creation."""
        request = self._make_request("192.168.1.1")
        AuditService.record(
            action="test.action",
            entity_type="TestModel",
            entity_id="123",
            summary="Test summary",
            before={"field": "old"},
            after={"field": "new"},
            request=request,
            actor=self.user,
        )
        entry = AuditLog.objects.first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.action, "test.action")
        self.assertEqual(entry.entity_type, "TestModel")
        self.assertEqual(entry.entity_id, "123")
        self.assertEqual(entry.summary, "Test summary")
        self.assertEqual(entry.before_json, {"field": "old"})
        self.assertEqual(entry.after_json, {"field": "new"})
        self.assertEqual(entry.ip_address, "192.168.1.1")
        self.assertEqual(entry.actor_id, self.user.id)
        self.assertEqual(entry.actor_username, "owner")

    def test_record_without_actor(self):
        """Test record without actor."""
        request = self._make_request("10.0.0.1")
        AuditService.record(
            action="test.action",
            entity_type="TestModel",
            entity_id="123",
            summary="Test summary",
            request=request,
            actor=None,
        )
        entry = AuditLog.objects.first()
        self.assertIsNone(entry.actor_id)
        self.assertIsNone(entry.actor_username)

    def test_record_without_request(self):
        """Test record without request."""
        AuditService.record(
            action="test.action",
            entity_type="TestModel",
            entity_id="123",
            summary="Test summary",
            request=None,
            actor=self.user,
        )
        entry = AuditLog.objects.first()
        self.assertEqual(entry.ip_address, "127.0.0.1")  # default

    def test_record_uses_remote_addr_not_xff(self):
        """Test that REMOTE_ADDR is used, X-Forwarded-For is ignored."""
        request = self._make_request("192.168.1.1", xff="10.0.0.1, 172.16.0.1")
        AuditService.record(
            action="test.action",
            entity_type="TestModel",
            entity_id="123",
            summary="Test summary",
            request=request,
            actor=self.user,
        )
        entry = AuditLog.objects.first()
        self.assertEqual(entry.ip_address, "192.168.1.1")

    def test_record_decimal_serialized_as_string(self):
        """Test that Decimal values are serialized as strings."""
        request = self._make_request()
        AuditService.record(
            action="test.action",
            entity_type="TestModel",
            entity_id="123",
            summary="Test summary",
            before={"price": Decimal("123.45"), "nested": {"cost": Decimal("10.00")}},
            after={"price": Decimal("150.00")},
            request=request,
            actor=self.user,
        )
        entry = AuditLog.objects.first()
        self.assertEqual(entry.before_json["price"], "123.45")
        self.assertEqual(entry.before_json["nested"]["cost"], "10.00")
        self.assertEqual(entry.after_json["price"], "150.00")

    def test_record_date_serialized_as_string(self):
        """Test that date/datetime values are serialized as ISO strings."""
        request = self._make_request()
        test_date = datetime.date(2026, 11, 5)
        test_datetime = datetime.datetime(2026, 11, 5, 14, 30, 45, tzinfo=datetime.UTC)
        AuditService.record(
            action="test.action",
            entity_type="TestModel",
            entity_id="123",
            summary="Test summary",
            before={"created": test_date, "updated": test_datetime},
            after={},
            request=request,
            actor=self.user,
        )
        entry = AuditLog.objects.first()
        self.assertEqual(entry.before_json["created"], "2026-11-05")
        self.assertEqual(entry.before_json["updated"], "2026-11-05T14:30:45+00:00")

    def test_record_uuid_serialized_as_string(self):
        """Test that UUID values are serialized as strings."""
        import uuid

        request = self._make_request()
        test_uuid = uuid.uuid4()
        AuditService.record(
            action="test.action",
            entity_type="TestModel",
            entity_id="123",
            summary="Test summary",
            before={"id": test_uuid},
            after={},
            request=request,
            actor=self.user,
        )
        entry = AuditLog.objects.first()
        self.assertEqual(entry.before_json["id"], str(test_uuid))

    def test_record_redacts_password_fields(self):
        """Test that password fields are redacted."""
        request = self._make_request()
        AuditService.record(
            action="test.action",
            entity_type="TestModel",
            entity_id="123",
            summary="Test summary",
            before={
                "password": "secret123",
                "old_password": "oldsecret",
                "new_password": "newsecret",
                "token": "abc123",
                "access": "access_token",
                "refresh": "refresh_token",
                "secret": "mysecret",
                "authorization": "Bearer xyz",
            },
            after={},
            request=request,
            actor=self.user,
        )
        entry = AuditLog.objects.first()
        for key in [
            "password",
            "old_password",
            "new_password",
            "token",
            "access",
            "refresh",
            "secret",
            "authorization",
        ]:
            self.assertEqual(entry.before_json[key.lower()], "[REDACTED]")

    def test_record_redacts_case_insensitive(self):
        """Test that redaction is case-insensitive."""
        request = self._make_request()
        AuditService.record(
            action="test.action",
            entity_type="TestModel",
            entity_id="123",
            summary="Test summary",
            before={
                "PASSWORD": "secret",
                "Old_Password": "old",
                "New-Password": "new",
                "TOKEN": "token",
                "ACCESS": "access",
                "REFRESH": "refresh",
                "SECRET": "secret",
                "AUTHORIZATION": "auth",
            },
            after={},
            request=request,
            actor=self.user,
        )
        entry = AuditLog.objects.first()
        for key in entry.before_json:
            self.assertEqual(entry.before_json[key], "[REDACTED]")

    def test_record_redacts_nested(self):
        """Test that redaction works in nested dicts."""
        request = self._make_request()
        AuditService.record(
            action="test.action",
            entity_type="TestModel",
            entity_id="123",
            summary="Test summary",
            before={
                "user": {
                    "password": "secret",
                    "profile": {"token": "nested_token"},
                }
            },
            after={},
            request=request,
            actor=self.user,
        )
        entry = AuditLog.objects.first()
        self.assertEqual(entry.before_json["user"]["password"], "[REDACTED]")
        self.assertEqual(entry.before_json["user"]["profile"]["token"], "[REDACTED]")

    def test_record_redacts_in_lists(self):
        """Test that redaction works inside lists of dicts."""
        request = self._make_request()
        AuditService.record(
            action="test.action",
            entity_type="TestModel",
            entity_id="123",
            summary="Test summary",
            before={
                "users": [{"password": "pass1"}, {"password": "pass2"}],
                "tokens": [{"token": "token1"}, {"token": "token2"}],
            },
            after={},
            request=request,
            actor=self.user,
        )
        entry = AuditLog.objects.first()
        self.assertEqual(entry.before_json["users"][0]["password"], "[REDACTED]")
        self.assertEqual(entry.before_json["users"][1]["password"], "[REDACTED]")
        self.assertEqual(entry.before_json["tokens"][0]["token"], "[REDACTED]")
        self.assertEqual(entry.before_json["tokens"][1]["token"], "[REDACTED]")

    def test_record_summary_truncated_to_500(self):
        """Test that summary is truncated to 500 characters."""
        request = self._make_request()
        long_summary = "x" * 600
        AuditService.record(
            action="test.action",
            entity_type="TestModel",
            entity_id="123",
            summary=long_summary,
            request=request,
            actor=self.user,
        )
        entry = AuditLog.objects.first()
        self.assertEqual(len(entry.summary), 500)

    def test_record_actor_username_truncated_to_150(self):
        """Test that actor_username is truncated to 150 characters."""
        request = self._make_request()
        # Create a mock actor with long username
        from unittest.mock import MagicMock

        long_username = "u" * 200
        actor = MagicMock()
        actor.id = 999
        actor.username = long_username
        AuditService.record(
            action="test.action",
            entity_type="TestModel",
            entity_id="123",
            summary="Test",
            request=request,
            actor=actor,
        )
        entry = AuditLog.objects.first()
        self.assertEqual(len(entry.actor_username), 150)
        self.assertEqual(entry.actor_username, "u" * 150)

    def test_record_in_transaction_rolls_back(self):
        """Test that audit entry rolls back with failed transaction."""
        request = self._make_request()
        try:
            with transaction.atomic():
                AuditService.record(
                    action="test.action",
                    entity_type="TestModel",
                    entity_id="123",
                    summary="Test summary",
                    request=request,
                    actor=self.user,
                )
                raise Exception("Force rollback")
        except Exception:
            pass
        self.assertEqual(AuditLog.objects.count(), 0)


class TestAuditLogAPI(TestCase):
    """Tests for /api/v1/audit-log/ endpoint."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="owner", password="SecurePass123!")
        self.login()

        # Clear any existing audit entries using TRUNCATE (allowed by trigger)
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("TRUNCATE TABLE core_auditlog RESTART IDENTITY CASCADE")

        # Create test entries
        now = timezone.now()
        AuditLog.objects.create(
            action="auth.login",
            entity_type="User",
            entity_id="1",
            summary="User logged in",
            timestamp=now,
            ip_address="127.0.0.1",
            actor_id=1,
            actor_username="owner",
        )
        AuditLog.objects.create(
            action="settings.updated",
            entity_type="AppSettings",
            entity_id="1",
            summary="Settings updated",
            timestamp=now,
            ip_address="127.0.0.1",
            actor_id=1,
            actor_username="owner",
        )
        AuditLog.objects.create(
            action="gst_rate.created",
            entity_type="GstRate",
            entity_id="2",
            summary="GST rate created",
            timestamp=now,
            ip_address="127.0.0.1",
            actor_id=1,
            actor_username="owner",
        )

    def login(self):
        response = self.client.post(
            "/api/v1/auth/login/",
            {"username": "owner", "password": "SecurePass123!"},
            format="json",
        )
        self.access_token = response.json()["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")

    def test_get_audit_log_requires_auth(self):
        """Test that audit log endpoint requires authentication."""
        client = APIClient()
        response = client.get("/api/v1/audit-log/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json()["code"], "AUTHENTICATION_FAILED")

    def test_get_audit_log_returns_paginated(self):
        """Test that audit log returns paginated results."""
        response = self.client.get("/api/v1/audit-log/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("results", data)
        self.assertEqual(len(data["results"]), 3)

    def test_get_audit_log_newest_first(self):
        """Test that results are ordered newest first."""
        response = self.client.get("/api/v1/audit-log/")
        data = response.json()
        # All have same timestamp, but should be ordered by -timestamp, -id
        # Just verify ordering is consistent
        self.assertEqual(data["results"][0]["action"], "gst_rate.created")

    def test_filter_by_action(self):
        """Test filtering by action."""
        response = self.client.get("/api/v1/audit-log/?action=auth.login")
        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["action"], "auth.login")

    def test_filter_by_entity_type(self):
        """Test filtering by entity_type."""
        response = self.client.get("/api/v1/audit-log/?entity_type=AppSettings")
        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["entity_type"], "AppSettings")

    def test_filter_by_entity_id(self):
        """Test filtering by entity_id."""
        response = self.client.get("/api/v1/audit-log/?entity_id=2")
        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["entity_id"], "2")

    def test_filter_by_date_from(self):
        """Test filtering by date_from."""
        from_date = (timezone.now().date()).isoformat()
        response = self.client.get(f"/api/v1/audit-log/?date_from={from_date}")
        data = response.json()
        self.assertEqual(len(data["results"]), 3)

    def test_filter_by_date_to(self):
        """Test filtering by date_to."""
        to_date = (timezone.now().date()).isoformat()
        response = self.client.get(f"/api/v1/audit-log/?date_to={to_date}")
        data = response.json()
        self.assertEqual(len(data["results"]), 3)

    def test_search_on_summary(self):
        """Test search on summary field."""
        response = self.client.get("/api/v1/audit-log/?search=logged")
        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertIn("logged", data["results"][0]["summary"].lower())

    def test_post_returns_405(self):
        """Test that POST returns 405."""
        response = self.client.post("/api/v1/audit-log/", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(response.json()["code"], "METHOD_NOT_ALLOWED")

    def test_put_returns_405(self):
        """Test that PUT returns 405."""
        response = self.client.put("/api/v1/audit-log/", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(response.json()["code"], "METHOD_NOT_ALLOWED")

    def test_patch_returns_405(self):
        """Test that PATCH returns 405."""
        response = self.client.patch("/api/v1/audit-log/", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(response.json()["code"], "METHOD_NOT_ALLOWED")

    def test_delete_returns_405(self):
        """Test that DELETE returns 405."""
        response = self.client.delete("/api/v1/audit-log/")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(response.json()["code"], "METHOD_NOT_ALLOWED")


class TestWiredActions(TestCase):
    """Tests that wired actions create audit entries."""

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

    def test_login_success_creates_audit(self):
        """Test that successful login creates audit entry."""
        # Login already happened in setUp, check audit log
        entries = AuditLog.objects.filter(action="auth.login")
        self.assertEqual(entries.count(), 1)
        entry = entries.first()
        self.assertEqual(entry.action, "auth.login")
        self.assertEqual(entry.entity_type, "User")
        self.assertEqual(entry.actor_username, "owner")

    def test_login_failed_creates_audit(self):
        """Test that failed login creates audit entry (without password)."""
        client = APIClient()
        client.post(
            "/api/v1/auth/login/",
            {"username": "owner", "password": "WrongPass123!"},
            format="json",
        )
        entries = AuditLog.objects.filter(action="auth.login_failed")
        self.assertEqual(entries.count(), 1)
        entry = entries.first()
        self.assertEqual(entry.action, "auth.login_failed")
        self.assertEqual(entry.entity_type, "User")
        self.assertEqual(entry.entity_id, "owner")  # username attempted
        # Ensure password is not in summary or before/after
        self.assertNotIn("WrongPass123", entry.summary)
        self.assertIsNone(entry.before_json)
        self.assertIsNone(entry.after_json)

    def test_logout_creates_audit(self):
        """Test that logout creates audit entry."""
        client = APIClient()
        response = client.post(
            "/api/v1/auth/login/",
            {"username": "owner", "password": "SecurePass123!"},
            format="json",
        )
        access = response.json()["access"]
        refresh = response.cookies.get("refresh_token").value
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        client.cookies["refresh_token"] = refresh

        client.post("/api/v1/auth/logout/", format="json")

        entries = AuditLog.objects.filter(action="auth.logout")
        self.assertEqual(entries.count(), 1)

    def test_change_password_creates_audit(self):
        """Test that password change creates audit entry."""
        self.client.post(
            "/api/v1/auth/change-password/",
            {"old_password": "SecurePass123!", "new_password": "NewSecurePass456!"},
            format="json",
        )
        entries = AuditLog.objects.filter(action="auth.password_changed")
        self.assertEqual(entries.count(), 1)
        entry = entries.first()
        self.assertEqual(entry.action, "auth.password_changed")
        # Ensure passwords are redacted
        if entry.before_json:
            for v in entry.before_json.values():
                if isinstance(v, str):
                    self.assertNotEqual(v, "SecurePass123!")
                    self.assertNotEqual(v, "NewSecurePass456!")

    def test_settings_update_creates_audit(self):
        """Test that settings update creates audit entry with before/after."""
        self.client.put(
            "/api/v1/settings/",
            {"shop_name": "New Shop Name", "commission_default_percent": "15.00"},
            format="json",
        )
        entries = AuditLog.objects.filter(action="settings.updated")
        self.assertEqual(entries.count(), 1)
        entry = entries.first()
        self.assertEqual(entry.action, "settings.updated")
        self.assertIsNotNone(entry.before_json)
        self.assertIsNotNone(entry.after_json)
        self.assertEqual(entry.after_json.get("shop_name"), "New Shop Name")

    def test_gst_rate_create_creates_audit(self):
        """Test that GST rate creation creates audit entry."""
        self.client.post(
            "/api/v1/settings/gst-rates/",
            {"rate": "18.00", "label": "Standard"},
            format="json",
        )
        entries = AuditLog.objects.filter(action="gst_rate.created")
        self.assertEqual(entries.count(), 1)
        entry = entries.first()
        self.assertEqual(entry.action, "gst_rate.created")
        self.assertEqual(entry.entity_type, "GstRate")

    def test_gst_rate_update_creates_audit(self):
        """Test that GST rate update creates audit entry."""
        # First create
        create_resp = self.client.post(
            "/api/v1/settings/gst-rates/",
            {"rate": "12.00", "label": "Low"},
            format="json",
        )
        rate_id = create_resp.json()["id"]

        # Count audit entries before update
        before_count = AuditLog.objects.filter(action="gst_rate.updated").count()

        # Now update
        self.client.put(
            f"/api/v1/settings/gst-rates/{rate_id}/",
            {"label": "Low Rate", "is_active": False},
            format="json",
        )
        after_count = AuditLog.objects.filter(action="gst_rate.updated").count()
        self.assertEqual(after_count - before_count, 1)
        entry = AuditLog.objects.filter(action="gst_rate.updated").first()
        self.assertEqual(entry.action, "gst_rate.updated")
        self.assertEqual(entry.entity_id, str(rate_id))


class TestSpectacularAuditLog(TestCase):
    """Tests for drf-spectacular schema for audit log endpoint."""

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
            output = stderr.getvalue() or stdout.getvalue()
            self.fail(f"Spectacular validation failed: {output}")
