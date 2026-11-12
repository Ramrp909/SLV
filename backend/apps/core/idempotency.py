"""Idempotency mechanism for create endpoints.

Provides a decorator @idempotent for DRF view methods that require
Idempotency-Key header and prevent duplicate processing.
"""

import hashlib
import json
import uuid
from functools import wraps

from common.errors import (
    IDEMPOTENCY_IN_PROGRESS,
    IDEMPOTENCY_KEY_INVALID,
    IDEMPOTENCY_KEY_REQUIRED,
    IDEMPOTENCY_KEY_REUSED,
)
from django.conf import settings
from django.db import IntegrityError, transaction
from drf_spectacular.utils import OpenApiParameter
from rest_framework import status
from rest_framework.response import Response

from apps.core.models import IdempotencyRecord
from apps.core.services import _json_safe

# OpenAPI parameter for Idempotency-Key header
IDEMPOTENCY_KEY_PARAMETER = OpenApiParameter(
    name="Idempotency-Key",
    location=OpenApiParameter.HEADER,
    description="Idempotency key (UUID). Required for create endpoints. "
    "Same key with same payload returns cached response. "
    "Same key with different payload returns 409.",
    required=True,
    type=str,
)


def compute_request_hash(
    method: str,
    path: str,
    body: dict | None,
    query_string: str | None,
) -> str:
    """
    Compute SHA-256 hash of request for idempotency comparison.

    Hash includes: method + path + canonical JSON body + sorted query string.
    Canonical JSON: sorted keys, no whitespace, unicode-safe.
    Decimals and numbers compared as sent (not normalized).

    Args:
        method: HTTP method (e.g., "POST")
        path: Request path (e.g., "/api/v1/invoices/")
        body: Request body as dict (already parsed from JSON)
        query_string: Raw query string (e.g., "foo=bar&baz=qux")

    Returns:
        SHA-256 hex digest (64 characters)
    """
    # Canonical JSON body
    if body is None:
        body_json = ""
    else:
        body_json = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    # Sort query string parameters for consistency
    if query_string:
        # Parse and sort query parameters
        params = []
        for pair in query_string.split("&"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                params.append((k, v))
            else:
                params.append((pair, ""))
        params.sort()
        query_canonical = "&".join(f"{k}={v}" for k, v in params)
    else:
        query_canonical = ""

    # Combine all components
    combined = f"{method}|{path}|{body_json}|{query_canonical}"

    # Compute SHA-256
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def _get_client_ip(request) -> str:
    """Extract client IP from request."""
    if request is None:
        return "127.0.0.1"
    return request.META.get("REMOTE_ADDR", "127.0.0.1")


def compute_advisory_lock_key(user_id: int | None, key_uuid: uuid.UUID) -> int:
    """
    Compute a stable 64-bit advisory lock key from (user_id, key).

    Uses hashlib.sha256, never Python's built-in hash() (which is randomized
    per process via PYTHONHASHSEED), so the same input always yields the same
    key regardless of interpreter or PYTHONHASHSEED. The value is masked to a
    positive int64 for pg_advisory_xact_lock.

    The advisory lock is transaction-level (pg_advisory_xact_lock): it is
    released automatically when the transaction commits or rolls back, so it
    cannot outlive the request and cause a permanent stall.

    Why the advisory lock exists at all: the unique constraint on
    (user_id, key) is the source of correctness - it guarantees at most one
    IdempotencyRecord per user/key and the replay path verifies
    method/path/request_hash before replaying, so a concurrent duplicate can
    never re-run the handler. The advisory lock only changes *timing*: it makes
    a contended request block and, once lock_timeout elapses, fail fast with
    LockNotAvailable (SQLSTATE 55P03) instead of waiting indefinitely. That
    error is mapped to 409 IDEMPOTENCY_IN_PROGRESS with Retry-After: 2.

    A hash collision may only cause unrelated (user, key) pairs to serialize on
    the same advisory lock (extra waiting). It can never cause a wrong replay.

    Args:
        user_id: Authenticated user id (may be None).
        key_uuid: Parsed Idempotency-Key UUID.

    Returns:
        Positive 64-bit integer suitable for pg_advisory_xact_lock.
    """
    payload = f"{user_id}:{key_uuid}".encode()
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "big", signed=False) & 0x7FFFFFFFFFFFFFFF


