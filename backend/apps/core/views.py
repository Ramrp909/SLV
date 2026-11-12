"""Views for core app."""

from common.errors import (
    METHOD_NOT_ALLOWED,
    NOT_FOUND,
    VALIDATION_ERROR,
)
from common.pagination import StandardPagination
from django.http import JsonResponse
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import AppSettings, AuditLog, GstRate
from apps.core.serializers import (
    AppSettingsSerializer,
    AuditLogSerializer,
    GstRateCreateSerializer,
    GstRateSerializer,
)


class HealthCheckView(APIView):
    """Health check endpoint - no authentication required."""

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        tags=["system"],
        summary="Health check",
        description="Returns OK status. No authentication required.",
        responses={
            200: OpenApiResponse(description="Health status"),
        },
        auth=[],
    )
    def get(self, request):
        return Response({"status": "ok"}, status=status.HTTP_200_OK)


def api_404_view(request, exception=None):
    """Return JSON 404 for API routes."""
    if request.path.startswith("/api/"):
        return JsonResponse(
            {
                "code": NOT_FOUND,
                "message": "Not found",
                "fields": {},
            },
            status=404,
        )
    # For non-API paths, fall back to Django's default 404
    from django.shortcuts import render

    return render(request, "404.html", status=404)


@extend_schema(
    tags=["settings"],
    summary="Get settings",
    description="Get the single row of app settings.",
    responses={
        200: AppSettingsSerializer,
        401: OpenApiResponse(description="Unauthenticated"),
    },
)
class SettingsView(APIView):
    """GET and PUT /api/v1/settings/ - single row settings."""

    permission_classes = [IsAuthenticated]
    serializer_class = AppSettingsSerializer

    def get(self, request):
        settings = AppSettings.get_settings()
        serializer = AppSettingsSerializer(settings)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["settings"],
        summary="Update settings",
        description="Partially update app settings. Only provided fields are updated.",
        request=AppSettingsSerializer,
        responses={
            200: AppSettingsSerializer,
            400: OpenApiResponse(description="Validation error"),
            401: OpenApiResponse(description="Unauthenticated"),
        },
    )
    def put(self, request):
        settings = AppSettings.get_settings()
        serializer = AppSettingsSerializer(settings, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    tags=["settings"],
    summary="List GST rates",
    description="List all approved GST rates.",
    responses={
        200: OpenApiResponse(description="Paginated list of GST rates"),
        401: OpenApiResponse(description="Unauthenticated"),
    },
)
class GstRateListView(APIView):
    """GET and POST /api/v1/settings/gst-rates/."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        rates = GstRate.objects.all().order_by("rate")
        serializer = GstRateSerializer(rates, many=True)
        return Response({"results": serializer.data}, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["settings"],
        summary="Create GST rate",
        description="Create a new approved GST rate. Rate value is immutable once created.",
        request=GstRateCreateSerializer,
        responses={
            201: GstRateCreateSerializer,
            400: OpenApiResponse(description="Validation error - duplicate rate or invalid value"),
            401: OpenApiResponse(description="Unauthenticated"),
        },
    )
    def post(self, request):
        serializer = GstRateCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["settings"],
    summary="Update GST rate",
    description="Update label or is_active of a GST rate. Rate value cannot be changed.",
    request=GstRateSerializer,
    responses={
        200: GstRateSerializer,
        400: OpenApiResponse(description="Validation error - rate value cannot be changed"),
        401: OpenApiResponse(description="Unauthenticated"),
        404: OpenApiResponse(description="GST rate not found"),
    },
)
class GstRateDetailView(APIView):
    """PUT /api/v1/settings/gst-rates/{id}/ - update label or is_active only."""

    permission_classes = [IsAuthenticated]
    serializer_class = GstRateSerializer

    def put(self, request, pk):
        try:
            rate = GstRate.objects.get(pk=pk)
        except GstRate.DoesNotExist:
            return Response(
                {
                    "code": NOT_FOUND,
                    "message": "GST rate not found",
                    "fields": {},
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # Only allow updating label and is_active
        allowed_fields = {"label", "is_active"}
        update_data = {k: v for k, v in request.data.items() if k in allowed_fields}

        if not update_data:
            return Response(
                {
                    "code": VALIDATION_ERROR,
                    "message": "Only label and is_active can be updated",
                    "fields": {},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = GstRateSerializer(rate, data=update_data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    tags=["system"],
    summary="List audit log entries",
    description="List audit log entries with filtering. Read-only endpoint.",
    parameters=[
        OpenApiParameter(name="action", type=str, description="Filter by action"),
        OpenApiParameter(name="entity_type", type=str, description="Filter by entity type"),
        OpenApiParameter(name="entity_id", type=str, description="Filter by entity ID"),
        OpenApiParameter(
            name="date_from", type=str, description="Filter by date from (YYYY-MM-DD)"
        ),
        OpenApiParameter(name="date_to", type=str, description="Filter by date to (YYYY-MM-DD)"),
        OpenApiParameter(name="search", type=str, description="Search in summary"),
    ],
    responses={
        200: OpenApiResponse(description="Paginated list of audit log entries"),
        401: OpenApiResponse(description="Unauthenticated"),
        405: OpenApiResponse(description="Method not allowed"),
    },
)
class AuditLogView(APIView):
    """GET /api/v1/audit-log/ - read-only audit log."""

    permission_classes = [IsAuthenticated]
    serializer_class = AuditLogSerializer
    pagination_class = StandardPagination

    def get(self, request):
        queryset = AuditLog.objects.all()

        # Filter by action
        action = request.query_params.get("action")
        if action:
            queryset = queryset.filter(action=action)

        # Filter by entity_type
        entity_type = request.query_params.get("entity_type")
        if entity_type:
            queryset = queryset.filter(entity_type=entity_type)

        # Filter by entity_id
        entity_id = request.query_params.get("entity_id")
        if entity_id:
            queryset = queryset.filter(entity_id=entity_id)

        # Filter by date_from
        date_from = request.query_params.get("date_from")
        if date_from:
            queryset = queryset.filter(timestamp__date__gte=date_from)

        # Filter by date_to
        date_to = request.query_params.get("date_to")
        if date_to:
            queryset = queryset.filter(timestamp__date__lte=date_to)

        # Search in summary
        search = request.query_params.get("search")
        if search:
            queryset = queryset.filter(summary__icontains=search)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        serializer = AuditLogSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        return Response(
            {"code": METHOD_NOT_ALLOWED, "message": "POST not allowed", "fields": {}},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def put(self, request):
        return Response(
            {"code": METHOD_NOT_ALLOWED, "message": "PUT not allowed", "fields": {}},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def patch(self, request):
        return Response(
            {"code": METHOD_NOT_ALLOWED, "message": "PATCH not allowed", "fields": {}},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def delete(self, request):
        return Response(
            {"code": METHOD_NOT_ALLOWED, "message": "DELETE not allowed", "fields": {}},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )
