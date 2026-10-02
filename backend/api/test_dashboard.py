"""The platform owner's dashboard: every figure counted from real rows."""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import AccountProfile, Business, Employee


class PlatformDashboardTests(APITestCase):
    password = "Cedar!Lantern-47-River"

    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user("platform-admin", "admin@example.com", self.password)
        AccountProfile.objects.create(user=self.admin, role="admin")
        self.business = Business.objects.create(name="Kigali Works")
        self.employer = User.objects.create_user("boss", "boss@example.com", self.password)
        AccountProfile.objects.create(user=self.employer, role="employer", business=self.business)
        self.client.force_authenticate(self.admin)

    def company(self, name, *, status="active", created=None, last_login=None, employer=True):
        business = Business.objects.create(name=name, status=status)
        if created:
            Business.objects.filter(pk=business.pk).update(created_at=created)
            business.refresh_from_db()
        if employer:
            user = User.objects.create_user(f"owner-{business.pk}", f"owner{business.pk}@example.com",
                                            self.password)
            user.last_login = last_login
            user.save(update_fields=["last_login"])
            AccountProfile.objects.create(user=user, role="employer", business=business)
        return business

    # --- 1. Platform scale ---------------------------------------------------

    def test_scale_counts_every_company_employer_and_employee(self):
        self.company("Aurora Ltd")
        self.company("Zed Co", status="suspended")
        self.company("Pending Plc", status="pending")
        Employee.objects.create(business=self.business, first_name="A", last_name="B",
                                email="a@example.com", job_title="Analyst",
                                date_joined=timezone.localdate())
        Employee.objects.create(business=self.business, first_name="C", last_name="D",
                                email="c@example.com", job_title="Clerk",
                                date_joined=timezone.localdate(), is_active=False)

        scale = self.client.get("/api/admin/overview/").data["scale"]
        self.assertEqual(scale["companies"], 4)
        self.assertEqual(scale["active_companies"], 2)
        self.assertEqual(scale["suspended_companies"], 1)
        self.assertEqual(scale["pending_companies"], 1)
        self.assertEqual(scale["employers"], 4)
        self.assertEqual(scale["employees"], 2)
        self.assertEqual(scale["active_employees"], 1)
        self.assertEqual(scale["companies_this_month"], 4)

    def test_companies_added_this_month_excludes_older_ones(self):
        self.company("Old Co", created=timezone.now() - timedelta(days=200))
        self.assertEqual(
            self.client.get("/api/admin/overview/").data["scale"]["companies_this_month"], 1)

    # --- 2. Company lifecycle ------------------------------------------------

    def test_lifecycle_lists_registrations_pending_suspended_and_dormant(self):
        self.company("Pending Plc", status="pending")
        quiet = self.company("Quiet Co", last_login=timezone.now() - timedelta(days=120))
        self.client.patch(f"/api/admin/businesses/{self.company('Gone Ltd').pk}/",
                          {"status": "suspended"}, format="json")

        life = self.client.get("/api/admin/overview/").data["lifecycle"]
        self.assertIn("Pending Plc", [row["name"] for row in life["awaiting_activation"]])
        self.assertIn("Gone Ltd", [row["name"] for row in life["recently_suspended"]])
        self.assertIn("Quiet Co", [row["name"] for row in life["dormant"]])
        self.assertEqual(life["dormant"][0]["id"], quiet.pk)
        # Newest registration first.
        self.assertEqual(life["recent_registrations"][0]["name"], "Gone Ltd")
        self.assertEqual(life["dormant_days"], 60)

    def test_a_company_that_never_signed_in_is_not_called_dormant(self):
        """Never used and gone quiet are different problems."""
        self.company("Never Co")
        data = self.client.get("/api/admin/overview/").data
        self.assertEqual(data["lifecycle"]["dormant"], [])
        self.assertEqual(data["issues"]["never_used_companies"], 2)

    # --- 3. Platform usage ---------------------------------------------------

    def test_usage_counts_activity_windows_from_real_sign_ins(self):
        self.company("Today Co", last_login=timezone.now())
        self.company("Week Co", last_login=timezone.now() - timedelta(days=3))
        self.company("Old Co", last_login=timezone.now() - timedelta(days=200))

        usage = self.client.get("/api/admin/overview/").data["usage"]
        self.assertEqual(usage["active_today"], 1)
        self.assertEqual(usage["active_week"], 2)
        # Rolling windows, so the three always nest whatever the date.
        self.assertEqual(usage["active_month"], 2)
        self.assertEqual(usage["total_users"], User.objects.count())

    def test_growth_series_and_percentage_come_from_registration_dates(self):
        last_month = timezone.now().replace(day=1) - timedelta(days=1)
        self.company("Older One", created=last_month)
        self.company("Older Two", created=last_month)
        self.company("New One")

        usage = self.client.get("/api/admin/overview/").data["usage"]
        self.assertEqual(usage["companies_last_month"], 2)
        self.assertEqual(usage["companies_this_month"], 2)
        self.assertEqual(usage["growth_percent"], 0)
        self.assertEqual(len(usage["growth"]), 12)
        self.assertEqual(usage["growth"][-1]["companies"], 2)
        # The running total never goes backwards.
        totals = [point["total"] for point in usage["growth"]]
        self.assertEqual(totals, sorted(totals))
        self.assertEqual(totals[-1], Business.objects.count())

    def test_growth_percent_handles_a_first_month(self):
        self.assertEqual(self.client.get("/api/admin/overview/").data["usage"]["growth_percent"], 100)

    # --- 4. Account issues ---------------------------------------------------

    def test_issues_report_accounts_needing_attention(self):
        self.company("Signed In Co", last_login=timezone.now())
        self.company("Orphan Co", employer=False)
        locked = User.objects.create_user("locked", "locked@example.com", self.password)
        locked.is_active = False
        locked.save(update_fields=["is_active"])
        Employee.objects.create(business=self.business, first_name="A", last_name="B",
                                email="a@example.com", job_title="Analyst",
                                date_joined=timezone.localdate(), invite_email_failed=True)

        issues = self.client.get("/api/admin/overview/").data["issues"]
        self.assertEqual(issues["dormant_employers"], 1)
        self.assertEqual(issues["disabled_accounts"], 1)
        self.assertEqual(issues["companies_without_employer"], 1)
        self.assertEqual(issues["failed_invitations"], 1)
        self.assertEqual(issues["companies_with_failed_invitations"], 1)
        self.assertFalse(issues["email_delivery_configured"])

    @override_settings(EMAIL_DELIVERS=True)
    def test_email_delivery_state_is_read_not_assumed(self):
        self.assertTrue(
            self.client.get("/api/admin/overview/").data["issues"]["email_delivery_configured"])

    # --- 5. Communication ----------------------------------------------------

    def test_messages_section_uses_the_existing_conversations(self):
        self.client.force_authenticate(self.employer)
        self.client.post("/api/messages/", {"body": "Please help."}, format="json")
        self.client.force_authenticate(self.admin)

        messages = self.client.get("/api/admin/overview/").data["messages"]
        self.assertEqual(messages["unread"], 1)
        self.assertEqual(messages["unresolved"], 1)
        self.assertEqual(messages["recent"][0]["business_name"], "Kigali Works")
        self.assertTrue(messages["recent"][0]["awaiting_reply"])

        # Answering it resolves the request.
        self.client.post(f"/api/admin/messages/{self.business.pk}/", {"body": "On it."},
                         format="json")
        messages = self.client.get("/api/admin/overview/").data["messages"]
        self.assertEqual(messages["unresolved"], 0)
        self.assertFalse(messages["recent"][0]["awaiting_reply"])

    @override_settings(EMAIL_DELIVERS=True)
    def test_an_emailed_message_is_not_shown_as_a_conversation(self):
        self.client.force_authenticate(self.employer)
        self.client.post("/api/messages/", {"body": "By mail.", "channel": "email"}, format="json")
        self.client.force_authenticate(self.admin)
        messages = self.client.get("/api/admin/overview/").data["messages"]
        self.assertEqual(messages["recent"], [])
        self.assertEqual(messages["unresolved"], 0)

    # --- 6. Platform health --------------------------------------------------

    def test_health_reflects_the_real_system(self):
        health = self.client.get("/api/admin/health/")
        self.assertEqual(health.status_code, 200)
        data = health.data
        self.assertEqual(data["database"]["status"], "operational")
        self.assertIsNotNone(data["database"]["latency_ms"])
        self.assertEqual(data["database"]["engine"], "sqlite")
        # No sender is configured in the test settings, so this must say so
        # rather than claiming everything is fine.
        self.assertEqual(data["email"]["status"], "not_configured")
        self.assertEqual(data["api"]["status"], "degraded")
        self.assertIn("email", data["api"]["detail"])
        self.assertIn(data["storage"]["status"], ("operational", "degraded", "unknown"))
        self.assertEqual(data["application"]["version"], "1.0.0")
        self.assertEqual(data["application"]["environment"],
                         "development" if settings.DEBUG else "production")
        self.assertTrue(data["application"]["django"])
        self.assertTrue(data["application"]["python"])

    @override_settings(EMAIL_DELIVERS=True)
    def test_health_is_clear_when_every_service_is_up(self):
        data = self.client.get("/api/admin/health/").data
        self.assertEqual(data["email"]["status"], "operational")
        if data["storage"]["status"] == "operational":
            self.assertEqual(data["api"]["status"], "operational")

    # --- Company status management -------------------------------------------

    def test_suspending_a_company_closes_its_workspace_and_activating_reopens_it(self):
        result = self.client.patch(f"/api/admin/businesses/{self.business.pk}/",
                                   {"status": "suspended"}, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data["status"], "suspended")
        self.employer.refresh_from_db()
        self.assertFalse(self.employer.is_active)
        self.business.refresh_from_db()
        self.assertIsNotNone(self.business.status_changed_at)

        self.client.force_authenticate(None)
        denied = self.client.post("/api/token/", {"username": "boss", "password": self.password},
                                  format="json")
        self.assertEqual(denied.status_code, 401)

        self.client.force_authenticate(self.admin)
        self.client.patch(f"/api/admin/businesses/{self.business.pk}/", {"status": "active"},
                          format="json")
        self.employer.refresh_from_db()
        self.assertTrue(self.employer.is_active)

    def test_marking_a_company_pending_does_not_close_its_workspace(self):
        """Verification is a queue for the administrator, not a lock-out."""
        self.client.patch(f"/api/admin/businesses/{self.business.pk}/", {"status": "pending"},
                          format="json")
        self.employer.refresh_from_db()
        self.assertTrue(self.employer.is_active)
        self.client.force_authenticate(self.employer)
        self.assertEqual(self.client.get("/api/employees/").status_code, 200)

    def test_an_unknown_status_is_rejected(self):
        rejected = self.client.patch(f"/api/admin/businesses/{self.business.pk}/",
                                     {"status": "deleted"}, format="json")
        self.assertEqual(rejected.status_code, 400)
        self.business.refresh_from_db()
        self.assertEqual(self.business.status, "active")

    def test_a_self_service_signup_arrives_awaiting_verification(self):
        self.client.force_authenticate(None)
        created = self.client.post("/api/signup/", {
            "username": "newco", "email": "newco@example.com", "password": self.password,
            "password_confirm": self.password, "role": "employer", "business_name": "New Co",
        }, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(Business.objects.get(name="New Co").status, "pending")

    def test_an_admin_created_company_is_active_immediately(self):
        created = self.client.post("/api/admin/employers/", {
            "username": "owner-two", "email": "owner-two@example.com",
            "password": self.password, "business_name": "Second Works",
        }, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(Business.objects.get(name="Second Works").status, "active")

    # --- The boundary the dashboard must not cross ---------------------------

    def test_the_dashboard_exposes_no_company_hr_records(self):
        """Attendance, leave, payroll, contracts, salaries, holidays and
        announcements belong to each employer, never to this dashboard."""
        payload = str(self.client.get("/api/admin/overview/").data)
        for word in ("attendance", "leave", "payroll", "contract", "salary", "salaries",
                     "holiday", "announcement"):
            self.assertNotIn(word, payload.lower())

    def test_only_an_administrator_can_read_the_dashboard(self):
        self.client.force_authenticate(self.employer)
        self.assertEqual(self.client.get("/api/admin/overview/").status_code, 403)
        self.assertEqual(self.client.get("/api/admin/health/").status_code, 403)
        self.assertEqual(
            self.client.patch(f"/api/admin/businesses/{self.business.pk}/",
                              {"status": "suspended"}, format="json").status_code, 403)
