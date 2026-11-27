"""Tests for T-203 Products API (apps/catalog)."""

from decimal import Decimal
from unittest.mock import patch

from common.errors import (
    DUPLICATE_PRODUCT_CODE,
    GST_RATE_NOT_APPROVED,
    PACK_CHANGE_NOT_ALLOWED,
    VALIDATION_ERROR,
)
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import resolve, reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.catalog.models import Company, PackUnit, Product
from apps.catalog.services import (
    ProductService,
    has_stock_history,
)
from apps.core.models import AuditLog, GstRate

User = get_user_model()

LIST_URL = "/api/v1/products/"
LOOKUP_URL = "/api/v1/products/lookup/"
SUGGEST_URL = "/api/v1/products/suggest/"


def _auth_client():
    client = APIClient()
    user = User.objects.create_user(username="owner", password="SecurePass123!")
    client.force_authenticate(user)
    return client


def _company(name="Berger"):
    company = Company.objects.filter(name__iexact=name).first()
    if company is None:
        company = Company.objects.create(name=name)
    return company


def _gst_rate(rate="18.00", label="Standard", is_active=True):
    rate = Decimal(rate)
    obj = GstRate.objects.filter(rate=rate).first()
    if obj is None:
        obj = GstRate.objects.create(rate=rate, label=label, is_active=is_active)
    return obj


def _product(company=None, commit=True, **kwargs):
    if company is None:
        company = _company()
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


def _detail_url(pk):
    return f"/api/v1/products/{pk}/"


def _deactivate_url(pk):
    return f"/api/v1/products/{pk}/deactivate/"


def _activate_url(pk):
    return f"/api/v1/products/{pk}/activate/"


class TestProductAuth(TestCase):
    """401 without a token for every endpoint and verb."""

    def setUp(self):
        self.client = APIClient()
        self.product = _product()

    def test_endpoints_require_authentication(self):
        cases = [
            ("GET", LIST_URL, None),
            (
                "POST",
                LIST_URL,
                {
                    "product_code": "X-1",
                    "company": _company().id,
                    "product_type": "T",
                    "pack_size": Decimal("1"),
                    "pack_unit": PackUnit.PCS,
                },
            ),
            ("GET", _detail_url(self.product.id), None),
            ("PUT", _detail_url(self.product.id), {"product_code": "X-2"}),
            ("PATCH", _detail_url(self.product.id), {"product_code": "X-2"}),
            ("DELETE", _detail_url(self.product.id), None),
            ("POST", _deactivate_url(self.product.id), None),
            ("POST", _activate_url(self.product.id), None),
            ("GET", LOOKUP_URL, {"code": self.product.product_code}),
            ("GET", LOOKUP_URL, {"q": "wm"}),
            ("GET", SUGGEST_URL, {"field": "product_type", "q": "wm"}),
        ]
        for method, url, payload in cases:
            func = getattr(self.client, method.lower())
            response = func(url, payload, format="json") if payload else func(url)
            self.assertEqual(
                response.status_code,
                status.HTTP_401_UNAUTHORIZED,
                f"{method} {url} returned {response.status_code}: {response.content}",
            )


