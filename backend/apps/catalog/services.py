"""Services for catalog app: Company write operations with audit."""

from django.db import transaction

from apps.catalog.models import Product
from apps.core.services import AuditService


class CompanyService:
    """Write operations for Company with audit entries in the same transaction."""

    AUDIT_FIELDS = ["name", "phone", "address", "gstin", "notes", "is_local", "is_active"]

    @staticmethod
    def _actor(request):
        return getattr(request, "user", None)

    @staticmethod
    def _snapshot(instance, fields):
        return {field: getattr(instance, field) for field in fields}

    @classmethod
    def create_company(cls, serializer, request):
        """Create a company and record company.created audit entry."""
        instance = serializer.save()
        AuditService.record(
            action="company.created",
            entity_type="Company",
            entity_id=str(instance.pk),
            summary=f"Company created: {instance.name}",
            before=None,
            after=cls._snapshot(instance, cls.AUDIT_FIELDS),
            request=request,
            actor=cls._actor(request),
        )
        return instance

    @classmethod
    def update_company(cls, instance, serializer, request):
        """Update a company; record company.updated only if something changed."""
        validated_data = serializer.validated_data or {}
        if not validated_data:
            return serializer.save()

        before = cls._snapshot(instance, validated_data.keys())
        instance = serializer.save()
        after = cls._snapshot(instance, validated_data.keys())
        if before == after:
            return instance

        AuditService.record(
            action="company.updated",
            entity_type="Company",
            entity_id=str(instance.pk),
            summary=f"Company updated: {instance.name}",
            before=before,
            after=after,
            request=request,
            actor=cls._actor(request),
        )
        return instance

    @classmethod
    def deactivate_company(cls, instance, request):
        """Deactivate a company; repeat calls are no-ops without new audit entries."""
        before = {"is_active": instance.is_active}
        instance.is_active = False
        instance.save()
        if before["is_active"]:
            AuditService.record(
                action="company.deactivated",
                entity_type="Company",
                entity_id=str(instance.pk),
                summary=f"Company deactivated: {instance.name}",
                before=before,
                after={"is_active": False},
                request=request,
                actor=cls._actor(request),
            )
        return instance

    @classmethod
    def activate_company(cls, instance, request):
        """Activate a company; repeat calls are no-ops without new audit entries."""
        before = {"is_active": instance.is_active}
        instance.is_active = True
        instance.save()
        if not before["is_active"]:
            AuditService.record(
                action="company.activated",
                entity_type="Company",
                entity_id=str(instance.pk),
                summary=f"Company activated: {instance.name}",
                before=before,
                after={"is_active": True},
                request=request,
                actor=cls._actor(request),
            )
        return instance


def deactivate_product(product: Product) -> Product:
    """Deactivate a product (flip is_active). Products are never deleted."""
    product.is_active = False
    product.save(update_fields=["is_active", "updated_at"])
    return product


def activate_product(product: Product) -> Product:
    """Activate a product (flip is_active)."""
    product.is_active = True
    product.save(update_fields=["is_active", "updated_at"])
    return product


class PackChangeNotAllowedError(Exception):
    """Raised when pack_size / pack_unit cannot be changed due to stock history."""

    def __init__(self, field: str):
        self.field = field
        super().__init__(f"Pack {field} cannot be changed once the product has stock history.")


PRODUCT_AUDIT_FIELDS = [
    "product_code",
    "company",
    "category",
    "product_type",
    "sub_type",
    "sub_sub_type",
    "description",
    "pack_size",
    "pack_unit",
    "qty_on_hand",
    "avg_buying_price",
    "last_buying_price",
    "selling_price",
    "gst_rate",
    "hsn_code",
    "min_stock",
    "allow_fractional_qty",
    "track_stock",
    "custom_fields",
    "is_active",
]


def has_stock_history(product: Product) -> bool:
    """T-203: stock history exists when any stock field has been touched.

    T-301: also true when the product has at least one StockMovement, even if
    the stock fields are null or zero. Imported here to avoid a circular
    import (apps.stock.models does not import this module).
    """
    if (
        product.qty_on_hand != 0
        or product.avg_buying_price is not None
        or product.last_buying_price is not None
    ):
        return True
    from apps.stock.models import StockMovement

    return StockMovement.objects.filter(product=product).exists()


def _actor(request):
    return getattr(request, "user", None) if request else None


def _product_snapshot(instance: Product) -> dict:
    data = {}
    for field in PRODUCT_AUDIT_FIELDS:
        if field == "company":
            data["company"] = getattr(instance, "company_id", None)
        else:
            data[field] = getattr(instance, field)
    return data


def create_product_with_audit(serializer, request):
    """Create a product and record product.created audit entry in the same transaction."""
    with transaction.atomic():
        instance = serializer.save()
        instance.full_clean()
        after = _product_snapshot(instance)
        AuditService.record(
            action="product.created",
            entity_type="Product",
            entity_id=str(instance.pk),
            summary=f"Product created: {instance.product_code}",
            before=None,
            after=after,
            request=request,
            actor=_actor(request),
        )
    return instance


def update_product_with_audit(instance, serializer, request):
    """Update a product; record product.updated only if something changed.

    Only the validated fields plus updated_at are written (explicit
    update_fields). A stale copy of the product must never be allowed to
    overwrite qty_on_hand / avg_buying_price / last_buying_price that
    StockService may have written through another row copy, so those fields
    are never part of an update unless the caller explicitly validated them
    (they are read-only in the serializer).
    """
    validated_data = serializer.validated_data or {}
    if not validated_data:
        return instance

    before = _product_snapshot(instance)
    with transaction.atomic():
        update_fields = set(validated_data) | {"updated_at"}
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save(update_fields=sorted(update_fields))
        instance.full_clean()
        after = _product_snapshot(instance)
        if before == after:
            return instance
        AuditService.record(
            action="product.updated",
            entity_type="Product",
            entity_id=str(instance.pk),
            summary=f"Product updated: {instance.product_code}",
            before=before,
            after=after,
            request=request,
            actor=_actor(request),
        )
    return instance


def set_product_active_with_audit(product: Product, is_active: bool, request):
    """Activate or deactivate a product; no-op repeats write no audit entry."""
    if product.is_active == is_active:
        return product

    before = _product_snapshot(product)
    with transaction.atomic():
        product.is_active = is_active
        product.save(update_fields=["is_active", "updated_at"])
        after = _product_snapshot(product)
        action = "product.activated" if is_active else "product.deactivated"
        AuditService.record(
            action=action,
            entity_type="Product",
            entity_id=str(product.pk),
            summary=f"Product {action.split('.')[1]}: {product.product_code}",
            before=before,
            after=after,
            request=request,
            actor=_actor(request),
        )
    return product


class ProductService:
    """Write operations for Product with audit entries in the same transaction."""

    @classmethod
    def create_product_with_audit(cls, serializer, request):
        return create_product_with_audit(serializer, request)

    @classmethod
    def update_product_with_audit(cls, instance, serializer, request):
        return update_product_with_audit(instance, serializer, request)

    @classmethod
    def set_product_active_with_audit(cls, product: Product, is_active: bool, request):
        return set_product_active_with_audit(product, is_active, request)
