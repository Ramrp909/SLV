"""Tests for exceptions.py - standard error format."""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import TestCase
from rest_framework import status
from rest_framework.exceptions import (
    AuthenticationFailed,
    MethodNotAllowed,
    NotAuthenticated,
    NotFound,
    ParseError,
    PermissionDenied,
    Throttled,
    ValidationError,
)
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


class TestExtendedExceptionHandler(TestCase):
    """Additional exception types handled in the standard format."""

    def _handle(self, exc, path="/api/test/"):
        factory = APIRequestFactory()
        request = factory.get(path)
        drf_request = Request(request)
        return custom_exception_handler(exc, {"request": drf_request})

    def _rendered_text(self, response):
        from rest_framework.renderers import JSONRenderer

        response.accepted_renderer = JSONRenderer()
        response.accepted_media_type = "application/json"
        response.renderer_context = {}
        response.render()
        return response.content.decode("utf-8")

    def test_django_validation_error(self):
        exc = DjangoValidationError({"rate": ["Rate must be between 0 and 100."]})
        response = self._handle(exc)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["code"] == "VALIDATION_ERROR"
        assert response.data["fields"]["rate"] == "Rate must be between 0 and 100."

    def test_method_not_allowed(self):
        exc = MethodNotAllowed("POST")
        response = self._handle(exc)
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert response.data["code"] == "METHOD_NOT_ALLOWED"

    def test_not_authenticated(self):
        exc = NotAuthenticated()
        response = self._handle(exc)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data["code"] == "AUTHENTICATION_FAILED"

    def test_parse_error(self):
        exc = ParseError("Malformed JSON")
        response = self._handle(exc)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["code"] == "VALIDATION_ERROR"

    def test_permission_denied(self):
        exc = PermissionDenied("You do not have permission")
        response = self._handle(exc)
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data["code"] == "PERMISSION_DENIED"

    def test_throttled_keeps_retry_after(self):
        exc = Throttled()
        exc.wait = 5
        response = self._handle(exc)
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert response.data["code"] == "THROTTLED"
        assert response["Retry-After"] == "5"

    def test_unexpected_error_logs_traceback_and_leaks_nothing(self):
        factory = APIRequestFactory()
        request = factory.get("/api/test/")
        drf_request = Request(request)
        # DRF invokes the handler inside an ``except`` block, so sys.exc_info()
        # is active and the traceback is logged server side.
        try:
            raise ValueError("boom")
        except ValueError as exc:
            with self.assertLogs("common.exceptions", level="ERROR") as cm:
                response = custom_exception_handler(exc, {"request": drf_request})

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.data["code"] == "INTERNAL_ERROR"
        assert response.data["message"] == "An unexpected error occurred"
        assert response.data["fields"] == {}
        assert any("Traceback" in line for line in cm.output), cm.output

        text = self._rendered_text(response)
        assert "Traceback" not in text
        assert "common/exceptions.py" not in text
        assert "ValueError" not in text

    def test_no_stack_trace_in_any_error_response(self):
        for exc, status_code in [
            (ValidationError({"x": ["bad"]}), status.HTTP_400_BAD_REQUEST),
            (NotFound("missing"), status.HTTP_404_NOT_FOUND),
            (PermissionDenied("no"), status.HTTP_403_FORBIDDEN),
            (MethodNotAllowed("DELETE"), status.HTTP_405_METHOD_NOT_ALLOWED),
        ]:
            response = self._handle(exc)
            assert response.status_code == status_code
            text = self._rendered_text(response)
            assert "Traceback" not in text
            assert ".py" not in text
