"""Tests for T-201 Companies and T-202 Product model (apps/catalog)."""

import uuid
from datetime import timedelta
from decimal import Decimal

from common.errors import GST_RATE_NOT_APPROVED
from common.validators import validate_gstin, validate_phone
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import DataError, IntegrityError
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.catalog.models import Company, PackUnit, Product
from apps.catalog.serializers import CompanySerializer
from apps.catalog.services import CompanyService
from apps.core.models import AuditLog, GstRate

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


class _ProductMixin:
    """Helper to build a minimally valid product."""

    def _company(self, name="Berger"):
        company = Company.objects.filter(name__iexact=name).first()
        if company is None:
            company = Company.objects.create(name=name)
        return company

    def _product(self, company=None, commit=True, **kwargs):
        if company is None:
            company = self._company()
        defaults = {
            "product_code": "BGR-WM-P1-20L",
            "company": company,
            "product_type": "Walmasta",
            "pack_size": Decimal("20"),
            "pack_unit": PackUnit.LTR,
        }
        defaults.update(kwargs)
        instance = Product(**defaults)
        if commit:
            instance.save()
        return instance


class TestProductRequiredFields(_ProductMixin, TestCase):
    """A product with only the five required fields must save."""

    def test_only_required_fields_save(self):
        product = self._product()
        self.assertEqual(product.product_code, "BGR-WM-P1-20L")
        self.assertEqual(product.qty_on_hand, Decimal("0"))
        self.assertTrue(product.track_stock)
        self.assertTrue(product.is_active)
        self.assertFalse(product.allow_fractional_qty)
        self.assertIsNone(product.selling_price)
        self.assertIsNone(product.gst_rate)
        self.assertIsNone(product.hsn_code)
        self.assertFalse(product.billing_ready)

    def test_optional_fields_can_be_left_blank(self):
        company = self._company()
        product = Product.objects.create(
            product_code="X-1",
            company=company,
            product_type="Walmasta",
            pack_size=Decimal("1"),
            pack_unit=PackUnit.PCS,
        )
        self.assertIsNone(product.category)
        self.assertIsNone(product.sub_type)
        self.assertIsNone(product.sub_sub_type)
        self.assertIsNone(product.description)
        self.assertIsNone(product.selling_price)
        self.assertIsNone(product.gst_rate)
        self.assertIsNone(product.hsn_code)
        self.assertIsNone(product.min_stock)
        self.assertIsNone(product.avg_buying_price)
        self.assertIsNone(product.last_buying_price)
        self.assertEqual(product.custom_fields, {})


class TestProductCode(_ProductMixin, TestCase):
    def test_code_uppercased_and_trimmed_on_save(self):
        product = self._product(product_code=" bgr-wm-p1-20l ")
        self.assertEqual(product.product_code, "BGR-WM-P1-20L")

    def test_code_uppercased_and_trimmed_on_full_clean(self):
        product = Product(
            product_code=" bgr-wm ",
            company=self._company(),
            product_type="T",
            pack_size=Decimal("1"),
            pack_unit=PackUnit.PCS,
        )
        product.full_clean()
        self.assertEqual(product.product_code, "BGR-WM")

    def test_code_with_space_rejected(self):
        product = self._product(product_code="BGR WM", commit=False)
        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_code_with_dot_rejected(self):
        product = self._product(product_code="BGR.WM", commit=False)
        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_code_with_underscore_rejected(self):
        product = self._product(product_code="BGR_WM", commit=False)
        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_41_character_code_rejected(self):
        product = self._product(product_code="A" * 41, commit=False)
        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_duplicate_code_differing_by_case_rejected_on_full_clean(self):
        self._product(product_code="BGR-WM-20L")
        product = self._product(product_code="bgr-wm-20l", commit=False)
        with self.assertRaises(ValidationError) as ctx:
            product.full_clean()
        self.assertIn("product_code", ctx.exception.error_dict)
        # Django does not propagate the code argument to dict-based field errors,
        # so DUPLICATE_PRODUCT_CODE is not available via error_dict[field][0].code
        # after clean()/full_clean(). The code is set at source but dropped on the
        # dict re-wrap; T-203 must map this case without relying on that code.
        self.assertIsNone(ctx.exception.error_dict["product_code"][0].code)

    def test_duplicate_code_differing_by_case_rejected_at_database_level(self):
        self._product(product_code="BGR-WM-20L")
        with self.assertRaises(IntegrityError):
            Product.objects.bulk_create(
                [
                    Product(
                        product_code="bgr-wm-20l",
                        company=Company.objects.create(name="Beta"),
                        product_type="Walmasta",
                        pack_size=Decimal("10"),
                        pack_unit=PackUnit.LTR,
                    )
                ]
            )

    def test_unique_code_differing_by_case_is_allowed(self):
        self._product(product_code="BGR-WM-20L")
        product = self._product(product_code="bgr-wm-20M", commit=False)
        product.full_clean()  # different code, should pass
        self.assertEqual(product.product_code, "BGR-WM-20M")


