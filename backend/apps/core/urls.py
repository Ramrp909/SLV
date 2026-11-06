"""URLs for core app."""

from django.urls import path

from apps.core.views import (
    AuditLogView,
    GstRateDetailView,
    GstRateListView,
    HealthCheckView,
    SettingsView,
)

app_name = "core"

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health-check"),
    path("settings/", SettingsView.as_view(), name="settings"),
    path("settings/gst-rates/", GstRateListView.as_view(), name="gst-rate-list"),
    path("settings/gst-rates/<int:pk>/", GstRateDetailView.as_view(), name="gst-rate-detail"),
    path("audit-log/", AuditLogView.as_view(), name="audit-log"),
]
