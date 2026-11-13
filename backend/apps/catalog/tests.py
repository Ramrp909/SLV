"""Tests for T-201 Companies (apps/catalog)."""

from datetime import timedelta

from common.validators import validate_gstin, validate_phone
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.catalog.models import Company
from apps.core.models import AuditLog

User = get_user_model()

LIST_URL = "/api/v1/companies/"


def _auth_client():
    client = APIClient()
    user = User.objects.create_user(username="owner", password="SecurePass123!")
    client.force_authenticate(user)
    return client


def _company_payload(name="Berger", phone="+91 98765 43210", gstin="06AAAPC0000Q1ZS"):
    return {
        "name": name,
        "phone": phone,
        "address": "123 Main Street",
        "gstin": gstin,
        "notes": "Test supplier",
        "is_local": False,
        "is_active": True,
    }


class TestValidators(TestCase):
    """Shared GSTIN and phone validators (common/validators.py)."""

    def test_valid_gstin_accepted_and_uppercased(self):
        self.assertEqual(validate_gstin("06aaapc0000q1zs"), "06AAAPC0000Q1ZS")
        self.assertEqual(validate_gstin(" 06 AAAPC 0000 Q 1 Z S "), "06AAAPC0000Q1ZS")
        self.assertEqual(validate_gstin("27AAPFU0939R1ZB"), "27AAPFU0939R1ZB")

    def test_gstin_wrong_length_rejected(self):
        with self.assertRaises(ValidationError):
            validate_gstin("06AAAPC0000Q1Z")  # 14 chars
        with self.assertRaises(ValidationError):
            validate_gstin("06AAAPC0000Q1ZSS")  # 16 chars

    def test_gstin_wrong_pattern_rejected(self):
        with self.assertRaises(ValidationError):
            validate_gstin("06AAAPC0000Q11ZB")  # position 13 must be Z
        with self.assertRaises(ValidationError):
            validate_gstin("06AAAPC0000Q1Z*")  # invalid final character

    def test_gstin_empty_allowed(self):
        self.assertEqual(validate_gstin(None), None)
        self.assertEqual(validate_gstin(""), "")
        self.assertEqual(validate_gstin("   "), "")

    def test_phone_variants_accepted(self):
        self.assertEqual(validate_phone("+91 98765 43210"), "9876543210")
        self.assertEqual(validate_phone("09876543210"), "9876543210")
        self.assertEqual(validate_phone("9876543210"), "9876543210")
        self.assertEqual(validate_phone("+919876543210"), "9876543210")

    def test_phone_invalid_rejected(self):
        with self.assertRaises(ValidationError):
            validate_phone("123")
        with self.assertRaises(ValidationError):
            validate_phone("+91 98765 4321")  # 9 digits
        with self.assertRaises(ValidationError):
            validate_phone("919876543210")  # 12 digits without +
        with self.assertRaises(ValidationError):
            validate_phone("abcdefghij")

    def test_phone_empty_allowed(self):
        self.assertEqual(validate_phone(None), None)
        self.assertEqual(validate_phone(""), "")
        self.assertEqual(validate_phone("   "), "")