class TestProductLabels(_ProductMixin, TestCase):
    def test_label_canonicalisation_adopts_existing_spelling(self):
        self._product(product_code="A-1", product_type="Walmasta")
        product = self._product(product_code="A-2", product_type="WALMASTA ")
        self.assertEqual(product.product_type, "Walmasta")

    def test_sub_type_canonicalisation(self):
        self._product(product_code="A-1", sub_type="P1")
        product = self._product(product_code="A-2", sub_type=" p1 ")
        self.assertEqual(product.sub_type, "P1")

    def test_sub_sub_type_canonicalisation(self):
        self._product(product_code="A-1", sub_sub_type="Matt")
        product = self._product(product_code="A-2", sub_sub_type=" MATT ")
        self.assertEqual(product.sub_sub_type, "Matt")

    def test_category_canonicalisation(self):
        self._product(product_code="A-1", category="Interiors")
        product = self._product(product_code="A-2", category="  interiors  ")
        self.assertEqual(product.category, "Interiors")

    def test_new_label_spelling_is_kept_when_none_exists(self):
        product = self._product(product_code="A-1", product_type="NewPaint")
        self.assertEqual(product.product_type, "NewPaint")

    def test_sequential_canonicalisation_adopts_first_stored_spelling(self):
        # Labels repeat by design; the first stored spelling wins for subsequent
        # case-insensitive writers (see canonicalize_label limitation).
        self._product(product_code="S-1", product_type="Satin Finish")
        product = self._product(product_code="S-2", product_type="SATIN finish ")
        self.assertEqual(product.product_type, "Satin Finish")


class TestProductPackSizeAndUnit(_ProductMixin, TestCase):
    def test_pack_size_zero_rejected_on_model(self):
        product = self._product(pack_size=Decimal("0"), commit=False)
        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_pack_size_zero_rejected_at_database(self):
        with self.assertRaises(IntegrityError):
            Product.objects.bulk_create(
                [
                    Product(
                        product_code="X-1",
                        company=self._company(),
                        product_type="T",
                        pack_size=Decimal("0"),
                        pack_unit=PackUnit.PCS,
                    )
                ]
            )

    def test_pack_size_negative_rejected_on_model(self):
        product = self._product(pack_size=Decimal("-5"), commit=False)
        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_pack_size_negative_rejected_at_database(self):
        with self.assertRaises(IntegrityError):
            Product.objects.bulk_create(
                [
                    Product(
                        product_code="X-1",
                        company=self._company(),
                        product_type="T",
                        pack_size=Decimal("-1.5"),
                        pack_unit=PackUnit.PCS,
                    )
                ]
            )

    def test_unit_box_rejected_on_model(self):
        product = self._product(pack_unit="BOX", commit=False)
        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_unit_box_rejected_at_database(self):
        with self.assertRaises(IntegrityError):
            Product.objects.bulk_create(
                [
                    Product(
                        product_code="X-1",
                        company=self._company(),
                        product_type="T",
                        pack_size=Decimal("1"),
                        pack_unit="BOX",
                    )
                ]
            )


class TestProductPricesAndGst(_ProductMixin, TestCase):
    def setUp(self):
        GstRate.objects.create(rate=Decimal("18.00"), label="Standard", is_active=True)
        GstRate.objects.create(rate=Decimal("5.00"), label="Low", is_active=False)

    def test_selling_price_zero_rejected(self):
        product = self._product(selling_price=Decimal("0"), commit=False)
        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_selling_price_negative_rejected(self):
        product = self._product(selling_price=Decimal("-10"), commit=False)
        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_selling_price_null_accepted(self):
        product = self._product(selling_price=None)
        product.full_clean()
        self.assertIsNone(product.selling_price)

    def test_gst_rate_not_approved_rejected(self):
        product = self._product(gst_rate=Decimal("99.99"), commit=False)
        with self.assertRaises(ValidationError) as ctx:
            product.full_clean()
        # validate_gst_rate() raises a non-field error, so the code lives under
        # error_dict["__all__"], not under the gst_rate field key.
        self.assertEqual(ctx.exception.error_dict["__all__"][0].code, GST_RATE_NOT_APPROVED)

    def test_gst_rate_deactivated_rejected_when_set(self):
        product = self._product(gst_rate=Decimal("5.00"), commit=False)
        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_gst_rate_zero_seeded_accepted(self):
        product = self._product(gst_rate=Decimal("0.00"), commit=False)
        product.full_clean()  # 0.00 is the seeded active rate

    def test_gst_rate_150_rejected_at_database(self):
        with self.assertRaises(IntegrityError):
            Product.objects.bulk_create(
                [
                    Product(
                        product_code="X-1",
                        company=self._company(),
                        product_type="T",
                        pack_size=Decimal("1"),
                        pack_unit=PackUnit.PCS,
                        gst_rate=Decimal("150.00"),
                    )
                ]
            )

    def test_product_with_deactivated_rate_can_save_other_fields(self):
        GstRate.objects.create(rate=Decimal("12.00"), label="Twelve", is_active=True)
        product = self._product(product_code="R-1", gst_rate=Decimal("12.00"))
        GstRate.objects.filter(rate=Decimal("12.00")).update(is_active=False)
        product.selling_price = Decimal("100.00")
        product.save()
        product.refresh_from_db()
        self.assertEqual(product.selling_price, Decimal("100.00"))
        self.assertEqual(product.gst_rate, Decimal("12.00"))


