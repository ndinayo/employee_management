import importlib
import re
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.apps import apps as django_apps
from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from rest_framework.test import APITestCase

from . import user_emails
from .models import AccountProfile, Business, Employee

PASSWORD = "Cedar!Lantern-47-River"


class EmailSignInTests(APITestCase):
    def setUp(self):
        cache.clear()
        mail.outbox = []

    def signup(self, **changes):
        payload = {"username": "owner", "email": "owner@example.com", "role": "employer",
                   "business_name": "Cedar Trading", "password": PASSWORD, "password_confirm": PASSWORD, **changes}
        return self.client.post("/api/signup/", payload, format="json")

    def sign_in(self, login, password=PASSWORD):
        self.client.force_authenticate(None)
        return self.client.post("/api/token/", {"username": login, "password": password}, format="json")

    def account_for(self, login, password=PASSWORD):
        token = self.sign_in(login, password)
        self.assertEqual(token.status_code, 200, token.data)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.data['access']}")
        account = self.client.get("/api/account/").data
        self.client.credentials()
        return account

    def test_employer_signs_in_with_username_or_email_in_any_case(self):
        self.assertEqual(self.signup().status_code, 201)
        for login in ("owner", "owner@example.com", "OWNER@Example.com"):
            with self.subTest(login=login):
                account = self.account_for(login)
                self.assertEqual((account["username"], account["role"]), ("owner", "employer"))
                self.assertTrue(account["can_manage"])
        self.assertEqual(self.sign_in("owner@example.com", "Wrong!Password-11").status_code, 401)

    def test_hired_employee_signs_in_with_username_or_email(self):
        self.assertEqual(self.signup().status_code, 201)
        self.client.force_authenticate(User.objects.get(username="owner"))
        hired = self.client.post("/api/employees/", {"first_name": "Aline", "last_name": "Uwase",
                                                     "job_title": "Accountant", "email": "aline@example.com"},
                                 format="json")
        self.assertEqual(hired.status_code, 201, hired.data)
        invite = hired.data["invite"]
        password = invite.get("temporary_password") or re.search(
            r"Temporary password: (\S+)", mail.outbox[-1].body).group(1)
        for login in (invite["username"], "Aline@Example.com"):
            with self.subTest(login=login):
                account = self.account_for(login, password)
                self.assertEqual(account["role"], "employee")
                self.assertFalse(account["can_manage"])

    def test_super_admin_signs_in_with_username_or_email(self):
        with mock.patch.dict("os.environ", {"PLATFORM_ADMIN_PASSWORD": "TestSeedAdmin#5930"}):
            call_command("seed", stdout=StringIO())
        for login in ("admin", "ndinayoeric1@gmail.com"):
            with self.subTest(login=login):
                account = self.account_for(login, "TestSeedAdmin#5930")
                self.assertEqual(account["role"], "admin")
                self.assertTrue(account["can_admin"])

    def test_signup_rejects_an_email_already_in_use_in_any_case(self):
        self.assertEqual(self.signup().status_code, 201)
        for changes in ({"role": "employee", "business_name": ""}, {"business_name": "Second Company"}):
            with self.subTest(changes=changes):
                duplicate = self.signup(username="someone-else", email="Owner@EXAMPLE.com", **changes)
                self.assertEqual(duplicate.status_code, 400, duplicate.data)
                self.assertIn("email", duplicate.data)
        self.assertEqual(User.objects.filter(email__iexact="owner@example.com").count(), 1)
        self.assertEqual(Business.objects.count(), 1)
        self.assertEqual(AccountProfile.objects.count(), 1)

    def test_super_admin_cannot_create_an_employer_with_a_used_email(self):
        self.assertEqual(self.signup().status_code, 201)
        admin = User.objects.create_superuser("root", "root@example.com", PASSWORD)
        AccountProfile.objects.create(user=admin, role="admin")
        self.client.force_authenticate(admin)
        result = self.client.post("/api/admin/employers/", {
            "username": "copycat", "email": "OWNER@example.com", "password": PASSWORD,
            "business_name": "Copy Co"}, format="json")
        self.assertEqual(result.status_code, 400, result.data)
        self.assertIn("email", result.data)
        self.assertFalse(User.objects.filter(username="copycat").exists())

    def test_hiring_with_an_employer_email_creates_no_second_sign_in(self):
        self.assertEqual(self.signup().status_code, 201)
        owner = User.objects.get(username="owner")
        self.client.force_authenticate(owner)
        hired = self.client.post("/api/employees/", {"first_name": "Self", "last_name": "Hire",
                                                     "job_title": "Owner", "email": "owner@example.com"},
                                 format="json")
        self.assertEqual(hired.status_code, 201, hired.data)
        self.assertFalse(hired.data["invite"]["created"])
        self.assertEqual(User.objects.filter(email__iexact="owner@example.com").count(), 1)
        self.assertTrue(Employee.objects.filter(email="owner@example.com").exists())
        self.assertEqual(self.account_for("owner@example.com")["role"], "employer")

    def test_database_rejects_duplicate_emails_but_allows_blank_ones(self):
        self.assertTrue(user_emails.unique_index_exists())
        User.objects.create_user("first", "same@example.com", PASSWORD)
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user("second", "SAME@example.com", PASSWORD)
        User.objects.create_user("blank-one", "", PASSWORD)
        User.objects.create_user("blank-two", "", PASSWORD)

    def test_bootstrap_admin_skips_an_email_that_is_already_used(self):
        User.objects.create_user("owner", "owner@example.com", PASSWORD)
        env = {"DJANGO_SUPERUSER_USERNAME": "boot", "DJANGO_SUPERUSER_PASSWORD": PASSWORD,
               "DJANGO_SUPERUSER_EMAIL": "Owner@example.com"}
        out = StringIO()
        with mock.patch.dict("os.environ", env):
            call_command("bootstrap_admin", stdout=out)
        self.assertIn("already belongs to another account", out.getvalue())
        self.assertFalse(User.objects.filter(username="boot").exists())


