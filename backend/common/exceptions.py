"""Standard exception handling for Paint Shop Management System API.

Returns consistent error format:
{
    "code": "ERROR_CODE",
    "message": "Human-readable message",
    "fields": {"field_name": "error detail"}
}

Never includes stack traces, SQL or internal exception text in any response.
Unexpected exceptions are logged with the traceback server side and return a
generic 500 INTERNAL_ERROR.
"""

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    MethodNotAllowed,
    NotAuthenticated,
    NotFound,
    ParseError,
    PermissionDenied,
    Throttled,
    ValidationError,
)
from rest_framework.response import Response
from rest_framework.views import exception_handler

from common.errors import (
    AUTHENTICATION_FAILED,
    INTERNAL_ERROR,
    METHOD_NOT_ALLOWED,
    NOT_FOUND,
    PERMISSION_DENIED,
    THROTTLED,
    VALIDATION_ERROR,
)

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    """
    Custom exception handler returning standardized error format.

    Handles:
    - Django ValidationError -> VALIDATION_ERROR (400)
    - DRF ValidationError -> VALIDATION_ERROR (400)
    - ParseError -> VALIDATION_ERROR (400)
    - NotFound -> NOT_FOUND (404)
    - NotAuthenticated -> AUTHENTICATION_FAILED (401)
    - AuthenticationFailed -> AUTHENTICATION_FAILED (401)
    - PermissionDenied -> PERMISSION_DENIED (403)
    - MethodNotAllowed -> METHOD_NOT_ALLOWED (405)
    - Throttled -> THROTTLED (429, Retry-After header kept)
    - Unexpected exceptions -> INTERNAL_ERROR (500, logged server side)
    """
    # Django's ValidationError is not converted by DRF's default handler, so
    # handle it here as a 400 validation error before delegating to DRF.
    if isinstance(exc, DjangoValidationError):
        return _build_validation_error_response(exc)

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

    # Unhandled exception (500) - log the traceback server side, return generic
    # message to the client. Never leak stack traces, SQL or internals.
    logger.exception("Unhandled exception in API request")
    return Response(
        {
            "code": INTERNAL_ERROR,
            "message": "An unexpected error occurred",
            "fields": {},
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _build_validation_error_response(exc: DjangoValidationError) -> Response:
    """Build a 400 VALIDATION_ERROR response from a Django ValidationError."""
    message = "Validation failed"
    fields: dict = {}
    if hasattr(exc, "message_dict") and exc.message_dict:
        fields = {
            field: errors[0] if isinstance(errors, list) else str(errors)
            for field, errors in exc.message_dict.items()
        }
    elif hasattr(exc, "messages") and exc.messages:
        fields = {"non_field_errors": exc.messages[0]}
    return Response(
        {
            "code": VALIDATION_ERROR,
            "message": message,
            "fields": fields,
        },
        status=status.HTTP_400_BAD_REQUEST,
    )


def _get_error_code(exc) -> str:
    """Map exception type to error code."""
    if isinstance(exc, DjangoValidationError | ValidationError):
        return VALIDATION_ERROR
    elif isinstance(exc, NotFound):
        return NOT_FOUND
    elif isinstance(exc, NotAuthenticated | AuthenticationFailed):
        return AUTHENTICATION_FAILED
    elif isinstance(exc, PermissionDenied):
        return PERMISSION_DENIED
    elif isinstance(exc, MethodNotAllowed):
        return METHOD_NOT_ALLOWED
    elif isinstance(exc, Throttled):
        return THROTTLED
    elif isinstance(exc, ParseError):
        return VALIDATION_ERROR
    elif isinstance(exc, APIException):
        # Any other DRF APIException keeps its status but a generic code.
        return INTERNAL_ERROR
    return INTERNAL_ERROR


def _get_error_message(exc, response) -> str:
    """Extract human-readable message from exception."""
    if isinstance(exc, DjangoValidationError | ValidationError):
        return "Validation failed"
    elif isinstance(exc, NotFound):
        return str(exc.detail) if hasattr(exc, "detail") else "Resource not found"
    elif isinstance(exc, NotAuthenticated | AuthenticationFailed):
        return str(exc.detail) if hasattr(exc, "detail") else "Authentication failed"
    elif isinstance(exc, PermissionDenied):
        return str(exc.detail) if hasattr(exc, "detail") else "Permission denied"
    elif isinstance(exc, MethodNotAllowed):
        return str(exc.detail) if hasattr(exc, "detail") else "Method not allowed"
    elif isinstance(exc, Throttled):
        return f"Rate limit exceeded. Try again in {exc.wait} seconds."
    elif isinstance(exc, ParseError):
        return str(exc.detail) if hasattr(exc, "detail") else "Malformed request"
    return "An unexpected error occurred"


def _get_error_fields(exc, response) -> dict:
    """Extract field-specific errors from exception."""
    if isinstance(exc, DjangoValidationError):
        if hasattr(exc, "message_dict") and exc.message_dict:
            return {
                field: errors[0] if isinstance(errors, list) else str(errors)
                for field, errors in exc.message_dict.items()
            }
    if isinstance(exc, ValidationError) and hasattr(exc, "detail"):
        detail = exc.detail
        if isinstance(detail, dict):
            return {
                field: errors[0] if isinstance(errors, list) else str(errors)
                for field, errors in detail.items()
            }
        elif isinstance(detail, list):
            return {"non_field_errors": detail[0] if detail else "Validation failed"}
    return {}
