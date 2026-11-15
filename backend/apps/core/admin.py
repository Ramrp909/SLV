"""Admin configuration for core app."""

from django.contrib import admin

from apps.core.models import AppSettings, GstRate


@admin.register(AppSettings)
class AppSettingsAdmin(admin.ModelAdmin):
    """Admin for AppSettings - single row, no add/delete."""

    list_display = (
        "invoice_prefix",
        "series_start_number",
        "prices_include_gst",
        "commission_default_percent",
        "financial_year_start_month",
    )
    readonly_fields = ("id",)

    def has_add_permission(self, request):
        # Prevent adding new rows - only one allowed
        return not AppSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        # Prevent deletion
        return False


@admin.register(GstRate)
class GstRateAdmin(admin.ModelAdmin):
    """Admin for GstRate."""

    list_display = ("rate", "label", "is_active", "created_at", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("rate", "label")
    readonly_fields = ("id", "rate", "created_at", "updated_at")
