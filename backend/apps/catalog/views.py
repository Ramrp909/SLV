"""Views for catalog app: Company."""

from common.errors import METHOD_NOT_ALLOWED, NOT_FOUND, VALIDATION_ERROR
from common.pagination import StandardPagination
from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Company
from apps.catalog.serializers import CompanySerializer
from apps.catalog.services import CompanyService

ORDERING_FIELDS = {"name", "created_at", "-name", "-created_at"}
SEARCH_FIELDS = ("name", "gstin", "phone")


def _parse_bool_param(value, field_name):
    """Parse a boolean query parameter; return (value, error_response or None)."""
    if value is None:
        return None, None
    if value.lower() in ("true", "1"):
        return True, None
    if value.lower() in ("false", "0"):
        return False, None
    return None, Response(
        {
            "code": VALIDATION_ERROR,
            "message": f"{field_name} must be true or false.",
            "fields": {field_name: f"Invalid boolean value: {value}"},
        },
        status=status.HTTP_400_BAD_REQUEST,
    )


def _validate_ordering(value):
    """Validate ordering fields; return list of ordering fields or error response."""
    if not value:
        return ["name"], None
    fields = [part.strip() for part in value.split(",") if part.strip()]
    for field in fields:
        if field not in ORDERING_FIELDS:
            return None, Response(
                {
                    "code": VALIDATION_ERROR,
                    "message": f"Invalid ordering field: {field}",
                    "fields": {"ordering": f"Allowed fields: {', '.join(sorted(ORDERING_FIELDS))}"},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
    return fields, None


def _company_not_found():
    return Response(
        {"code": NOT_FOUND, "message": "Company not found", "fields": {}},
        status=status.HTTP_404_NOT_FOUND,
    )


def _method_not_allowed(message):
    return Response(
        {"code": METHOD_NOT_ALLOWED, "message": message, "fields": {}},
        status=status.HTTP_405_METHOD_NOT_ALLOWED,
    )


class CompanyListCreateView(APIView):
    """GET and POST /api/v1/companies/."""

    permission_classes = [IsAuthenticated]
    serializer_class = CompanySerializer
    pagination_class = StandardPagination

    @extend_schema(
        operation_id="companiesList",
        tags=["catalog"],
        summary="List companies",
        description="Paginated list of companies. Filters: is_active, is_local. Search: name, gstin, phone. Ordering: name, created_at (default name).",
        parameters=[
            OpenApiParameter(name="is_active", type=bool, description="Filter by active flag"),
            OpenApiParameter(
                name="is_local", type=bool, description="Filter by local/unbranded flag"
            ),
            OpenApiParameter(
                name="search", type=str, description="Search in name, GSTIN and phone"
            ),
            OpenApiParameter(
                name="ordering",
                type=str,
                description="Ordering field: name, created_at (prefix with '-' for descending)",
            ),
            OpenApiParameter(name="page", type=int, description="Page number"),
            OpenApiParameter(name="page_size", type=int, description="Page size (max 100)"),
        ],
        responses={
            200: OpenApiResponse(
                response=CompanySerializer(many=True),
                description="Paginated list of companies",
            ),
            400: OpenApiResponse(description="Validation error"),
            401: OpenApiResponse(description="Unauthenticated"),
        },
    )
    def get(self, request):
        queryset = Company.objects.all()

        is_active, error = _parse_bool_param(request.query_params.get("is_active"), "is_active")
        if error:
            return error
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)

        is_local, error = _parse_bool_param(request.query_params.get("is_local"), "is_local")
        if error:
            return error
        if is_local is not None:
            queryset = queryset.filter(is_local=is_local)

        search = request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(gstin__icontains=search) | Q(phone__icontains=search)
            )

        ordering_fields, error = _validate_ordering(request.query_params.get("ordering"))
        if error:
            return error
        queryset = queryset.order_by(*ordering_fields)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        serializer = CompanySerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)

    @extend_schema(
        operation_id="companiesCreate",
        tags=["catalog"],
        summary="Create company",
        description="Create a new company. Name is unique case-insensitively.",
        request=CompanySerializer,
        responses={
            201: CompanySerializer,
            400: OpenApiResponse(description="Validation error - duplicate name or invalid fields"),
            401: OpenApiResponse(description="Unauthenticated"),
        },
    )
    def post(self, request):
        serializer = CompanySerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        instance = CompanyService.create_company(serializer, request)
        return Response(
            CompanySerializer(instance, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class CompanyDetailView(APIView):
    """GET/PUT/PATCH/DELETE /api/v1/companies/{id}/."""

    permission_classes = [IsAuthenticated]
    serializer_class = CompanySerializer

    def _get_company(self, pk):
        try:
            return Company.objects.get(pk=pk)
        except Company.DoesNotExist:
            return None

    @extend_schema(
        operation_id="companiesRetrieve",
        tags=["catalog"],
        summary="Get company",
        responses={
            200: CompanySerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            404: OpenApiResponse(description="Company not found"),
        },
    )
    def get(self, request, pk):
        company = self._get_company(pk)
        if company is None:
            return _company_not_found()
        return Response(CompanySerializer(company, context={"request": request}).data)

    @extend_schema(
        operation_id="companiesUpdate",
        tags=["catalog"],
        summary="Update company",
        description="Full update. Name is required.",
        request=CompanySerializer,
        responses={
            200: CompanySerializer,
            400: OpenApiResponse(description="Validation error"),
            401: OpenApiResponse(description="Unauthenticated"),
            404: OpenApiResponse(description="Company not found"),
        },
    )
    def put(self, request, pk):
        company = self._get_company(pk)
        if company is None:
            return _company_not_found()
        serializer = CompanySerializer(company, data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        instance = CompanyService.update_company(company, serializer, request)
        return Response(CompanySerializer(instance, context={"request": request}).data)

    @extend_schema(
        operation_id="companiesPartialUpdate",
        tags=["catalog"],
        summary="Partially update company",
        request=CompanySerializer,
        responses={
            200: CompanySerializer,
            400: OpenApiResponse(description="Validation error"),
            401: OpenApiResponse(description="Unauthenticated"),
            404: OpenApiResponse(description="Company not found"),
        },
    )
    def patch(self, request, pk):
        company = self._get_company(pk)
        if company is None:
            return _company_not_found()
        serializer = CompanySerializer(
            company, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        instance = CompanyService.update_company(company, serializer, request)
        return Response(CompanySerializer(instance, context={"request": request}).data)

    @extend_schema(
        operation_id="companiesDestroy",
        tags=["catalog"],
        summary="Delete company (not allowed)",
        description="Companies are deactivated, never deleted. Use /deactivate/ instead.",
        responses={
            401: OpenApiResponse(description="Unauthenticated"),
            404: OpenApiResponse(description="Company not found"),
            405: OpenApiResponse(description="Method not allowed"),
        },
    )
    def delete(self, request, pk):
        # Delete is never supported for companies; return 405 in the standard
        # error format regardless of whether the company exists.
        return _method_not_allowed("DELETE not allowed; deactivate instead of delete")


class CompanyDeactivateView(APIView):
    """POST /api/v1/companies/{id}/deactivate/"""

    permission_classes = [IsAuthenticated]
    serializer_class = CompanySerializer

    @extend_schema(
        operation_id="companiesDeactivate",
        tags=["catalog"],
        summary="Deactivate company",
        description="Deactivate a company. Repeating on an already inactive company returns the current state without error.",
        responses={
            200: CompanySerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            404: OpenApiResponse(description="Company not found"),
        },
    )
    def post(self, request, pk):
        try:
            company = Company.objects.get(pk=pk)
        except Company.DoesNotExist:
            return _company_not_found()
        instance = CompanyService.deactivate_company(company, request)
        return Response(CompanySerializer(instance, context={"request": request}).data)


class CompanyActivateView(APIView):
    """POST /api/v1/companies/{id}/activate/"""

    permission_classes = [IsAuthenticated]
    serializer_class = CompanySerializer

    @extend_schema(
        operation_id="companiesActivate",
        tags=["catalog"],
        summary="Activate company",
        description="Activate a company. Repeating on an already active company returns the current state without error.",
        responses={
            200: CompanySerializer,
            401: OpenApiResponse(description="Unauthenticated"),
            404: OpenApiResponse(description="Company not found"),
        },
    )
    def post(self, request, pk):
        try:
            company = Company.objects.get(pk=pk)
        except Company.DoesNotExist:
            return _company_not_found()
        instance = CompanyService.activate_company(company, request)
        return Response(CompanySerializer(instance, context={"request": request}).data)
