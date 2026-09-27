from django.contrib.auth.models import User
from django.core.cache import cache
from rest_framework.test import APITestCase

from .models import AccountProfile, Business, Employee


class PlatformAdminTests(APITestCase):
    password = "Cedar!Lantern-47-River"

    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user("ndinayoeric1", "ndinayoeric1@gmail.com", "Muyango@12345")
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
        self.assertEqual(overview.data["employers"], 1)

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
        self.assertEqual(self.client.delete(f"/api/admin/employers/{created.data['id']}/").status_code, 204)
        self.assertFalse(Business.objects.filter(name="Second Works").exists())

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
            "username": "ndinayoeric1@gmail.com", "password": "Muyango@12345",
        }, format="json")
        self.assertEqual(result.status_code, 200, result.data)
