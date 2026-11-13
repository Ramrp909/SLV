"""Serializers for catalog app: Company."""

from common.errors import DUPLICATE_COMPANY_NAME
from common.validators import validate_gstin, validate_phone
from django.db.models import Value
from django.db.models.functions import Lower
from rest_framework import serializers

from apps.catalog.models import Company


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
