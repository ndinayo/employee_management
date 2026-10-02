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

    def test_promotes_an_existing_superuser_named_admin_once(self):
        legacy = User.objects.create_superuser("admin", "", "Cedar!Lantern-47-River")
        legacy.is_active = False
        legacy.save()
        with mock.patch.dict("os.environ", WITH_PASSWORD):
            self.assertIn("promoted to platform admin", seed())
        with mock.patch.dict("os.environ", {"PLATFORM_ADMIN_PASSWORD": "Another#Pass-7742"}):
            self.assertIn("leaving the account unchanged", seed())
        legacy.refresh_from_db()
        self.assertEqual(User.objects.get().pk, legacy.pk)
        self.assertEqual(legacy.email, "ndinayoeric1@gmail.com")
        self.assertTrue(legacy.is_active and legacy.is_staff and legacy.is_superuser)
        self.assertEqual(legacy.account_profile.role, "admin")
        self.assertTrue(legacy.check_password(PASSWORD))

    def test_promotion_without_a_password_keeps_the_existing_one(self):
        legacy = User.objects.create_user("admin", "", "Cedar!Lantern-47-River")
        with mock.patch.dict("os.environ", NO_PASSWORD):
            self.assertIn("password was not changed", seed())
        legacy.refresh_from_db()
        self.assertTrue(legacy.check_password("Cedar!Lantern-47-River"))
        self.assertEqual(legacy.account_profile.role, "admin")

    def test_promotes_an_unlinked_account_that_owns_the_email(self):
        signed_up = User.objects.create_user("eric", "NdinayoEric1@gmail.com", "Cedar!Lantern-47-River")
        AccountProfile.objects.create(user=signed_up, role="employee")
        with mock.patch.dict("os.environ", WITH_PASSWORD):
            seed()
        signed_up.refresh_from_db()
        self.assertEqual((signed_up.username, signed_up.email), ("admin", "ndinayoeric1@gmail.com"))
        self.assertEqual(signed_up.account_profile.role, "admin")
        self.assertEqual(AccountProfile.objects.count(), 1)

    def test_weak_password_blocks_promotion_without_changes(self):
        legacy = User.objects.create_user("admin", "", "Cedar!Lantern-47-River")
        with mock.patch.dict("os.environ", {"PLATFORM_ADMIN_PASSWORD": "123"}), self.assertRaises(CommandError):
            seed()
        legacy.refresh_from_db()
        self.assertFalse(legacy.is_superuser or AccountProfile.objects.exists())
        self.assertTrue(legacy.check_password("Cedar!Lantern-47-River"))

    def test_refuses_to_promote_an_employer_using_the_email(self):
        employer = User.objects.create_user("boss", "ndinayoeric1@gmail.com", "Cedar!Lantern-47-River")
        AccountProfile.objects.create(user=employer, role="employer", business=Business.objects.create(name="Works"))
        with mock.patch.dict("os.environ", WITH_PASSWORD), self.assertRaises(CommandError):
            seed()
        employer.refresh_from_db()
        self.assertEqual((employer.username, employer.account_profile.role), ("boss", "employer"))
        self.assertFalse(employer.is_superuser)

    def test_account_named_admin_wins_when_another_account_has_the_email(self):
        legacy = User.objects.create_superuser("admin", "", "Cedar!Lantern-47-River")
        older = platform_admin("ndinayoeric1", "ndinayoeric1@gmail.com")
        with mock.patch.dict("os.environ", WITH_PASSWORD):
            self.assertIn("belongs to another account", seed())
        legacy.refresh_from_db()
        older.refresh_from_db()
        self.assertEqual(legacy.account_profile.role, "admin")
        self.assertEqual(legacy.email, "")
        self.assertEqual(older.email, "ndinayoeric1@gmail.com")
        self.assertEqual((older.username, older.account_profile.role), ("ndinayoeric1", "admin"))
        self.assertTrue(older.check_password("Changed#Later-5521"))
        self.assertEqual(User.objects.count(), 2)

    def test_creating_the_admin_requires_a_valid_password(self):
        for password in ("", "123"):
            with mock.patch.dict("os.environ", {"PLATFORM_ADMIN_PASSWORD": password}):
                with self.assertRaises(CommandError):
                    seed()
        self.assertFalse(User.objects.exists())
