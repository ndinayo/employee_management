from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APITestCase

from .models import AccountProfile, Business, PlatformMessage


@override_settings(EMAIL_DELIVERS=True)
class PlatformMessagingTests(APITestCase):
    password = "Cedar!Lantern-47-River"

    def setUp(self):
        cache.clear()
        mail.outbox = []
        self.admin = User.objects.create_user("platform-admin", "admin@example.com", self.password)
        AccountProfile.objects.create(user=self.admin, role="admin")
        self.business = Business.objects.create(name="Kigali Works")
        self.employer = User.objects.create_user("boss", "boss@example.com", self.password)
        AccountProfile.objects.create(user=self.employer, role="employer", business=self.business)

    def test_a_dashboard_message_is_not_emailed(self):
        """The default channel stays inside the dashboard."""
        self.client.force_authenticate(self.admin)
        sent = self.client.post(f"/api/admin/messages/{self.business.pk}/",
                                {"body": "  Your workspace is ready.  "}, format="json")
        self.assertEqual(sent.status_code, 201, sent.data)
        self.assertEqual(sent.data["body"], "Your workspace is ready.")
        self.assertEqual(sent.data["channel"], "message")
        self.assertTrue(sent.data["from_admin"])
        self.assertFalse(sent.data["emailed"])
        self.assertEqual(len(mail.outbox), 0)

        # The sender sees no badge for their own message; the company does.
        self.assertEqual(self.client.get(f"/api/admin/messages/{self.business.pk}/").data["unread"], 0)
        self.client.force_authenticate(self.employer)
        thread = self.client.get("/api/messages/").data
        self.assertEqual(thread["unread"], 1)
        self.assertEqual(thread["messages"][0]["body"], "Your workspace is ready.")
        self.assertEqual(thread["business_name"], "Kigali Works")

        # Reading the thread does not clear the badge; opening it does.
        self.assertEqual(self.client.get("/api/messages/").data["unread"], 1)
        self.assertEqual(self.client.post("/api/messages/read/").data["unread"], 0)
        self.assertEqual(self.client.get("/api/messages/").data["unread"], 0)

    def test_company_message_reaches_the_admin_dashboard(self):
        self.client.force_authenticate(self.employer)
        sent = self.client.post("/api/messages/", {"body": "Invitation emails are not arriving."},
                                format="json")
        self.assertEqual(sent.status_code, 201, sent.data)
        self.assertFalse(sent.data["from_admin"])
        self.assertEqual(len(mail.outbox), 0)

        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get("/api/admin/overview/").data["messages"]["unread"], 1)
        listed = self.client.get("/api/admin/messages/").data
        self.assertEqual(listed[0]["business"], self.business.pk)
        self.assertEqual(listed[0]["unread"], 1)
        self.assertEqual(listed[0]["last_body"], "Invitation emails are not arriving.")
        self.assertFalse(listed[0]["last_from_admin"])

        self.assertEqual(self.client.post(f"/api/admin/messages/{self.business.pk}/read/").data["unread"], 0)
        self.assertEqual(self.client.get("/api/admin/overview/").data["messages"]["unread"], 0)

    def test_companies_without_a_conversation_are_still_listed(self):
        quiet = Business.objects.create(name="Aurora Ltd")
        self.client.force_authenticate(self.admin)
        rows = self.client.get("/api/admin/messages/").data
        names = [row["business_name"] for row in rows]
        self.assertIn("Aurora Ltd", names)
        aurora = next(row for row in rows if row["business"] == quiet.pk)
        self.assertEqual(aurora["last_body"], "")
        self.assertEqual(aurora["unread"], 0)

    def test_companies_waiting_on_a_reply_are_listed_first(self):
        Business.objects.create(name="Aurora Ltd")
        self.client.force_authenticate(self.employer)
        self.client.post("/api/messages/", {"body": "Please call us."}, format="json")
        self.client.force_authenticate(self.admin)
        rows = self.client.get("/api/admin/messages/").data
        self.assertEqual(rows[0]["business_name"], "Kigali Works")
        self.assertEqual(rows[0]["unread"], 1)

    def test_an_emailed_message_goes_to_the_inbox_only(self):
        """It reaches their inbox and never their dashboard, and the sender
        keeps a copy so nothing written is lost."""
        self.client.force_authenticate(self.admin)
        sent = self.client.post(f"/api/admin/messages/{self.business.pk}/",
                                {"body": "Please confirm your billing address.",
                                 "channel": "email"}, format="json")
        self.assertEqual(sent.status_code, 201, sent.data)
        self.assertEqual(sent.data["channel"], "email")
        self.assertTrue(sent.data["emailed"])
        self.assertFalse(sent.data["read"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["boss@example.com"])
        self.assertIn("Please confirm your billing address.", mail.outbox[0].body)

        # The sender keeps it on screen.
        own = self.client.get(f"/api/admin/messages/{self.business.pk}/").data
        self.assertEqual(len(own["messages"]), 1)
        self.assertEqual(own["messages"][0]["channel"], "email")

        # The company sees nothing in the dashboard, and gets no badge.
        self.client.force_authenticate(self.employer)
        thread = self.client.get("/api/messages/").data
        self.assertEqual(thread["messages"], [])
        self.assertEqual(thread["unread"], 0)

    def test_an_emailed_message_from_a_company_stays_out_of_the_admin_dashboard(self):
        self.client.force_authenticate(self.employer)
        sent = self.client.post("/api/messages/", {"body": "Call us, please.", "channel": "email"},
                                format="json")
        self.assertEqual(sent.status_code, 201, sent.data)
        self.assertEqual(mail.outbox[-1].to, ["admin@example.com"])

        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get("/api/admin/overview/").data["messages"]["unread"], 0)
        thread = self.client.get(f"/api/admin/messages/{self.business.pk}/").data
        self.assertEqual(thread["messages"], [])
        self.assertEqual(self.client.get("/api/admin/messages/").data[0]["last_body"], "")

    def test_an_unknown_channel_is_rejected(self):
        self.client.force_authenticate(self.admin)
        rejected = self.client.post(f"/api/admin/messages/{self.business.pk}/",
                                    {"body": "Hello.", "channel": "sms"}, format="json")
        self.assertEqual(rejected.status_code, 400)
        self.assertFalse(PlatformMessage.objects.exists())

    def test_the_admin_can_clear_every_unread_message_at_once(self):
        """With many companies, opening each thread is not practical."""
        other = Business.objects.create(name="Aurora Ltd")
        rival = User.objects.create_user("rival", "rival@example.com", self.password)
        AccountProfile.objects.create(user=rival, role="employer", business=other)
        self.client.force_authenticate(self.employer)
        self.client.post("/api/messages/", {"body": "One."}, format="json")
        self.client.force_authenticate(rival)
        self.client.post("/api/messages/", {"body": "Two."}, format="json")

        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get("/api/admin/overview/").data["messages"]["unread"], 2)
        cleared = self.client.post("/api/admin/messages/read-all/")
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(cleared.data["cleared"], 2)
        self.assertEqual(cleared.data["unread"], 0)
        self.assertEqual(self.client.get("/api/admin/overview/").data["messages"]["unread"], 0)

        # Nothing was deleted: both conversations are still there.
        self.assertEqual(PlatformMessage.objects.count(), 2)
        self.assertEqual(len(self.client.get(f"/api/admin/messages/{self.business.pk}/").data["messages"]), 1)

        # Clearing again is harmless.
        self.assertEqual(self.client.post("/api/admin/messages/read-all/").data["cleared"], 0)

    def test_clearing_all_does_not_touch_the_companies_own_badges(self):
        self.client.force_authenticate(self.admin)
        self.client.post(f"/api/admin/messages/{self.business.pk}/", {"body": "For you."},
                         format="json")
        self.client.post("/api/admin/messages/read-all/")

        self.client.force_authenticate(self.employer)
        self.assertEqual(self.client.get("/api/messages/").data["unread"], 1)

    def test_only_an_administrator_can_clear_every_thread(self):
        self.client.force_authenticate(self.employer)
        self.assertEqual(self.client.post("/api/admin/messages/read-all/").status_code, 403)

    def test_an_empty_message_is_rejected(self):
        self.client.force_authenticate(self.admin)
        rejected = self.client.post(f"/api/admin/messages/{self.business.pk}/",
                                    {"body": "   "}, format="json")
        self.assertEqual(rejected.status_code, 400)
        self.assertFalse(PlatformMessage.objects.exists())

    def test_a_company_only_ever_sees_its_own_thread(self):
        other = Business.objects.create(name="Aurora Ltd")
        rival = User.objects.create_user("rival", "rival@example.com", self.password)
        AccountProfile.objects.create(user=rival, role="employer", business=other)

        self.client.force_authenticate(self.admin)
        self.client.post(f"/api/admin/messages/{self.business.pk}/", {"body": "Private note."},
                         format="json")

        self.client.force_authenticate(rival)
        thread = self.client.get("/api/messages/").data
        self.assertEqual(thread["business"], other.pk)
        self.assertEqual(thread["messages"], [])

    def test_employees_and_strangers_cannot_use_the_conversation(self):
        worker = User.objects.create_user("worker", "worker@example.com", self.password)
        AccountProfile.objects.create(user=worker, role="employee")
        self.client.force_authenticate(worker)
        self.assertEqual(self.client.get("/api/messages/").status_code, 403)
        self.assertEqual(self.client.get("/api/admin/messages/").status_code, 403)

        self.client.force_authenticate(self.employer)
        self.assertEqual(self.client.get("/api/admin/messages/").status_code, 403)
        self.assertEqual(
            self.client.get(f"/api/admin/messages/{self.business.pk}/").status_code, 403)

    def test_a_failed_email_is_reported_and_still_kept(self):
        """Nothing written is thrown away, and the sender is told it did not go."""
        self.employer.email = ""
        self.employer.save(update_fields=["email"])
        self.client.force_authenticate(self.admin)
        sent = self.client.post(f"/api/admin/messages/{self.business.pk}/",
                                {"body": "Still stored.", "channel": "email"}, format="json")
        self.assertEqual(sent.status_code, 201)
        self.assertFalse(sent.data["emailed"])
        self.assertEqual(len(mail.outbox), 0)

        own = self.client.get(f"/api/admin/messages/{self.business.pk}/").data
        self.assertEqual(own["messages"][0]["body"], "Still stored.")
        self.assertFalse(own["messages"][0]["emailed"])

    def test_deleting_a_company_takes_its_conversation(self):
        self.client.force_authenticate(self.admin)
        self.client.post(f"/api/admin/messages/{self.business.pk}/", {"body": "Hello."}, format="json")
        self.assertEqual(self.client.delete(f"/api/admin/businesses/{self.business.pk}/").status_code, 204)
        self.assertFalse(PlatformMessage.objects.exists())

    def test_a_missing_company_is_reported(self):
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get("/api/admin/messages/9999/").status_code, 404)
        self.assertEqual(self.client.post("/api/admin/messages/9999/read/").status_code, 404)
