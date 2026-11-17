"""Views for catalog app: Company and Product."""

from common.errors import (
    DUPLICATE_PRODUCT_CODE,
    GST_RATE_NOT_APPROVED,
    METHOD_NOT_ALLOWED,
    NOT_FOUND,
    PACK_CHANGE_NOT_ALLOWED,
    VALIDATION_ERROR,
)
from common.pagination import StandardPagination
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, F, OuterRef, Q
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Company, Product
from apps.catalog.serializers import CompanySerializer, ProductCompactSerializer, ProductSerializer
from apps.catalog.services import (
    CompanyService,
    PackChangeNotAllowedError,
    ProductService,
)
from apps.core.models import GstRate

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


# ---------------------------------------------------------------------------
# Product error helpers
# ---------------------------------------------------------------------------


def _product_not_found():
    return Response(
        {"code": NOT_FOUND, "message": "Product not found", "fields": {}},
        status=status.HTTP_404_NOT_FOUND,
    )


def _method_not_allowed(message):
    return Response(
        {"code": METHOD_NOT_ALLOWED, "message": message, "fields": {}},
        status=status.HTTP_405_METHOD_NOT_ALLOWED,
    )


def _validation_response(errors):
    fields = {}
    for field, errors_list in errors.items():
        fields[field] = errors_list[0] if isinstance(errors_list, list) else str(errors_list)
    code = VALIDATION_ERROR
    if list(fields.keys()) == ["gst_rate"]:
        code = GST_RATE_NOT_APPROVED
    return Response(
        {"code": code, "message": "Validation failed", "fields": fields},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _duplicate_response():
    return Response(
        {
            "code": DUPLICATE_PRODUCT_CODE,
            "message": "Product code already exists (case-insensitive).",
            "fields": {"product_code": "Product code already exists (case-insensitive)."},
        },
        status=status.HTTP_400_BAD_REQUEST,
    )


def _django_validation_response(exc):
    fields = {}
    if hasattr(exc, "message_dict") and exc.message_dict:
        for field, errors in exc.message_dict.items():
            fields[field] = errors[0] if isinstance(errors, list) else str(errors)
    code = VALIDATION_ERROR
    if list(fields.keys()) == ["gst_rate"]:
        code = GST_RATE_NOT_APPROVED
    return Response(
        {"code": code, "message": "Validation failed", "fields": fields},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _pack_change_response(field):
    return Response(
        {
            "code": PACK_CHANGE_NOT_ALLOWED,
            "message": f"Pack {field} cannot be changed once the product has stock history.",
            "fields": {
                field: f"Pack {field} cannot be changed once the product has stock history."
            },
        },
        status=status.HTTP_400_BAD_REQUEST,
    )


# ---------------------------------------------------------------------------
# Product list / create
# ---------------------------------------------------------------------------

PRODUCT_ORDERING_FIELDS = {
    "product_code",
    "product_type",
    "sub_type",
    "created_at",
    "qty_on_hand",
    "selling_price",
}

LABEL_FILTER_FIELDS = ("category", "product_type", "sub_type", "sub_sub_type", "pack_unit")


def _parse_bool_param(value, field_name):
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


def _build_product_queryset(request):
    """Build the annotated, filtered and ordered product queryset.

    Returns (queryset, None) or (None, error Response).
    """
    active_rate = Exists(GstRate.objects.filter(rate=OuterRef("gst_rate"), is_active=True))
    queryset = Product.objects.select_related("company").annotate(_gst_rate_active=active_rate)

    company = request.query_params.get("company")
    if company is not None:
        queryset = queryset.filter(company_id=company)

    for field in LABEL_FILTER_FIELDS:
        value = request.query_params.get(field)
        if value:
            value = " ".join(str(value).split())
            queryset = queryset.filter(**{f"{field}__iexact": value})

    is_active, error = _parse_bool_param(request.query_params.get("is_active"), "is_active")
    if error:
        return None, error
    if is_active is not None:
        queryset = queryset.filter(is_active=is_active)

    track_stock, error = _parse_bool_param(request.query_params.get("track_stock"), "track_stock")
    if error:
        return None, error
    if track_stock is not None:
        queryset = queryset.filter(track_stock=track_stock)

    billing_ready = request.query_params.get("billing_ready")
    if billing_ready is not None:
        if billing_ready.lower() not in ("true", "false", "1", "0"):
            return None, Response(
                {
                    "code": VALIDATION_ERROR,
                    "message": "billing_ready must be true or false.",
                    "fields": {"billing_ready": f"Invalid value: {billing_ready}"},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        ready_pks = Product.objects.billing_ready().values_list("pk", flat=True)
        if billing_ready.lower() in ("true", "1"):
            queryset = queryset.filter(pk__in=ready_pks)
        else:
            queryset = queryset.exclude(pk__in=ready_pks)

    stock_status = request.query_params.get("stock_status")
    if stock_status == "in":
        queryset = queryset.filter(qty_on_hand__gt=0)
    elif stock_status == "low":
        queryset = queryset.filter(
            track_stock=True,
            min_stock__isnull=False,
            qty_on_hand__gt=0,
            qty_on_hand__lte=F("min_stock"),
        )
    elif stock_status == "out":
        queryset = queryset.filter(track_stock=True, qty_on_hand__lte=0)
    elif stock_status not in (None, ""):
        return None, Response(
            {
                "code": VALIDATION_ERROR,
                "message": "stock_status must be one of in, low, out.",
                "fields": {"stock_status": f"Invalid value: {stock_status}"},
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    search = request.query_params.get("search")
    if search:
        # icontains is used because Django's PostgreSQL backend escapes LIKE
        # wildcards (backslash, percent, underscore) in the generated SQL, so
        # user-supplied %, _, \ are treated as literals, not wildcards.
        for term in search.split():
            queryset = queryset.filter(
                Q(product_code__icontains=term)
                | Q(product_type__icontains=term)
                | Q(sub_type__icontains=term)
                | Q(sub_sub_type__icontains=term)
                | Q(category__icontains=term)
                | Q(company__name__icontains=term)
            )

    ordering = request.query_params.get("ordering", "product_code")
    fields = [part.strip() for part in ordering.split(",") if part.strip()]
    for field in fields:
        name = field.lstrip("-")
        if name not in PRODUCT_ORDERING_FIELDS:
            return None, Response(
                {
                    "code": VALIDATION_ERROR,
                    "message": f"Invalid ordering field: {field}",
                    "fields": {
                        "ordering": f"Allowed fields: {', '.join(sorted(PRODUCT_ORDERING_FIELDS))}"
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
    queryset = queryset.order_by(*fields)
    return queryset, None


class ProductListCreateView(APIView):
    """GET and POST /api/v1/products/."""

    permission_classes = [IsAuthenticated]
    serializer_class = ProductSerializer
    pagination_class = StandardPagination

    @extend_schema(
        operation_id="productsList",
        tags=["catalog"],
        summary="List products",
        description="Paginated list of products. Filters: company, category, product_type, "
        "sub_type, sub_sub_type, pack_unit, is_active, track_stock, billing_ready, stock_status. "
        "Search: space-separated terms matched against code, type, sub-types, category and company.",
        parameters=[
            OpenApiParameter(name="company", type=int, description="Company id (exact)."),
            OpenApiParameter(
                name="category", type=str, description="Case-insensitive exact category."
            ),
            OpenApiParameter(
                name="product_type", type=str, description="Case-insensitive exact product type."
            ),
            OpenApiParameter(
                name="sub_type", type=str, description="Case-insensitive exact sub type."
            ),
            OpenApiParameter(
                name="sub_sub_type", type=str, description="Case-insensitive exact sub-sub type."
            ),
            OpenApiParameter(
                name="pack_unit", type=str, description="Case-insensitive exact pack unit."
            ),
            OpenApiParameter(name="is_active", type=bool, description="Filter by active flag."),
            OpenApiParameter(
                name="track_stock", type=bool, description="Filter by track_stock flag."
            ),
            OpenApiParameter(
                name="billing_ready",
                type=bool,
                description="Filter by billing readiness.",
            ),
            OpenApiParameter(
                name="stock_status",
                type=str,
                description="in: qty_on_hand>0; low: 0<qty_on_hand<=min_stock with track_stock; out: track_stock and qty_on_hand<=0.",
            ),
            OpenApiParameter(
                name="search",
                type=str,
                description="Space-separated terms; every term must match code, type, sub-types, category or company name.",
            ),
            OpenApiParameter(
                name="ordering",
                type=str,
                description="product_code, product_type, sub_type, created_at, qty_on_hand, selling_price (prefix '-' for desc).",
            ),
            OpenApiParameter(name="page", type=int, description="Page number."),
            OpenApiParameter(name="page_size", type=int, description="Page size (max 100)."),
        ],
        responses={
            200: OpenApiResponse(
                response=ProductSerializer(many=True), description="Paginated product list"
            ),
            400: OpenApiResponse(description="Validation error"),
            401: OpenApiResponse(description="Unauthenticated"),
        },
    )
    def get(self, request):
        queryset, error = _build_product_queryset(request)
        if error:
            return error
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        serializer = ProductSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(serializer.data)

    @extend_schema(
        operation_id="productsCreate",
        tags=["catalog"],
        summary="Create product",
        description="Create a product. Only product_code, company, product_type, pack_size and pack_unit are required.",
        request=ProductSerializer,
        responses={
            201: OpenApiResponse(response=ProductSerializer, description="Product created"),
            400: OpenApiResponse(description="Validation error"),
            401: OpenApiResponse(description="Unauthenticated"),
        },
    )
    def post(self, request):
        serializer = ProductSerializer(data=request.data, context={"request": request})
        try:
            valid = serializer.is_valid()
        except PackChangeNotAllowedError as exc:
            return _pack_change_response(exc.field)
        if not valid:
            return _validation_response(serializer.errors)
        try:
            with transaction.atomic():
                instance = ProductService.create_product_with_audit(serializer, request)
        except IntegrityError:
            return _duplicate_response()
        except DjangoValidationError as exc:
            return _django_validation_response(exc)
        return Response(
            ProductSerializer(instance, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Product detail
# ---------------------------------------------------------------------------


class ProductDetailView(APIView):
    """GET, PUT, PATCH /api/v1/products/{id}/. DELETE returns 405."""

    permission_classes = [IsAuthenticated]
    serializer_class = ProductSerializer

    def _get_product(self, pk):
        try:
            return Product.objects.get(pk=pk)
        except Product.DoesNotExist:
            return None

    @extend_schema(
        operation_id="productsRetrieve",
        tags=["catalog"],
        summary="Get product",
        responses={
            200: OpenApiResponse(response=ProductSerializer),
            401: OpenApiResponse(description="Unauthenticated"),
            404: OpenApiResponse(description="Product not found"),
        },
    )
    def get(self, request, pk):
        product = self._get_product(pk)
        if product is None:
            return _product_not_found()
        return Response(ProductSerializer(product, context={"request": request}).data)

    @extend_schema(
        operation_id="productsUpdate",
        tags=["catalog"],
        summary="Update product (full)",
        request=ProductSerializer,
        responses={
            200: OpenApiResponse(response=ProductSerializer),
            400: OpenApiResponse(description="Validation error"),
            401: OpenApiResponse(description="Unauthenticated"),
            404: OpenApiResponse(description="Product not found"),
            405: OpenApiResponse(description="Method not allowed"),
        },
    )
    def put(self, request, pk):
        product = self._get_product(pk)
        if product is None:
            return _product_not_found()
        serializer = ProductSerializer(product, data=request.data, context={"request": request})
        try:
            valid = serializer.is_valid()
        except PackChangeNotAllowedError as exc:
            return _pack_change_response(exc.field)
        if not valid:
            return _validation_response(serializer.errors)
        try:
            with transaction.atomic():
                instance = ProductService.update_product_with_audit(product, serializer, request)
        except IntegrityError:
            return _duplicate_response()
        except DjangoValidationError as exc:
            return _django_validation_response(exc)
        return Response(ProductSerializer(instance, context={"request": request}).data)

    @extend_schema(
        operation_id="productsPartialUpdate",
        tags=["catalog"],
        summary="Update product (partial)",
        request=ProductSerializer,
        responses={
            200: OpenApiResponse(response=ProductSerializer),
            400: OpenApiResponse(description="Validation error"),
            401: OpenApiResponse(description="Unauthenticated"),
            404: OpenApiResponse(description="Product not found"),
        },
    )
    def patch(self, request, pk):
        product = self._get_product(pk)
        if product is None:
            return _product_not_found()
        serializer = ProductSerializer(
            product, data=request.data, partial=True, context={"request": request}
        )
        try:
            valid = serializer.is_valid()
        except PackChangeNotAllowedError as exc:
            return _pack_change_response(exc.field)
        if not valid:
            return _validation_response(serializer.errors)
        try:
            with transaction.atomic():
                instance = ProductService.update_product_with_audit(product, serializer, request)
        except IntegrityError:
            return _duplicate_response()
        except DjangoValidationError as exc:
            return _django_validation_response(exc)
        return Response(ProductSerializer(instance, context={"request": request}).data)

    @extend_schema(
        operation_id="productsDestroy",
        tags=["catalog"],
        summary="Delete product (not allowed)",
        responses={
            401: OpenApiResponse(description="Unauthenticated"),
            404: OpenApiResponse(description="Product not found"),
            405: OpenApiResponse(description="Method not allowed"),
        },
    )
    def delete(self, request, pk):
        return _method_not_allowed("DELETE not allowed; deactivate instead of delete")


# ---------------------------------------------------------------------------
# Product activate / deactivate
# ---------------------------------------------------------------------------


class ProductDeactivateView(APIView):
    """POST /api/v1/products/{id}/deactivate/"""

    permission_classes = [IsAuthenticated]
    serializer_class = ProductSerializer

    @extend_schema(
        operation_id="productsDeactivate",
        tags=["catalog"],
        summary="Deactivate product",
        responses={
            200: OpenApiResponse(response=ProductSerializer),
            401: OpenApiResponse(description="Unauthenticated"),
            404: OpenApiResponse(description="Product not found"),
        },
    )
    def post(self, request, pk):
        try:
            product = Product.objects.get(pk=pk)
        except Product.DoesNotExist:
            return _product_not_found()
        instance = ProductService.set_product_active_with_audit(product, False, request)
        return Response(ProductSerializer(instance, context={"request": request}).data)


class ProductActivateView(APIView):
    """POST /api/v1/products/{id}/activate/"""

    permission_classes = [IsAuthenticated]
    serializer_class = ProductSerializer

    @extend_schema(
        operation_id="productsActivate",
        tags=["catalog"],
        summary="Activate product",
        responses={
            200: OpenApiResponse(response=ProductSerializer),
            401: OpenApiResponse(description="Unauthenticated"),
            404: OpenApiResponse(description="Product not found"),
        },
    )
    def post(self, request, pk):
        try:
            product = Product.objects.get(pk=pk)
        except Product.DoesNotExist:
            return _product_not_found()
        instance = ProductService.set_product_active_with_audit(product, True, request)
        return Response(ProductSerializer(instance, context={"request": request}).data)


# ---------------------------------------------------------------------------
# Product lookup
# ---------------------------------------------------------------------------


class ProductLookupView(APIView):
    """GET /api/v1/products/lookup/?code=XYZ or ?q=text"""

    permission_classes = [IsAuthenticated]
    serializer_class = ProductCompactSerializer

    @extend_schema(
        operation_id="productsLookup",
        tags=["catalog"],
        summary="Lookup a product by code or text",
        description="code: exact match after trimming and uppercasing. q: ranked text search "
        "(exact code, prefix, contains, label, company), active products only unless include_inactive=true.",
        parameters=[
            OpenApiParameter(
                name="code", type=str, description="Exact product code (trimmed, uppercased)."
            ),
            OpenApiParameter(name="q", type=str, description="Free text search (max 15 results)."),
            OpenApiParameter(
                name="include_inactive",
                type=bool,
                description="Include inactive products for q search (default false).",
            ),
        ],
        responses={
            200: OpenApiResponse(response=ProductCompactSerializer(many=True)),
            400: OpenApiResponse(description="Provide exactly one of code or q"),
            401: OpenApiResponse(description="Unauthenticated"),
            404: OpenApiResponse(description="Product not found (code lookup)"),
        },
    )
    def get(self, request):
        code = request.query_params.get("code")
        q = request.query_params.get("q")
        if (code is None) == (q is None):
            return Response(
                {
                    "code": VALIDATION_ERROR,
                    "message": "Provide exactly one of 'code' or 'q'.",
                    "fields": {},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if code is not None:
            normalized = code.strip().upper()
            try:
                product = Product.objects.select_related("company").get(product_code=normalized)
            except Product.DoesNotExist:
                return _product_not_found()
            serializer = ProductCompactSerializer(product, context={"request": request})
            return Response(serializer.data)

        text = (q or "").strip()
        include_inactive = request.query_params.get("include_inactive", "false").lower() in (
            "true",
            "1",
        )
        qs = Product.objects.select_related("company").annotate(
            _gst_rate_active=Exists(
                GstRate.objects.filter(rate=OuterRef("gst_rate"), is_active=True)
            )
        )
        if not include_inactive:
            qs = qs.filter(is_active=True)
        if text:
            # icontains is used because Django's PostgreSQL backend escapes LIKE
            # wildcards (backslash, percent, underscore) in the generated SQL.
            qs = qs.filter(
                Q(product_code__icontains=text)
                | Q(product_type__icontains=text)
                | Q(sub_type__icontains=text)
                | Q(sub_sub_type__icontains=text)
                | Q(category__icontains=text)
                | Q(company__name__icontains=text)
            )
        text_code = text.upper()
        ranked = []
        for product in qs:
            code_val = product.product_code
            if code_val == text_code:
                tier = 0
            elif code_val.startswith(text_code):
                tier = 1
            elif text_code in code_val:
                tier = 2
            elif any(
                getattr(product, field) and text.lower() in str(getattr(product, field)).lower()
                for field in ("product_type", "sub_type", "sub_sub_type", "category")
            ):
                tier = 3
            elif product.company and text.lower() in product.company.name.lower():
                tier = 4
            else:
                continue
            ranked.append((tier, code_val, product))
        ranked.sort(key=lambda item: (item[0], item[1]))
        top = [product for _, _, product in ranked[:15]]
        serializer = ProductCompactSerializer(top, many=True, context={"request": request})
        return Response(serializer.data)


# ---------------------------------------------------------------------------
# Product suggest
# ---------------------------------------------------------------------------


class ProductSuggestView(APIView):
    """GET /api/v1/products/suggest/?field=...&q=..."""

    permission_classes = [IsAuthenticated]
    ALLOWED_FIELDS = {"product_type", "sub_type", "sub_sub_type", "category"}

    @extend_schema(
        operation_id="productsSuggest",
        tags=["catalog"],
        summary="Suggest distinct labels for a product field",
        description="Distinct stored labels, case-insensitive contains, most-used first then alphabetical (max 20).",
        parameters=[
            OpenApiParameter(
                name="field",
                type=str,
                description="One of product_type, sub_type, sub_sub_type, category.",
            ),
            OpenApiParameter(name="q", type=str, description="Case-insensitive contains filter."),
        ],
        responses={
            200: OpenApiResponse(description="List of label strings"),
            400: OpenApiResponse(description="Invalid field"),
            401: OpenApiResponse(description="Unauthenticated"),
        },
    )
    def get(self, request):
        field = request.query_params.get("field")
        if field not in self.ALLOWED_FIELDS:
            return Response(
                {
                    "code": VALIDATION_ERROR,
                    "message": "Invalid suggest field.",
                    "fields": {
                        "field": f"Must be one of {', '.join(sorted(self.ALLOWED_FIELDS))}."
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        text = (request.query_params.get("q") or "").strip()
        qs = Product.objects.all()
        if text:
            # icontains is used because Django's PostgreSQL backend escapes LIKE
            # wildcards (backslash, percent, underscore) in the generated SQL.
            qs = qs.filter(**{f"{field}__icontains": text})
        qs = qs.exclude(**{f"{field}__isnull": True}).exclude(**{f"{field}": ""})
        labels = (qs.values(field).annotate(cnt=Count("id")).order_by("-cnt", field))[:20]
        return Response([item[field] for item in labels])
