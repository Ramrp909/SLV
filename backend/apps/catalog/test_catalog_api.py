"""Tests for T-204 Catalog and readiness endpoints (apps/catalog)."""

from decimal import Decimal

from common.errors import METHOD_NOT_ALLOWED, VALIDATION_ERROR
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import resolve, reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.catalog.models import Company, PackUnit, Product
from apps.catalog.selectors import missing_for_billing
from apps.core.models import GstRate

User = get_user_model()

COMPANIES_URL = "/api/v1/catalog/companies/"
READINESS_URL = "/api/v1/catalog/readiness/"
READINESS_SUMMARY_URL = "/api/v1/catalog/readiness/summary/"
PRODUCT_LIST_URL = "/api/v1/products/"
COMPANY_LIST_URL = "/api/v1/companies/"


def _auth_client():
    client = APIClient()
    user = User.objects.create_user(username="owner", password="SecurePass123!")
    client.force_authenticate(user)
    return client


def _company(name="Berger", is_active=True, is_local=False):
    company = Company.objects.filter(name__iexact=name).first()
    if company is None:
        company = Company.objects.create(name=name, is_active=is_active, is_local=is_local)
    return company


def _gst_rate(rate="18.00", label="Standard", is_active=True):
    rate = Decimal(rate)
    obj = GstRate.objects.filter(rate=rate).first()
    if obj is None:
        obj = GstRate.objects.create(rate=rate, label=label, is_active=is_active)
    return obj


def _product(
    company=None,
    product_code="X-1",
    product_type="T",
    pack_size=Decimal("1"),
    pack_unit=PackUnit.PCS,
    is_active=True,
    selling_price=None,
    gst_rate=None,
    hsn_code=None,
    category=None,
    sub_type=None,
    sub_sub_type=None,
):
    if company is None:
        company = _company()
    instance = Product(
        product_code=product_code,
        company=company,
        product_type=product_type,
        pack_size=pack_size,
        pack_unit=pack_unit,
        is_active=is_active,
        selling_price=selling_price,
        gst_rate=gst_rate,
        hsn_code=hsn_code,
        category=category,
        sub_type=sub_type,
        sub_sub_type=sub_sub_type,
    )
    instance.save()
    return instance


class TestCatalogAuthentication(TestCase):
    """401 without a token for every endpoint and verb."""

    def setUp(self):
        self.client = APIClient()

    def test_endpoints_require_authentication(self):
        cases = [
            ("GET", COMPANIES_URL),
            ("POST", COMPANIES_URL),
            ("PUT", COMPANIES_URL),
            ("PATCH", COMPANIES_URL),
            ("DELETE", COMPANIES_URL),
            ("GET", READINESS_URL),
            ("POST", READINESS_URL),
            ("PUT", READINESS_URL),
            ("PATCH", READINESS_URL),
            ("DELETE", READINESS_URL),
            ("GET", READINESS_SUMMARY_URL),
            ("POST", READINESS_SUMMARY_URL),
            ("PUT", READINESS_SUMMARY_URL),
            ("PATCH", READINESS_SUMMARY_URL),
            ("DELETE", READINESS_SUMMARY_URL),
        ]
        for method, url in cases:
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method.lower())(url)
                self.assertEqual(
                    response.status_code,
                    status.HTTP_401_UNAUTHORIZED,
                    f"{method} {url} returned {response.status_code}: {response.content}",
                )


class TestCatalogMethodNotAllowed(TestCase):
    """POST, PUT, PATCH and DELETE return 405 in the standard format."""

    def setUp(self):
        self.client = _auth_client()

    def test_write_methods_return_405(self):
        for url in (COMPANIES_URL, READINESS_URL, READINESS_SUMMARY_URL):
            for method in ("post", "put", "patch", "delete"):
                with self.subTest(url=url, method=method):
                    response = getattr(self.client, method)(url, {}, format="json")
                    self.assertEqual(
                        response.status_code,
                        status.HTTP_405_METHOD_NOT_ALLOWED,
                        f"{method.upper()} {url} returned {response.status_code}: {response.content}",
                    )
                    data = response.json()
                    self.assertEqual(data["code"], METHOD_NOT_ALLOWED)
                    self.assertEqual(data["fields"], {})


