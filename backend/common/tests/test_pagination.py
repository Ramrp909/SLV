"""Tests for pagination.py."""

from django.test import TestCase
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from common.pagination import StandardPagination


class TestStandardPagination(TestCase):
    """Tests for StandardPagination class."""

    def test_default_page_size(self):
        pagination = StandardPagination()
        assert pagination.page_size == 25

    def test_max_page_size(self):
        pagination = StandardPagination()
        assert pagination.max_page_size == 100

    def test_page_query_param(self):
        pagination = StandardPagination()
        assert pagination.page_query_param == "page"

    def test_page_size_query_param(self):
        pagination = StandardPagination()
        assert pagination.page_size_query_param == "page_size"

    def test_custom_page_size_via_query(self):
        factory = APIRequestFactory()
        request = factory.get("/api/test/?page_size=50")
        drf_request = Request(request)

        pagination = StandardPagination()
        pagination.request = drf_request

        assert pagination.get_page_size(drf_request) == 50

    def test_page_size_capped_at_max(self):
        factory = APIRequestFactory()
        request = factory.get("/api/test/?page_size=200")
        drf_request = Request(request)

        pagination = StandardPagination()
        pagination.request = drf_request

        assert pagination.get_page_size(drf_request) == 100

    def test_invalid_page_size_falls_back_to_default(self):
        factory = APIRequestFactory()
        request = factory.get("/api/test/?page_size=abc")
        drf_request = Request(request)

        pagination = StandardPagination()
        pagination.request = drf_request

        assert pagination.get_page_size(drf_request) == 25
