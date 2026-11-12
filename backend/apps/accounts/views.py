"""Views for accounts authentication."""

from common.errors import AUTHENTICATION_FAILED, CSRF_FAILED, VALIDATION_ERROR
from django.core.exceptions import ValidationError
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError

from apps.accounts.serializers import (
    ChangePasswordRequestSerializer,
    ChangePasswordResponseSerializer,
    LoginRequestSerializer,
    LoginResponseSerializer,
    LogoutResponseSerializer,
    MeResponseSerializer,
    RefreshRequestSerializer,
    RefreshResponseSerializer,
)
from apps.accounts.services import AuthenticationService, TokenCookieService
from apps.core.services import AuditService


class LoginRateThrottle(AnonRateThrottle):
    """Throttle for login endpoint."""

    scope = "login"
    rate = "100/minute"


class LoginView(GenericAPIView):
    """POST /api/v1/auth/login/ - Owner login."""

    permission_classes = [AllowAny]
    throttle_classes = [LoginRateThrottle]
    serializer_class = LoginRequestSerializer

    @extend_schema(
        tags=["auth"],
        summary="Owner login",
        description="Authenticate owner with username and password. Returns access token in body and sets refresh token as httpOnly cookie.",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "username": {"type": "string"},
                    "password": {"type": "string", "format": "password"},
                },
                "required": ["username", "password"],
            }
        },
        responses={
            200: LoginResponseSerializer,
            400: OpenApiResponse(description="Validation error"),
            401: OpenApiResponse(
                description="Authentication failed - generic error for wrong password, lockout, or nonexistent user"
            ),
        },
        auth=[],
    )
    def post(self, request):
        username = request.data.get("username", "").strip()
        password = request.data.get("password", "")

        if not username or not password:
            return Response(
                {
                    "code": VALIDATION_ERROR,
                    "message": "Username and password are required",
                    "fields": {"username": "Required", "password": "Required"},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = AuthenticationService.authenticate_user(username, password, request)

        if user is None:
            # Record failed login audit entry (username only, never password)
            AuditService.record(
                action="auth.login_failed",
                entity_type="User",
                entity_id=username,
                summary=f"Failed login attempt for user: {username}",
                request=request,
                actor=None,
            )
            # Generic error for both wrong password and lockout
            return Response(
                {
                    "code": AUTHENTICATION_FAILED,
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

        # Record successful login audit entry
        AuditService.record(
            action="auth.login",
            entity_type="User",
            entity_id=str(user.pk),
            summary="User logged in successfully",
            request=request,
            actor=user,
        )

        return response


@extend_schema(
    tags=["auth"],
    summary="Refresh access token",
    description="Rotate refresh token. Requires refresh_token cookie and X-Requested-With: XMLHttpRequest header. Returns new access token and rotates refresh cookie.",
    request=RefreshRequestSerializer,
    responses={
        200: RefreshResponseSerializer,
        400: OpenApiResponse(description="Refresh token in body not allowed"),
        401: OpenApiResponse(description="Invalid or expired refresh token"),
        403: OpenApiResponse(description="Missing X-Requested-With header"),
    },
    auth=[],
    parameters=[
        OpenApiParameter(
            name="X-Requested-With",
            location=OpenApiParameter.HEADER,
            required=True,
            type=str,
            enum=["XMLHttpRequest"],
            description="CSRF protection header",
        ),
    ],
)
class RefreshView(APIView):
    """POST /api/v1/auth/refresh/ - Rotate refresh token."""

    permission_classes = [AllowAny]
    serializer_class = RefreshRequestSerializer

    def post(self, request):
        # CSRF protection: require X-Requested-With header
        if request.META.get("HTTP_X_REQUESTED_WITH") != "XMLHttpRequest":
            return Response(
                {
                    "code": CSRF_FAILED,
                    "message": "Invalid request",
                    "fields": {},
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # Reject if token is sent in body (must come from cookie only)
        if request.data.get("refresh"):
            return Response(
                {
                    "code": VALIDATION_ERROR,
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
                    "code": AUTHENTICATION_FAILED,
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
                    "code": AUTHENTICATION_FAILED,
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


@extend_schema(
    tags=["auth"],
    summary="Logout",
    description="Blacklist refresh token and clear cookie.",
    request=None,
    responses={
        200: LogoutResponseSerializer,
    },
    auth=[],
)
class LogoutView(APIView):
    """POST /api/v1/auth/logout/ - Logout and blacklist refresh token."""

    permission_classes = [AllowAny]
    serializer_class = LogoutResponseSerializer

    def post(self, request):
        refresh_token = TokenCookieService.get_refresh_token_from_request(request)

        # Get user from refresh token for audit
        user = None
        if refresh_token:
            from rest_framework_simplejwt.tokens import RefreshToken

            try:
                refresh = RefreshToken(refresh_token)
                user_id = refresh.payload.get("user_id")
                if user_id:
                    from django.contrib.auth import get_user_model

                    User = get_user_model()
                    user = User.objects.filter(id=user_id).first()
            except Exception:
                pass

        if refresh_token:
            AuthenticationService.logout(refresh_token)

        response = Response(
            {"message": "Logged out successfully"},
            status=status.HTTP_200_OK,
        )

        # Clear refresh cookie
        TokenCookieService.clear_refresh_cookie(response)

        # Record logout audit entry
        AuditService.record(
            action="auth.logout",
            entity_type="User",
            entity_id=str(user.pk) if user else "unknown",
            summary="User logged out",
            request=request,
            actor=user,
        )

        return response


@extend_schema(
    tags=["auth"],
    summary="Change password",
    description="Change owner password. Requires old password, invalidates all refresh tokens.",
    request=ChangePasswordRequestSerializer,
    responses={
        200: ChangePasswordResponseSerializer,
        400: OpenApiResponse(description="Validation error or incorrect old password"),
        401: OpenApiResponse(description="Unauthenticated"),
    },
)
class ChangePasswordView(APIView):
    """POST /api/v1/auth/change-password/ - Change owner password."""

    permission_classes = [IsAuthenticated]
    serializer_class = ChangePasswordRequestSerializer

    def post(self, request):
        old_password = request.data.get("old_password", "")
        new_password = request.data.get("new_password", "")

        if not old_password or not new_password:
            return Response(
                {
                    "code": VALIDATION_ERROR,
                    "message": "Old password and new password are required",
                    "fields": {
                        "old_password": "Required" if not old_password else None,
                        "new_password": "Required" if not new_password else None,
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            AuthenticationService.change_password(request.user, old_password, new_password, request)
        except ValidationError as e:
            return Response(
                {
                    "code": VALIDATION_ERROR,
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


@extend_schema(
    tags=["auth"],
    summary="Get current user",
    description="Returns the username of the authenticated owner.",
    responses={
        200: MeResponseSerializer,
        401: OpenApiResponse(description="Unauthenticated"),
    },
)
class MeView(APIView):
    """GET /api/v1/auth/me/ - Get current user profile."""

    permission_classes = [IsAuthenticated]
    serializer_class = MeResponseSerializer

    def get(self, request):
        return Response(
            {"username": request.user.username},
            status=status.HTTP_200_OK,
        )