class TestCompaniesList(TestCase):
    """GET /api/v1/catalog/companies/ - counts, filters, ordering, pagination."""

    def setUp(self):
        self.client = _auth_client()
        _gst_rate("18.00", "Standard", True)
        self.alpha = _company(name="Alpha Paints", is_active=True, is_local=False)
        self.beta = _company(name="Beta Traders", is_active=False, is_local=True)
        self.gamma = _company(name="Gamma Co", is_active=True, is_local=False)
        self.delta = _company(name="Delta Local", is_active=True, is_local=True)
        _product(
            company=self.alpha,
            product_code="A-READY",
            product_type="Walmasta",
            selling_price=Decimal("100"),
            gst_rate=Decimal("18.00"),
            hsn_code="3208",
        )
        _product(company=self.alpha, product_code="A-NOT", product_type="Blade")
        _product(
            company=self.alpha, product_code="A-INACT", product_type="Walmasta", is_active=False
        )
        _product(
            company=self.beta,
            product_code="B-1",
            product_type="Walmasta",
            selling_price=Decimal("100"),
            gst_rate=Decimal("18.00"),
            hsn_code="3208",
        )

    def _counts(self, company):
        return {
            "product_count": company.product_count,
            "inactive_product_count": company.inactive_product_count,
            "billing_ready_count": company.billing_ready_count,
            "not_billing_ready_count": company.not_billing_ready_count,
        }

    def test_default_hides_inactive_companies(self):
        response = self.client.get(COMPANIES_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        names = {item["name"] for item in response.json()["results"]}
        self.assertEqual(names, {"Alpha Paints", "Gamma Co", "Delta Local"})

    def test_include_inactive_shows_inactive_companies(self):
        response = self.client.get(COMPANIES_URL, {"include_inactive": "true"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        names = {item["name"] for item in response.json()["results"]}
        self.assertEqual(names, {"Alpha Paints", "Beta Traders", "Gamma Co", "Delta Local"})

    def test_counts_for_mixed_products(self):
        response = self.client.get(COMPANIES_URL, {"include_inactive": "true"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        data = {item["name"]: item for item in response.json()["results"]}
        self.assertEqual(data["Alpha Paints"]["product_count"], 2)
        self.assertEqual(data["Alpha Paints"]["inactive_product_count"], 1)
        self.assertEqual(data["Alpha Paints"]["billing_ready_count"], 1)
        self.assertEqual(data["Alpha Paints"]["not_billing_ready_count"], 1)
        self.assertEqual(data["Beta Traders"]["product_count"], 1)
        self.assertEqual(data["Beta Traders"]["inactive_product_count"], 0)
        self.assertEqual(data["Beta Traders"]["billing_ready_count"], 1)
        self.assertEqual(data["Beta Traders"]["not_billing_ready_count"], 0)
        self.assertEqual(
            (
                data["Gamma Co"]["product_count"],
                data["Gamma Co"]["inactive_product_count"],
                data["Gamma Co"]["billing_ready_count"],
                data["Gamma Co"]["not_billing_ready_count"],
            ),
            (0, 0, 0, 0),
        )

    def test_company_with_no_products_shows_zeros(self):
        response = self.client.get(COMPANIES_URL)
        data = {item["name"]: item for item in response.json()["results"]}
        self.assertEqual(
            (
                data["Gamma Co"]["product_count"],
                data["Gamma Co"]["inactive_product_count"],
                data["Gamma Co"]["billing_ready_count"],
                data["Gamma Co"]["not_billing_ready_count"],
            ),
            (0, 0, 0, 0),
        )
        self.assertEqual(
            (
                data["Delta Local"]["product_count"],
                data["Delta Local"]["inactive_product_count"],
                data["Delta Local"]["billing_ready_count"],
                data["Delta Local"]["not_billing_ready_count"],
            ),
            (0, 0, 0, 0),
        )

    def test_inactive_products_do_not_count_in_product_count(self):
        response = self.client.get(COMPANIES_URL, {"include_inactive": "true"})
        data = {item["name"]: item for item in response.json()["results"]}
        self.assertEqual(data["Alpha Paints"]["product_count"], 2)

    def test_is_local_filter(self):
        response = self.client.get(COMPANIES_URL, {"is_local": "true", "include_inactive": "true"})
        names = {item["name"] for item in response.json()["results"]}
        self.assertEqual(names, {"Beta Traders", "Delta Local"})
        response = self.client.get(COMPANIES_URL, {"is_local": "false"})
        names = {item["name"] for item in response.json()["results"]}
        self.assertEqual(names, {"Alpha Paints", "Gamma Co"})

    def test_is_active_filter(self):
        response = self.client.get(
            COMPANIES_URL, {"is_active": "false", "include_inactive": "true"}
        )
        names = {item["name"] for item in response.json()["results"]}
        self.assertEqual(names, {"Beta Traders"})

    def test_search_case_insensitive_on_name(self):
        response = self.client.get(COMPANIES_URL, {"search": "alpha"})
        names = {item["name"] for item in response.json()["results"]}
        self.assertEqual(names, {"Alpha Paints"})
        response = self.client.get(COMPANIES_URL, {"search": "TRADERS", "include_inactive": "true"})
        names = {item["name"] for item in response.json()["results"]}
        self.assertEqual(names, {"Beta Traders"})
        response = self.client.get(COMPANIES_URL, {"search": "nonexistent"})
        self.assertEqual(response.json()["count"], 0)

    def test_ordering_by_name(self):
        response = self.client.get(COMPANIES_URL, {"include_inactive": "true", "ordering": "name"})
        names = [item["name"] for item in response.json()["results"]]
        self.assertEqual(names, ["Alpha Paints", "Beta Traders", "Delta Local", "Gamma Co"])
        response = self.client.get(COMPANIES_URL, {"include_inactive": "true", "ordering": "-name"})
        names = [item["name"] for item in response.json()["results"]]
        self.assertEqual(names, ["Gamma Co", "Delta Local", "Beta Traders", "Alpha Paints"])

    def test_ordering_by_product_count(self):
        response = self.client.get(
            COMPANIES_URL, {"include_inactive": "true", "ordering": "product_count"}
        )
        counts = [item["product_count"] for item in response.json()["results"]]
        self.assertEqual(counts, sorted(counts))
        response = self.client.get(
            COMPANIES_URL, {"include_inactive": "true", "ordering": "-product_count"}
        )
        counts = [item["product_count"] for item in response.json()["results"]]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_ordering_by_not_billing_ready_count(self):
        response = self.client.get(
            COMPANIES_URL, {"include_inactive": "true", "ordering": "not_billing_ready_count"}
        )
        counts = [item["not_billing_ready_count"] for item in response.json()["results"]]
        self.assertEqual(counts, sorted(counts))

    def test_ordering_invalid_field(self):
        response = self.client.get(COMPANIES_URL, {"ordering": "notafield"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        self.assertEqual(response.json()["code"], VALIDATION_ERROR)

    def test_invalid_boolean_params(self):
        for param in ("is_active", "is_local", "include_inactive"):
            with self.subTest(param=param):
                response = self.client.get(COMPANIES_URL, {param: "maybe"})
                self.assertEqual(
                    response.status_code, status.HTTP_400_BAD_REQUEST, response.content
                )
                self.assertEqual(response.json()["code"], VALIDATION_ERROR)

    def test_pagination(self):
        response = self.client.get(COMPANIES_URL, {"page_size": 2, "page": 1})
        data = response.json()
        self.assertEqual(data["count"], 3)
        self.assertEqual(len(data["results"]), 2)
        self.assertIsNotNone(data["next"])
        response = self.client.get(COMPANIES_URL, {"page": 2, "page_size": 2})
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertIsNone(response.json()["next"])

    def test_page_size_capped_at_100(self):
        for i in range(101):
            _company(name=f"Co {i:03d}")
        response = self.client.get(COMPANIES_URL, {"page_size": 200, "include_inactive": "true"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.json()["count"], 105)
        self.assertEqual(len(response.json()["results"]), 100)

    def test_decimal_counts_are_integers(self):
        response = self.client.get(COMPANIES_URL)
        item = response.json()["results"][0]
        for field in (
            "product_count",
            "inactive_product_count",
            "billing_ready_count",
            "not_billing_ready_count",
        ):
            self.assertIsInstance(item[field], int)


class TestReadinessList(TestCase):
    """GET /api/v1/catalog/readiness/ - not billing ready products."""

    def setUp(self):
        self.client = _auth_client()
        _gst_rate("18.00", "Standard", True)
        _gst_rate("5.00", "Low", False)
        self.c1 = _company(name="Alpha Paints")
        self.c2 = _company(name="Beta Traders")
        self.ready = _product(
            company=self.c1,
            product_code="R-1",
            product_type="Walmasta",
            selling_price=Decimal("100"),
            gst_rate=Decimal("18.00"),
            hsn_code="3208",
        )
        self.m_price = _product(
            company=self.c1,
            product_code="M-PRICE",
            product_type="Walmasta",
            gst_rate=Decimal("18.00"),
            hsn_code="3208",
        )
        self.m_rate = _product(
            company=self.c1,
            product_code="M-RATE",
            product_type="Blade",
            selling_price=Decimal("100"),
            hsn_code="3208",
        )
        self.m_rate_inactive = _product(
            company=self.c1,
            product_code="M-RATE-INACT",
            product_type="Blade",
            selling_price=Decimal("100"),
            gst_rate=Decimal("5.00"),
            hsn_code="3208",
        )
        self.m_hsn = _product(
            company=self.c1,
            product_code="M-HSN",
            product_type="Blade",
            selling_price=Decimal("100"),
            gst_rate=Decimal("18.00"),
            category="Interiors",
        )
        self.m_all = _product(
            company=self.c2,
            product_code="M-ALL",
            product_type="Sandpaper",
        )
        self.wild_percent = _product(
            company=self.c2,
            product_code="W-PCT",
            product_type="100% Acrylic",
        )
        self.wild_underscore = _product(
            company=self.c2,
            product_code="W-UND",
            product_type="Plain",
            sub_type="A_B",
        )
        self.inactive = _product(
            company=self.c1,
            product_code="I-1",
            product_type="Walmasta",
            is_active=False,
        )

    def _codes(self, response):
        return {item["product_code"] for item in response.json()["results"]}

    def test_only_not_ready_active_products_by_default(self):
        response = self.client.get(READINESS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        codes = self._codes(response)
        self.assertEqual(
            codes,
            {"M-PRICE", "M-RATE", "M-RATE-INACT", "M-HSN", "M-ALL", "W-PCT", "W-UND"},
        )
        self.assertNotIn("R-1", codes)
        self.assertNotIn("I-1", codes)

    def test_include_inactive_adds_inactive_products(self):
        response = self.client.get(READINESS_URL, {"include_inactive": "true"})
        codes = self._codes(response)
        self.assertIn("I-1", codes)
        self.assertIn("M-ALL", codes)

    def test_missing_for_billing_lists(self):
        response = self.client.get(READINESS_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        data = {item["product_code"]: item for item in response.json()["results"]}
        self.assertEqual(data["M-PRICE"]["missing_for_billing"], ["selling_price"])
        self.assertEqual(data["M-RATE"]["missing_for_billing"], ["gst_rate"])
        self.assertEqual(data["M-RATE-INACT"]["missing_for_billing"], ["gst_rate_inactive"])
        self.assertEqual(data["M-HSN"]["missing_for_billing"], ["hsn_code"])
        self.assertEqual(
            data["M-ALL"]["missing_for_billing"], ["selling_price", "gst_rate", "hsn_code"]
        )

    def test_items_have_expected_fields(self):
        response = self.client.get(READINESS_URL)
        item = {item["product_code"]: item for item in response.json()["results"]}["M-PRICE"]
        self.assertEqual(
            set(item),
            {
                "id",
                "product_code",
                "display_name",
                "company_name",
                "product_type",
                "sub_type",
                "sub_sub_type",
                "pack_size",
                "pack_unit",
                "missing_for_billing",
                "is_active",
            },
        )
        self.assertEqual(item["display_name"], "Alpha Paints Walmasta 1 PCS")
        self.assertEqual(item["company_name"], "Alpha Paints")
        self.assertEqual(item["product_type"], "Walmasta")
        self.assertIsInstance(item["pack_size"], str)

    def test_missing_filters(self):
        cases = {
            "selling_price": {"M-PRICE", "M-ALL", "W-PCT", "W-UND"},
            "gst_rate": {"M-RATE", "M-ALL", "W-PCT", "W-UND"},
            "gst_rate_inactive": {"M-RATE-INACT"},
            "hsn_code": {"M-HSN", "M-ALL", "W-PCT", "W-UND"},
        }
        for missing, expected in cases.items():
            with self.subTest(missing=missing):
                response = self.client.get(READINESS_URL, {"missing": missing})
                self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
                self.assertEqual(self._codes(response), expected)

    def test_invalid_missing_filter(self):
        response = self.client.get(READINESS_URL, {"missing": "notareason"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        self.assertEqual(response.json()["code"], VALIDATION_ERROR)

    def test_company_filter(self):
        response = self.client.get(READINESS_URL, {"company": self.c2.id})
        self.assertEqual(self._codes(response), {"M-ALL", "W-PCT", "W-UND"})
        response = self.client.get(READINESS_URL, {"company": self.c1.id})
        self.assertEqual(self._codes(response), {"M-PRICE", "M-RATE", "M-RATE-INACT", "M-HSN"})

    def test_company_filter_unknown_id_empty_page(self):
        response = self.client.get(READINESS_URL, {"company": 999999})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.json()["count"], 0)
        self.assertEqual(response.json()["results"], [])

    def test_product_type_and_category_filters_are_case_insensitive_exact(self):
        response = self.client.get(READINESS_URL, {"product_type": "walmasta "})
        self.assertEqual(self._codes(response), {"M-PRICE"})
        response = self.client.get(READINESS_URL, {"product_type": "WALMASTA"})
        self.assertEqual(self._codes(response), {"M-PRICE"})
        response = self.client.get(READINESS_URL, {"category": "interiors"})
        self.assertEqual(self._codes(response), {"M-HSN"})
        response = self.client.get(READINESS_URL, {"category": "INTERIORS"})
        self.assertEqual(self._codes(response), {"M-HSN"})

    def test_search_multi_term_every_term_must_match(self):
        response = self.client.get(READINESS_URL, {"search": "sandpaper beta"})
        self.assertEqual(self._codes(response), {"M-ALL"})
        response = self.client.get(READINESS_URL, {"search": "sandpaper alpha"})
        self.assertEqual(self._codes(response), set())
        response = self.client.get(READINESS_URL, {"search": "zzz"})
        self.assertEqual(response.json()["count"], 0)

    def test_search_company_name_term(self):
        response = self.client.get(READINESS_URL, {"search": "traders"})
        self.assertEqual(self._codes(response), {"M-ALL", "W-PCT", "W-UND"})

    def test_search_wildcard_characters_match_literally(self):
        response = self.client.get(READINESS_URL, {"search": "%"})
        self.assertEqual(self._codes(response), {"W-PCT"})
        response = self.client.get(READINESS_URL, {"search": "_"})
        self.assertEqual(self._codes(response), {"W-UND"})
        response = self.client.get(READINESS_URL, {"search": "\\"})
        self.assertEqual(self._codes(response), set())

    def test_default_ordering_by_product_code(self):
        response = self.client.get(READINESS_URL)
        codes = [item["product_code"] for item in response.json()["results"]]
        self.assertEqual(codes, sorted(codes))

    def test_ordering_descending(self):
        response = self.client.get(READINESS_URL, {"ordering": "-product_code"})
        codes = [item["product_code"] for item in response.json()["results"]]
        self.assertEqual(codes, sorted(codes, reverse=True))

    def test_ordering_invalid_field(self):
        response = self.client.get(READINESS_URL, {"ordering": "notafield"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        self.assertEqual(response.json()["code"], VALIDATION_ERROR)

    def test_pagination(self):
        response = self.client.get(READINESS_URL, {"page_size": 2, "page": 1})
        data = response.json()
        self.assertEqual(data["count"], 7)
        self.assertEqual(len(data["results"]), 2)
        response = self.client.get(READINESS_URL, {"page": 3, "page_size": 2})
        self.assertEqual(len(response.json()["results"]), 2)

    def test_fully_ready_product_never_appears(self):
        response = self.client.get(READINESS_URL, {"include_inactive": "true"})
        self.assertNotIn("R-1", self._codes(response))

    def test_constant_query_count_independent_of_page_size(self):
        for i in range(50):
            _product(company=self.c1, product_code=f"QC-{i:02d}", product_type="T")
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(READINESS_URL, {"page_size": 1})
        count_one = len(ctx.captured_queries)
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(READINESS_URL, {"page_size": 50})
        count_fifty = len(ctx.captured_queries)
        self.assertEqual(count_one, count_fifty, f"{count_one} != {count_fifty}")


class TestReadinessEquivalence(TestCase):
    """missing_for_billing agrees with the model across every condition combination."""

    def setUp(self):
        self.client = _auth_client()
        _gst_rate("18.00", "Standard", True)
        _gst_rate("5.00", "Low", False)
        self.company = _company(name="Equivalence Co")

    def test_all_combinations_agree(self):
        price_cases = (("set", Decimal("100")), ("none", None))
        rate_cases = (
            ("approved", Decimal("18.00")),
            ("none", None),
            ("deactivated", Decimal("5.00")),
        )
        hsn_cases = (("set", "3208"), ("empty", ""))
        expected = {
            ("none", "none", "empty"): ["selling_price", "gst_rate", "hsn_code"],
            ("none", "none", "set"): ["selling_price", "gst_rate"],
            ("none", "approved", "empty"): ["selling_price", "hsn_code"],
            ("none", "approved", "set"): ["selling_price"],
            ("none", "deactivated", "empty"): ["selling_price", "gst_rate_inactive", "hsn_code"],
            ("none", "deactivated", "set"): ["selling_price", "gst_rate_inactive"],
            ("set", "none", "empty"): ["gst_rate", "hsn_code"],
            ("set", "none", "set"): ["gst_rate"],
            ("set", "approved", "empty"): ["hsn_code"],
            ("set", "approved", "set"): [],
            ("set", "deactivated", "empty"): ["gst_rate_inactive", "hsn_code"],
            ("set", "deactivated", "set"): ["gst_rate_inactive"],
        }
        wanted_by_code = {}
        products = []
        for (p_label, price), (r_label, rate), (h_label, hsn) in (
            (p, r, h) for p in price_cases for r in rate_cases for h in hsn_cases
        ):
            code = f"EQ-{p_label}-{r_label}-{h_label}"
            product = _product(
                company=self.company,
                product_code=code,
                product_type="T",
                selling_price=price,
                gst_rate=rate,
                hsn_code=hsn,
            )
            wanted_by_code[product.product_code] = expected[(p_label, r_label, h_label)]
            products.append(product)

        ready_pks = set(Product.objects.billing_ready().values_list("pk", flat=True))
        not_ready_pks = set(Product.objects.not_billing_ready().values_list("pk", flat=True))
        for product in products:
            code = product.product_code
            wanted = wanted_by_code[code]
            self.assertEqual(missing_for_billing(product), wanted, code)
            self.assertEqual(product.billing_ready, wanted == [], code)
            self.assertEqual(product.pk in ready_pks, wanted == [], code)
            self.assertEqual(product.pk in not_ready_pks, wanted != [], code)

    def test_endpoint_membership_matches_missing_for_billing(self):
        _product(
            company=self.company,
            product_code="EQ-READY",
            product_type="T",
            selling_price=Decimal("100"),
            gst_rate=Decimal("18.00"),
            hsn_code="3208",
        )
        _product(company=self.company, product_code="EQ-NOT", product_type="T")
        response = self.client.get(READINESS_URL)
        codes = {item["product_code"] for item in response.json()["results"]}
        self.assertEqual(codes, {"EQ-NOT"})
        response = self.client.get(READINESS_URL, {"include_inactive": "true"})
        self.assertEqual({item["product_code"] for item in response.json()["results"]}, {"EQ-NOT"})


class TestReadinessSummary(TestCase):
    """GET /api/v1/catalog/readiness/summary/"""

    def setUp(self):
        self.client = _auth_client()
        _gst_rate("18.00", "Standard", True)
        _gst_rate("5.00", "Low", False)
        self.company = _company(name="Summary Co")
        _product(
            company=self.company,
            product_code="S-READY",
            product_type="Walmasta",
            selling_price=Decimal("100"),
            gst_rate=Decimal("18.00"),
            hsn_code="3208",
        )
        _product(
            company=self.company,
            product_code="S-PRICE",
            product_type="Walmasta",
            gst_rate=Decimal("18.00"),
            hsn_code="3208",
        )
        _product(
            company=self.company,
            product_code="S-RATE",
            product_type="Blade",
            selling_price=Decimal("100"),
            hsn_code="3208",
        )
        _product(
            company=self.company,
            product_code="S-HSN",
            product_type="Blade",
            selling_price=Decimal("100"),
            gst_rate=Decimal("18.00"),
        )
        _product(
            company=self.company,
            product_code="S-PRICE-HSN",
            product_type="Blade",
            gst_rate=Decimal("18.00"),
        )
        _product(
            company=self.company,
            product_code="S-RATEINACT-HSN",
            product_type="Sandpaper",
            selling_price=Decimal("100"),
            gst_rate=Decimal("5.00"),
        )
        _product(company=self.company, product_code="S-ALL", product_type="Putty")
        _product(
            company=self.company, product_code="S-INACTIVE", product_type="Putty", is_active=False
        )

    def test_summary_counts_with_overlap(self):
        response = self.client.get(READINESS_SUMMARY_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        data = response.json()
        self.assertEqual(data["active_products"], 7)
        self.assertEqual(data["billing_ready"], 1)
        self.assertEqual(data["not_billing_ready"], 6)
        self.assertEqual(data["billing_ready"] + data["not_billing_ready"], data["active_products"])
        missing = data["missing"]
        self.assertEqual(missing["selling_price"], 3)
        self.assertEqual(missing["gst_rate"], 2)
        self.assertEqual(missing["gst_rate_inactive"], 1)
        self.assertEqual(missing["hsn_code"], 4)
        self.assertEqual(sum(missing.values()), 10)  # reasons overlap: more than not_billing_ready

    def test_inactive_products_excluded_from_summary(self):
        response = self.client.get(READINESS_SUMMARY_URL)
        self.assertEqual(response.json()["active_products"], 7)


class TestCatalogQueryCounts(TestCase):
    """Each endpoint runs a constant number of queries for 1 and 50 rows."""

    def setUp(self):
        self.client = _auth_client()
        _gst_rate("18.00", "Standard", True)
        self.company = _company(name="Query Co")

    def _query_count(self, url, params=None):
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(url, params or {})
        return len(ctx.captured_queries)

    def test_companies_constant_queries(self):
        for i in range(50):
            _product(company=self.company, product_code=f"CQ-{i:02d}")
        one = self._query_count(COMPANIES_URL, {"page_size": 1})
        fifty = self._query_count(COMPANIES_URL, {"page_size": 50, "include_inactive": "true"})
        self.assertEqual(one, fifty)

    def test_readiness_constant_queries(self):
        for i in range(50):
            _product(company=self.company, product_code=f"RQ-{i:02d}")
        one = self._query_count(READINESS_URL, {"page_size": 1})
        fifty = self._query_count(READINESS_URL, {"page_size": 50})
        self.assertEqual(one, fifty)

    def test_summary_constant_queries(self):
        one = self._query_count(READINESS_SUMMARY_URL)
        fifty = self._query_count(READINESS_SUMMARY_URL)
        self.assertEqual(one, fifty)


class TestCatalogRoutes(TestCase):
    """Existing routes unchanged; new routes mounted with trailing slash."""

    def test_product_and_company_route_names_unchanged(self):
        self.assertEqual(reverse("catalog:product-list"), PRODUCT_LIST_URL)
        self.assertEqual(reverse("catalog:company-list"), COMPANY_LIST_URL)

    def test_new_routes_resolve(self):
        resolve(COMPANIES_URL)
        resolve(READINESS_URL)
        resolve(READINESS_SUMMARY_URL)

    def test_missing_trailing_slash_returns_404(self):
        for url in (COMPANIES_URL, READINESS_URL, READINESS_SUMMARY_URL):
            with self.subTest(url=url):
                response = self.client.get(url.rstrip("/"))
                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, response.content)
