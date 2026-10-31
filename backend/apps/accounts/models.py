"""Models for accounts app."""

from django.db import models


class LoginAttempt(models.Model):
    """
    Track login attempts for lockout functionality.

    After 5 failed attempts within 15 minutes for a username,
    further logins are rejected for 15 minutes.
    """

    username = models.CharField(max_length=150, db_index=True)
    ip_address = models.GenericIPAddressField()
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    success = models.BooleanField(default=False)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["username", "timestamp"]),
            models.Index(fields=["username", "success", "timestamp"]),
        ]

    def __str__(self):
        status = "success" if self.success else "failed"
        return f"{self.username} - {status} at {self.timestamp}"

    @classmethod
    def is_locked(cls, username: str) -> bool:
        """
        Check if a username is locked out.

        Lockout: 5 failed attempts within 15 minutes -> reject for 15 minutes.
        """
        from datetime import timedelta

        from django.utils import timezone

        now = timezone.now()
        window_start = now - timedelta(minutes=15)

        # Count failed attempts in the last 15 minutes
        failed_count = cls.objects.filter(
            username=username,
            success=False,
            timestamp__gte=window_start,
        ).count()

        return failed_count >= 5

    @classmethod
    def record_attempt(cls, username: str, ip_address: str, success: bool) -> "LoginAttempt":
        """Record a login attempt."""
        return cls.objects.create(
            username=username,
            ip_address=ip_address,
            success=success,
        )