class TestProductBillingReady(_ProductMixin, TestCase):
    def setUp(self):
        GstRate.objects.create(rate=Decimal("18.00"), label="Standard", is_active=True)

    def test_not_billing_ready_with_required_fields_only(self):
        product = self._product()
        self.assertFalse(product.billing_ready)

    def test_billing_ready_when_all_set(self):
        product = self._product(
            selling_price=Decimal("450.00"),
            gst_rate=Decimal("18.00"),
            hsn_code="3208",
        )
        self.assertTrue(product.billing_ready)

    def test_not_billing_ready_missing_each_part(self):
        self.assertFalse(
            self._product(
                product_code="N-1", selling_price=None, gst_rate=Decimal("18.00"), hsn_code="3208"
            ).billing_ready
        )
        self.assertFalse(
            self._product(
                product_code="N-2", selling_price=Decimal("450.00"), gst_rate=None, hsn_code="3208"
            ).billing_ready
        )
        self.assertFalse(
            self._product(
                product_code="N-3",
                selling_price=Decimal("450.00"),
                gst_rate=Decimal("18.00"),
                hsn_code="",
            ).billing_ready
        )
        product = self._product(
            product_code="N-4",
            selling_price=Decimal("0"),
            gst_rate=Decimal("18.00"),
            hsn_code="3208",
            commit=False,
        )
        self.assertFalse(product.billing_ready)

    def test_not_billing_ready_when_rate_deactivated_later(self):
        product = self._product(
            selling_price=Decimal("450.00"), gst_rate=Decimal("18.00"), hsn_code="3208"
        )
        self.assertTrue(product.billing_ready)
        GstRate.objects.filter(rate=Decimal("18.00")).update(is_active=False)
        self.assertFalse(product.billing_ready)

    def test_objects_billing_ready_and_not_billing_ready(self):
        ready = self._product(
            product_code="R-1",
            selling_price=Decimal("100"),
            gst_rate=Decimal("18.00"),
            hsn_code="3208",
        )
        not_ready_1 = self._product(product_code="R-2")  # no price/gst/hsn
        not_ready_2 = self._product(
            product_code="R-3", selling_price=Decimal("100"), hsn_code="3208"
        )  # no gst
        not_ready_3 = self._product(
            product_code="R-4", selling_price=Decimal("100"), gst_rate=Decimal("18.00")
        )  # no hsn

        ready_qs = Product.objects.billing_ready()
        self.assertEqual(set(ready_qs.values_list("product_code", flat=True)), {ready.product_code})

        not_ready_qs = Product.objects.not_billing_ready()
        codes = set(not_ready_qs.values_list("product_code", flat=True))
        self.assertIn(not_ready_1.product_code, codes)
        self.assertIn(not_ready_2.product_code, codes)
        self.assertIn(not_ready_3.product_code, codes)
        self.assertNotIn(ready.product_code, codes)


class TestProductHsn(_ProductMixin, TestCase):
    def test_hsn_invalid_chars_rejected(self):
        product = self._product(hsn_code="12ab", commit=False)
        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_hsn_too_short_rejected(self):
        product = self._product(hsn_code="1", commit=False)
        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_hsn_too_long_rejected(self):
        product = self._product(hsn_code="123456789", commit=False)
        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_hsn_valid_accepted(self):
        for hsn in ("3208", "32089090"):
            product = self._product(hsn_code=hsn, commit=False)
            product.full_clean()

    def test_hsn_empty_accepted(self):
        product = self._product(hsn_code="")
        self.assertEqual(product.hsn_code, "")


