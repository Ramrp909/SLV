"""Read-only query helpers for the catalog app (T-204).

Single source of truth for billing readiness: mirrors ``Product.billing_ready``
and ``ProductSerializer.get_missing_for_billing`` so the readiness endpoints,
the product API and direct model access agree on exactly which reasons make a
product not billing ready.
"""

from django.db.models import Count, Exists, OuterRef, Q

from apps.catalog.models import Company, Product
from apps.core.models import GstRate

MISSING_SELLING_PRICE = "selling_price"
MISSING_GST_RATE = "gst_rate"
MISSING_GST_RATE_INACTIVE = "gst_rate_inactive"
MISSING_HSN_CODE = "hsn_code"

MISSING_REASONS = (
    MISSING_SELLING_PRICE,
    MISSING_GST_RATE,
    MISSING_GST_RATE_INACTIVE,
    MISSING_HSN_CODE,
)


def missing_for_billing(product: Product) -> list:
    """Reasons (blueprint order) why *product* is not billing ready.

    Mirrors ``ProductSerializer.get_missing_for_billing()`` and
    ``Product.billing_ready``: selling price, then ``gst_rate`` /
    ``gst_rate_inactive`` (mutually exclusive), then ``hsn_code``. Empty list
    <=> billing ready.

    Reads the annotated ``_gst_rate_active`` flag when present (queryset path,
    no per-row queries); otherwise hits the GST rates table once for the rate.
    """
    missing = []
    if product.selling_price is None or product.selling_price <= 0:
        missing.append(MISSING_SELLING_PRICE)
    if product.gst_rate is None:
        missing.append(MISSING_GST_RATE)
    else:
        gst_active = getattr(product, "_gst_rate_active", None)
        if gst_active is None:
            gst_active = GstRate.objects.filter(rate=product.gst_rate, is_active=True).exists()
        if not gst_active:
            missing.append(MISSING_GST_RATE_INACTIVE)
    if not product.hsn_code:
        missing.append(MISSING_HSN_CODE)
    return missing


def annotate_billing_readiness(queryset):
    """Annotate a product queryset with ``_gst_rate_active`` (one Exists subquery)."""
    gst_rate_active = Exists(GstRate.objects.filter(rate=OuterRef("gst_rate"), is_active=True))
    return queryset.annotate(_gst_rate_active=gst_rate_active)


def _active_gst_rate_values():
    """Rate values of active approved GST rates (materialised once per request)."""
    return list(GstRate.objects.filter(is_active=True).values_list("rate", flat=True))


def _lookup(prefix: str, name: str) -> str:
    """Lookup key optionally prefixed with a relation (e.g. 'products__')."""
    return f"{prefix}__{name}" if prefix else name


def billing_ready_condition(active_rates=None, prefix=""):
    """Q matching fully billing-ready products (price, active rate, HSN)."""
    if active_rates is None:
        active_rates = _active_gst_rate_values()
    return (
        Q(
            **{_lookup(prefix, "selling_price__gt"): 0},
            **{_lookup(prefix, "gst_rate__isnull"): False},
            **{_lookup(prefix, "gst_rate__in"): active_rates},
        )
        & ~Q(**{_lookup(prefix, "hsn_code__isnull"): True})
        & ~Q(**{_lookup(prefix, "hsn_code"): ""})
    )


def not_billing_ready_condition(active_rates=None, prefix=""):
    """Q matching products that are not billing ready (NULL-safe complement)."""
    if active_rates is None:
        active_rates = _active_gst_rate_values()
    return (
        Q(**{_lookup(prefix, "selling_price__isnull"): True})
        | Q(**{_lookup(prefix, "selling_price__lte"): 0})
        | Q(**{_lookup(prefix, "gst_rate__isnull"): True})
        | ~Q(**{_lookup(prefix, "gst_rate__in"): active_rates})
        | Q(**{_lookup(prefix, "hsn_code__isnull"): True})
        | Q(**{_lookup(prefix, "hsn_code"): ""})
    )


def companies_with_counts(queryset=None):
    """Company queryset annotated with the four product counts (one aggregated query)."""
    if queryset is None:
        queryset = Company.objects.all()
    active_rates = _active_gst_rate_values()
    ready = billing_ready_condition(active_rates, prefix="products")
    not_ready = Q(products__is_active=True) & not_billing_ready_condition(
        active_rates, prefix="products"
    )
    return queryset.annotate(
        product_count=Count("products", filter=Q(products__is_active=True)),
        inactive_product_count=Count("products", filter=Q(products__is_active=False)),
        billing_ready_count=Count("products", filter=ready),
        not_billing_ready_count=Count("products", filter=not_ready),
    )
