from django.contrib.auth.models import User
from django.core.cache import cache
from rest_framework.test import APITestCase

from .models import AccountProfile, Business, Employee


class PlatformAdminTests(APITestCase):
    password = "Cedar!Lantern-47-River"

    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user("ndinayoeric1", "ndinayoeric1@gmail.com", "TestPlatformAdmin#4821")
        AccountProfile.objects.create(user=self.admin, role="admin")
        self.business = Business.objects.create(name="Kigali Works")
        self.employer = User.objects.create_user("boss", "boss@example.com", self.password)
        AccountProfile.objects.create(user=self.employer, role="employer", business=self.business)
        self.client.force_authenticate(self.admin)

    def test_admin_sees_when_an_employer_joined(self):
        result = self.client.get("/api/admin/employers/")
        self.assertEqual(result.status_code, 200)
        row = result.data[0]
        self.assertEqual(row["username"], "boss")
        from django.utils import timezone
        self.assertEqual(row["date_joined"], timezone.localtime(self.employer.date_joined).isoformat())
        self.assertEqual(row["workspace_started"], timezone.localtime(self.business.created_at).isoformat())
        self.assertEqual(row["last_login"], "")
        self.assertIn("email_configured", row)
        self.assertEqual(row["employee_count"], 0)

    def test_account_reports_the_admin_workspace(self):
        result = self.client.get("/api/account/")
        self.assertTrue(result.data["can_admin"])
        self.assertFalse(result.data["can_manage"])
        self.assertEqual(result.data["role"], "admin")

    def test_admin_can_list_and_create_employers_and_employees(self):
        overview = self.client.get("/api/admin/overview/")
        self.assertEqual(overview.status_code, 200)
        self.assertEqual(overview.data["scale"]["employers"], 1)

        created = self.client.post("/api/admin/employers/", {
            "username": "owner-two", "email": "owner-two@example.com",
            "password": self.password, "business_name": "Second Works",
        }, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["business_name"], "Second Works")

        hired = self.client.post("/api/admin/employees/", {
            "business": created.data["business_id"], "first_name": "Aline",
            "last_name": "Uwase", "job_title": "Analyst", "email": "aline@example.com",
        }, format="json")
        self.assertEqual(hired.status_code, 201, hired.data)
        self.assertTrue(hired.data["invite"]["created"])
        self.assertEqual(self.client.get("/api/admin/employees/").data[0]["business_name"], "Second Works")

        self.assertEqual(self.client.delete(f"/api/admin/employees/{hired.data['id']}/").status_code, 204)
        self.assertEqual(self.client.delete(f"/api/admin/businesses/{created.data['business_id']}/").status_code, 204)
        self.assertFalse(Business.objects.filter(name="Second Works").exists())

    def test_admin_cannot_delete_an_employer_on_its_own(self):
        """The employer sign-in belongs to its company; only the company goes."""
        blocked = self.client.delete(f"/api/admin/employers/{self.employer.pk}/")
        self.assertEqual(blocked.status_code, 405)
        self.employer.refresh_from_db()
        self.assertTrue(Business.objects.filter(pk=self.business.pk).exists())

    def test_deleting_a_company_removes_its_employer_and_employees(self):
        hired = self.client.post("/api/admin/employees/", {
            "business": self.business.pk, "first_name": "Aline", "last_name": "Uwase",
            "job_title": "Analyst", "email": "aline@example.com",
        }, format="json")
        self.assertEqual(hired.status_code, 201, hired.data)

        deleted = self.client.delete(f"/api/admin/businesses/{self.business.pk}/")
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(Business.objects.filter(pk=self.business.pk).exists())
        self.assertFalse(User.objects.filter(pk=self.employer.pk).exists())
        self.assertFalse(Employee.objects.filter(pk=hired.data["id"]).exists())
        self.assertEqual(self.client.delete("/api/admin/businesses/9999/").status_code, 404)

    def test_overview_reports_company_signals_not_employee_onboarding(self):
        """The admin is alerted about companies; employee onboarding is their
        own employer's business, so it is not reported here."""
        hired = self.client.post("/api/admin/employees/", {
            "business": self.business.pk, "first_name": "Aline", "last_name": "Uwase",
            "job_title": "Analyst", "email": "aline@example.com",
        }, format="json")
        self.assertEqual(hired.status_code, 201, hired.data)
        self.assertTrue(AccountProfile.objects.filter(role="employee", must_change_password=True).exists())

        overview = self.client.get("/api/admin/overview/").data
        self.assertNotIn("invited_employees", overview["issues"])
        # The employer has never signed in, so the one signal raised is theirs.
        self.assertEqual(overview["issues"]["dormant_employers"], 1)
        self.assertEqual(overview["issues"]["suspended_employers"], 0)
        self.assertEqual(overview["scale"]["employees"], 1)

        self.client.patch(f"/api/admin/employers/{self.employer.pk}/", {"is_active": False}, format="json")
        overview = self.client.get("/api/admin/overview/").data
        self.assertEqual(overview["issues"]["dormant_employers"], 0)
        self.assertEqual(overview["issues"]["suspended_employers"], 1)

    def test_company_list_carries_its_employer_and_counts(self):
        rows = self.client.get("/api/admin/businesses/").data
        row = next(item for item in rows if item["id"] == self.business.pk)
        self.assertEqual(row["employer_username"], self.employer.username)
        self.assertTrue(row["employer_is_active"])
        self.assertEqual(row["employee_count"], Employee.objects.filter(business=self.business).count())

    def test_employer_cannot_use_the_admin_api(self):
        self.client.force_authenticate(self.employer)
        self.assertEqual(self.client.get("/api/admin/overview/").status_code, 403)
        self.assertEqual(self.client.get("/api/admin/employers/").status_code, 403)
        self.assertEqual(self.client.get("/api/admin/employees/").status_code, 403)

    def test_admin_can_deactivate_an_employer(self):
        result = self.client.patch(f"/api/admin/employers/{self.employer.pk}/", {"is_active": False}, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        self.assertFalse(result.data["is_active"])
        self.employer.refresh_from_db()
        self.assertFalse(self.employer.is_active)
        self.assertTrue(Business.objects.filter(pk=self.business.pk).exists())

        self.client.force_authenticate(None)
        denied = self.client.post("/api/token/", {"username": "boss", "password": self.password}, format="json")
        self.assertEqual(denied.status_code, 401)
        self.client.force_authenticate(self.employer)
        self.assertEqual(self.client.get("/api/employees/").status_code, 403)

        self.client.force_authenticate(self.admin)
        restored = self.client.patch(f"/api/admin/employers/{self.employer.pk}/", {"is_active": True}, format="json")
        self.assertTrue(restored.data["is_active"])
        self.client.force_authenticate(None)
        allowed = self.client.post("/api/token/", {"username": "boss", "password": self.password}, format="json")
        self.assertEqual(allowed.status_code, 200, allowed.data)

    def test_admin_signs_in_with_email(self):
        self.client.force_authenticate(None)
        result = self.client.post("/api/token/", {
            "username": "ndinayoeric1@gmail.com", "password": "TestPlatformAdmin#4821",
        }, format="json")
        self.assertEqual(result.status_code, 200, result.data)
