"""Serializers for accounts app."""

from rest_framework import serializers


class LoginRequestSerializer(serializers.Serializer):
    """Serializer for login request."""

    username = serializers.CharField()
    password = serializers.CharField(write_only=True)


class LoginResponseSerializer(serializers.Serializer):
    """Serializer for login response."""

    access = serializers.CharField()
    username = serializers.CharField()


class RefreshRequestSerializer(serializers.Serializer):
    """Serializer for refresh request - no body, uses cookie."""

    pass


class RefreshResponseSerializer(serializers.Serializer):
    """Serializer for refresh response."""

    access = serializers.CharField()


class LogoutResponseSerializer(serializers.Serializer):
    """Serializer for logout response."""

    message = serializers.CharField()


class ChangePasswordRequestSerializer(serializers.Serializer):
    """Serializer for change-password request."""

    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)


class ChangePasswordResponseSerializer(serializers.Serializer):
    """Serializer for change-password response."""

    message = serializers.CharField()


class MeResponseSerializer(serializers.Serializer):
    """Serializer for me response."""

    username = serializers.CharField()
