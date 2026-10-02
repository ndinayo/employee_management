from io import StringIO
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from .models import AccountProfile, Business

PASSWORD = "TestSeedAdmin#5930"
WITH_PASSWORD = {"PLATFORM_ADMIN_PASSWORD": PASSWORD}
NO_PASSWORD = {"PLATFORM_ADMIN_PASSWORD": ""}


def seed():
    out = StringIO()
    call_command("seed", stdout=out)
    return out.getvalue()


def platform_admin(username, email, password="Changed#Later-5521"):
    user = User.objects.create_superuser(username, email, password)
    AccountProfile.objects.create(user=user, role="admin")
    return user


class SeedCommandTests(TestCase):
    def test_creates_admin_with_the_fixed_identity_and_is_idempotent(self):
        Group.objects.filter(name="Managers").delete()
        with mock.patch.dict("os.environ", WITH_PASSWORD):
            seed()
            self.assertIn("leaving the account unchanged", seed())
        admin = User.objects.get()
        self.assertEqual((admin.username, admin.email), ("admin", "ndinayoeric1@gmail.com"))
        self.assertTrue(admin.is_superuser and admin.is_staff and admin.check_password(PASSWORD))
        self.assertEqual(admin.account_profile.role, "admin")
        self.assertIsNone(admin.account_profile.business)
        self.assertEqual(Group.objects.filter(name="Managers").count(), 1)

    def test_never_overwrites_an_existing_admin_password(self):
        admin = platform_admin("admin", "ndinayoeric1@gmail.com")
        for env in (WITH_PASSWORD, NO_PASSWORD):
            with mock.patch.dict("os.environ", env):
                seed()
        admin.refresh_from_db()
        self.assertTrue(admin.check_password("Changed#Later-5521"))
        self.assertEqual(User.objects.count(), 1)

    def test_existing_admin_with_the_email_is_renamed_instead_of_duplicated(self):
        existing = platform_admin("ndinayoeric1", "ndinayoeric1@gmail.com")
        with mock.patch.dict("os.environ", WITH_PASSWORD):
            self.assertIn("updated its username", seed())
            seed()
        existing.refresh_from_db()
        self.assertEqual(existing.username, "admin")
        self.assertTrue(existing.check_password("Changed#Later-5521"))
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(AccountProfile.objects.filter(role="admin").count(), 1)

    def test_existing_admin_named_admin_gets_the_email(self):
        existing = platform_admin("admin", "old@example.com")
        with mock.patch.dict("os.environ", NO_PASSWORD):
            self.assertIn("updated its email", seed())
        existing.refresh_from_db()
        self.assertEqual(existing.email, "ndinayoeric1@gmail.com")
        self.assertTrue(existing.check_password("Changed#Later-5521"))

    def test_refuses_to_promote_a_superuser_without_a_platform_admin_profile(self):
        User.objects.create_superuser("admin", "", "Cedar!Lantern-47-River")
        with mock.patch.dict("os.environ", WITH_PASSWORD), self.assertRaises(CommandError):
            seed()
        self.assertFalse(AccountProfile.objects.exists())
        self.assertEqual(User.objects.get().email, "")

    def test_refuses_to_promote_an_employer_using_the_email(self):
        employer = User.objects.create_user("boss", "ndinayoeric1@gmail.com", "Cedar!Lantern-47-River")
        AccountProfile.objects.create(user=employer, role="employer", business=Business.objects.create(name="Works"))
        with mock.patch.dict("os.environ", WITH_PASSWORD), self.assertRaises(CommandError):
            seed()
        employer.refresh_from_db()
        self.assertEqual((employer.username, employer.account_profile.role), ("boss", "employer"))
        self.assertFalse(employer.is_superuser)

    def test_refuses_when_username_and_email_are_different_accounts(self):
        User.objects.create_superuser("admin", "", "Cedar!Lantern-47-River")
        platform_admin("ndinayoeric1", "ndinayoeric1@gmail.com")
        with mock.patch.dict("os.environ", WITH_PASSWORD), self.assertRaises(CommandError):
            seed()
        self.assertTrue(User.objects.filter(username="ndinayoeric1").exists())
        self.assertEqual(User.objects.count(), 2)

    def test_creating_the_admin_requires_a_valid_password(self):
        for password in ("", "123"):
            with mock.patch.dict("os.environ", {"PLATFORM_ADMIN_PASSWORD": password}):
                with self.assertRaises(CommandError):
                    seed()
        self.assertFalse(User.objects.exists())
