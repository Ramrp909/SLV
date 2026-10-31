"""Management command to create the owner user."""

import getpass
import sys

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

User = get_user_model()


class Command(BaseCommand):
    """Create the single owner user."""

    help = "Create the owner user (only one allowed)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            type=str,
            help="Username for the owner",
        )
        parser.add_argument(
            "--password",
            type=str,
            help="Password for the owner (will prompt if not provided)",
        )
        parser.add_argument(
            "--no-input",
            action="store_true",
            help="Do not prompt for input (requires --username and --password)",
        )

    def handle(self, *args, **options):
        # Check if any user already exists
        if User.objects.exists():
            self.stdout.write(self.style.ERROR("Owner user already exists"))
            sys.exit(1)

        username = options.get("username")
        password = options.get("password")
        no_input = options.get("no_input", False)

        # Get username
        if not username:
            if no_input:
                raise CommandError("--username is required when using --no-input")
            username = input("Username: ").strip()

        if not username:
            raise CommandError("Username cannot be empty")

        # Check if username already exists (should not happen since we checked .exists())
        if User.objects.filter(username=username).exists():
            raise CommandError(f"User '{username}' already exists")

        # Get password
        if not password:
            if no_input:
                raise CommandError("--password is required when using --no-input")
            password = getpass.getpass("Password: ")
            confirm = getpass.getpass("Confirm password: ")
            if password != confirm:
                raise CommandError("Passwords do not match")

        if not password:
            raise CommandError("Password cannot be empty")

        # Validate password
        try:
            validate_password(password)
        except ValidationError as e:
            self.stderr.write(self.style.ERROR("Password validation failed:"))
            for error in e.messages:
                self.stderr.write(f"  - {error}")
            sys.exit(1)

        # Create the owner user
        user = User.objects.create_user(username=username, password=password)
        user.is_active = True
        user.save()

        self.stdout.write(self.style.SUCCESS("Owner user created"))