class TestProductMinStock(_ProductMixin, TestCase):
    def test_min_stock_negative_rejected(self):
        product = self._product(min_stock=Decimal("-1"), commit=False)
        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_min_stock_zero_accepted(self):
        product = self._product(min_stock=Decimal("0"))
        self.assertEqual(product.min_stock, Decimal("0"))


class TestProductStockFieldsReadOnly(_ProductMixin, TestCase):
    def test_stock_fields_are_not_editable(self):
        for field in ("qty_on_hand", "avg_buying_price", "last_buying_price"):
            self.assertFalse(Product._meta.get_field(field).editable)

    def test_full_clean_accepts_unchanged_stock_fields(self):
        product = self._product()
        product.full_clean()  # stock fields present but unchanged should not fail


class TestProductCustomFields(_ProductMixin, TestCase):
    def test_custom_fields_dict_accepted(self):
        product = self._product(custom_fields={"finish": "matt"})
        self.assertEqual(product.custom_fields, {"finish": "matt"})

    def test_custom_fields_list_rejected(self):
        product = self._product(custom_fields=["a", "b"], commit=False)
        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_custom_fields_string_rejected(self):
        product = self._product(custom_fields="not an object", commit=False)
        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_custom_fields_defaults_to_empty_dict(self):
        product = self._product()
        self.assertEqual(product.custom_fields, {})


class TestProductDisplayName(_ProductMixin, TestCase):
    def test_display_name_full(self):
        product = self._product(
            product_code="D-1",
            product_type="Walmasta",
            sub_type="P1",
            pack_size=Decimal("20.000"),
            pack_unit=PackUnit.LTR,
        )
        self.assertEqual(product.display_name(), "Walmasta P1 20 LTR")

    def test_display_name_with_company(self):
        product = self._product(
            product_code="D-2",
            product_type="Walmasta",
            sub_type="P1",
            pack_size=Decimal("20"),
            pack_unit=PackUnit.LTR,
        )
        self.assertEqual(product.display_name(include_company=True), "Berger Walmasta P1 20 LTR")

    def test_display_name_without_sub_types(self):
        product = self._product(
            product_code="D-3",
            product_type="Blade",
            pack_size=Decimal("1"),
            pack_unit=PackUnit.PCS,
        )
        self.assertEqual(product.display_name(), "Blade 1 PCS")

    def test_display_name_with_sub_sub_type(self):
        product = self._product(
            product_code="D-4",
            product_type="Sandpaper",
            sub_type="120",
            sub_sub_type="Waterproof",
            pack_size=Decimal("1"),
            pack_unit=PackUnit.PCS,
        )
        self.assertEqual(product.display_name(), "Sandpaper 120 Waterproof 1 PCS")


class TestProductDuplicateVariants(_ProductMixin, TestCase):
    def test_find_duplicate_variants_finds_same_variant_another_code(self):
        original = self._product(
            product_code="V-1",
            product_type="Walmasta",
            sub_type="P1",
            pack_size=Decimal("20"),
            pack_unit=PackUnit.LTR,
        )
        duplicate = self._product(
            product_code="V-2",
            product_type="walmasta ",
            sub_type=" p1 ",
            pack_size=Decimal("20"),
            pack_unit=PackUnit.LTR,
        )
        variants = original.find_duplicate_variants()
        self.assertIn(duplicate, variants)

    def test_find_duplicate_variants_ignores_different_size(self):
        original = self._product(
            product_code="V-1", pack_size=Decimal("20"), pack_unit=PackUnit.LTR
        )
        self._product(product_code="V-2", pack_size=Decimal("10"), pack_unit=PackUnit.LTR)
        variants = original.find_duplicate_variants()
        self.assertEqual(list(variants), [])

    def test_find_duplicate_variants_excludes_self(self):
        original = self._product(product_code="V-1")
        variants = original.find_duplicate_variants()
        self.assertEqual(list(variants), [])

    def test_saving_duplicate_variant_is_allowed(self):
        self._product(
            product_code="V-1",
            product_type="Walmasta",
            pack_size=Decimal("20"),
            pack_unit=PackUnit.LTR,
        )
        product = self._product(
            product_code="V-2",
            product_type="Walmasta",
            pack_size=Decimal("20"),
            pack_unit=PackUnit.LTR,
        )
        self.assertEqual(product.product_code, "V-2")

    def test_find_duplicate_variants_treats_20_and_20_000_as_same(self):
        # Decimal("20") and Decimal("20.000") are numerically equal; PostgreSQL
        # stores both as the same DECIMAL value, so they are one variant.
        original = self._product(
            product_code="E-1", pack_size=Decimal("20"), pack_unit=PackUnit.LTR
        )
        duplicate = self._product(
            product_code="E-2", pack_size=Decimal("20.000"), pack_unit=PackUnit.LTR
        )
        variants = original.find_duplicate_variants()
        self.assertIn(duplicate, variants)


