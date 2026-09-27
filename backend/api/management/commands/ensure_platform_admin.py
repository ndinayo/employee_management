"""Create the platform administrator if that account is missing."""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from api.models import AccountProfile

EMAIL = "ndinayoeric1@gmail.com"
USERNAME = "ndinayoeric1"
PASSWORD = "Muyango@12345"


class Command(BaseCommand):
    help = "Create the super-admin workspace account if it does not exist."

    def handle(self, *args, **options):
        User = get_user_model()
        user = User.objects.filter(email__iexact=EMAIL).first() or User.objects.filter(username__iexact=USERNAME).first()
        if user:
            profile, _ = AccountProfile.objects.get_or_create(
                user=user, defaults={"role": "admin", "business": None})
            if profile.role != "admin":
                profile.role = "admin"
                profile.business = None
                profile.save(update_fields=["role", "business"])
            user.email = EMAIL
            user.is_staff = True
            user.is_superuser = True
            user.is_active = True
            user.set_password(PASSWORD)
            user.save()
            self.stdout.write("Platform admin was already present; sign-in details were refreshed.")
            return
        user = User.objects.create_superuser(username=USERNAME, email=EMAIL, password=PASSWORD)
        AccountProfile.objects.create(user=user, role="admin")
        self.stdout.write(self.style.SUCCESS("Platform admin created."))