class DuplicateEmailReportTests(APITestCase):
    def report(self):
        out = StringIO()
        call_command("check_duplicate_emails", stdout=out)
        return out.getvalue()

    def test_reports_legacy_duplicates_without_changing_them(self):
        user_emails.drop_unique_index()
        business = Business.objects.create(name="Kigali Works")
        employer = User.objects.create_user("boss", "shared@example.com", PASSWORD)
        AccountProfile.objects.create(user=employer, role="employer", business=business)
        employee = User.objects.create_user("boss-staff", "Shared@Example.com", PASSWORD)
        AccountProfile.objects.create(user=employee, role="employee")

        output = self.report()
        self.assertIn("shared@example.com", output)
        self.assertIn(f"id={employer.pk} username='boss'", output)
        self.assertIn("role=employer, business", output)
        self.assertIn(f"id={employee.pk} username='boss-staff'", output)
        self.assertNotIn(PASSWORD, output)
        self.assertFalse(user_emails.unique_index_exists())
        self.assertEqual(User.objects.filter(email__iexact="shared@example.com").count(), 2)

        employee.email = "staff@example.com"
        employee.save()
        self.assertIn("Unique email index created", self.report())
        self.assertTrue(user_emails.unique_index_exists())
        self.assertIn("already in place", self.report())

    def test_migration_skips_the_index_while_duplicates_exist(self):
        migration = importlib.import_module("api.migrations.0029_user_email_unique_index")
        user_emails.drop_unique_index()
        User.objects.create_user("one", "shared@example.com", PASSWORD)
        User.objects.create_user("two", "SHARED@example.com", PASSWORD)
        editor = SimpleNamespace(connection=connection, quote_name=connection.ops.quote_name,
                                 execute=lambda sql: connection.cursor().execute(sql))
        with mock.patch("builtins.print") as printed:
            migration.add_unique_email_index(django_apps, editor)
        self.assertIn("Skipped", printed.call_args.args[0])
        self.assertFalse(user_emails.unique_index_exists())
        self.assertEqual(User.objects.count(), 2)

        User.objects.filter(username="two").update(email="two@example.com")
        migration.add_unique_email_index(django_apps, editor)
        self.assertTrue(user_emails.unique_index_exists())
