"""Services for accounts authentication."""

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.accounts.models import LoginAttempt
from apps.core.services import AuditService

User = get_user_model()

# Generic error message for security
GENERIC_AUTH_ERROR = "Invalid username or password, or account temporarily locked"


class AuthenticationService:
    """Service for handling authentication logic."""

    @staticmethod
    def check_lockout(username: str) -> bool:
        """Check if username is locked out."""
        return LoginAttempt.is_locked(username)

    @staticmethod
    def record_attempt(username: str, ip_address: str, success: bool) -> LoginAttempt:
        """Record a login attempt."""
        return LoginAttempt.record_attempt(username, ip_address, success)

    @staticmethod
    def authenticate_user(username: str, password: str, request=None) -> User | None:
        """
        Authenticate a user with lockout protection.

        Returns User if successful, None if failed (with generic error).
        """
        ip_address = AuthenticationService._get_client_ip(request)

        # Check lockout first
        if AuthenticationService.check_lockout(username):
            AuthenticationService.record_attempt(username, ip_address, False)
            return None

        user = authenticate(username=username, password=password)

        if user is not None and user.is_active:
            AuthenticationService.record_attempt(username, ip_address, True)
            return user
        else:
            AuthenticationService.record_attempt(username, ip_address, False)
            return None

    @staticmethod
    def _get_client_ip(request) -> str:
        """Extract client IP from request."""
        if request is None:
            return "127.0.0.1"

        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "127.0.0.1")

    @staticmethod
    def create_tokens(user: User) -> dict:
        """Create access and refresh tokens for a user."""
        refresh = RefreshToken.for_user(user)
        return {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        }

    @staticmethod
    def rotate_refresh_token(refresh_token_str: str) -> dict:
        """
        Rotate a refresh token (blacklist old, create new).

        Returns new tokens dict or raises TokenError.
        """
        try:
            refresh = RefreshToken(refresh_token_str)
            # Blacklist the old token
            refresh.blacklist()
        except TokenError:
            raise

        # Get user from the old token
        user_id = refresh.payload.get("user_id")
        if not user_id:
            raise TokenError("Invalid token payload")

        user = User.objects.get(id=user_id)
        if not user.is_active:
            raise TokenError("User inactive")

        # Create new tokens
        return AuthenticationService.create_tokens(user)

    @staticmethod
    def logout(refresh_token_str: str) -> None:
        """Blacklist a refresh token on logout."""
        try:
            refresh = RefreshToken(refresh_token_str)
            refresh.blacklist()
        except TokenError:
            # Token already blacklisted or invalid - that's fine for logout
            pass

    @staticmethod
    def change_password(user: User, old_password: str, new_password: str, request=None) -> None:
        """
        Change user password and invalidate all refresh tokens.

        Args:
            user: The user changing password
            old_password: Current password for verification
            new_password: New password
            request: HTTP request object (for audit logging)

        Raises:
            ValidationError: If old password is wrong or new password fails validation
        """
        if not user.check_password(old_password):
            raise ValidationError("Current password is incorrect")

        # Validate new password
        validate_password(new_password, user)

        # Set new password
        user.set_password(new_password)
        user.save()

        # Record audit entry for password change
        AuditService.record(
            action="auth.password_changed",
            entity_type="User",
            entity_id=str(user.pk),
            summary="Password changed",
            request=request,
            actor=user,
        )

        # Invalidate all refresh tokens for this user
        # We need to blacklist all outstanding tokens for this user
        from rest_framework_simplejwt.token_blacklist.models import (
            BlacklistedToken,
            OutstandingToken,
        )

        outstanding_tokens = OutstandingToken.objects.filter(user=user)
        for token in outstanding_tokens:
            try:
                BlacklistedToken.objects.get_or_create(token=token)
            except Exception:
                pass  # Already blacklisted or race condition

    @staticmethod
    def get_user_from_access_token(access_token_str: str) -> User | None:
        """Get user from access token string."""
        try:
            access = AccessToken(access_token_str)
            user_id = access.payload.get("user_id")
            if user_id:
                return User.objects.get(id=user_id, is_active=True)
        except (TokenError, User.DoesNotExist):
            pass
        return None


class TokenCookieService:
    """Service for managing refresh token cookies."""

    REFRESH_COOKIE_NAME = "refresh_token"
    REFRESH_COOKIE_PATH = "/api/v1/auth/"

    @classmethod
    def _get_debug_setting(cls) -> bool:
        """Get DEBUG setting at runtime."""
        return getattr(settings, "DEBUG", True)

    @classmethod
    def set_refresh_cookie(cls, response, refresh_token: str) -> None:
        """Set the refresh token cookie on response."""
        import datetime

        from rest_framework_simplejwt.tokens import RefreshToken

        refresh = RefreshToken(refresh_token)
        expires = datetime.datetime.fromtimestamp(refresh.payload["exp"], tz=datetime.UTC)

        response.set_cookie(
            key=cls.REFRESH_COOKIE_NAME,
            value=refresh_token,
            expires=expires,
            httponly=True,
            secure=not cls._get_debug_setting(),
            samesite="Lax",
            path=cls.REFRESH_COOKIE_PATH,
        )

    @classmethod
    def clear_refresh_cookie(cls, response) -> None:
        """Clear the refresh token cookie."""
        response.delete_cookie(
            key=cls.REFRESH_COOKIE_NAME,
            path=cls.REFRESH_COOKIE_PATH,
            samesite="Lax",
        )

    @classmethod
    def get_refresh_token_from_request(cls, request) -> str | None:
        """Get refresh token from cookie."""
        return request.COOKIES.get(cls.REFRESH_COOKIE_NAME)
