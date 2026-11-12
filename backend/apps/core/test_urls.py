"""Test URL configuration for idempotency tests (mounted at /api/v1/ for tests only)."""

import time
from threading import Event, Lock

from django.urls import path
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.idempotency import idempotent
from apps.core.models import AuditLog

# Module-level flags for controlling test behavior
_should_fail = False
_should_raise = False
_raise_operational_error = False
_raise_database_error = False
_wait_before_write = 0
_release_immediately = False


# Shared state for lock timeout test
_lock_held = Lock()
_lock_holder_thread = None

# Different advisory lock key used to test that the handler runs with the
# normal database timeout (lock_timeout restored after the idempotency insert).
_different_lock_key = 999999
_wait_on_different_lock = False

# Event barriers for deterministic lock-timeout tests.
# _lock_started is set by the holder once its handler has entered (advisory lock
# is held at that point). _lock_release is set by the test to let the holder
# complete. _lock_handler_calls counts handler executions across thread instances.
_lock_started = Event()
_lock_release = Event()
_lock_handler_calls = 0
_lock_handler_lock = Lock()


def _reset_test_flags():
    """Reset all test flags to default values."""
    global \
        _should_fail, \
        _should_raise, \
        _raise_operational_error, \
        _raise_database_error, \
        _wait_before_write, \
        _release_immediately
    _should_fail = False
    _should_raise = False
    _raise_operational_error = False
    _raise_database_error = False
    _wait_before_write = 0
    _release_immediately = False


class _IdempotencyTestView(APIView):
    """Test view that uses the @idempotent decorator for POST /test-idempotency/."""

    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.handler_call_count = 0

    @idempotent
    def post(self, request):
        global _should_fail, _should_raise, _wait_before_write
        self.handler_call_count += 1
        # Simulate some work
        if _should_fail:
            return Response(
                {"code": "VALIDATION_ERROR", "message": "Intentional failure", "fields": {}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if _should_raise:
            raise Exception("Intentional exception")
        if _wait_before_write > 0:
            time.sleep(_wait_before_write)
        # Write a test record to simulate business logic
        AuditLog.objects.create(
            action="test.idempotency_write",
            entity_type="Test",
            entity_id=str(self.handler_call_count),
            summary="Test write",
        )
        return Response(
            {"result": "success", "count": self.handler_call_count}, status=status.HTTP_201_CREATED
        )

    @idempotent
    def put(self, request):
        """Different HTTP method on same path for testing method differentiation."""
        self.handler_call_count += 1
        AuditLog.objects.create(
            action="test.idempotency_write_put",
            entity_type="Test",
            entity_id=str(self.handler_call_count),
            summary="Test write PUT",
        )
        return Response(
            {"result": "success", "count": self.handler_call_count, "method": "PUT"},
            status=status.HTTP_201_CREATED,
        )


class _IdempotencyTestViewOtherPath(APIView):
    """Test view on a different path for testing path differentiation."""

    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.handler_call_count = 0

    @idempotent
    def post(self, request):
        self.handler_call_count += 1
        AuditLog.objects.create(
            action="test.idempotency_write_other",
            entity_type="Test",
            entity_id=str(self.handler_call_count),
            summary="Test write other path",
        )
        return Response(
            {"result": "success", "count": self.handler_call_count, "path": "other"},
            status=status.HTTP_201_CREATED,
        )


class _IdempotencyLockTimeoutView(APIView):
    """Test view for lock timeout testing - holds the advisory lock until released."""

    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.handler_call_count = 0

    @idempotent
    def post(self, request):
        global _lock_started, _lock_release, _lock_handler_calls
        self.handler_call_count += 1
        with _lock_handler_lock:
            _lock_handler_calls += 1
        # Signal that the handler has started. Because the handler runs inside
        # the idempotent transaction (advisory lock held), a concurrent request
        # with the same key blocks on pg_advisory_xact_lock from this point on.
        _lock_started.set()
        # Wait for the test to release us; this holds the advisory lock and the
        # transaction open, simulating a long-running request.
        _lock_release.wait(timeout=10)

        AuditLog.objects.create(
            action="test.idempotency_lock_timeout",
            entity_type="Test",
            entity_id=str(self.handler_call_count),
            summary="Test lock timeout",
        )
        return Response(
            {"result": "success", "count": self.handler_call_count},
            status=status.HTTP_201_CREATED,
        )


class _IdempotencyDifferentLockView(APIView):
    """Test view whose handler waits on a *different* advisory lock.

    Used to verify that lock_timeout is restored before the handler runs:
    with IDEMPOTENCY_LOCK_TIMEOUT_MS set small, the handler's wait on a
    different lock must NOT fail with 55P03/IDEMPOTENCY_IN_PROGRESS.
    """

    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.handler_call_count = 0

    @idempotent
    def post(self, request):
        global _wait_on_different_lock
        self.handler_call_count += 1
        if _wait_on_different_lock:
            from django.db import transaction

            with transaction.get_connection().cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_different_lock_key])

        AuditLog.objects.create(
            action="test.idempotency_different_lock",
            entity_type="Test",
            entity_id=str(self.handler_call_count),
            summary="Test different lock",
        )
        return Response(
            {"result": "success", "count": self.handler_call_count},
            status=status.HTTP_201_CREATED,
        )


class _IdempotencyErrorView(APIView):
    """Test view that can raise various errors for testing error handling."""

    permission_classes = [IsAuthenticated]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.handler_call_count = 0

    @idempotent
    def post(self, request):
        global _raise_operational_error, _raise_database_error, _should_fail, _should_raise
        self.handler_call_count += 1

        if _raise_operational_error:
            from django.db import OperationalError

            raise OperationalError("Some other operational error")

        if _raise_database_error:
            from django.db import DatabaseError

            raise DatabaseError("Some database error")

        if _should_fail:
            return Response(
                {"code": "VALIDATION_ERROR", "message": "Intentional failure", "fields": {}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if _should_raise:
            raise Exception("Intentional exception")

        AuditLog.objects.create(
            action="test.idempotency_error_write",
            entity_type="Test",
            entity_id=str(self.handler_call_count),
            summary="Test error write",
        )
        return Response(
            {"result": "success", "count": self.handler_call_count},
            status=status.HTTP_201_CREATED,
        )


# URL patterns - only used when ROOT_URLCONF is overridden in tests
urlpatterns = [
    path("api/v1/test-idempotency/", _IdempotencyTestView.as_view(), name="test-idempotency"),
    path(
        "api/v1/test-idempotency-other/",
        _IdempotencyTestViewOtherPath.as_view(),
        name="test-idempotency-other",
    ),
    path(
        "api/v1/test-lock-timeout/", _IdempotencyLockTimeoutView.as_view(), name="test-lock-timeout"
    ),
    path(
        "api/v1/test-different-lock/",
        _IdempotencyDifferentLockView.as_view(),
        name="test-different-lock",
    ),
    path("api/v1/test-error/", _IdempotencyErrorView.as_view(), name="test-error"),
]
