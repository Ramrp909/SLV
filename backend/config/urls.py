"""
URL configuration for config project.
"""

from common.errors import INTERNAL_ERROR
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from django.views import defaults as default_views
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from apps.core.views import api_404_view

handler404 = api_404_view


def api_500_view(request):
    """Return the standard JSON error format for /api/ routes.

    Other URLs keep Django's default 500 page.
    """
    if request.path.startswith("/api/"):
        return JsonResponse(
            {
                "code": INTERNAL_ERROR,
                "message": "An unexpected error occurred",
                "fields": {},
            },
            status=500,
        )
    return default_views.server_error(request)


handler500 = api_500_view

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("apps.core.urls")),
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/companies/", include("apps.catalog.urls")),
    # API Schema
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
