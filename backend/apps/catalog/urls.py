"""URLs for catalog app."""

from django.urls import path

from apps.catalog.views import (
    CompanyActivateView,
    CompanyDeactivateView,
    CompanyDetailView,
    CompanyListCreateView,
    ProductActivateView,
    ProductDeactivateView,
    ProductDetailView,
    ProductListCreateView,
    ProductLookupView,
    ProductSuggestView,
)

app_name = "catalog"

urlpatterns = [
    path("companies/", CompanyListCreateView.as_view(), name="company-list"),
    path("companies/<int:pk>/", CompanyDetailView.as_view(), name="company-detail"),
    path(
        "companies/<int:pk>/deactivate/",
        CompanyDeactivateView.as_view(),
        name="company-deactivate",
    ),
    path(
        "companies/<int:pk>/activate/",
        CompanyActivateView.as_view(),
        name="company-activate",
    ),
    path("products/", ProductListCreateView.as_view(), name="product-list"),
    path("products/<int:pk>/", ProductDetailView.as_view(), name="product-detail"),
    path(
        "products/<int:pk>/deactivate/",
        ProductDeactivateView.as_view(),
        name="product-deactivate",
    ),
    path(
        "products/<int:pk>/activate/",
        ProductActivateView.as_view(),
        name="product-activate",
    ),
    path("products/lookup/", ProductLookupView.as_view(), name="product-lookup"),
    path("products/suggest/", ProductSuggestView.as_view(), name="product-suggest"),
]