def _postgres_sqlstate(exc: BaseException) -> str | None:
    """
    Return the PostgreSQL SQLSTATE for an exception, walking the cause chain.

    Django wraps native driver errors (psycopg) into
    django.db.utils exceptions, so the SQLSTATE may live on the original
    exception chained via __cause__/__context__ rather than on the surface
    exception. LockNotAvailable is SQLSTATE 55P03.
    """
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        code = getattr(current, "pgcode", None) or getattr(current, "sqlstate", None)
        if code:
            return str(code)
        current = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
    return None


def idempotent(view_func):
    """
    Decorator for DRF view methods to enforce idempotency.

    Behavior:
    1. Requires Idempotency-Key header (valid UUID)
    2. Computes request hash from method, path, body, query string
    3. Acquires advisory lock on (user_id, key) to serialize concurrent requests
    4. Opens ONE transaction.atomic() with lock_timeout for the INSERT
       - If IntegrityError (key exists):
         * Transaction rolls back automatically
         * Read existing record in a fresh transaction
         * If response_status == 0 -> 409 IDEMPOTENCY_IN_PROGRESS (handler still running)
         * If hash/method/path differs -> 409 IDEMPOTENCY_KEY_REUSED
         * Else -> replay stored response with Idempotent-Replayed: true
       - If LockNotAvailable (SQLSTATE 55P03) -> 409 IDEMPOTENCY_IN_PROGRESS with Retry-After: 2
    4. If INSERT succeeds, run handler in the same transaction:
       - If 2xx: save response_status/body, commit
       - If 4xx/5xx: rollback (record deleted), return error
       - If exception: rollback (record deleted), re-raise

    The decorator must run AFTER authentication (request.user must be set).
    """

    @wraps(view_func)
    def wrapper(view_instance, request, *args, **kwargs):
        # 1. Check Idempotency-Key header
        idempotency_key = request.headers.get("Idempotency-Key")
        if not idempotency_key:
            return Response(
                {
                    "code": IDEMPOTENCY_KEY_REQUIRED,
                    "message": "Idempotency-Key header is required",
                    "fields": {},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 2. Validate UUID format
        try:
            key_uuid = uuid.UUID(idempotency_key)
        except ValueError:
            return Response(
                {
                    "code": IDEMPOTENCY_KEY_INVALID,
                    "message": "Idempotency-Key must be a valid UUID",
                    "fields": {},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 3. Get user_id (must be authenticated)
        if not hasattr(request, "user") or not request.user.is_authenticated:
            # Let DRF's authentication handle this - return 401
            pass

        user_id = request.user.id if request.user.is_authenticated else None

        # 4. Compute request hash
        method = request.method
        path = request.path
        body = request.data if hasattr(request, "data") else None
        query_string = request.META.get("QUERY_STRING", "")
        request_hash = compute_request_hash(method, path, body, query_string)

        # Get lock timeout from settings (default 10000ms = 10s)
        lock_timeout_ms = getattr(settings, "IDEMPOTENCY_LOCK_TIMEOUT_MS", 10000)

        # Compute advisory lock key from user_id and key_uuid
        # Use a STABLE hash (hashlib, never Python's built-in hash()) so the key
        # is identical across processes and PYTHONHASHSEED values.
        lock_key = compute_advisory_lock_key(user_id, key_uuid)

        # Acquire advisory lock for the duration of the transaction
        # This serializes concurrent requests with the same key. lock_timeout is
        # set BEFORE pg_advisory_xact_lock so a contended acquisition fails fast
        # with SQLSTATE 55P03 instead of waiting indefinitely. The original
        # lock_timeout is saved with SHOW lock_timeout and restored before the
        # handler runs (SET LOCAL in a finally block) so the business handler
        # executes with the normal database timeout, not the short advisory-lock
        # timeout.
        original_timeout: str | None = None
        with transaction.atomic():
            with transaction.get_connection().cursor() as cursor:
                cursor.execute("SHOW lock_timeout")
                original_timeout = cursor.fetchone()[0]
                cursor.execute(
                    "SET LOCAL lock_timeout = %s",
                    [f"{lock_timeout_ms}ms"],
                )
                try:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_key])
                except Exception as exc:  # noqa: BLE001 - map only SQLSTATE 55P03 to 409
                    # LockNotAvailable is SQLSTATE 55P03. Django wraps native
                    # driver errors, so detect via the SQLSTATE chain rather
                    # than by exception type. Any other error is re-raised.
                    if _postgres_sqlstate(exc) == "55P03":
                        # Could not acquire the advisory lock within lock_timeout:
                        # another request with the same key is still being processed.
                        transaction.set_rollback(True)
                        response = Response(
                            {
                                "code": IDEMPOTENCY_IN_PROGRESS,
                                "message": (
                                    "Another request with the same Idempotency-Key "
                                    "is in progress. Please retry."
                                ),
                                "fields": {},
                            },
                            status=status.HTTP_409_CONFLICT,
                        )
                        response["Retry-After"] = "2"
                        return response
                    raise

            # Try to create the idempotency record
            try:
                record = IdempotencyRecord.objects.create(
                    user_id=user_id,
                    key=key_uuid,
                    method=method,
                    path=path,
                    request_hash=request_hash,
                    response_status=0,  # Placeholder, updated after handler
                    response_body={},  # Placeholder
                )
            except IntegrityError:
                # Key already exists - transaction will roll back
                # The advisory lock ensures we wait for the other transaction to complete
                # If we reach here, the other transaction has committed or rolled back
                pass  # Fall through to replay logic below

            # Record created successfully - run the handler
            else:
                # Restore lock_timeout before running the handler so it uses
                # the normal database timeout, not the short advisory-lock timeout.
                try:
                    with transaction.get_connection().cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = %s", [original_timeout])
                finally:
                    pass

                response = view_func(view_instance, request, *args, **kwargs)

                if not isinstance(response, Response):
                    response = Response(response)

                if 200 <= response.status_code < 300:
                    # Success - update record and commit
                    record.response_status = response.status_code
                    response_data = response.data if hasattr(response, "data") else {}
                    record.response_body = _json_safe(response_data)
                    record.save()
                    return response
                else:
                    # Error response (4xx, 5xx) - rollback (record deleted)
                    transaction.set_rollback(True)
                    return response

        # If we reach here, it means IntegrityError occurred (key already exists)
        # The advisory lock ensures we wait for the other transaction to complete
        # The other transaction has completed (committed or rolled back) due to advisory lock
        # Read existing record in a fresh transaction
        with transaction.atomic():
            existing = IdempotencyRecord.objects.get(user_id=user_id, key=key_uuid)
            # If response_status is 0, the original request is still being processed
            # (shouldn't happen with advisory lock, but handle anyway)
            if existing.response_status == 0:
                response = Response(
                    {
                        "code": IDEMPOTENCY_IN_PROGRESS,
                        "message": "Another request with the same Idempotency-Key is in progress. Please retry.",
                        "fields": {},
                    },
                    status=status.HTTP_409_CONFLICT,
                )
                response["Retry-After"] = "2"
                return response
            if (
                existing.request_hash != request_hash
                or existing.method != method
                or existing.path != path
            ):
                return Response(
                    {
                        "code": IDEMPOTENCY_KEY_REUSED,
                        "message": (
                            "Idempotency-Key already used with a different request "
                            "(method, path, or payload differs from original)"
                        ),
                        "fields": {},
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            # Same request - replay the stored response
            response = Response(
                existing.response_body,
                status=existing.response_status,
            )
            response["Idempotent-Replayed"] = "true"
            return response

    return wrapper
