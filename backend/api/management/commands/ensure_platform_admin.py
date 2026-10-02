"""Create the platform administrator if that account is missing."""
import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from api.models import AccountProfile

USERNAME = "admin"
EMAIL = "ndinayoeric1@gmail.com"
PASSWORD_VARIABLE = "PLATFORM_ADMIN_PASSWORD"


class Command(BaseCommand):
    help = (f"Create the platform super admin ({USERNAME} / {EMAIL}) if it does not exist, using the "
            f"{PASSWORD_VARIABLE} environment variable. An existing super admin keeps its password.")

    def handle(self, *args, **options):
        User = get_user_model()
        by_username = User.objects.filter(username__iexact=USERNAME).first()
        by_email = User.objects.filter(email__iexact=EMAIL).first()
        if by_username and by_email and by_username.pk != by_email.pk:
            raise CommandError(f"The username {USERNAME!r} and the email {EMAIL} belong to two different accounts; "
                               "no account was changed.")
        user = by_username or by_email
        if user:
            profile = AccountProfile.objects.filter(user=user).first()
            if not (profile and profile.role == "admin"):
                raise CommandError(f"{user.username!r} already uses that username or email but is not a platform "
                                   "admin; no account was changed.")
            changed = []
            if user.username != USERNAME:
                user.username = USERNAME
                changed.append("username")
            if user.email != EMAIL:
                user.email = EMAIL
                changed.append("email")
            if changed:
                user.save(update_fields=changed)
                self.stdout.write(f"Platform admin already exists; updated its {' and '.join(changed)}. "
                                  "The password was not changed.")
            else:
                self.stdout.write("Platform admin already exists; leaving the account unchanged.")
            return

        password = os.getenv(PASSWORD_VARIABLE, "")
        if not password.strip():
            raise CommandError(f"Set {PASSWORD_VARIABLE} to create the platform admin; no account was created.")
        try:
            validate_password(password, User(username=USERNAME, email=EMAIL))
        except ValidationError as error:
            raise CommandError("Platform admin password did not pass validation: " + " ".join(error.messages))
        with transaction.atomic():
            user = User.objects.create_superuser(username=USERNAME, email=EMAIL, password=password)
            AccountProfile.objects.create(user=user, role="admin")
        self.stdout.write(self.style.SUCCESS(
            f"Platform admin created. Remove {PASSWORD_VARIABLE} from the environment now that it is no longer needed."))
