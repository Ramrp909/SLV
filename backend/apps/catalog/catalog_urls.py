"""URLs for T-204 catalog/readiness endpoints, mounted at /api/v1/catalog/."""

from django.urls import path

from apps.catalog.catalog_views import CompaniesListView, ReadinessListView, ReadinessSummaryView

urlpatterns = [
    path("companies/", CompaniesListView.as_view(), name="companies-list"),
    path("readiness/", ReadinessListView.as_view(), name="readiness-list"),
    path("readiness/summary/", ReadinessSummaryView.as_view(), name="readiness-summary"),
]