class TestCompanyCreate(TestCase):
    """POST /api/v1/companies/"""

    def setUp(self):
        self.client = _auth_client()

    def test_create_with_only_name(self):
        response = self.client.post(LIST_URL, {"name": "Berger"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        data = response.json()
        self.assertEqual(data["name"], "Berger")
        self.assertTrue(data["is_active"])
        self.assertFalse(data["is_local"])
        self.assertIsNone(data["gstin"])
        self.assertIsNone(data["phone"])
        self.assertIn("id", data)
        self.assertIn("created_at", data)
        self.assertIn("updated_at", data)

    def test_create_with_all_fields(self):
        response = self.client.post(LIST_URL, _company_payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        data = response.json()
        self.assertEqual(data["name"], "Berger")
        self.assertEqual(data["phone"], "9876543210")
        self.assertEqual(data["gstin"], "06AAAPC0000Q1ZS")
        self.assertEqual(data["address"], "123 Main Street")
        self.assertEqual(data["notes"], "Test supplier")
        self.assertFalse(data["is_local"])
        self.assertTrue(data["is_active"])

    def test_name_normalised_on_save(self):
        response = self.client.post(LIST_URL, {"name": " berger   paints  "}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        self.assertEqual(response.json()["name"], "berger paints")
        company = Company.objects.get(pk=response.json()["id"])
        self.assertEqual(company.name, "berger paints")

    def test_gstin_lowercase_uppercased_on_save(self):
        response = self.client.post(
            LIST_URL, {"name": "Alpha", "gstin": "27aapfu0939r1zb"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        self.assertEqual(response.json()["gstin"], "27AAPFU0939R1ZB")

    def test_duplicate_name_differing_by_case_rejected(self):
        self.client.post(LIST_URL, {"name": "Berger"}, format="json")
        response = self.client.post(LIST_URL, {"name": "berger"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["code"], "VALIDATION_ERROR")

    def test_duplicate_name_differing_by_spaces_rejected(self):
        self.client.post(LIST_URL, {"name": "Berger"}, format="json")
        response = self.client.post(LIST_URL, {"name": " Berger  "}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_name_database_level_bulk_create(self):
        Company.objects.create(name="Alpha")
        with self.assertRaises(IntegrityError):
            Company.objects.bulk_create([Company(name="alpha")])

    def test_invalid_gstin_rejected(self):
        response = self.client.post(LIST_URL, {"name": "Beta", "gstin": "INVALID"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_required_name_rejected(self):
        response = self.client.post(LIST_URL, {"phone": "9876543210"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TestCompanyList(TestCase):
    """GET /api/v1/companies/ - filters, search, ordering, pagination."""

    def setUp(self):
        self.client = _auth_client()
        Company.objects.create(name="Alpha Paints", is_active=True, is_local=False)
        Company.objects.create(name="beta traders", is_active=False, is_local=True)
        Company.objects.create(
            name="Gamma Co", gstin="27AAPFU0939R1ZB", phone="09876543210", is_active=True
        )

    def test_list_default_ordering_by_name(self):
        response = self.client.get(LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["count"], 3)
        names = [item["name"] for item in data["results"]]
        self.assertEqual(names, sorted(names, key=str.lower))
        self.assertEqual(names[0], "Alpha Paints")

    def test_is_active_filter(self):
        response = self.client.get(LIST_URL, {"is_active": "true"})
        self.assertEqual(response.json()["count"], 2)
        response = self.client.get(LIST_URL, {"is_active": "false"})
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["name"], "beta traders")

    def test_is_local_filter(self):
        response = self.client.get(LIST_URL, {"is_local": "true"})
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["name"], "beta traders")

    def test_search_name_gstin_phone(self):
        response = self.client.get(LIST_URL, {"search": "gamma"})
        self.assertEqual(response.json()["count"], 1)
        response = self.client.get(LIST_URL, {"search": "27AAPFU0939R1ZB"})
        self.assertEqual(response.json()["count"], 1)
        response = self.client.get(LIST_URL, {"search": "9876543210"})
        self.assertEqual(response.json()["count"], 1)
        response = self.client.get(LIST_URL, {"search": "nonexistent"})
        self.assertEqual(response.json()["count"], 0)

    def test_ordering_by_name_desc(self):
        response = self.client.get(LIST_URL, {"ordering": "-name"})
        names = [item["name"] for item in response.json()["results"]]
        self.assertEqual(names, ["Gamma Co", "beta traders", "Alpha Paints"])

    def test_ordering_by_created_at(self):
        now = timezone.now()
        for i, company in enumerate(Company.objects.order_by("name")):
            Company.objects.filter(pk=company.pk).update(created_at=now - timedelta(minutes=i))
        response = self.client.get(LIST_URL, {"ordering": "-created_at"})
        names = [item["name"] for item in response.json()["results"]]
        self.assertEqual(names, ["Alpha Paints", "beta traders", "Gamma Co"])

    def test_pagination(self):
        response = self.client.get(LIST_URL, {"page_size": 2, "page": 1})
        data = response.json()
        self.assertEqual(data["count"], 3)
        self.assertEqual(len(data["results"]), 2)
        self.assertIsNotNone(data["next"])
        response = self.client.get(LIST_URL, {"page": 2, "page_size": 2})
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertIsNone(response.json()["next"])


class TestCompanyDetail(TestCase):
    """GET/PUT/PATCH/DELETE /api/v1/companies/{id}/"""

    def setUp(self):
        self.client = _auth_client()
        self.company = Company.objects.create(name="Delta Corp", phone="9999999999")

    def test_get_detail(self):
        response = self.client.get(f"/api/v1/companies/{self.company.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "Delta Corp")

    def test_put_update(self):
        response = self.client.put(
            f"/api/v1/companies/{self.company.id}/",
            _company_payload(name="Delta Corp"),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["phone"], "9876543210")

    def test_patch_partial_update(self):
        response = self.client.patch(
            f"/api/v1/companies/{self.company.id}/",
            {"is_local": True, "notes": "updated"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["is_local"], True)
        self.assertEqual(response.json()["notes"], "updated")
        self.assertEqual(response.json()["name"], "Delta Corp")

    def test_patch_no_changes_writes_no_audit_entry(self):
        audit_before = AuditLog.objects.count()
        response = self.client.patch(f"/api/v1/companies/{self.company.id}/", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(AuditLog.objects.count(), audit_before)

    def test_update_duplicate_name_rejected(self):
        Company.objects.create(name="Other Co")
        response = self.client.put(
            f"/api/v1/companies/{self.company.id}/",
            {"name": "other co"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_get_detail_not_found(self):
        response = self.client.get("/api/v1/companies/999999/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json()["code"], "NOT_FOUND")

    def test_delete_not_allowed(self):
        response = self.client.delete(f"/api/v1/companies/{self.company.id}/")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(response.json()["code"], "METHOD_NOT_ALLOWED")
        # company still exists
        self.assertTrue(Company.objects.filter(pk=self.company.id).exists())


class TestCompanyDeactivateActivate(TestCase):
    """POST /api/v1/companies/{id}/deactivate/ and /activate/"""

    def setUp(self):
        self.client = _auth_client()
        self.company = Company.objects.create(name="Echo Ltd", is_active=True)

    def test_deactivate(self):
        response = self.client.post(f"/api/v1/companies/{self.company.id}/deactivate/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.json()["is_active"])
        self.company.refresh_from_db()
        self.assertFalse(self.company.is_active)

    def test_repeat_deactivate_returns_current_state_without_error(self):
        response1 = self.client.post(f"/api/v1/companies/{self.company.id}/deactivate/")
        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        from apps.core.models import AuditLog

        count_after_first = AuditLog.objects.filter(action="company.deactivated").count()
        response2 = self.client.post(f"/api/v1/companies/{self.company.id}/deactivate/")
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        self.assertFalse(response2.json()["is_active"])
        count_after_second = AuditLog.objects.filter(action="company.deactivated").count()
        self.assertEqual(count_after_second, count_after_first)

    def test_activate(self):
        self.client.post(f"/api/v1/companies/{self.company.id}/deactivate/")
        response = self.client.post(f"/api/v1/companies/{self.company.id}/activate/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["is_active"])

    def test_activate_already_active(self):
        response = self.client.post(f"/api/v1/companies/{self.company.id}/activate/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["is_active"])

    def test_not_found(self):
        response = self.client.post("/api/v1/companies/999999/deactivate/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TestCompanyAudit(TestCase):
    """Audit entries for company.create/update/deactivate/activate."""

    def setUp(self):
        self.client = _auth_client()
        from apps.core.models import AuditLog

        self.AuditLog = AuditLog

    def _audit_count(self, action):
        return self.AuditLog.objects.filter(action=action).count()

    def test_create_writes_one_company_created_entry(self):
        before = self._audit_count("company.created")
        response = self.client.post(LIST_URL, _company_payload(name="Foxtrot"), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self._audit_count("company.created"), before + 1)
        entry = self.AuditLog.objects.filter(action="company.created").order_by("-id").first()
        self.assertIsNone(entry.before_json)
        self.assertEqual(entry.after_json["name"], "Foxtrot")
        self.assertEqual(entry.entity_type, "Company")
        self.assertEqual(entry.entity_id, str(response.json()["id"]))

    def test_update_writes_one_company_updated_entry_with_before_after(self):
        company = Company.objects.create(name="Golf Inc", phone="1111111111")
        before = self._audit_count("company.updated")
        response = self.client.patch(
            f"/api/v1/companies/{company.id}/",
            {"phone": "2222222222", "notes": "new note"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._audit_count("company.updated"), before + 1)
        entry = self.AuditLog.objects.filter(action="company.updated").order_by("-id").first()
        self.assertEqual(entry.before_json["phone"], "1111111111")
        self.assertEqual(entry.before_json["notes"], None)
        self.assertEqual(entry.after_json["phone"], "2222222222")
        self.assertEqual(entry.after_json["notes"], "new note")

    def test_deactivate_writes_company_deactivated_entry(self):
        company = Company.objects.create(name="Hotel Pvt", is_active=True)
        before = self._audit_count("company.deactivated")
        self.client.post(f"/api/v1/companies/{company.id}/deactivate/")
        self.assertEqual(self._audit_count("company.deactivated"), before + 1)
        entry = self.AuditLog.objects.filter(action="company.deactivated").order_by("-id").first()
        self.assertEqual(entry.before_json, {"is_active": True})
        self.assertEqual(entry.after_json, {"is_active": False})

    def test_activate_writes_company_activated_entry(self):
        company = Company.objects.create(name="India Co", is_active=False)
        before = self._audit_count("company.activated")
        self.client.post(f"/api/v1/companies/{company.id}/activate/")
        self.assertEqual(self._audit_count("company.activated"), before + 1)
        entry = self.AuditLog.objects.filter(action="company.activated").order_by("-id").first()
        self.assertEqual(entry.before_json, {"is_active": False})
        self.assertEqual(entry.after_json, {"is_active": True})


class TestCompanyAuthentication(TestCase):
    """401 without a token for every endpoint."""

    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Juniper", is_active=True)

    def test_endpoints_require_authentication(self):
        cases = [
            ("GET", LIST_URL, None),
            ("POST", LIST_URL, {"name": "X"}),
            ("GET", f"/api/v1/companies/{self.company.id}/", None),
            ("PUT", f"/api/v1/companies/{self.company.id}/", {"name": "X"}),
            ("PATCH", f"/api/v1/companies/{self.company.id}/", {"name": "X"}),
            ("DELETE", f"/api/v1/companies/{self.company.id}/", None),
            ("POST", f"/api/v1/companies/{self.company.id}/deactivate/", None),
            ("POST", f"/api/v1/companies/{self.company.id}/activate/", None),
        ]
        for method, url, payload in cases:
            response = (
                getattr(self.client, method.lower())(url, payload, format="json")
                if payload
                else getattr(self.client, method.lower())(url)
            )
            self.assertEqual(
                response.status_code,
                status.HTTP_401_UNAUTHORIZED,
                f"{method} {url} returned {response.status_code}",
            )