class TestProductDeactivate(_ProductMixin, TestCase):
    def test_delete_raises(self):
        product = self._product()
        with self.assertRaises(ValidationError):
            product.delete()
        self.assertTrue(Product.objects.filter(pk=product.pk).exists())

    def test_queryset_delete_raises(self):
        product = self._product()
        with self.assertRaises(ValidationError):
            Product.objects.filter(pk=product.pk).delete()
        self.assertTrue(Product.objects.filter(pk=product.pk).exists())

    def test_deactivate_and_activate(self):
        product = self._product()
        from apps.catalog.services import activate_product, deactivate_product

        deactivate_product(product)
        product.refresh_from_db()
        self.assertFalse(product.is_active)

        activate_product(product)
        product.refresh_from_db()
        self.assertTrue(product.is_active)

    def test_bulk_create_still_works(self):
        products = [
            Product(
                product_code="B-1",
                company=self._company(),
                product_type="T",
                pack_size=Decimal("1"),
                pack_unit=PackUnit.PCS,
            ),
            Product(
                product_code="B-2",
                company=self._company(),
                product_type="T",
                pack_size=Decimal("1"),
                pack_unit=PackUnit.PCS,
            ),
        ]
        created = Product.objects.bulk_create(products)
        self.assertEqual(len(created), 2)


class TestProductDbConstraints(_ProductMixin, TestCase):
    """Database check constraints are enforced even when save()/full_clean() are bypassed."""

    def _make(self, **kwargs):
        defaults = {
            "product_code": "DB-1",
            "company": self._company(),
            "product_type": "T",
            "pack_size": Decimal("1"),
            "pack_unit": PackUnit.PCS,
        }
        defaults.update(kwargs)
        return Product(**defaults)

    def _expect_integrity_error(self, product: Product) -> None:
        with self.assertRaises(IntegrityError):
            Product.objects.bulk_create([product])

    def test_pack_size_zero_rejected_at_database(self):
        self._expect_integrity_error(self._make(pack_size=Decimal("0")))

    def test_pack_size_negative_rejected_at_database(self):
        self._expect_integrity_error(self._make(pack_size=Decimal("-1.5")))

    def test_pack_size_0_001_accepted_at_database(self):
        Product.objects.bulk_create([self._make(pack_size=Decimal("0.001"), product_code="DB-2")])

    def test_pack_unit_box_rejected_at_database(self):
        self._expect_integrity_error(self._make(pack_unit="BOX"))

    def test_selling_price_zero_rejected_at_database(self):
        self._expect_integrity_error(self._make(selling_price=Decimal("0")))

    def test_selling_price_negative_rejected_at_database(self):
        self._expect_integrity_error(self._make(selling_price=Decimal("-10")))

    def test_selling_price_0_01_accepted_at_database(self):
        Product.objects.bulk_create(
            [self._make(selling_price=Decimal("0.01"), product_code="DB-2")]
        )

    def test_min_stock_negative_rejected_at_database(self):
        self._expect_integrity_error(self._make(min_stock=Decimal("-1")))

    def test_min_stock_zero_accepted_at_database(self):
        Product.objects.bulk_create([self._make(min_stock=Decimal("0"), product_code="DB-2")])

    def test_avg_buying_price_negative_rejected_at_database(self):
        self._expect_integrity_error(self._make(avg_buying_price=Decimal("-1")))

    def test_avg_buying_price_zero_accepted_at_database(self):
        Product.objects.bulk_create(
            [self._make(avg_buying_price=Decimal("0"), product_code="DB-2")]
        )

    def test_last_buying_price_negative_rejected_at_database(self):
        self._expect_integrity_error(self._make(last_buying_price=Decimal("-1")))

    def test_last_buying_price_zero_accepted_at_database(self):
        Product.objects.bulk_create(
            [self._make(last_buying_price=Decimal("0"), product_code="DB-2")]
        )

    def test_gst_rate_negative_rejected_at_database(self):
        self._expect_integrity_error(self._make(gst_rate=Decimal("-0.01")))

    def test_gst_rate_above_100_rejected_at_database(self):
        self._expect_integrity_error(self._make(gst_rate=Decimal("100.01")))

    def test_gst_rate_zero_and_100_accepted_at_database(self):
        Product.objects.bulk_create([self._make(gst_rate=Decimal("0"), product_code="DB-2")])
        Product.objects.bulk_create([self._make(gst_rate=Decimal("100"), product_code="DB-3")])

    def test_product_code_empty_rejected_at_database(self):
        self._expect_integrity_error(self._make(product_code=""))

    def test_product_code_41_rejected_at_database(self):
        # The varchar(40) column rejects 41+ chars first (DataError); the
        # product_code_max_length_40 check constraint documents the limit for the
        # DB layer but is shadowed by the column type for this case.
        with self.assertRaises(DataError):
            Product.objects.bulk_create([self._make(product_code="A" * 41)])

    def test_product_code_lowercase_rejected_at_database(self):
        self._expect_integrity_error(self._make(product_code="db-1"))

    def test_product_code_untrimmed_rejected_at_database(self):
        self._expect_integrity_error(self._make(product_code=" DB-1 "))

    def test_product_code_length_40_accepted_at_database(self):
        Product.objects.bulk_create([self._make(product_code="A" * 40)])