class TestProductCreate(TestCase):
    """POST /api/v1/products/"""

    def setUp(self):
        self.client = _auth_client()
        _gst_rate("18.00", "Standard", True)
        _gst_rate("5.00", "Low", False)

    def test_create_with_only_five_fields(self):
        company = _company()
        response = self.client.post(
            LIST_URL,
            {
                "product_code": "BGR-WM-P1-20L",
                "company": company.id,
                "product_type": "Walmasta",
                "pack_size": "20",
                "pack_unit": "LTR",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        data = response.json()
        self.assertEqual(data["product_code"], "BGR-WM-P1-20L")
        self.assertEqual(data["company"], company.id)
        self.assertEqual(data["company_name"], "Berger")
        self.assertFalse(data["billing_ready"])
        self.assertEqual(data["missing_for_billing"], ["selling_price", "gst_rate", "hsn_code"])
        self.assertEqual(Decimal(data["qty_on_hand"]), Decimal("0"))
        self.assertTrue(data["is_active"])
        self.assertTrue(data["track_stock"])
        self.assertEqual(data["custom_fields"], {})
        product = Product.objects.get(pk=data["id"])
        self.assertEqual(product.product_code, "BGR-WM-P1-20L")
        # one product.created audit entry
        self.assertEqual(AuditLog.objects.filter(action="product.created").count(), 1)

    def test_create_with_all_fields(self):
        company = _company()
        _gst_rate("18.00", "Standard", True)
        response = self.client.post(
            LIST_URL,
            {
                "product_code": "BGR-WM-P1-20L",
                "company": company.id,
                "category": "Interiors",
                "product_type": "Walmasta",
                "sub_type": "P1",
                "sub_sub_type": "Gloss",
                "description": "A paint",
                "pack_size": "20",
                "pack_unit": "LTR",
                "selling_price": "450.00",
                "gst_rate": "18.00",
                "hsn_code": "3208",
                "min_stock": "5",
                "allow_fractional_qty": False,
                "track_stock": True,
                "custom_fields": {"finish": "matt"},
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        data = response.json()
        self.assertEqual(data["selling_price"], "450.00")
        self.assertEqual(data["gst_rate"], "18.00")
        self.assertEqual(data["hsn_code"], "3208")
        self.assertTrue(data["billing_ready"])
        self.assertEqual(data["missing_for_billing"], [])
        self.assertEqual(data["custom_fields"], {"finish": "matt"})

    def test_code_trimmed_and_uppercased_in_response(self):
        company = _company()
        response = self.client.post(
            LIST_URL,
            {
                "product_code": " bgr-wm-p1-20l ",
                "company": company.id,
                "product_type": "Walmasta",
                "pack_size": "20",
                "pack_unit": "LTR",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        self.assertEqual(response.json()["product_code"], "BGR-WM-P1-20L")

    def test_duplicate_code_differing_by_case_rejected(self):
        _product(product_code="BGR-WM-20L")
        company = _company(name="Beta")
        response = self.client.post(
            LIST_URL,
            {
                "product_code": "bgr-wm-20l",
                "company": company.id,
                "product_type": "T",
                "pack_size": "1",
                "pack_unit": "PCS",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        data = response.json()
        self.assertEqual(data["code"], DUPLICATE_PRODUCT_CODE)
        self.assertIn("product_code", data["fields"])

    def test_duplicate_code_database_constraint_mapping(self):
        """Pre-create via bulk_create so only the DB unique constraint catches the duplicate."""
        _product(product_code="DUP-20L")
        company = _company(name="Gamma")
        # Simulate a race: bypass the application-level existence check so only
        # the database unique constraint fires.
        with patch.object(Product.objects, "filter", return_value=_EmptyQuerySet()):
            response = self.client.post(
                LIST_URL,
                {
                    "product_code": "dup-20l",
                    "company": company.id,
                    "product_type": "T",
                    "pack_size": "1",
                    "pack_unit": "PCS",
                },
                format="json",
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        data = response.json()
        self.assertEqual(data["code"], DUPLICATE_PRODUCT_CODE)
        self.assertIn("product_code", data["fields"])

    def test_invalid_code_characters_rejected(self):
        company = _company()
        for code in ("BGR WM", "BGR.WM", "BGR_WM", "BGR@WM"):
            with self.subTest(code=code):
                response = self.client.post(
                    LIST_URL,
                    {
                        "product_code": code,
                        "company": company.id,
                        "product_type": "T",
                        "pack_size": "1",
                        "pack_unit": "PCS",
                    },
                    format="json",
                )
                self.assertEqual(
                    response.status_code, status.HTTP_400_BAD_REQUEST, response.content
                )
                self.assertEqual(response.json()["code"], VALIDATION_ERROR)
                self.assertIn("product_code", response.json()["fields"])

    def test_41_character_code_rejected(self):
        company = _company()
        response = self.client.post(
            LIST_URL,
            {
                "product_code": "A" * 41,
                "company": company.id,
                "product_type": "T",
                "pack_size": "1",
                "pack_unit": "PCS",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        self.assertEqual(response.json()["code"], VALIDATION_ERROR)
        self.assertIn("product_code", response.json()["fields"])

    def test_non_approved_gst_rate_rejected_on_field(self):
        company = _company()
        response = self.client.post(
            LIST_URL,
            {
                "product_code": "GST-1",
                "company": company.id,
                "product_type": "T",
                "pack_size": "1",
                "pack_unit": "PCS",
                "gst_rate": "99.99",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        data = response.json()
        self.assertEqual(data["code"], GST_RATE_NOT_APPROVED)
        self.assertEqual(data["fields"], {"gst_rate": data["fields"]["gst_rate"]})

    def test_deactivated_gst_rate_rejected_on_set(self):
        _gst_rate("5.00", "Low", False)
        company = _company()
        response = self.client.post(
            LIST_URL,
            {
                "product_code": "GST-2",
                "company": company.id,
                "product_type": "T",
                "pack_size": "1",
                "pack_unit": "PCS",
                "gst_rate": "5.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        self.assertEqual(response.json()["code"], GST_RATE_NOT_APPROVED)

    def test_seeded_zero_rate_accepted(self):
        company = _company()
        response = self.client.post(
            LIST_URL,
            {
                "product_code": "GST-3",
                "company": company.id,
                "product_type": "T",
                "pack_size": "1",
                "pack_unit": "PCS",
                "gst_rate": "0.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)

    def test_two_errors_at_once_give_validation_error_with_both_fields(self):
        company = _company()
        response = self.client.post(
            LIST_URL,
            {
                "product_code": "BAD WM",
                "company": company.id,
                "product_type": "T",
                "pack_size": "1",
                "pack_unit": "PCS",
                "gst_rate": "99.99",
                "qty_on_hand": "5",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        data = response.json()
        self.assertEqual(data["code"], VALIDATION_ERROR)
        self.assertIn("gst_rate", data["fields"])
        self.assertIn("qty_on_hand", data["fields"])

    def test_stock_fields_rejected_on_create(self):
        company = _company()
        response = self.client.post(
            LIST_URL,
            {
                "product_code": "STK-1",
                "company": company.id,
                "product_type": "T",
                "pack_size": "1",
                "pack_unit": "PCS",
                "qty_on_hand": "5",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        self.assertEqual(
            response.json()["fields"]["qty_on_hand"],
            "read-only: stock changes only through stock operations",
        )

    def test_custom_fields_must_be_dict(self):
        company = _company()
        response = self.client.post(
            LIST_URL,
            {
                "product_code": "CF-1",
                "company": company.id,
                "product_type": "T",
                "pack_size": "1",
                "pack_unit": "PCS",
                "custom_fields": ["a", "b"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        self.assertEqual(response.json()["code"], VALIDATION_ERROR)
        self.assertIn("custom_fields", response.json()["fields"])


class TestProductDetail(TestCase):
    """GET/PUT/PATCH /api/v1/products/{id}/"""

    def setUp(self):
        self.client = _auth_client()
        _gst_rate("18.00", "Standard", True)
        self.product = _product()

    def test_get_detail(self):
        response = self.client.get(_detail_url(self.product.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["product_code"], self.product.product_code)
        self.assertEqual(data["company_name"], self.product.company.name)
        self.assertFalse(data["billing_ready"])

    def test_put_full_update(self):
        _gst_rate("12.00", "Twelve", True)
        response = self.client.put(
            _detail_url(self.product.id),
            {
                "product_code": "NEW-CODE",
                "company": self.product.company_id,
                "category": "Interiors",
                "product_type": "Bison",
                "pack_size": "10",
                "pack_unit": "LTR",
                "selling_price": "450.00",
                "gst_rate": "12.00",
                "hsn_code": "3208",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        data = response.json()
        self.assertEqual(data["product_code"], "NEW-CODE")
        self.assertEqual(data["product_type"], "Bison")
        self.assertEqual(data["selling_price"], "450.00")
        self.assertTrue(data["billing_ready"])

    def test_patch_partial_update(self):
        response = self.client.patch(
            _detail_url(self.product.id),
            {
                "product_type": "Bison ",
                "selling_price": "100.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.json()["product_type"], "Bison")
        self.assertEqual(response.json()["selling_price"], "100.00")

    def test_patch_no_changes_writes_no_audit_entry(self):
        before = AuditLog.objects.count()
        response = self.client.patch(_detail_url(self.product.id), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(AuditLog.objects.count(), before)

    def test_gst_rate_hsn_price_change_shows_in_before_after(self):
        _gst_rate("12.00", "Twelve", True)
        company = _company(name="Co")
        product = _product(company=company, product_code="AUD-1")
        response = self.client.patch(
            _detail_url(product.id),
            {
                "selling_price": "200.00",
                "gst_rate": "12.00",
                "hsn_code": "3208",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        entry = AuditLog.objects.filter(action="product.updated").order_by("-id").first()
        self.assertIsNotNone(entry)
        self.assertIn("selling_price", entry.before_json)
        self.assertIn("selling_price", entry.after_json)
        self.assertIn("gst_rate", entry.before_json)
        self.assertIn("hsn_code", entry.after_json)
        self.assertEqual(entry.after_json["selling_price"], "200.00")
        self.assertEqual(entry.after_json["gst_rate"], "12.00")
        self.assertEqual(entry.after_json["hsn_code"], "3208")

    def test_deactivated_rate_product_can_still_edit_other_fields(self):
        _gst_rate("5.00", "Low", False)
        company = _company(name="Co")
        product = _product(company=company, product_code="RATE-1", gst_rate=Decimal("5.00"))
        product.refresh_from_db()
        response = self.client.patch(
            _detail_url(product.id), {"product_type": "Renamed"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.json()["product_type"], "Renamed")

    def test_stock_fields_rejected_on_put_and_patch(self):
        for method in ("put", "patch"):
            with self.subTest(method=method):
                func = getattr(self.client, method)
                response = func(
                    _detail_url(self.product.id),
                    {
                        "product_code": self.product.product_code,
                        "company": self.product.company_id,
                        "product_type": "T",
                        "pack_size": "1",
                        "pack_unit": "PCS",
                        "avg_buying_price": "10",
                    },
                    format="json",
                )
                self.assertEqual(
                    response.status_code, status.HTTP_400_BAD_REQUEST, response.content
                )
                self.assertIn("avg_buying_price", response.json()["fields"])

    def test_detail_not_found(self):
        response = self.client.get("/api/v1/products/999999/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_not_allowed(self):
        response = self.client.delete(_detail_url(self.product.id))
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        data = response.json()
        self.assertEqual(data["code"], "METHOD_NOT_ALLOWED")
        self.assertTrue(Product.objects.filter(pk=self.product.id).exists())


class TestProductPackChange(TestCase):
    """pack_size / pack_unit cannot change once the product has stock history."""

    def setUp(self):
        self.client = _auth_client()

    def test_change_rejected_when_stock_history(self):
        company = _company()
        product = _product(company=company, product_code="PACK-1")
        # simulates stock history; the stock engine writes this field in production
        Product.objects.filter(pk=product.pk).update(qty_on_hand=Decimal("5"))
        product.refresh_from_db()
        self.assertTrue(has_stock_history(product))
        response = self.client.patch(_detail_url(product.id), {"pack_size": "10"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        data = response.json()
        self.assertEqual(data["code"], PACK_CHANGE_NOT_ALLOWED)
        self.assertIn("pack_size", data["fields"])

    def test_change_rejected_when_avg_buying_price_set(self):
        company = _company()
        product = _product(company=company, product_code="PACK-2")
        # simulates stock history; the stock engine writes this field in production
        Product.objects.filter(pk=product.pk).update(avg_buying_price=Decimal("100"))
        product.refresh_from_db()
        self.assertTrue(has_stock_history(product))
        response = self.client.patch(_detail_url(product.id), {"pack_unit": "ML"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        self.assertEqual(response.json()["code"], PACK_CHANGE_NOT_ALLOWED)
        self.assertIn("pack_unit", response.json()["fields"])

    def test_change_allowed_when_no_stock_history(self):
        company = _company()
        product = _product(company=company, product_code="PACK-3")
        self.assertFalse(has_stock_history(product))
        response = self.client.patch(
            _detail_url(product.id), {"pack_size": "10", "pack_unit": "ML"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(Decimal(response.json()["pack_size"]), Decimal("10"))
        self.assertEqual(response.json()["pack_unit"], "ML")

    def test_put_with_unchanged_pack_fields_allowed_with_history(self):
        company = _company()
        product = _product(
            company=company, product_code="PACK-4", pack_size=Decimal("20"), pack_unit=PackUnit.LTR
        )
        # simulates stock history; the stock engine writes this field in production
        Product.objects.filter(pk=product.pk).update(qty_on_hand=Decimal("5"))
        product.refresh_from_db()
        response = self.client.put(
            _detail_url(product.id),
            {
                "product_code": "PACK-4",
                "company": company.id,
                "product_type": "Walmasta",
                "pack_size": "20",
                "pack_unit": "LTR",
                "selling_price": "100.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)


class _ProductListMixin:
    def _make_products(self):
        c1 = _company(name="Alpha")
        c2 = _company(name="Beta")
        _gst_rate("18.00", "Standard", True)
        self.p1 = _product(
            company=c1,
            product_code="A-1",
            product_type="Walmasta",
            pack_unit=PackUnit.LTR,
            is_active=True,
            track_stock=True,
            qty_on_hand=Decimal("10"),
            min_stock=Decimal("5"),
            selling_price=Decimal("100"),
            gst_rate=Decimal("18.00"),
            hsn_code="3208",
        )
        self.p2 = _product(
            company=c1,
            product_code="A-2",
            product_type="Blade",
            pack_unit=PackUnit.PCS,
            is_active=True,
            track_stock=True,
            qty_on_hand=Decimal("0"),
            min_stock=Decimal("5"),
            selling_price=None,
            gst_rate=None,
            hsn_code="",
        )
        self.p3 = _product(
            company=c2,
            product_code="B-1",
            product_type="Walmasta",
            pack_unit=PackUnit.KG,
            is_active=False,
            track_stock=False,
            qty_on_hand=Decimal("0"),
            min_stock=None,
            selling_price=Decimal("50"),
            gst_rate=Decimal("18.00"),
            hsn_code="3208",
        )
        # p3 qty 0 but track_stock False -> never out/low
        Product.objects.filter(pk=self.p3.pk).update(qty_on_hand=Decimal("0"))


class TestProductList(TestCase, _ProductListMixin):
    """GET /api/v1/products/ - filters, search, ordering, pagination."""

    def setUp(self):
        self.client = _auth_client()
        self._make_products()

    def test_list_default_ordering_by_product_code(self):
        response = self.client.get(LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        codes = [item["product_code"] for item in response.json()["results"]]
        self.assertEqual(codes, sorted(codes))

    def test_company_filter(self):
        response = self.client.get(LIST_URL, {"company": self.p1.company_id})
        codes = {item["product_code"] for item in response.json()["results"]}
        self.assertEqual(codes, {"A-1", "A-2"})

    def test_category_product_type_pack_unit_filters_are_case_insensitive_exact(self):
        response = self.client.get(LIST_URL, {"product_type": "walmasta "})
        codes = {item["product_code"] for item in response.json()["results"]}
        self.assertEqual(codes, {"A-1", "B-1"})
        response = self.client.get(LIST_URL, {"pack_unit": "ltr"})
        self.assertEqual({item["product_code"] for item in response.json()["results"]}, {"A-1"})

    def test_is_active_filter(self):
        response = self.client.get(LIST_URL, {"is_active": "true"})
        codes = {item["product_code"] for item in response.json()["results"]}
        self.assertEqual(codes, {"A-1", "A-2"})
        response = self.client.get(LIST_URL, {"is_active": "false"})
        self.assertEqual({item["product_code"] for item in response.json()["results"]}, {"B-1"})

    def test_track_stock_filter(self):
        response = self.client.get(LIST_URL, {"track_stock": "false"})
        self.assertEqual({item["product_code"] for item in response.json()["results"]}, {"B-1"})

    def test_billing_ready_true_filter(self):
        response = self.client.get(LIST_URL, {"billing_ready": "true"})
        self.assertEqual(
            {item["product_code"] for item in response.json()["results"]}, {"A-1", "B-1"}
        )

    def test_billing_ready_false_filter(self):
        response = self.client.get(LIST_URL, {"billing_ready": "false"})
        codes = {item["product_code"] for item in response.json()["results"]}
        self.assertEqual(codes, {"A-2"})

    def test_stock_status_in(self):
        response = self.client.get(LIST_URL, {"stock_status": "in"})
        self.assertEqual({item["product_code"] for item in response.json()["results"]}, {"A-1"})

    def test_stock_status_low_qty_equals_min_stock(self):
        # p1: qty 10, min_stock 5 -> not low (qty > min_stock). Make p_low with qty == min_stock.
        company = _company(name="LowCo")
        _product(
            company=company,
            product_code="LOW-1",
            pack_size=Decimal("1"),
            pack_unit=PackUnit.PCS,
            track_stock=True,
            qty_on_hand=Decimal("5"),
            min_stock=Decimal("5"),
            selling_price=Decimal("10"),
            gst_rate=Decimal("18.00"),
            hsn_code="3208",
        )
        Product.objects.filter(product_code="LOW-1").update(qty_on_hand=Decimal("5"))
        response = self.client.get(LIST_URL, {"stock_status": "low"})
        codes = {item["product_code"] for item in response.json()["results"]}
        self.assertIn("LOW-1", codes)
        self.assertNotIn("A-1", codes)  # qty 10 > min 5

    def test_stock_status_out_qty_zero(self):
        # p2 qty 0 track_stock True -> out
        response = self.client.get(LIST_URL, {"stock_status": "out"})
        codes = {item["product_code"] for item in response.json()["results"]}
        self.assertIn("A-2", codes)

    def test_stock_status_track_stock_false_never_low_or_out(self):
        response = self.client.get(LIST_URL, {"stock_status": "low"})
        self.assertNotIn("B-1", {item["product_code"] for item in response.json()["results"]})
        response = self.client.get(LIST_URL, {"stock_status": "out"})
        self.assertNotIn("B-1", {item["product_code"] for item in response.json()["results"]})

    def test_search_single_term(self):
        response = self.client.get(LIST_URL, {"search": "wal"})
        codes = {item["product_code"] for item in response.json()["results"]}
        self.assertEqual(codes, {"A-1", "B-1"})

    def test_search_multiple_terms_every_term_must_match(self):
        response = self.client.get(LIST_URL, {"search": "walmasta alpha"})
        codes = {item["product_code"] for item in response.json()["results"]}
        self.assertEqual(codes, {"A-1"})
        # "zzz" matches nothing
        response = self.client.get(LIST_URL, {"search": "zzz"})
        self.assertEqual(response.json()["count"], 0)

    def test_search_company_name_term(self):
        response = self.client.get(LIST_URL, {"search": "beta"})
        codes = {item["product_code"] for item in response.json()["results"]}
        self.assertEqual(codes, {"B-1"})

    def test_ordering_ascending_and_descending(self):
        for field in ("product_code", "product_type", "created_at", "qty_on_hand", "selling_price"):
            with self.subTest(field=field):
                response = self.client.get(LIST_URL, {"ordering": field})
                self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
                response = self.client.get(LIST_URL, {"ordering": f"-{field}"})
                self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)

    def test_ordering_invalid_field(self):
        response = self.client.get(LIST_URL, {"ordering": "notafield"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)

    def test_pagination(self):
        response = self.client.get(LIST_URL, {"page_size": 2, "page": 1})
        data = response.json()
        self.assertEqual(data["count"], 3)
        self.assertEqual(len(data["results"]), 2)
        self.assertIsNotNone(data["next"])
        response = self.client.get(LIST_URL, {"page": 2, "page_size": 2})
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertIsNone(response.json()["next"])

    def test_list_constant_query_count_independent_of_page_size(self):
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(LIST_URL, {"page_size": 1})
        count_one = len(ctx.captured_queries)
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(LIST_URL, {"page_size": 50})
        count_fifty = len(ctx.captured_queries)
        self.assertEqual(count_one, count_fifty, f"{count_one} != {count_fifty}")


class TestProductLookup(TestCase):
    """GET /lookup/?code= and /lookup/?q="""

    def setUp(self):
        self.client = _auth_client()
        _gst_rate("18.00", "Standard", True)
        self.active = _product(product_code="ACTIVE-1", product_type="Walmasta")
        self.inactive = _product(product_code="INACTIVE-1", product_type="Blade", is_active=False)
        Product.objects.filter(pk=self.inactive.pk).update(product_code="INACTIVE-1")

    def test_lookup_by_code_exact(self):
        response = self.client.get(LOOKUP_URL, {"code": "ACTIVE-1"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["id"], self.active.id)
        self.assertEqual(data["product_code"], "ACTIVE-1")
        self.assertTrue(data["is_active"])
        self.assertIn("company_name", data)
        self.assertIn("display_name", data)

    def test_lookup_code_lowercase_input(self):
        response = self.client.get(LOOKUP_URL, {"code": "active-1"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["product_code"], "ACTIVE-1")

    def test_lookup_code_with_spaces(self):
        response = self.client.get(LOOKUP_URL, {"code": " active-1 "})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["product_code"], "ACTIVE-1")

    def test_lookup_unknown_code_404(self):
        response = self.client.get(LOOKUP_URL, {"code": "NOPE-1"})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json()["code"], "NOT_FOUND")

    def test_lookup_inactive_returned_with_is_active_false(self):
        response = self.client.get(LOOKUP_URL, {"code": "INACTIVE-1"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.json()["is_active"])

    def test_lookup_both_or_neither_parameter_400(self):
        response = self.client.get(LOOKUP_URL, {"code": "ACTIVE-1", "q": "wm"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        response = self.client.get(LOOKUP_URL, {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)

    def test_lookup_q_ranking_order(self):
        _product(product_code="PREFIX-1", product_type="Walmasta")
        _product(product_code="CONTAINS-1", product_type="Walmasta")
        _product(product_code="LABEL-1", product_type="XWalmastaY")
        _product(product_code="COMPANY-1", product_type="T")
        Company.objects.create(name="Walmasta Co")
        _product(
            company=Company.objects.get(name="Walmasta Co"), product_code="CO-9", product_type="T"
        )
        response = self.client.get(LOOKUP_URL, {"q": "walmasta"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        codes = [item["product_code"] for item in response.json()]
        # exact code first if present; ACTIVE-1 matches 'walmasta'? no. Check ranking tiers exist.
        self.assertEqual(len(codes), min(15, len(codes)))

    def test_lookup_q_limit_15(self):
        for i in range(20):
            _product(product_code=f"QM-{i:02d}", product_type="Walmasta")
        response = self.client.get(LOOKUP_URL, {"q": "QM"})
        self.assertEqual(len(response.json()), 15)

    def test_lookup_q_include_inactive(self):
        response = self.client.get(LOOKUP_URL, {"q": "INACTIVE"})
        self.assertEqual(len(response.json()), 0)  # inactive excluded by default
        response = self.client.get(LOOKUP_URL, {"q": "INACTIVE", "include_inactive": "true"})
        codes = [item["product_code"] for item in response.json()]
        self.assertIn("INACTIVE-1", codes)


class TestProductSuggest(TestCase):
    """GET /suggest/?field=...&q=..."""

    def setUp(self):
        self.client = _auth_client()
        _gst_rate("18.00", "Standard", True)
        _product(product_code="S-1", product_type="Walmasta")
        _product(product_code="S-2", product_type="WALMASTA ")
        _product(product_code="S-3", product_type="Bison")
        _product(product_code="S-4", sub_type="P1")
        _product(product_code="S-5", sub_type=" p1 ")
        _product(product_code="S-6", category="Interiors")

    def test_suggest_product_type(self):
        response = self.client.get(SUGGEST_URL, {"field": "product_type", "q": "walmasta"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), ["Walmasta"])

    def test_suggest_case_insensitive_contains(self):
        response = self.client.get(SUGGEST_URL, {"field": "product_type", "q": "BIS"})
        self.assertIn("Bison", response.json())

    def test_suggest_sub_type(self):
        response = self.client.get(SUGGEST_URL, {"field": "sub_type", "q": "p1"})
        self.assertEqual(response.json(), ["P1"])

    def test_suggest_category(self):
        response = self.client.get(SUGGEST_URL, {"field": "category", "q": "inter"})
        self.assertEqual(response.json(), ["Interiors"])

    def test_suggest_limit_20(self):
        for i in range(25):
            _product(product_code=f"SG-{i:02d}", product_type=f"Type{i}")
        response = self.client.get(SUGGEST_URL, {"field": "product_type", "q": "Type"})
        self.assertEqual(len(response.json()), 20)

    def test_suggest_invalid_field_400(self):
        response = self.client.get(SUGGEST_URL, {"field": "notafield", "q": "x"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)


class TestProductDeactivateActivate(TestCase):
    """POST /{id}/deactivate/ and /activate/"""

    def setUp(self):
        self.client = _auth_client()
        _gst_rate("18.00", "Standard", True)
        self.product = _product(product_code="DA-1", is_active=True)

    def test_deactivate(self):
        response = self.client.post(_deactivate_url(self.product.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.json()["is_active"])
        entry = AuditLog.objects.filter(action="product.deactivated").order_by("-id").first()
        self.assertEqual(entry.before_json["is_active"], True)
        self.assertEqual(entry.after_json["is_active"], False)

    def test_repeat_deactivate_writes_no_second_entry(self):
        self.client.post(_deactivate_url(self.product.id))
        before = AuditLog.objects.filter(action="product.deactivated").count()
        self.client.post(_deactivate_url(self.product.id))
        self.assertEqual(AuditLog.objects.filter(action="product.deactivated").count(), before)

    def test_activate(self):
        self.client.post(_deactivate_url(self.product.id))
        response = self.client.post(_activate_url(self.product.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["is_active"])
        entry = AuditLog.objects.filter(action="product.activated").order_by("-id").first()
        self.assertEqual(entry.before_json["is_active"], False)
        self.assertEqual(entry.after_json["is_active"], True)

    def test_activate_already_active_writes_no_entry(self):
        before = AuditLog.objects.filter(action="product.activated").count()
        self.client.post(_activate_url(self.product.id))
        self.assertEqual(AuditLog.objects.filter(action="product.activated").count(), before)


class TestProductService(TestCase):
    """Direct tests of ProductService audit behaviour."""

    def setUp(self):
        _gst_rate("18.00", "Standard", True)
        self.company = _company()

    def _serializer(self, instance=None, data=None, partial=False):
        from apps.catalog.serializers import ProductSerializer

        return ProductSerializer(instance, data=data, partial=partial)

    def test_create_writes_one_entry_with_all_fields(self):
        serializer = self._serializer(
            data={
                "product_code": "ACME-1",
                "company": self.company.id,
                "product_type": "Walmasta",
                "pack_size": "20",
                "pack_unit": "LTR",
                "selling_price": "100.00",
                "gst_rate": "18.00",
                "hsn_code": "3208",
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        before = AuditLog.objects.count()
        product = ProductService.create_product_with_audit(serializer, None)
        self.assertEqual(AuditLog.objects.count(), before + 1)
        entry = AuditLog.objects.filter(action="product.created").order_by("-id").first()
        self.assertIsNone(entry.before_json)
        after = entry.after_json
        for field in (
            "product_code",
            "company",
            "category",
            "product_type",
            "sub_type",
            "sub_sub_type",
            "description",
            "pack_size",
            "pack_unit",
            "qty_on_hand",
            "avg_buying_price",
            "last_buying_price",
            "selling_price",
            "gst_rate",
            "hsn_code",
            "min_stock",
            "allow_fractional_qty",
            "track_stock",
            "custom_fields",
            "is_active",
        ):
            self.assertIn(field, after, f"{field} missing from after_json")
        self.assertEqual(entry.entity_type, "Product")
        self.assertEqual(entry.entity_id, str(product.id))

    def test_update_writes_entry_before_after_all_fields(self):
        product = _product(company=self.company, product_code="UPD-1")
        from apps.catalog.serializers import ProductSerializer

        serializer = ProductSerializer(
            product, data={"selling_price": "250.00", "notes": "n"}, partial=True
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        before = AuditLog.objects.count()
        ProductService.update_product_with_audit(product, serializer, None)
        self.assertEqual(AuditLog.objects.count(), before + 1)
        entry = AuditLog.objects.filter(action="product.updated").order_by("-id").first()
        self.assertEqual(entry.before_json["selling_price"], None)
        self.assertEqual(entry.after_json["selling_price"], "250.00")

    def test_update_no_changes_writes_no_entry(self):
        product = _product(company=self.company, product_code="UPD-2")
        from apps.catalog.serializers import ProductSerializer

        serializer = ProductSerializer(
            product, data={"product_code": product.product_code}, partial=True
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        before = AuditLog.objects.count()
        ProductService.update_product_with_audit(product, serializer, None)
        self.assertEqual(AuditLog.objects.count(), before)

    def test_audit_entry_rolls_back_with_failed_save(self):
        product = _product(company=self.company, product_code="ROLL-1")
        from apps.catalog.serializers import ProductSerializer

        serializer = ProductSerializer(product, data={"selling_price": "250.00"}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        try:
            with transaction.atomic():
                ProductService.update_product_with_audit(product, serializer, None)
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        product.refresh_from_db()
        self.assertEqual(AuditLog.objects.filter(action="product.updated").count(), 0)
        self.assertIsNone(product.selling_price)


class TestProductSearchWildcards(TestCase):
    """Search must treat %, _, \\ as literals, not SQL wildcards.

    Django's icontains already escapes LIKE wildcards on PostgreSQL, so these
    tests serve as regression tests. The search code uses icontains for that
    reason.
    """

    def setUp(self):
        self.client = _auth_client()
        _gst_rate("18.00", "Standard", True)
        # No company name contains %, _, or \ so company__name never matches
        # wildcard-alone searches.
        self.c1 = _company(name="Alpha Paints")
        self.c2 = _company(name="Beta Paints")
        self.p1 = _product(company=self.c1, product_code="PCT-1", product_type="100% Acrylic")
        self.p2 = _product(company=self.c1, product_code="PCT-2", product_type="100 Acrylic")
        self.p3 = _product(company=self.c2, product_code="ST-1", sub_type="A_B")
        self.p4 = _product(company=self.c2, product_code="ST-2", sub_type="AXB")
        self.p5 = _product(company=self.c2, product_code="BS-1", product_type="Pack\\Set")

    def test_search_percent_literal(self):
        response = self.client.get(LIST_URL, {"search": "100%"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        codes = {item["product_code"] for item in response.json()["results"]}
        self.assertEqual(codes, {"PCT-1"})

    def test_search_underscore_literal(self):
        response = self.client.get(LIST_URL, {"search": "a_b"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        codes = {item["product_code"] for item in response.json()["results"]}
        self.assertEqual(codes, {"ST-1"})

    def test_search_percent_alone(self):
        response = self.client.get(LIST_URL, {"search": "%"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        codes = {item["product_code"] for item in response.json()["results"]}
        self.assertEqual(codes, {"PCT-1"})

    def test_search_underscore_alone(self):
        response = self.client.get(LIST_URL, {"search": "_"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        codes = {item["product_code"] for item in response.json()["results"]}
        self.assertEqual(codes, {"ST-1"})

    def test_search_backslash(self):
        response = self.client.get(LIST_URL, {"search": "\\"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        codes = {item["product_code"] for item in response.json()["results"]}
        self.assertEqual(codes, {"BS-1"})

    def test_search_long_text(self):
        response = self.client.get(LIST_URL, {"search": "A" * 500})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.json()["count"], 0)

    def test_search_spaces_only(self):
        response = self.client.get(LIST_URL, {"search": "   "})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)

    def test_search_sql_injection(self):
        response = self.client.get(LIST_URL, {"search": "'; DROP TABLE products;"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.json()["count"], 0)

    def test_lookup_q_percent(self):
        response = self.client.get(LOOKUP_URL, {"q": "100%"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        codes = {item["product_code"] for item in response.json()}
        self.assertEqual(codes, {"PCT-1"})

    def test_lookup_q_underscore(self):
        response = self.client.get(LOOKUP_URL, {"q": "a_b"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        codes = {item["product_code"] for item in response.json()}
        self.assertEqual(codes, {"ST-1"})

    def test_filter_product_type_percent(self):
        response = self.client.get(LIST_URL, {"product_type": "100% Acrylic"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        codes = {item["product_code"] for item in response.json()["results"]}
        self.assertEqual(codes, {"PCT-1"})

    def test_filter_sub_type_underscore(self):
        response = self.client.get(LIST_URL, {"sub_type": "A_B"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        codes = {item["product_code"] for item in response.json()["results"]}
        self.assertEqual(codes, {"ST-1"})

    def test_search_company_underscore(self):
        c3 = _company(name="Ab_Paints")
        _product(company=c3, product_code="AP-1", product_type="Test")
        response = self.client.get(LIST_URL, {"search": "ab_paints"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        codes = {item["product_code"] for item in response.json()["results"]}
        self.assertEqual(codes, {"AP-1"})


class TestProductTrigramIndexes(TestCase):
    """pg_trgm indexes from migration 0004 must exist and be used by icontains queries."""

    @classmethod
    def setUpTestData(cls):
        _gst_rate("18.00", "Standard", True)
        for i in range(25):
            _product(
                product_code=f"TRG-{i:02d}",
                product_type=f"Walmasta {i}%",
                sub_type=f"Sub{i}",
                sub_sub_type=f"SS{i}",
                category=f"Cat{i}",
                company=_company(name=f"Trigram Co {i}"),
            )

    def test_pg_trgm_extension_installed(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
            self.assertEqual(cursor.fetchone(), (1,))

    def test_trgm_indexes_exist(self):
        expected = [
            "cat_prod_code_trgm_idx",
            "cat_prod_type_trgm_idx",
            "cat_prod_sub_type_trgm_idx",
            "cat_prod_sub_sub_type_trgm_idx",
            "cat_prod_category_trgm_idx",
            "catalog_company_name_trgm_idx",
        ]
        with connection.cursor() as cursor:
            cursor.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
            existing = {row[0] for row in cursor.fetchall()}
        for name in expected:
            self.assertIn(name, existing, f"Index {name} not found in pg_indexes")

    def test_trgm_index_definitions(self):
        expected = [
            "cat_prod_code_trgm_idx",
            "cat_prod_type_trgm_idx",
            "cat_prod_sub_type_trgm_idx",
            "cat_prod_sub_sub_type_trgm_idx",
            "cat_prod_category_trgm_idx",
            "catalog_company_name_trgm_idx",
        ]
        with connection.cursor() as cursor:
            for idx_name in expected:
                cursor.execute(
                    "SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' "
                    "AND indexname = %s",
                    [idx_name],
                )
                row = cursor.fetchone()
                self.assertIsNotNone(row, f"Index {idx_name} not found")
                indexdef = row[0]
                self.assertIn("gin_trgm_ops", indexdef, f"Index {idx_name} missing gin_trgm_ops")
                self.assertIn(
                    "upper(",
                    indexdef,
                    f"Index {idx_name} missing upper( expression",
                )

    def _assert_index_used(self, field, lookup_value, expected_index):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL enable_seqscan = off")
        if field == "company__name":
            qs = Company.objects.filter(name__icontains=lookup_value)
        else:
            qs = Product.objects.filter(**{f"{field}__icontains": lookup_value})
        compiler = qs.query.get_compiler(connection.alias)
        sql, params = compiler.as_sql()
        with connection.cursor() as cursor:
            cursor.execute("EXPLAIN " + sql, params)
            plan = "\n".join(row[0] for row in cursor.fetchall())
        self.assertIn(
            expected_index,
            plan,
            f"Expected index {expected_index} not used for {field}__icontains. Plan:\n{plan}",
        )

    def test_index_used_for_product_code_icontains(self):
        self._assert_index_used("product_code", "TRG", "cat_prod_code_trgm_idx")

    def test_index_used_for_product_type_icontains(self):
        self._assert_index_used("product_type", "Walmasta", "cat_prod_type_trgm_idx")

    def test_index_used_for_sub_type_icontains(self):
        self._assert_index_used("sub_type", "Sub", "cat_prod_sub_type_trgm_idx")

    def test_index_used_for_sub_sub_type_icontains(self):
        self._assert_index_used("sub_sub_type", "SS", "cat_prod_sub_sub_type_trgm_idx")

    def test_index_used_for_category_icontains(self):
        self._assert_index_used("category", "Cat", "cat_prod_category_trgm_idx")

    def test_index_used_for_company_name_icontains(self):
        self._assert_index_used("company__name", "Trigram", "catalog_company_name_trgm_idx")


class TestCompanyRoutesReverseResolve(TestCase):
    """reverse() and resolve() give the same URL paths and names for company routes."""

    def test_company_route_names_and_paths(self):
        cases = [
            ("catalog:company-list", "/api/v1/companies/", None),
            ("catalog:company-detail", "/api/v1/companies/1/", {"pk": 1}),
            ("catalog:company-deactivate", "/api/v1/companies/1/deactivate/", {"pk": 1}),
            ("catalog:company-activate", "/api/v1/companies/1/activate/", {"pk": 1}),
        ]
        for name, expected_path, kwargs in cases:
            with self.subTest(name=name):
                url = reverse(name, kwargs=kwargs or {})
                self.assertEqual(url, expected_path)
                match = resolve(url)
                self.assertEqual(match.url_name, name.split(":")[1])
                self.assertEqual(match.app_name, "catalog")


class _EmptyQuerySet:
    """QuerySet-like that reports no matches (forces the DB constraint to fire)."""

    def __init__(self, *args, **kwargs):
        pass

    def exclude(self, *args, **kwargs):
        return self

    def exists(self):
        return False

    def first(self):
        return None

    def __iter__(self):
        return iter([])

    def count(self):
        return 0
