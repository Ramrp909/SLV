"""URLs for accounts app."""

from django.urls import path

from apps.accounts.views import (
    ChangePasswordView,
    LoginView,
    LogoutView,
    MeView,
    RefreshView,
)

app_name = "accounts"

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("refresh/", RefreshView.as_view(), name="refresh"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("change-password/", ChangePasswordView.as_view(), name="change-password"),
    path("me/", MeView.as_view(), name="me"),
]
