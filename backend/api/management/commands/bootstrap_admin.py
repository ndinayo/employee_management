import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create an initial admin from environment variables without changing existing accounts."

    def handle(self, *args, **options):
        username = os.getenv("DJANGO_SUPERUSER_USERNAME", "")
        password = os.getenv("DJANGO_SUPERUSER_PASSWORD", "")
        email = os.getenv("DJANGO_SUPERUSER_EMAIL", "")
        if not any([username, password, email]):
            self.stdout.write("No initial admin requested; skipping.")
            return
        if not username or not password:
            raise CommandError("Set DJANGO_SUPERUSER_USERNAME and DJANGO_SUPERUSER_PASSWORD together, or remove all DJANGO_SUPERUSER_* variables.")
        user_model = get_user_model()
        existing = user_model.objects.filter(username=username).first()
        if existing:
            if not existing.is_superuser:
                raise CommandError("The requested username already belongs to a non-admin account; no account was changed.")
            self.stdout.write("Initial admin already exists; leaving the account unchanged.")
            return
        if email and user_model.objects.filter(email__iexact=email).exists():
            # start.sh runs this on every deploy, so a used email skips rather than fails.
            self.stdout.write("DJANGO_SUPERUSER_EMAIL already belongs to another account; no initial admin was created.")
            return
        try:
            validate_password(password, user_model(username=username, email=email))
        except ValidationError as error:
            raise CommandError("Initial admin password did not pass validation: " + " ".join(error.messages))
        user_model.objects.create_superuser(username=username, email=email, password=password)
        self.stdout.write(self.style.SUCCESS("Initial admin created. Remove the DJANGO_SUPERUSER_* variables from the service environment."))
