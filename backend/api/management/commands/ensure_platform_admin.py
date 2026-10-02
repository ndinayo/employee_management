"""Create the platform administrator, or promote the existing account that owns its identity."""
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
    help = (f"Make sure the platform super admin ({USERNAME} / {EMAIL}) exists. An existing account with that "
            f"username or email is promoted instead of duplicated. {PASSWORD_VARIABLE} sets the password only "
            "when the account is created or promoted; an existing super admin keeps its password.")

    def handle(self, *args, **options):
        User = get_user_model()
        by_username = User.objects.filter(username__iexact=USERNAME).first()
        by_email = list(User.objects.filter(email__iexact=EMAIL).order_by("pk"))
        email_admins = [user for user in by_email if is_platform_admin(user)]
        user = by_username or (email_admins or by_email or [None])[0]

        if user is None:
            password = self.configured_password(User, required=True)
            with transaction.atomic():
                user = User.objects.create_superuser(username=USERNAME, email=EMAIL, password=password)
                AccountProfile.objects.create(user=user, role="admin")
            self.stdout.write(self.style.SUCCESS(
                f"Platform admin created. Remove {PASSWORD_VARIABLE} from the environment now that it is no longer needed."))
            return

        if is_platform_admin(user):
            changed = self.align_identity(user)
            if changed:
                user.save(update_fields=changed)
                self.stdout.write(f"Platform admin already exists; updated its {' and '.join(changed)}. "
                                  "The password was not changed.")
            else:
                self.stdout.write("Platform admin already exists; leaving the account unchanged.")
            return

        profile = AccountProfile.objects.filter(user=user).first()
        if profile and (profile.business_id or profile.employee_id):
            raise CommandError(
                f"{user.username!r} uses the platform admin username or email but is a {profile.role} linked to a "
                "company or employee record. Promoting it would detach that record, so no account was changed.")
        password = self.configured_password(User, required=False)
        with transaction.atomic():
            changed = self.align_identity(user) + ["is_staff", "is_superuser", "is_active"]
            user.is_staff = user.is_superuser = user.is_active = True
            if password:
                user.set_password(password)
                changed.append("password")
            user.save(update_fields=changed)
            if profile:
                profile.role = "admin"
                profile.save(update_fields=["role"])
            else:
                AccountProfile.objects.create(user=user, role="admin")
        self.stdout.write(self.style.SUCCESS(
            f"Existing account {user.username!r} promoted to platform admin. "
            + (f"Its password was set from {PASSWORD_VARIABLE}; remove that variable now."
               if password else "Its password was not changed.")))
        others = [other.username for other in email_admins if other.pk != user.pk]
        if others:
            self.stdout.write(f"Note: {', '.join(others)} also uses {EMAIL} and remains a platform admin.")

    def align_identity(self, user):
        changed = []
        if user.username != USERNAME:
            user.username = USERNAME
            changed.append("username")
        if user.email != EMAIL:
            user.email = EMAIL
            changed.append("email")
        return changed

    def configured_password(self, User, required):
        password = os.getenv(PASSWORD_VARIABLE, "")
        if not password.strip():
            if required:
                raise CommandError(f"Set {PASSWORD_VARIABLE} to create the platform admin; no account was created.")
            return ""
        try:
            validate_password(password, User(username=USERNAME, email=EMAIL))
        except ValidationError as error:
            raise CommandError("Platform admin password did not pass validation: " + " ".join(error.messages))
        return password


def is_platform_admin(user):
    return AccountProfile.objects.filter(user=user, role="admin").exists()
