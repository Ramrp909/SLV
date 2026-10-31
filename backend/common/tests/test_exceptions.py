"""Tests for exceptions.py - standard error format."""

from django.test import TestCase
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from common.exceptions import custom_exception_handler
from common.money import D


class TestCustomExceptionHandler(TestCase):
    """Tests for custom_exception_handler returning standard error format."""

    def test_validation_error_format(self):
        factory = APIRequestFactory()
        request = factory.post("/api/test/")
        drf_request = Request(request)

        exc = ValidationError({"field": ["This field is required."]})
        response = custom_exception_handler(exc, {"request": drf_request})

        assert response is not None
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        data = response.data
        assert "code" in data
        assert "message" in data
        assert "fields" in data
        assert data["code"] == "VALIDATION_ERROR"

    def test_not_found_error_format(self):
        factory = APIRequestFactory()
        request = factory.get("/api/test/999/")
        drf_request = Request(request)

        exc = NotFound("Object not found")
        response = custom_exception_handler(exc, {"request": drf_request})

        assert response is not None
        assert response.status_code == status.HTTP_404_NOT_FOUND
        data = response.data
        assert data["code"] == "NOT_FOUND"
        assert "message" in data
        assert "fields" in data

    def test_authentication_error_format(self):
        factory = APIRequestFactory()
        request = factory.get("/api/test/")
        drf_request = Request(request)

        exc = AuthenticationFailed("Invalid token")
        response = custom_exception_handler(exc, {"request": drf_request})

        assert response is not None
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        data = response.data
        assert data["code"] == "AUTHENTICATION_FAILED"
        assert "message" in data
        assert "fields" in data

    def test_unexpected_error_format(self):
        factory = APIRequestFactory()
        request = factory.get("/api/test/")
        drf_request = Request(request)

        exc = Exception("Something went wrong")
        response = custom_exception_handler(exc, {"request": drf_request})

        assert response is not None
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        data = response.data
        assert data["code"] == "INTERNAL_ERROR"
        assert "message" in data
        assert "fields" in data


class TestDecimalInResponse(TestCase):
    """Tests that Decimal values in API responses are returned as strings."""

    def test_decimal_serialized_as_string(self):
        """DRF with COERCE_DECIMAL_TO_STRING=True should serialize Decimal as string."""
        from rest_framework.serializers import DecimalField, Serializer

        class TestSerializer(Serializer):
            amount = DecimalField(max_digits=10, decimal_places=2)

        serializer = TestSerializer({"amount": D("123.45")})
        data = serializer.data
        assert isinstance(data["amount"], str)
        assert data["amount"] == "123.45"
