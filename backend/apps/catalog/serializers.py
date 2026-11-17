"""Serializers for catalog app: Company and Product."""

from common.errors import DUPLICATE_COMPANY_NAME, GST_RATE_NOT_APPROVED
from common.validators import validate_gstin, validate_phone
from django.core.exceptions import ValidationError
from django.db.models import Value
from django.db.models.functions import Lower
from rest_framework import serializers

from apps.catalog.models import Company, Product
from apps.catalog.services import PackChangeNotAllowedError, has_stock_history
from apps.core.validators import validate_gst_rate


class CompanySerializer(serializers.ModelSerializer):
    """Serializer for Company - create and update."""

    class Meta:
        model = Company
        fields = [
            "id",
            "name",
            "phone",
            "address",
            "gstin",
            "notes",
            "is_local",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_name(self, value):
        """Normalise the name (trim, collapse spaces) and enforce uniqueness."""
        value = " ".join(str(value).split())
        if not value:
            raise serializers.ValidationError("Company name is required.")
        qs = Company.objects.annotate(ln=Lower("name")).filter(ln=Lower(Value(value)))
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "Company with this name already exists.", code=DUPLICATE_COMPANY_NAME
            )
        return value

    def validate_phone(self, value):
        return validate_phone(value)

    def validate_gstin(self, value):
        return validate_gstin(value)


class ProductSerializer(serializers.ModelSerializer):
    """Serializer for Product - full representation used by create, update, list and detail."""

    company_name = serializers.CharField(source="company.name", read_only=True)
    display_name = serializers.SerializerMethodField()
    billing_ready = serializers.SerializerMethodField()
    missing_for_billing = serializers.SerializerMethodField()

    STOCK_READ_ONLY_FIELDS = ("qty_on_hand", "avg_buying_price", "last_buying_price")

    class Meta:
        model = Product
        fields = [
            "id",
            "product_code",
            "company",
            "company_name",
            "display_name",
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
            "billing_ready",
            "missing_for_billing",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "company_name",
            "display_name",
            "qty_on_hand",
            "avg_buying_price",
            "last_buying_price",
            "billing_ready",
            "missing_for_billing",
            "created_at",
            "updated_at",
        ]

    def get_display_name(self, obj) -> str:
        return obj.display_name(include_company=False)

    def get_billing_ready(self, obj) -> bool:
        gst_active = getattr(obj, "_gst_rate_active", None)
        if gst_active is None:
            from apps.core.models import GstRate

            gst_active = GstRate.objects.filter(rate=obj.gst_rate, is_active=True).exists()
        return bool(
            obj.selling_price is not None
            and obj.selling_price > 0
            and obj.gst_rate is not None
            and gst_active
            and obj.hsn_code
        )

    def get_missing_for_billing(self, obj) -> list:
        missing = []
        if obj.selling_price is None or obj.selling_price <= 0:
            missing.append("selling_price")
        if obj.gst_rate is None:
            missing.append("gst_rate")
        else:
            gst_active = getattr(obj, "_gst_rate_active", None)
            if gst_active is None:
                from apps.core.models import GstRate

                gst_active = GstRate.objects.filter(rate=obj.gst_rate, is_active=True).exists()
            if not gst_active:
                missing.append("gst_rate_inactive")
        if not obj.hsn_code:
            missing.append("hsn_code")
        return missing

    def to_internal_value(self, data):
        present = [f for f in self.STOCK_READ_ONLY_FIELDS if f in data]
        try:
            internal = super().to_internal_value(data)
        except serializers.ValidationError as exc:
            detail = {}
            if isinstance(exc.detail, dict):
                detail = {k: list(v) for k, v in exc.detail.items()}
            elif isinstance(exc.detail, list):
                detail = {"non_field_errors": list(exc.detail)}
            for field in present:
                detail[field] = ["read-only: stock changes only through stock operations"]
            raise serializers.ValidationError(detail) from None
        if present:
            raise serializers.ValidationError(
                {
                    field: ["read-only: stock changes only through stock operations"]
                    for field in present
                }
            )
        return internal

    def validate_gst_rate(self, value):
        if value is None:
            return value
        try:
            validate_gst_rate(value)
        except ValidationError:
            raise serializers.ValidationError(
                "GST rate is not an approved active rate.",
                code=GST_RATE_NOT_APPROVED,
            ) from None
        return value

    def validate(self, attrs):
        instance = self.instance
        if instance is not None:
            for field in ("pack_size", "pack_unit"):
                if field in attrs and has_stock_history(instance):
                    if attrs[field] != getattr(instance, field):
                        raise PackChangeNotAllowedError(field)
        return attrs


class ProductCompactSerializer(serializers.ModelSerializer):
    """Compact representation used by lookup and suggest endpoints."""

    company_name = serializers.CharField(source="company.name", read_only=True)
    display_name = serializers.SerializerMethodField()
    billing_ready = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "product_code",
            "display_name",
            "company_name",
            "product_type",
            "sub_type",
            "sub_sub_type",
            "pack_size",
            "pack_unit",
            "qty_on_hand",
            "selling_price",
            "gst_rate",
            "hsn_code",
            "track_stock",
            "is_active",
            "billing_ready",
        ]
        read_only_fields = fields

    def get_display_name(self, obj) -> str:
        return obj.display_name(include_company=True)

    def get_billing_ready(self, obj) -> bool:
        gst_active = getattr(obj, "_gst_rate_active", None)
        if gst_active is None:
            from apps.core.models import GstRate

            gst_active = GstRate.objects.filter(rate=obj.gst_rate, is_active=True).exists()
        return bool(
            obj.selling_price is not None
            and obj.selling_price > 0
            and obj.gst_rate is not None
            and gst_active
            and obj.hsn_code
        )
