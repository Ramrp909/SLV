"""URLs for catalog app."""

from django.urls import path

from apps.catalog.views import (
    CompanyActivateView,
    CompanyDeactivateView,
    CompanyDetailView,
    CompanyListCreateView,
)

app_name = "catalog"

urlpatterns = [
    path("", CompanyListCreateView.as_view(), name="company-list"),
    path("<int:pk>/", CompanyDetailView.as_view(), name="company-detail"),
    path("<int:pk>/deactivate/", CompanyDeactivateView.as_view(), name="company-deactivate"),
    path("<int:pk>/activate/", CompanyActivateView.as_view(), name="company-activate"),
]