class TestProductPrecision(_ProductMixin, TestCase):
    def test_decimal_field_max_digits_and_decimal_places(self):
        expected = {
            "pack_size": (10, 3),
            "selling_price": (12, 2),
            "gst_rate": (5, 2),
            "min_stock": (10, 3),
            "qty_on_hand": (10, 3),
            "avg_buying_price": (14, 4),
            "last_buying_price": (14, 4),
        }
        for field_name, (max_digits, decimal_places) in expected.items():
            field = Product._meta.get_field(field_name)
            with self.subTest(field=field_name):
                self.assertEqual(field.max_digits, max_digits)
                self.assertEqual(field.decimal_places, decimal_places)

    def test_decimal_values_round_trip_through_database(self):
        cases = [
            ("pack_size", Decimal("12.345"), Decimal("12.345")),
            ("selling_price", Decimal("99.99"), Decimal("99.99")),
            ("gst_rate", Decimal("18.00"), Decimal("18.00")),
            ("min_stock", Decimal("5.000"), Decimal("5.000")),
            ("qty_on_hand", Decimal("0"), Decimal("0")),
            ("avg_buying_price", Decimal("1234.5678"), Decimal("1234.5678")),
            ("last_buying_price", Decimal("1234.5678"), Decimal("1234.5678")),
        ]
        for i, (field_name, value, stored) in enumerate(cases):
            product = self._product(product_code=f"P-{i}", **{field_name: value})
            product.refresh_from_db()
            with self.subTest(field=field_name):
                self.assertEqual(getattr(product, field_name), stored)

    def test_too_many_decimals_are_rounded_not_rejected(self):
        # A value with more decimals than the field's decimal_places is rounded by
        # the database (DECIMAL) on save; Model.save() does not raise ValidationError.
        # The reloaded value shows the rounded result.
        product = self._product(product_code="R-1", pack_size=Decimal("1.2345"))
        product.refresh_from_db()
        self.assertEqual(product.pack_size, Decimal("1.235"))

        product = self._product(product_code="R-2", selling_price=Decimal("10.005"))
        product.refresh_from_db()
        self.assertEqual(product.selling_price, Decimal("10.01"))


class _FakeRequest:
    """Minimal request-like object carrying .user and .META for AuditService."""

    def __init__(self, user=None, remote_addr="127.0.0.1"):
        self.user = user
        self.META = {"REMOTE_ADDR": remote_addr}


def _audit_user(username=None):
    if username is None:
        username = f"audit_actor_{uuid.uuid4().hex[:8]}"
    return User.objects.create_user(username=username, password="SecurePass123!")


