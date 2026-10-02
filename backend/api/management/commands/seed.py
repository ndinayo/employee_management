"""Initialise the data a fresh deployment needs. Safe to run any number of times."""
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

# Account roles (employee, employer, admin) are fixed choices on AccountProfile and
# access is enforced in api/permissions.py, so neither needs database rows. The
# Managers group is the one permission record the code looks up by name.
MANAGER_GROUP = "Managers"


class Command(BaseCommand):
    help = ("Create required production data: the Managers group and the platform super admin, whose "
            "password comes from PLATFORM_ADMIN_PASSWORD. Running it again never creates duplicates "
            "or changes a password.")

    def handle(self, *args, **options):
        with transaction.atomic():
            _, created = Group.objects.get_or_create(name=MANAGER_GROUP)
            self.stdout.write(f"{MANAGER_GROUP} group: {'created' if created else 'already present'}.")
            call_command("ensure_platform_admin", stdout=self.stdout, stderr=self.stderr)
        self.stdout.write(self.style.SUCCESS("Seeding complete."))
