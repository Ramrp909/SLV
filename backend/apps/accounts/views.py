"""Views for accounts authentication."""

from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError

from apps.accounts.services import AuthenticationService, TokenCookieService


class LoginRateThrottle(AnonRateThrottle):
    """Throttle for login endpoint."""

    scope = "login"
    rate = "100/minute"


class LoginView(APIView):
    """POST /api/v1/auth/login/ - Owner login."""

    permission_classes = [AllowAny]
    throttle_classes = [LoginRateThrottle]

    def post(self, request):
        username = request.data.get("username", "").strip()
        password = request.data.get("password", "")

        if not username or not password:
            return Response(
                {
                    "code": "VALIDATION_ERROR",
                    "message": "Username and password are required",
                    "fields": {"username": "Required", "password": "Required"},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = AuthenticationService.authenticate_user(username, password, request)

        if user is None:
            # Generic error for both wrong password and lockout
            return Response(
                {
                    "code": "AUTHENTICATION_FAILED",
                    "message": "Invalid username or password, or account temporarily locked",
                    "fields": {},
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        tokens = AuthenticationService.create_tokens(user)

        response = Response(
            {
                "access": tokens["access"],
                "username": user.username,
            },
            status=status.HTTP_200_OK,
        )

        # Set refresh token as httpOnly cookie
        TokenCookieService.set_refresh_cookie(response, tokens["refresh"])

        # TODO: Write audit entry for successful login

        return response


class RefreshView(APIView):
    """POST /api/v1/auth/refresh/ - Rotate refresh token."""

    permission_classes = [AllowAny]

    def post(self, request):
        # CSRF protection: require X-Requested-With header
        if request.META.get("HTTP_X_REQUESTED_WITH") != "XMLHttpRequest":
            return Response(
                {
                    "code": "CSRF_FAILED",
                    "message": "Invalid request",
                    "fields": {},
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # Reject if token is sent in body (must come from cookie only)
        if request.data.get("refresh"):
            return Response(
                {
                    "code": "VALIDATION_ERROR",
                    "message": "Refresh token must be sent via cookie, not request body",
                    "fields": {"refresh": "Must be sent via httpOnly cookie"},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get refresh token from cookie only
        refresh_token = TokenCookieService.get_refresh_token_from_request(request)

        if not refresh_token:
            return Response(
                {
                    "code": "AUTHENTICATION_FAILED",
                    "message": "Refresh token not found",
                    "fields": {},
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            tokens = AuthenticationService.rotate_refresh_token(refresh_token)
        except TokenError:
            return Response(
                {
                    "code": "AUTHENTICATION_FAILED",
                    "message": "Invalid or expired refresh token",
                    "fields": {},
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        response = Response(
            {
                "access": tokens["access"],
            },
            status=status.HTTP_200_OK,
        )

        # Set new rotated refresh token cookie
        TokenCookieService.set_refresh_cookie(response, tokens["refresh"])

        # TODO: Write audit entry for token refresh

        return response


class LogoutView(APIView):
    """POST /api/v1/auth/logout/ - Logout and blacklist refresh token."""

    permission_classes = [AllowAny]

    def post(self, request):
        refresh_token = TokenCookieService.get_refresh_token_from_request(request)

        if refresh_token:
            AuthenticationService.logout(refresh_token)

        response = Response(
            {"message": "Logged out successfully"},
            status=status.HTTP_200_OK,
        )

        # Clear refresh cookie
        TokenCookieService.clear_refresh_cookie(response)

        # TODO: Write audit entry for logout

        return response


class ChangePasswordView(APIView):
    """POST /api/v1/auth/change-password/ - Change owner password."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        old_password = request.data.get("old_password", "")
        new_password = request.data.get("new_password", "")

        if not old_password or not new_password:
            return Response(
                {
                    "code": "VALIDATION_ERROR",
                    "message": "Old password and new password are required",
                    "fields": {
                        "old_password": "Required" if not old_password else None,
                        "new_password": "Required" if not new_password else None,
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            AuthenticationService.change_password(request.user, old_password, new_password)
        except ValidationError as e:
            return Response(
                {
                    "code": "VALIDATION_ERROR",
                    "message": str(e.message) if hasattr(e, "message") else str(e),
                    "fields": {"old_password": "Incorrect password"}
                    if "incorrect" in str(e).lower()
                    else {},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        response = Response(
            {"message": "Password changed successfully"},
            status=status.HTTP_200_OK,
        )

        # Clear refresh cookie since all tokens are invalidated
        TokenCookieService.clear_refresh_cookie(response)

        return response


class MeView(APIView):
    """GET /api/v1/auth/me/ - Get current user profile."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            {"username": request.user.username},
            status=status.HTTP_200_OK,
        )