class TestCompanyService(TestCase):
    """Direct tests of CompanyService audit behaviour (T-201 restored contract)."""

    def setUp(self):
        self.CompanySerializer = CompanySerializer

    def _serializer(self, instance=None, data=None, partial=False):
        return self.CompanySerializer(instance, data=data, partial=partial)

    # a. create writes exactly one entry; after holds all seven fields; before empty.
    def test_create_writes_one_entry_with_all_seven_fields(self):
        user = _audit_user()
        request = _FakeRequest(user=user)
        serializer = self._serializer(
            data={
                "name": "Acme Paints",
                "phone": "+91 98765 43210",
                "address": "1 Main St",
                "gstin": "06AAAPC0000Q1ZS",
                "notes": "supplier",
                "is_local": True,
                "is_active": True,
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        before = AuditLog.objects.count()
        company = CompanyService.create_company(serializer, request)
        self.assertEqual(AuditLog.objects.count(), before + 1)
        entry = AuditLog.objects.filter(action="company.created").order_by("-id").first()
        self.assertEqual(entry.entity_type, "Company")
        self.assertEqual(entry.entity_id, str(company.id))
        self.assertIsNone(entry.before_json)
        after = entry.after_json
        for field in ("name", "phone", "address", "gstin", "notes", "is_local", "is_active"):
            self.assertIn(field, after)
        self.assertEqual(after["name"], "Acme Paints")
        self.assertEqual(after["phone"], "9876543210")
        self.assertEqual(after["gstin"], "06AAAPC0000Q1ZS")
        self.assertEqual(after["address"], "1 Main St")
        self.assertEqual(after["notes"], "supplier")
        self.assertTrue(after["is_local"])
        self.assertTrue(after["is_active"])
        self.assertEqual(entry.actor_id, user.id)
        self.assertEqual(entry.actor_username, user.username)
        self.assertEqual(entry.ip_address, "127.0.0.1")

    # b. update that changes only gstin writes one entry showing the gstin change.
    def test_update_only_gstin_writes_entry_showing_gstin_change(self):
        company = Company.objects.create(name="Beta Co", gstin="06AAAPC0000Q1ZS")
        user = _audit_user()
        request = _FakeRequest(user=user)
        serializer = self._serializer(company, data={"gstin": "27AAPFU0939R1ZB"}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        before = AuditLog.objects.count()
        CompanyService.update_company(company, serializer, request)
        self.assertEqual(AuditLog.objects.count(), before + 1)
        entry = AuditLog.objects.filter(action="company.updated").order_by("-id").first()
        self.assertEqual(entry.before_json["gstin"], "06AAAPC0000Q1ZS")
        self.assertEqual(entry.after_json["gstin"], "27AAPFU0939R1ZB")

    # c. same for only address, only is_local, only name, only phone, only notes.
    def test_update_each_field_writes_entry_with_before_after(self):
        cases = [
            ("address", "1 Main St", "2 Main St"),
            ("is_local", False, True),
            ("name", "Gamma Corp", "Gamma Corp Ltd"),
            ("phone", "9876543210", "9876543211"),
            ("notes", "old note", "new note"),
        ]
        for index, (field, old, new) in enumerate(cases):
            with self.subTest(field=field):
                company = Company.objects.create(name=f"Co-{index}-{field}")
                setattr(company, field, old)
                company.save()
                old_stored = getattr(company, field)
                user = _audit_user()
                request = _FakeRequest(user=user)
                serializer = self._serializer(company, data={field: new}, partial=True)
                self.assertTrue(serializer.is_valid(), serializer.errors)
                before_count = AuditLog.objects.count()
                CompanyService.update_company(company, serializer, request)
                self.assertEqual(AuditLog.objects.count(), before_count + 1)
                entry = AuditLog.objects.filter(action="company.updated").order_by("-id").first()
                company.refresh_from_db()
                new_stored = getattr(company, field)
                self.assertEqual(entry.before_json[field], old_stored)
                self.assertEqual(entry.after_json[field], new_stored)

    # d. an update that changes nothing writes NO entry.
    def test_update_no_changes_writes_no_entry(self):
        company = Company.objects.create(name="Delta", phone="9999999999")
        user = _audit_user()
        request = _FakeRequest(user=user)
        serializer = self._serializer(company, data={"name": "Delta", "phone": "9999999999"})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        before_count = AuditLog.objects.count()
        CompanyService.update_company(company, serializer, request)
        self.assertEqual(AuditLog.objects.count(), before_count)

    # e. before and after of company.updated contain all seven fields.
    def test_updated_entry_contains_all_seven_fields(self):
        company = Company.objects.create(
            name="Echo",
            phone="1111111111",
            address="1 St",
            gstin="06AAAPC0000Q1ZS",
            notes="old",
            is_local=False,
            is_active=True,
        )
        user = _audit_user()
        request = _FakeRequest(user=user)
        payload = {
            "name": "Echo",
            "phone": "2222222222",
            "address": "2 St",
            "gstin": "27AAPFU0939R1ZB",
            "notes": "new",
            "is_local": True,
            "is_active": False,
        }
        serializer = self._serializer(company, data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        CompanyService.update_company(company, serializer, request)
        entry = AuditLog.objects.filter(action="company.updated").order_by("-id").first()
        for field in ("name", "phone", "address", "gstin", "notes", "is_local", "is_active"):
            self.assertIn(field, entry.before_json, f"{field} missing from before_json")
            self.assertIn(field, entry.after_json, f"{field} missing from after_json")

    # f. deactivating an active company writes one deactivated entry.
    def test_deactivate_active_writes_one_deactivated_entry(self):
        company = Company.objects.create(name="Foxtrot", is_active=True)
        user = _audit_user()
        request = _FakeRequest(user=user)
        before_count = AuditLog.objects.filter(action="company.deactivated").count()
        CompanyService.deactivate_company(company, request)
        self.assertEqual(
            AuditLog.objects.filter(action="company.deactivated").count(), before_count + 1
        )
        entry = AuditLog.objects.filter(action="company.deactivated").order_by("-id").first()
        self.assertEqual(entry.before_json, {"is_active": True})
        self.assertEqual(entry.after_json, {"is_active": False})
        company.refresh_from_db()
        self.assertFalse(company.is_active)

    # g. deactivating an already inactive company writes NO entry.
    def test_deactivate_already_inactive_writes_no_entry(self):
        company = Company.objects.create(name="Golf", is_active=False)
        user = _audit_user()
        request = _FakeRequest(user=user)
        before_count = AuditLog.objects.filter(action="company.deactivated").count()
        result = CompanyService.deactivate_company(company, request)
        self.assertEqual(
            AuditLog.objects.filter(action="company.deactivated").count(), before_count
        )
        self.assertIs(result, company)
        self.assertFalse(result.is_active)

    # h. activating an inactive company writes one entry; activating an active one writes none.
    def test_activate_inactive_writes_one_activated_entry(self):
        company = Company.objects.create(name="Hotel", is_active=False)
        user = _audit_user()
        request = _FakeRequest(user=user)
        before_count = AuditLog.objects.filter(action="company.activated").count()
        CompanyService.activate_company(company, request)
        self.assertEqual(
            AuditLog.objects.filter(action="company.activated").count(), before_count + 1
        )
        entry = AuditLog.objects.filter(action="company.activated").order_by("-id").first()
        self.assertEqual(entry.before_json, {"is_active": False})
        self.assertEqual(entry.after_json, {"is_active": True})
        company.refresh_from_db()
        self.assertTrue(company.is_active)

    def test_activate_already_active_writes_no_entry(self):
        company = Company.objects.create(name="India", is_active=True)
        user = _audit_user()
        request = _FakeRequest(user=user)
        before_count = AuditLog.objects.filter(action="company.activated").count()
        CompanyService.activate_company(company, request)
        self.assertEqual(AuditLog.objects.filter(action="company.activated").count(), before_count)
        company.refresh_from_db()
        self.assertTrue(company.is_active)

    # i. the audit entry is written in the same transaction (rollback on failure).
    def test_audit_entry_in_same_transaction_rolls_back(self):
        company = Company.objects.create(name="Juniper", is_active=True)
        user = _audit_user()
        request = _FakeRequest(user=user)
        from django.db import transaction

        try:
            with transaction.atomic():
                CompanyService.deactivate_company(company, request)
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        company.refresh_from_db()
        self.assertTrue(company.is_active)
        self.assertEqual(AuditLog.objects.filter(action="company.deactivated").count(), 0)

    # j. actor and request address are recorded when a request is given; None is safe.
    def test_actor_and_ip_recorded_with_request_and_none_without(self):
        user = _audit_user()
        company = Company.objects.create(name="Kilo", is_active=True)
        request = _FakeRequest(user=user, remote_addr="10.0.0.5")
        CompanyService.deactivate_company(company, request)
        entry = AuditLog.objects.filter(action="company.deactivated").order_by("-id").first()
        self.assertEqual(entry.actor_id, user.id)
        self.assertEqual(entry.actor_username, user.username)
        self.assertEqual(entry.ip_address, "10.0.0.5")

        company2 = Company.objects.create(name="Lima", is_active=True)
        CompanyService.deactivate_company(company2, None)
        entry2 = AuditLog.objects.filter(action="company.deactivated").order_by("-id").first()
        self.assertIsNone(entry2.actor_id)
        self.assertIsNone(entry2.actor_username)
        self.assertEqual(entry2.ip_address, "127.0.0.1")


class TestProductActivateDeactivateNoAudit(TestCase):
    """deactivate_product / activate_product only flip is_active and write no audit entry."""

    def test_deactivate_product_flips_only_is_active_no_audit(self):
        from apps.catalog.services import deactivate_product

        product = Product.objects.create(
            product_code="Z-1",
            company=Company.objects.create(name="Milo"),
            product_type="T",
            pack_size=Decimal("1"),
            pack_unit=PackUnit.PCS,
        )
        before = AuditLog.objects.count()
        deactivate_product(product)
        product.refresh_from_db()
        self.assertFalse(product.is_active)
        self.assertEqual(AuditLog.objects.count(), before)

    def test_activate_product_flips_only_is_active_no_audit(self):
        from apps.catalog.services import activate_product

        product = Product.objects.create(
            product_code="Z-2",
            company=Company.objects.create(name="Nilo"),
            product_type="T",
            pack_size=Decimal("1"),
            pack_unit=PackUnit.PCS,
            is_active=False,
        )
        before = AuditLog.objects.count()
        activate_product(product)
        product.refresh_from_db()
        self.assertTrue(product.is_active)
        self.assertEqual(AuditLog.objects.count(), before)
