"""Filters for catalog app: Company."""

import django_filters

from apps.catalog.models import Company


class CompanyFilter(django_filters.FilterSet):
    """Filter set for the company list: is_active and is_local."""

    class Meta:
        model = Company
        fields = ["is_active", "is_local"]
