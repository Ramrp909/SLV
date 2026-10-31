"""Standard exception handling for Paint Shop Management System API.

Returns consistent error format:
{
    "code": "ERROR_CODE",
    "message": "Human-readable message",
    "fields": {"field_name": "error detail"}
}
"""

from rest_framework import status
from rest_framework.exceptions import (
    AuthenticationFailed,
    NotFound,
    PermissionDenied,
    Throttled,
    ValidationError,
)
from rest_framework.response import Response
from rest_framework.views import exception_handler


def custom_exception_handler(exc, context):
    """
    Custom exception handler returning standardized error format.

    Handles:
    - ValidationError -> VALIDATION_ERROR (400)
    - NotFound -> NOT_FOUND (404)
    - AuthenticationFailed -> AUTHENTICATION_FAILED (401)
    - PermissionDenied -> PERMISSION_DENIED (403)
    - Throttled -> THROTTLED (429)
    - Unexpected exceptions -> INTERNAL_ERROR (500)
    """
    # Call DRF's default exception handler first
    response = exception_handler(exc, context)

    if response is not None:
        # DRF handled it, customize the response format
        error_code = _get_error_code(exc)
        message = _get_error_message(exc, response)
        fields = _get_error_fields(exc, response)

        custom_response_data = {
            "code": error_code,
            "message": message,
            "fields": fields,
        }

        response.data = custom_response_data
        return response

    # Unhandled exception (500)
    return Response(
        {
            "code": "INTERNAL_ERROR",
            "message": "An unexpected error occurred",
            "fields": {},
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _get_error_code(exc) -> str:
    """Map exception type to error code."""
    if isinstance(exc, ValidationError):
        return "VALIDATION_ERROR"
    elif isinstance(exc, NotFound):
        return "NOT_FOUND"
    elif isinstance(exc, AuthenticationFailed):
        return "AUTHENTICATION_FAILED"
    elif isinstance(exc, PermissionDenied):
        return "PERMISSION_DENIED"
    elif isinstance(exc, Throttled):
        return "THROTTLED"
    return "INTERNAL_ERROR"


def _get_error_message(exc, response) -> str:
    """Extract human-readable message from exception."""
    if isinstance(exc, ValidationError):
        return "Validation failed"
    elif isinstance(exc, NotFound):
        return str(exc.detail) if hasattr(exc, "detail") else "Resource not found"
    elif isinstance(exc, AuthenticationFailed):
        return str(exc.detail) if hasattr(exc, "detail") else "Authentication failed"
    elif isinstance(exc, PermissionDenied):
        return str(exc.detail) if hasattr(exc, "detail") else "Permission denied"
    elif isinstance(exc, Throttled):
        return f"Rate limit exceeded. Try again in {exc.wait} seconds."
    return "An unexpected error occurred"


def _get_error_fields(exc, response) -> dict:
    """Extract field-specific errors from exception."""
    if isinstance(exc, ValidationError) and hasattr(exc, "detail"):
        detail = exc.detail
        if isinstance(detail, dict):
            # Field-specific errors: {"field": ["error1", "error2"]}
            return {
                field: errors[0] if isinstance(errors, list) else str(errors)
                for field, errors in detail.items()
            }
        elif isinstance(detail, list):
            # Non-field errors: ["error1", "error2"]
            return {"non_field_errors": detail[0] if detail else "Validation failed"}
    return {}
