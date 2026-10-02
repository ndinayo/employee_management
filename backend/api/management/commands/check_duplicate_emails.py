"""Report accounts that share a sign-in email. Read-only apart from adding the unique index."""
from django.core.management.base import BaseCommand

from api import user_emails
from api.models import AccountProfile


class Command(BaseCommand):
    help = ("List every email address used by more than one account, without changing any account. "
            "When none remain, add the case-insensitive unique email index.")

    def handle(self, *args, **options):
        groups = user_emails.duplicate_email_groups()
        if not groups:
            created = not user_emails.unique_index_exists()
            user_emails.ensure_unique_index()
            self.stdout.write("No duplicate sign-in emails. Unique email index "
                              + ("created." if created else "already in place."))
            return
        self.stdout.write(self.style.WARNING(
            f"{len(groups)} email address(es) are shared by several accounts. Nothing was changed; "
            "the unique email index will be added once these are resolved."))
        for email, users in groups.items():
            self.stdout.write(f"  {email}")
            for user in users:
                self.stdout.write(f"    {describe(user)}")


def describe(user):
    profile = AccountProfile.objects.select_related("business", "employee").filter(user=user).first()
    if profile is None:
        role = "no profile"
    else:
        role = profile.role
        if profile.business:
            role += f", business #{profile.business_id} {profile.business.name!r}"
        if profile.employee:
            role += f", employee #{profile.employee_id} (business #{profile.employee.business_id})"
    flags = [flag for flag, on in (("superuser", user.is_superuser), ("staff", user.is_staff),
                                   ("inactive", not user.is_active)) if on]
    last_login = user.last_login.strftime("%Y-%m-%d") if user.last_login else "never recorded"
    return (f"id={user.pk} username={user.username!r} email={user.email!r} role={role}"
            f"{' [' + ', '.join(flags) + ']' if flags else ''} joined={user.date_joined:%Y-%m-%d} "
            f"last_login={last_login}")
