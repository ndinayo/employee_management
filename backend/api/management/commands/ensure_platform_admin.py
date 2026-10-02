"""Create the platform administrator from environment variables if that account is missing."""
import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from api.models import AccountProfile

VARIABLES = ("PLATFORM_ADMIN_USERNAME", "PLATFORM_ADMIN_EMAIL", "PLATFORM_ADMIN_PASSWORD")


class Command(BaseCommand):
    help = ("Create the super-admin workspace account from PLATFORM_ADMIN_USERNAME, PLATFORM_ADMIN_EMAIL "
            "and PLATFORM_ADMIN_PASSWORD. Existing accounts are never changed.")

    def handle(self, *args, **options):
        values = {name: os.getenv(name, "").strip() for name in VARIABLES}
        if not any(values.values()):
            self.stdout.write("No platform admin requested (PLATFORM_ADMIN_* variables are not set); skipping.")
            return
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise CommandError("Set PLATFORM_ADMIN_USERNAME, PLATFORM_ADMIN_EMAIL and PLATFORM_ADMIN_PASSWORD together. "
                               "Missing: " + ", ".join(missing) + ".")
        username = values["PLATFORM_ADMIN_USERNAME"]
        email = values["PLATFORM_ADMIN_EMAIL"]
        password = os.environ["PLATFORM_ADMIN_PASSWORD"]

        User = get_user_model()
        by_username = User.objects.filter(username__iexact=username).first()
        by_email = User.objects.filter(email__iexact=email).first()
        if by_username and by_email and by_username.pk != by_email.pk:
            raise CommandError("The username and email belong to two different accounts; no account was changed.")
        user = by_username or by_email
        if user:
            profile = AccountProfile.objects.filter(user=user).first()
            if profile and profile.role == "admin":
                self.stdout.write("Platform admin already exists; leaving the account unchanged.")
                return
            raise CommandError("That username or email already belongs to an account that is not a platform admin; "
                               "no account was changed.")

        try:
            validate_password(password, User(username=username, email=email))
        except ValidationError as error:
            raise CommandError("Platform admin password did not pass validation: " + " ".join(error.messages))
        with transaction.atomic():
            user = User.objects.create_superuser(username=username, email=email, password=password)
            AccountProfile.objects.create(user=user, role="admin")
        self.stdout.write(self.style.SUCCESS(
            "Platform admin created. Remove PLATFORM_ADMIN_PASSWORD from the environment now that it is no longer needed."))
