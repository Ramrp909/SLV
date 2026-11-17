"""Serializers for T-204 catalog/readiness endpoints."""

from rest_framework import serializers

from apps.catalog.models import PackUnit


class ErrorSerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()
    fields = serializers.DictField(child=serializers.ListField(child=serializers.CharField()))


class CompanyCountsSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    is_local = serializers.BooleanField()
    is_active = serializers.BooleanField()
    product_count = serializers.IntegerField()
    inactive_product_count = serializers.IntegerField()
    billing_ready_count = serializers.IntegerField()
    not_billing_ready_count = serializers.IntegerField()


class ReadinessItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    product_code = serializers.CharField()
    display_name = serializers.SerializerMethodField()
    company_name = serializers.CharField(source="company.name")
    product_type = serializers.CharField(allow_null=True)
    sub_type = serializers.CharField(allow_null=True)
    sub_sub_type = serializers.CharField(allow_null=True)
    pack_size = serializers.DecimalField(max_digits=10, decimal_places=3)
    pack_unit = serializers.ChoiceField(choices=PackUnit.choices)
    missing_for_billing = serializers.SerializerMethodField()
    is_active = serializers.BooleanField()

    def get_display_name(self, obj) -> str:
        return obj.display_name(include_company=True)

    def get_missing_for_billing(self, obj) -> list:
        from apps.catalog.selectors import missing_for_billing

        return missing_for_billing(obj)


class ReadinessSummarySerializer(serializers.Serializer):
    active_products = serializers.IntegerField()
    billing_ready = serializers.IntegerField()
    not_billing_ready = serializers.IntegerField()
    missing = serializers.DictField(child=serializers.IntegerField())
