import json
from email.utils import parseaddr
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.core.mail import EmailMessage
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APITestCase

from . import onboarding
from .brevo import BrevoEmailBackend
from .models import AccountProfile, Business, InvitationEmailSettings

SYSTEM_SENDER = "Employee Management <hr@example.com>"


class FakeResponse:
    status = 201

    def read(self):
        return b'{"messageId": "<test@smtp-relay.brevo.com>"}'

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@override_settings(BREVO_API_KEY="xkeysib-test", DEFAULT_FROM_EMAIL="HR <hr@example.com>")
class BrevoBackendTests(SimpleTestCase):
    def test_posts_the_message_to_the_brevo_api(self):
        message = EmailMessage("Welcome", "Your password is ready.", None, ["Aline <aline@example.com>"],
                               reply_to=["boss@example.com"])
        with mock.patch("api.brevo.urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
            self.assertEqual(BrevoEmailBackend().send_messages([message]), 1)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.brevo.com/v3/smtp/email")
        self.assertEqual(request.get_header("Api-key"), "xkeysib-test")
        payload = json.loads(request.data)
        self.assertEqual(payload["sender"], {"email": "hr@example.com", "name": "HR"})
        self.assertEqual(payload["to"], [{"email": "aline@example.com", "name": "Aline"}])
        self.assertEqual(payload["replyTo"], {"email": "boss@example.com"})
        self.assertEqual(payload["subject"], "Welcome")
        self.assertEqual(payload["textContent"], "Your password is ready.")

    def test_a_personal_sender_keeps_the_platform_mailbox_and_replies_to_the_author(self):
        message = EmailMessage("Hello", "Body", '"Eric via Employee Management" <hr@example.com>',
                               ["admin@example.com"], reply_to=["eric@gmail.com"])
        with mock.patch("api.brevo.urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
            BrevoEmailBackend().send_messages([message])
        payload = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(payload["sender"], {"email": "hr@example.com", "name": "Eric via Employee Management"})
        self.assertEqual(payload["replyTo"], {"email": "eric@gmail.com"})

    def test_a_rejected_message_raises_unless_failing_silently(self):
        message = EmailMessage("Welcome", "Body", "hr@example.com", ["aline@example.com"])
        with mock.patch("api.brevo.urllib.request.urlopen", side_effect=OSError("down")):
            with self.assertRaises(OSError):
                BrevoEmailBackend().send_messages([message])
            self.assertEqual(BrevoEmailBackend(fail_silently=True).send_messages([message]), 0)


@override_settings(BREVO_API_KEY="xkeysib-test", DEFAULT_FROM_EMAIL="hr@example.com", EMAIL_DELIVERS=True)
class PlatformMailSettingsTests(APITestCase):
    def setUp(self):
        self.business = Business.objects.create(name="Kigali Works")
        self.employer = User.objects.create_user("boss", "boss@example.com", "Cedar!Lantern-47-River")
        AccountProfile.objects.create(user=self.employer, role="employer", business=self.business)
        self.client.force_authenticate(self.employer)

    def test_brevo_overrides_a_saved_gmail_sender(self):
        InvitationEmailSettings.objects.create(
            pk=1, owner_business=self.business, email_host_user="boss@gmail.com", email_host_password="app")
        self.assertEqual(onboarding.from_address(), "hr@example.com")
        settings = self.client.get("/api/account/email/").data
        self.assertTrue(settings["email_configured"])
        self.assertFalse(settings["can_manage_email_settings"])
        self.assertEqual(settings["email_host_user"], "hr@example.com")

    def test_employers_cannot_replace_the_platform_sender(self):
        result = self.client.patch("/api/account/email/", {
            "email_host_user": "boss@gmail.com", "email_host_password": "app-password"}, format="json")
        self.assertEqual(result.status_code, 403)
        self.assertFalse(InvitationEmailSettings.objects.exists())


class PersonalSenderTests(APITestCase):
    """Mail a person writes carries their name and Reply-To; system mail does not."""

    password = "Cedar!Lantern-47-River"

    def setUp(self):
        cache.clear()
        mail.outbox = []
        self.admin = User.objects.create_user("platform-admin", "admin@example.com", self.password)
        AccountProfile.objects.create(user=self.admin, role="admin")
        self.business = Business.objects.create(name="Kigali Works")
        self.employer = User.objects.create_user("eric", "eric@gmail.com", self.password,
                                                 first_name="Eric", last_name="Ndinayo")
        AccountProfile.objects.create(user=self.employer, role="employer", business=self.business)

    def email_platform_team(self, user=None):
        self.client.force_authenticate(user or self.employer)
        sent = self.client.post("/api/messages/", {"body": "Please call us.", "channel": "email"},
                                format="json")
        self.assertEqual(sent.status_code, 201, sent.data)
        self.assertTrue(sent.data["emailed"], sent.data)
        return mail.outbox[-1]

    @override_settings(BREVO_API_KEY="xkeysib-test", DEFAULT_FROM_EMAIL=SYSTEM_SENDER, EMAIL_DELIVERS=True)
    def test_employer_email_uses_their_name_and_reply_to_with_brevo(self):
        sent = self.email_platform_team()
        self.assertEqual(parseaddr(sent.from_email),
                         ("Eric Ndinayo via Employee Management", "hr@example.com"))
        self.assertEqual(sent.reply_to, ["eric@gmail.com"])
        self.assertEqual(sent.to, ["admin@example.com"])

    @override_settings(BREVO_API_KEY="xkeysib-test", DEFAULT_FROM_EMAIL=SYSTEM_SENDER, EMAIL_DELIVERS=True)
    def test_each_author_is_named_from_their_own_account(self):
        other = User.objects.create_user("aline-hr", "aline@example.com", self.password)
        AccountProfile.objects.create(user=other, role="employer",
                                      business=Business.objects.create(name="Huye Foods"))
        self.email_platform_team()
        sent = self.email_platform_team(other)
        self.assertEqual(parseaddr(sent.from_email), ("aline-hr via Employee Management", "hr@example.com"))
        self.assertEqual(sent.reply_to, ["aline@example.com"])

    @override_settings(BREVO_API_KEY="xkeysib-test", DEFAULT_FROM_EMAIL=SYSTEM_SENDER, EMAIL_DELIVERS=True)
    def test_an_author_without_an_email_gets_no_reply_to(self):
        self.employer.email = ""
        self.employer.save()
        sent = self.email_platform_team()
        self.assertEqual(parseaddr(sent.from_email)[1], "hr@example.com")
        self.assertEqual(sent.reply_to, [])

    @override_settings(BREVO_API_KEY="", DEFAULT_FROM_EMAIL="fallback@example.com", EMAIL_DELIVERS=False)
    def test_gmail_fallback_names_the_author_on_the_saved_gmail_account(self):
        InvitationEmailSettings.objects.create(
            pk=1, owner_business=self.business, email_host_user="platform@gmail.com", email_host_password="app")
        sent = self.email_platform_team()
        self.assertEqual(parseaddr(sent.from_email),
                         ("Eric Ndinayo via Employee Management", "platform@gmail.com"))
        self.assertEqual(sent.reply_to, ["eric@gmail.com"])

    @override_settings(BREVO_API_KEY="xkeysib-test", DEFAULT_FROM_EMAIL=SYSTEM_SENDER, EMAIL_DELIVERS=True)
    def test_platform_team_email_keeps_the_system_sender(self):
        self.client.force_authenticate(self.admin)
        self.client.post(f"/api/admin/messages/{self.business.pk}/",
                         {"body": "Your workspace is ready.", "channel": "email"}, format="json")
        self.assertEqual(mail.outbox[-1].from_email, SYSTEM_SENDER)
        self.assertEqual(mail.outbox[-1].reply_to, [])

    @override_settings(BREVO_API_KEY="xkeysib-test", DEFAULT_FROM_EMAIL=SYSTEM_SENDER, EMAIL_DELIVERS=True)
    def test_automated_emails_keep_the_system_sender(self):
        self.client.force_authenticate(self.employer)
        hired = self.client.post("/api/employees/", {
            "first_name": "Aline", "last_name": "Uwase", "job_title": "Accountant",
            "email": "aline@example.com"}, format="json")
        self.assertEqual(hired.status_code, 201, hired.data)
        self.client.force_authenticate(None)
        self.client.post("/api/password-reset/", {"identifier": "eric@gmail.com"}, format="json")
        self.assertEqual(len(mail.outbox), 2)
        for sent in mail.outbox:
            self.assertEqual(sent.from_email, SYSTEM_SENDER)
            self.assertEqual(sent.reply_to, [])


@override_settings(BREVO_API_KEY="xkeysib-regression-secret", DEFAULT_FROM_EMAIL=SYSTEM_SENDER,
                   EMAIL_BACKEND="api.brevo.BrevoEmailBackend", EMAIL_DELIVERS=False)
class BrevoWithoutGmailRegressionTests(APITestCase):
    """Production: BREVO_API_KEY is set and no employer ever saved a Gmail App Password.

    EMAIL_DELIVERS is pinned False so the key alone must count as configured.
    """

    password = "Cedar!Lantern-47-River"

    def setUp(self):
        cache.clear()
        self.business = Business.objects.create(name="Vatcho")
        self.employer = User.objects.create_user("ndinayo", "ndinayo@example.com", self.password)
        AccountProfile.objects.create(user=self.employer, role="employer", business=self.business)
        self.client.force_authenticate(self.employer)
        self.assertFalse(InvitationEmailSettings.objects.exists())

    def hire(self):
        return self.client.post("/api/employees/", {
            "first_name": "Kamana", "last_name": "Muhire", "job_title": "Sales Manager",
            "email": "kamana@example.com"}, format="json")

    def test_invitation_is_sent_through_brevo_and_never_called_unconfigured(self):
        with mock.patch("api.brevo.urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
            result = self.hire()
        self.assertEqual(result.status_code, 201, result.data)
        invite = result.data["invite"]
        self.assertTrue(invite["email_sent"], invite)
        self.assertEqual(invite["detail"], "Sign-in details were emailed to kamana@example.com.")
        self.assertNotIn("not set up", invite["detail"])
        self.assertNotIn("Gmail", invite["detail"])
        self.assertNotIn("temporary_password", invite)

        urlopen.assert_called_once()
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.brevo.com/v3/smtp/email")
        payload = json.loads(request.data)
        self.assertEqual(payload["to"], [{"email": "kamana@example.com"}])
        self.assertEqual(payload["sender"], {"email": "hr@example.com", "name": "Employee Management"})
        self.assertNotIn("replyTo", payload)

    def test_employer_is_not_asked_for_gmail(self):
        account = self.client.get("/api/account/").data
        self.assertTrue(account["email_configured"])
        settings = self.client.get("/api/account/email/").data
        self.assertTrue(settings["email_configured"])
        self.assertFalse(settings["can_manage_email_settings"])

    def test_a_brevo_rejection_is_reported_as_a_failed_send_not_as_unconfigured(self):
        with mock.patch("api.brevo.urllib.request.urlopen", side_effect=OSError("401")):
            invite = self.hire().data["invite"]
        self.assertFalse(invite["email_sent"])
        self.assertIn("could not be sent", invite["detail"])
        self.assertNotIn("Gmail", invite["detail"])

    def test_health_reports_brevo_without_leaking_the_key(self):
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email"], {"provider": "brevo", "brevo_configured": True})
        self.assertNotIn(b"xkeysib", response.content)
        self.assertNotIn(b"hr@example.com", response.content)


class HealthWithoutBrevoTests(APITestCase):
    @override_settings(BREVO_API_KEY="", EMAIL_DELIVERS=False)
    def test_health_reports_no_email_provider(self):
        self.assertEqual(self.client.get("/api/health/").json()["email"],
                         {"provider": "none", "brevo_configured": False})


class EnvValueTests(SimpleTestCase):
    def test_pasted_quotes_and_whitespace_are_removed(self):
        from backend.settings import env_value

        cases = {
            '  xkeysib-abc  ': "xkeysib-abc",
            '"xkeysib-abc"': "xkeysib-abc",
            "'xkeysib-abc'": "xkeysib-abc",
            '"Employee Management <hr@example.com>"': "Employee Management <hr@example.com>",
            '"Employee Management" <hr@example.com>': '"Employee Management" <hr@example.com>',
            "": "",
        }
        for raw, expected in cases.items():
            with mock.patch.dict("os.environ", {"EM_TEST_VALUE": raw}):
                self.assertEqual(env_value("EM_TEST_VALUE"), expected, raw)


@override_settings(DEFAULT_FROM_EMAIL=SYSTEM_SENDER, BREVO_API_KEY="xkeysib-test")
class PersonalFromAddressTests(SimpleTestCase):
    def test_quotes_and_line_breaks_in_names_cannot_break_the_header(self):
        author = User(username="x", first_name='Eric "E"\r\nBcc: evil@example.com', last_name="Ndinayo")
        value = onboarding.personal_from_address(author)
        self.assertNotIn("\n", value)
        self.assertEqual(parseaddr(value),
                         ('Eric "E" Bcc: evil@example.com Ndinayo via Employee Management', "hr@example.com"))

    def test_without_an_author_the_system_sender_is_used(self):
        self.assertEqual(onboarding.personal_from_address(None), SYSTEM_SENDER)
