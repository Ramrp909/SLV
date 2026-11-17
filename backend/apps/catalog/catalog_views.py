"""Views for T-204 catalog/readiness endpoints (read-only).

GET /api/v1/catalog/companies/
GET /api/v1/catalog/readiness/
GET /api/v1/catalog/readiness/summary/

POST/PUT/PATCH/DELETE return 405 in the standard error format.
"""

from common.errors import VALIDATION_ERROR
from common.pagination import StandardPagination
from django.db.models import Count, Q
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.catalog_serializers import (
    CompanyCountsSerializer,
    ErrorSerializer,
    ReadinessItemSerializer,
    ReadinessSummarySerializer,
)
from apps.catalog.models import Product
from apps.catalog.selectors import (
    annotate_billing_readiness,
    billing_ready_condition,
    companies_with_counts,
    not_billing_ready_condition,
)
from apps.core.models import GstRate

READINESS_ORDERING_FIELDS = ("product_code", "-product_code")
COMPANY_ORDERING_FIELDS = (
    "name",
    "product_count",
    "not_billing_ready_count",
    "-name",
    "-product_count",
    "-not_billing_ready_count",
)

MISSING_FILTER_VALUES = ("selling_price", "gst_rate", "gst_rate_inactive", "hsn_code")


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


def _validate_ordering(value, allowed, field_name):
    """Validate ordering fields; return list of ordering fields or error response."""
    if not value:
        return [allowed[0]], None
    fields = [part.strip() for part in value.split(",") if part.strip()]
    for field in fields:
        if field not in allowed:
            return None, Response(
                {
                    "code": VALIDATION_ERROR,
                    "message": f"Invalid ordering field: {field}",
                    "fields": {"ordering": f"Allowed fields: {', '.join(sorted(allowed))}"},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
    return fields, None


def _build_product_search(queryset, search):
    """Multi-term search reused from the products list: every term must match."""
    if not search:
        return queryset
    for term in search.split():
        queryset = queryset.filter(
            Q(product_code__icontains=term)
            | Q(product_type__icontains=term)
            | Q(sub_type__icontains=term)
            | Q(sub_sub_type__icontains=term)
            | Q(category__icontains=term)
            | Q(company__name__icontains=term)
        )
    return queryset


# ---------------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------------


class CompaniesListView(APIView):
    """GET /api/v1/catalog/companies/"""

    permission_classes = [IsAuthenticated]
    http_method_names = ["get"]
    serializer_class = CompanyCountsSerializer
    pagination_class = StandardPagination

    @extend_schema(
        operation_id="catalogCompaniesList",
        tags=["catalog"],
        summary="Companies with product readiness counts",
        description="One aggregated query computes product_count, inactive_product_count, "
        "billing_ready_count and not_billing_ready_count per company.",
        parameters=[
            OpenApiParameter(
                name="is_active", type=bool, description="Filter by active flag (default true)."
            ),
            OpenApiParameter(
                name="include_inactive",
                type=bool,
                description="Include inactive companies (default false).",
            ),
            OpenApiParameter(
                name="is_local", type=bool, description="Filter by local/unbranded flag."
            ),
            OpenApiParameter(
                name="search",
                type=str,
                description="Case-insensitive contains search on company name.",
            ),
            OpenApiParameter(
                name="ordering",
                type=str,
                description="name, product_count or not_billing_ready_count (prefix '-' for descending; default name).",
            ),
            OpenApiParameter(name="page", type=int, description="Page number."),
            OpenApiParameter(name="page_size", type=int, description="Page size (max 100)."),
        ],
        responses={
            200: CompanyCountsSerializer(many=True),
            400: OpenApiResponse(response=ErrorSerializer, description="Validation error"),
            401: OpenApiResponse(response=ErrorSerializer, description="Unauthenticated"),
            405: OpenApiResponse(response=ErrorSerializer, description="Method not allowed"),
        },
    )
    def get(self, request):
        is_active, error = _parse_bool_param(request.query_params.get("is_active"), "is_active")
        if error:
            return error
        include_inactive, error = _parse_bool_param(
            request.query_params.get("include_inactive"), "include_inactive"
        )
        if error:
            return error
        is_local, error = _parse_bool_param(request.query_params.get("is_local"), "is_local")
        if error:
            return error

        queryset = companies_with_counts()
        if not include_inactive:
            queryset = queryset.filter(is_active=True)
        elif is_active is not None:
            queryset = queryset.filter(is_active=is_active)
        if is_local is not None:
            queryset = queryset.filter(is_local=is_local)

        search = request.query_params.get("search")
        if search:
            for term in search.split():
                queryset = queryset.filter(name__icontains=term)

        ordering_fields, error = _validate_ordering(
            request.query_params.get("ordering", "name"), COMPANY_ORDERING_FIELDS, "ordering"
        )
        if error:
            return error
        queryset = queryset.order_by(*ordering_fields)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        serializer = CompanyCountsSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


# ---------------------------------------------------------------------------
# Readiness list
# ---------------------------------------------------------------------------


class ReadinessListView(APIView):
    """GET /api/v1/catalog/readiness/"""

    permission_classes = [IsAuthenticated]
    http_method_names = ["get"]
    pagination_class = StandardPagination

    @extend_schema(
        operation_id="catalogReadinessList",
        tags=["catalog"],
        summary="Active products that are not billing ready",
        description="Lists products missing selling price, GST rate, an active GST rate or an HSN code. "
        "include_inactive=true also lists inactive products.",
        parameters=[
            OpenApiParameter(
                name="include_inactive",
                type=bool,
                description="Include inactive products (default false).",
            ),
            OpenApiParameter(
                name="missing",
                type=str,
                description="Reason filter: selling_price, gst_rate, gst_rate_inactive or hsn_code.",
            ),
            OpenApiParameter(
                name="company",
                type=int,
                description="Company id (exact). Unknown id yields an empty page.",
            ),
            OpenApiParameter(
                name="product_type",
                type=str,
                description="Case-insensitive exact match on the stored product type label.",
            ),
            OpenApiParameter(
                name="category",
                type=str,
                description="Case-insensitive exact match on the stored category label.",
            ),
            OpenApiParameter(
                name="search",
                type=str,
                description="Space-separated terms; every term must match product code, labels or company name.",
            ),
            OpenApiParameter(
                name="ordering",
                type=str,
                description="product_code (prefix '-' for descending; default product_code).",
            ),
            OpenApiParameter(name="page", type=int, description="Page number."),
            OpenApiParameter(name="page_size", type=int, description="Page size (max 100)."),
        ],
        responses={
            200: ReadinessItemSerializer(many=True),
            400: OpenApiResponse(response=ErrorSerializer, description="Validation error"),
            401: OpenApiResponse(response=ErrorSerializer, description="Unauthenticated"),
            405: OpenApiResponse(response=ErrorSerializer, description="Method not allowed"),
        },
    )
    def get(self, request):
        include_inactive, error = _parse_bool_param(
            request.query_params.get("include_inactive"), "include_inactive"
        )
        if error:
            return error

        missing = request.query_params.get("missing")
        if missing is not None and missing not in MISSING_FILTER_VALUES:
            return Response(
                {
                    "code": VALIDATION_ERROR,
                    "message": f"Invalid missing value: {missing}",
                    "fields": {"missing": f"Must be one of {', '.join(MISSING_FILTER_VALUES)}."},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        company = request.query_params.get("company")
        product_type = request.query_params.get("product_type")
        category = request.query_params.get("category")
        search = request.query_params.get("search")

        ordering_fields, error = _validate_ordering(
            request.query_params.get("ordering", "product_code"),
            READINESS_ORDERING_FIELDS,
            "ordering",
        )
        if error:
            return error

        active_rates = list(GstRate.objects.filter(is_active=True).values_list("rate", flat=True))
        queryset = annotate_billing_readiness(Product.objects.select_related("company"))
        if not include_inactive:
            queryset = queryset.filter(is_active=True)
        queryset = queryset.filter(not_billing_ready_condition(active_rates))
        if missing == "selling_price":
            queryset = queryset.filter(Q(selling_price__isnull=True) | Q(selling_price__lte=0))
        elif missing == "gst_rate":
            queryset = queryset.filter(gst_rate__isnull=True)
        elif missing == "gst_rate_inactive":
            queryset = queryset.filter(gst_rate__isnull=False).exclude(gst_rate__in=active_rates)
        elif missing == "hsn_code":
            queryset = queryset.filter(Q(hsn_code__isnull=True) | Q(hsn_code=""))
        if company is not None:
            queryset = queryset.filter(company_id=company)
        if product_type:
            queryset = queryset.filter(product_type__iexact=" ".join(str(product_type).split()))
        if category:
            queryset = queryset.filter(category__iexact=" ".join(str(category).split()))
        queryset = _build_product_search(queryset, search)
        queryset = queryset.order_by(*ordering_fields)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        data = [ReadinessItemSerializer(item).data for item in page]
        return paginator.get_paginated_response(data)


# ---------------------------------------------------------------------------
# Readiness summary
# ---------------------------------------------------------------------------


class ReadinessSummaryView(APIView):
    """GET /api/v1/catalog/readiness/summary/"""

    permission_classes = [IsAuthenticated]
    http_method_names = ["get"]

    @extend_schema(
        operation_id="catalogReadinessSummary",
        tags=["catalog"],
        summary="Billing readiness summary over active products",
        description="active_products, billing_ready and not_billing_ready counts, plus "
        "per-reason missing counts over active products. A product with several missing "
        "reasons is counted under each reason, so the reason counts add up to more than "
        "not_billing_ready by design.",
        parameters=[
            OpenApiParameter(
                name="page", type=int, description="Page number (unused, kept for consistency)."
            ),
            OpenApiParameter(
                name="page_size", type=int, description="Page size (unused, kept for consistency)."
            ),
        ],
        responses={
            200: ReadinessSummarySerializer,
            400: OpenApiResponse(response=ErrorSerializer, description="Validation error"),
            401: OpenApiResponse(response=ErrorSerializer, description="Unauthenticated"),
            405: OpenApiResponse(response=ErrorSerializer, description="Method not allowed"),
        },
    )
    def get(self, request):
        active_rates = list(GstRate.objects.filter(is_active=True).values_list("rate", flat=True))
        ready = billing_ready_condition(active_rates)
        active = Product.objects.filter(is_active=True)
        aggregate = active.aggregate(
            active_products=Count("id"),
            billing_ready=Count("id", filter=ready),
            missing_selling_price=Count(
                "id", filter=Q(selling_price__isnull=True) | Q(selling_price__lte=0)
            ),
            missing_gst_rate=Count("id", filter=Q(gst_rate__isnull=True)),
            missing_gst_rate_inactive=Count(
                "id", filter=Q(gst_rate__isnull=False) & ~Q(gst_rate__in=active_rates)
            ),
            missing_hsn_code=Count("id", filter=Q(hsn_code__isnull=True) | Q(hsn_code="")),
        )
        not_billing_ready = aggregate["active_products"] - aggregate["billing_ready"]
        data = {
            "active_products": aggregate["active_products"],
            "billing_ready": aggregate["billing_ready"],
            "not_billing_ready": not_billing_ready,
            "missing": {
                "selling_price": aggregate["missing_selling_price"],
                "gst_rate": aggregate["missing_gst_rate"],
                "gst_rate_inactive": aggregate["missing_gst_rate_inactive"],
                "hsn_code": aggregate["missing_hsn_code"],
            },
        }
        serializer = ReadinessSummarySerializer(data)
        return Response(serializer.data)
