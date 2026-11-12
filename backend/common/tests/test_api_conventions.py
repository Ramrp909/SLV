"""API conventions: pagination, filtering, search, ordering and Decimal-as-string.

Uses a test-only list view (never added to production URLs) backed by GstRate.
Rows are created per test in setUp so they roll back and never pollute the
shared test database.
"""

from django.test import TestCase
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, serializers
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.test import APIRequestFactory

from apps.core.models import GstRate
from common.pagination import StandardPagination


class _RateSerializer(serializers.ModelSerializer):
    class Meta:
        model = GstRate
        fields = ["rate", "label", "is_active"]


class _RateList(generics.ListAPIView):
    """Test-only list view - not registered in production URLs."""

    queryset = GstRate.objects.all()
    serializer_class = _RateSerializer
    permission_classes = []
    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["is_active"]
    search_fields = ["label"]
    ordering_fields = ["rate"]
    ordering = ["rate"]


class TestApiConventions(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        GstRate.objects.all().delete()
        GstRate.objects.create(rate="0.01", label="Rate 1%", is_active=True)
        GstRate.objects.create(rate="0.05", label="Rate 5%", is_active=True)
        GstRate.objects.create(rate="0.10", label="Rate 10%", is_active=False)
        GstRate.objects.create(rate="0.50", label="Rate 50%", is_active=False)
        GstRate.objects.create(rate="1.00", label="Rate 100%", is_active=True)

    def _call(self, **params):
        request = self.factory.get("/api/test-rates/", params)
        view = _RateList.as_view()
        return view(request)

    def test_page_and_page_size(self):
        response = self._call(page=1, page_size=3)
        self.assertEqual(response.status_code, 200)
        data = response.data
        self.assertEqual(data["count"], 5)
        self.assertEqual(len(data["results"]), 3)
        self.assertEqual(data["results"][0]["rate"], "0.01")
        self.assertIsNone(data["previous"])
        self.assertIsNotNone(data["next"])

    def test_page_2(self):
        response = self._call(page=2, page_size=2)
        self.assertEqual(len(response.data["results"]), 2)
        self.assertEqual(response.data["results"][0]["rate"], "0.10")

    def test_page_size_capped_at_100(self):
        GstRate.objects.all().delete()
        for i in range(1, 102):
            GstRate.objects.create(rate=f"{i / 100:.2f}", label=f"Rate {i}%", is_active=(i <= 10))
        response = self._call(page=1, page_size=200)
        self.assertEqual(response.data["count"], 101)
        self.assertEqual(len(response.data["results"]), 100)

    def test_ordering_descending(self):
        response = self._call(ordering="-rate")
        self.assertEqual(response.data["results"][0]["rate"], "1.00")

    def test_ordering_ascending(self):
        response = self._call(ordering="rate")
        self.assertEqual(response.data["results"][0]["rate"], "0.01")

    def test_search(self):
        response = self._call(search="Rate 1%")
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["label"], "Rate 1%")

        response = self._call(search="nonexistent")
        self.assertEqual(response.data["count"], 0)

    def test_django_filter(self):
        response = self._call(is_active=True)
        self.assertEqual(response.data["count"], 3)

        response = self._call(is_active=False)
        self.assertEqual(response.data["count"], 2)

    def test_decimal_fields_come_back_as_strings(self):
        response = self._call(page=1, page_size=5)
        for item in response.data["results"]:
            self.assertIsInstance(item["rate"], str)
        self.assertEqual(response.data["results"][0]["rate"], "0.01")


class TestPaginationDefaults(TestCase):
    def test_defaults(self):
        pagination = StandardPagination()
        self.assertEqual(pagination.page_size, 25)
        self.assertEqual(pagination.max_page_size, 100)
        self.assertEqual(pagination.page_query_param, "page")
        self.assertEqual(pagination.page_size_query_param, "page_size")
