import base64
import re
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
from unittest.mock import patch
from tempfile import TemporaryDirectory

from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
from PIL import Image

from .models import (AccountProfile, Attendance, Business, Contract, Employee, Holiday,
                     InvitationEmailSettings, LeaveRequest, Payroll, Salary)


class SignupTests(APITestCase):
    password = "Cedar!Lantern-47-River"

    def setUp(self):
        cache.clear()

    def payload(self, **changes):
        return {"username": "new-person", "email": "person@example.com", "role": "employee",
                "password": self.password, "password_confirm": self.password, **changes}

    def signup(self, **changes):
        return self.client.post("/api/signup/", self.payload(**changes), format="json")

    def test_employee_signup_login_and_account_restore(self):
        result = self.signup()
        self.assertEqual(result.status_code, 201, result.data)
        user = User.objects.get(username="new-person")
        self.assertTrue(user.check_password(self.password))
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertEqual(user.account_profile.role, "employee")
        self.assertIsNone(user.account_profile.business)
        self.assertNotIn("password", result.data["user"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {result.data['access']}")
        profile = self.client.get("/api/account/")
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.data["role"], "employee")
        self.assertFalse(profile.data["can_manage"])
        for resource in ("employees", "contracts", "attendance", "leave", "holidays", "salaries", "payroll", "reports"):
            self.assertEqual(self.client.get(f"/api/{resource}/").status_code, 403, resource)
            self.assertEqual(self.client.post(f"/api/{resource}/", {}, format="json").status_code, 403, resource)
        self.client.credentials()
        self.assertEqual(self.client.get("/api/account/").status_code, 401)
        login = self.client.post("/api/token/", {"username": user.username, "password": self.password})
        self.assertEqual(login.status_code, 200, login.data)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        self.assertEqual(self.client.get("/api/account/").data, profile.data)
        refresh = self.client.post("/api/token/refresh/", {"refresh": result.data["refresh"]})
        self.assertEqual(refresh.status_code, 200)

    def test_employer_gets_private_business_without_admin_privileges(self):
        result = self.signup(role="employer", business_name="  Cedar Trading  ", is_staff=True, is_superuser=True)
        self.assertEqual(result.status_code, 201, result.data)
        user = User.objects.get(username="new-person")
        self.assertEqual(user.account_profile.business.name, "Cedar Trading")
        self.assertFalse(user.is_staff or user.is_superuser or user.groups.exists())
        self.assertTrue(result.data["user"]["can_manage"])
        self.assertEqual(result.data["user"]["business_name"], "Cedar Trading")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {result.data['access']}")
        self.assertEqual(self.client.get("/api/employees/").data, [])
        login = self.client.post("/api/token/", {"username": user.username, "password": self.password})
        self.assertEqual(login.status_code, 200)

    def test_invalid_signup_creates_no_partial_accounts(self):
        cases = [
            ({"role": "employer"}, "business_name"),
            ({"role": "employer", "business_name": "   "}, "business_name"),
            ({"role": "admin"}, "role"),
            ({"role": "employee", "business_name": "Not mine"}, "business_name"),
            ({"password_confirm": "different"}, "password_confirm"),
            ({"password": "12345678", "password_confirm": "12345678"}, "password"),
            ({"email": "invalid-email"}, "email"),
            ({"username": "invalid username"}, "username"),
        ]
        for changes, field in cases:
            with self.subTest(changes=changes):
                result = self.signup(**changes)
                self.assertEqual(result.status_code, 400, result.data)
                self.assertIn(field, result.data)
                self.assertEqual(User.objects.count(), 0)
                self.assertEqual(Business.objects.count(), 0)
                self.assertEqual(AccountProfile.objects.count(), 0)

    def test_required_fields_and_duplicate_username(self):
        self.assertEqual(self.client.post("/api/signup/", {}, format="json").status_code, 400)
        self.assertEqual(self.signup().status_code, 201)
        duplicate = self.signup(role="employer", business_name="Other business")
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("username", duplicate.data)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Business.objects.count(), 0)

    def test_concurrent_username_conflict_is_a_validation_error(self):
        with patch("api.accounts.SignupSerializer.create", side_effect=IntegrityError):
            result = self.signup()
        self.assertEqual(result.status_code, 400)
        self.assertIn("username", result.data)

    def test_failed_profile_creation_rolls_back_user_and_business(self):
        with patch("api.accounts.AccountProfile.objects.create", side_effect=IntegrityError):
            self.assertEqual(self.signup(role="employer", business_name="Rolled back").status_code, 400)
        self.assertFalse(User.objects.exists())
        self.assertFalse(Business.objects.exists())

    def test_bad_password_and_inactive_account_cannot_log_in(self):
        self.signup()
        result = self.client.post("/api/token/", {"username": "new-person", "password": "incorrect"})
        self.assertEqual(result.status_code, 401)
        User.objects.filter(username="new-person").update(is_active=False)
        result = self.client.post("/api/token/", {"username": "new-person", "password": self.password})
        self.assertEqual(result.status_code, 401)

    def test_signup_rate_limit(self):
        for _ in range(20):
            self.assertEqual(self.client.post("/api/signup/", {}, format="json").status_code, 400)
        self.assertEqual(self.client.post("/api/signup/", {}, format="json").status_code, 429)

    @override_settings(CORS_ALLOWED_ORIGINS=["https://company.example"], CORS_ALLOW_ALL_ORIGINS=False)
    def test_cors_allows_signup_and_account_only_for_configured_origin(self):
        for path, method in [("/api/signup/", "POST"), ("/api/account/", "GET")]:
            response = self.client.options(path, HTTP_ORIGIN="https://company.example",
                HTTP_ACCESS_CONTROL_REQUEST_METHOD=method, HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type,authorization")
            self.assertEqual(response["Access-Control-Allow-Origin"], "https://company.example")
            response = self.client.options(path, HTTP_ORIGIN="https://other.example", HTTP_ACCESS_CONTROL_REQUEST_METHOD=method)
            self.assertNotIn("Access-Control-Allow-Origin", response)


class BusinessIsolationTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.owners = []
        self.records = []
        for index in range(2):
            result = self.client.post("/api/signup/", {
                "username": f"owner-{index}", "email": f"owner{index}@example.com", "role": "employer",
                "business_name": f"Business {index}", "password": SignupTests.password,
                "password_confirm": SignupTests.password,
            }, format="json")
            self.assertEqual(result.status_code, 201, result.data)
            user = User.objects.get(username=f"owner-{index}")
            self.owners.append(user)
            self.records.append(self.make_records(user.account_profile.business, index))
        self.legacy = User.objects.create_user(username="existing-manager")
        self.legacy.groups.add(Group.objects.get(name="Managers"))
        self.records.append(self.make_records(None, 2))
        self.client.force_authenticate(self.owners[0])

    def make_records(self, business, index):
        employee = Employee.objects.create(business=business, first_name=f"Person {index}", last_name="Example",
            email="shared@example.com", department="Operations", job_title="Analyst", date_joined="2026-01-01")
        return {
            "employees": employee,
            "contracts": Contract.objects.create(employee=employee, title="Contract", start_date="2026-01-01", end_date="2026-09-29"),
            "attendance": Attendance.objects.create(employee=employee, date="2026-09-24", hours_worked=8),
            "leave": LeaveRequest.objects.create(employee=employee, start_date="2026-10-01", end_date="2026-10-02"),
            "holidays": Holiday.objects.create(business=business, name="Holiday", date="2026-12-25"),
            "salaries": Salary.objects.create(employee=employee, monthly_amount=100, effective_date="2026-01-01"),
            "payroll": Payroll.objects.create(employee=employee, period_start="2026-09-01", period_end="2026-09-24",
                base_salary=100, employee_name=str(employee), employee_email=employee.email, department=employee.department, job_title=employee.job_title),
        }

    def test_lists_details_changes_deletions_and_private_files_are_scoped(self):
        for resource, own in self.records[0].items():
            result = self.client.get(f"/api/{resource}/")
            self.assertEqual(result.status_code, 200)
            self.assertEqual([row["id"] for row in result.data], [own.pk], resource)
            for other in self.records[1:]:
                path = f"/api/{resource}/{other[resource].pk}/"
                self.assertEqual(self.client.get(path).status_code, 404, path)
                self.assertEqual(self.client.patch(path, {}, format="json").status_code, 404, path)
                self.assertEqual(self.client.delete(path).status_code, 404, path)
        for other in self.records[1:]:
            for resource, action in [("employees", "photo"), ("contracts", "document"), ("contracts", "preview"), ("salaries", "mark_paid")]:
                path = f"/api/{resource}/{other[resource].pk}/{action}/"
                result = self.client.post(path) if action == "mark_paid" else self.client.get(path)
                self.assertEqual(result.status_code, 404, path)

    def test_cannot_assign_related_records_to_another_business(self):
        data_by_resource = {
            "contracts": {"title": "Forged", "start_date": "2026-01-01"},
            "attendance": {"date": "2026-11-01"},
            "leave": {"start_date": "2026-11-01", "end_date": "2026-11-02"},
            "salaries": {"monthly_amount": "100", "effective_date": "2026-01-01"},
            "payroll": {"period_start": "2026-11-01", "period_end": "2026-11-30", "base_salary": "100"},
        }
        for resource, data in data_by_resource.items():
            for other in self.records[1:]:
                result = self.client.post(f"/api/{resource}/", {**data, "employee": other["employees"].pk}, format="json")
                self.assertEqual(result.status_code, 400, result.data)
                self.assertIn("employee", result.data)
                path = f"/api/{resource}/{self.records[0][resource].pk}/"
                self.assertEqual(self.client.patch(path, {"employee": other["employees"].pk}, format="json").status_code, 400)

    def test_reports_include_only_own_business(self):
        Holiday.objects.create(business=self.owners[1].account_profile.business, name="Other holiday", date="2026-09-24")
        result = self.client.get("/api/reports/?date=2026-09-24&days=30")
        self.assertEqual(result.status_code, 200, result.data)
        self.assertTrue(result.data["working_day"])
        for field in ("active_employees", "present_count", "pending_leave_count"):
            self.assertEqual(result.data[field], 1, field)
        self.assertEqual([row["employee_id"] for row in result.data["working_hours"]], [self.records[0]["employees"].pk])
        self.assertEqual([row["id"] for row in result.data["expiring_contracts"]], [self.records[0]["contracts"].pk])
        self.assertEqual(result.data["payroll_totals"][0]["net"], "100.00")

    def test_business_is_assigned_server_side_and_cannot_be_changed(self):
        other_business = self.owners[1].account_profile.business
        result = self.client.post("/api/employees/", {"first_name": "New", "last_name": "Person",
            "email": "new@example.com", "department": "HR", "job_title": "Assistant", "date_joined": "2026-01-01",
            "business": other_business.pk}, format="json")
        self.assertEqual(result.status_code, 201, result.data)
        person = Employee.objects.get(pk=result.data["id"])
        self.assertEqual(person.business, self.owners[0].account_profile.business)
        self.client.patch(f"/api/employees/{person.pk}/", {"business": other_business.pk}, format="json")
        person.refresh_from_db()
        self.assertEqual(person.business, self.owners[0].account_profile.business)
        holiday = self.client.post("/api/holidays/", {"name": "My holiday", "date": "2026-10-10", "business": other_business.pk}, format="json")
        self.assertEqual(holiday.status_code, 201)
        self.assertEqual(Holiday.objects.get(pk=holiday.data["id"]).business, person.business)

    def test_duplicate_emails_and_holidays_are_validated_within_business(self):
        # The fixtures already prove the same email/date can be used by different businesses.
        result = self.client.post("/api/employees/", {"first_name": "New", "last_name": "Person",
            "email": "shared@example.com", "department": "HR", "job_title": "Assistant", "date_joined": "2026-01-01"}, format="json")
        self.assertEqual(result.status_code, 400)
        self.assertIn("email", result.data)
        self.assertEqual(self.client.post("/api/holidays/", {"name": "Duplicate", "date": "2026-12-25"}).status_code, 400)

    def test_existing_managers_keep_only_the_original_workspace(self):
        self.client.force_authenticate(self.legacy)
        self.assertEqual(self.client.get("/api/account/").data["role"], "manager")
        for resource, record in self.records[2].items():
            self.assertEqual([row["id"] for row in self.client.get(f"/api/{resource}/").data], [record.pk])

    def test_salary_payment_in_own_business_uses_scoped_serializer(self):
        result = self.client.post(f"/api/salaries/{self.records[0]['salaries'].pk}/mark_paid/",
                                  {"month": "2026-08", "paid_date": "2026-08-31"}, format="json")
        self.assertEqual(result.status_code, 201, result.data)
        self.assertEqual(result.data["employee"], self.records[0]["employees"].pk)

    def test_employer_employee_form_contract_upload_stays_in_business(self):
        document = b"%PDF-1.4\nprivate contract\n%%EOF"
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            result = self.client.post("/api/employees/", {
                "first_name": "Contract", "last_name": "Person", "email": "contract@example.com",
                "department": "HR", "job_title": "Assistant", "date_joined": "2026-01-01",
                "contract_document": SimpleUploadedFile("contract.pdf", document, content_type="application/pdf"),
            }, format="multipart")
            self.assertEqual(result.status_code, 201, result.data)
            contract_id = result.data["latest_contract"]["id"]
            path = f"/api/contracts/{contract_id}/preview/"
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b"".join(response.streaming_content), document)
            response.close()
            self.client.force_authenticate(self.owners[1])
            self.assertEqual(self.client.get(path).status_code, 404)


# Pinned so the suite does not depend on whether SMTP happens to be configured.
@override_settings(
    EMAIL_DELIVERS=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class EmployeeOnboardingTests(APITestCase):
    """An employer hires with four fields; the system does the rest."""

    password = "Cedar!Lantern-47-River"

    def setUp(self):
        cache.clear()
        mail.outbox = []
        self.business = Business.objects.create(name="Kigali Works")
        self.employer = User.objects.create_user("boss", "boss@example.com", self.password)
        AccountProfile.objects.create(user=self.employer, role="employer", business=self.business)
        self.client.force_authenticate(self.employer)

    def hire(self, **changes):
        payload = {"first_name": "Aline", "last_name": "Uwase", "job_title": "Accountant",
                   "email": "aline@example.com", **changes}
        return self.client.post("/api/employees/", payload, format="json")

    def emailed_password(self):
        """Read the temporary password out of the invitation the employee got."""
        self.assertEqual(len(mail.outbox), 1)
        match = re.search(r"Temporary password: (\S+)", mail.outbox[0].body)
        self.assertIsNotNone(match, mail.outbox[0].body)
        return match.group(1)

    def test_hire_needs_only_names_title_and_email(self):
        result = self.hire()
        self.assertEqual(result.status_code, 201, result.data)
        employee = Employee.objects.get(email="aline@example.com")
        self.assertEqual(employee.business, self.business)
        self.assertEqual(employee.department, "")
        self.assertEqual(employee.date_joined, timezone.localdate())

    def test_hire_creates_account_and_emails_a_temporary_password(self):
        result = self.hire()
        self.assertTrue(result.data["invite"]["created"])
        self.assertTrue(result.data["invite"]["email_sent"])
        self.assertEqual(result.data["account_status"], "pending_first_sign_in")

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["aline@example.com"])
        self.assertIn("Kigali Works", message.subject)

        employee = Employee.objects.get(email="aline@example.com")
        account = employee.account
        self.assertEqual(account.role, "employee")
        self.assertTrue(account.must_change_password)
        # The password reached the employee only through the email body; the
        # employer is never shown it when delivery succeeded.
        self.assertNotIn("temporary_password", result.data["invite"])
        self.assertTrue(account.user.check_password(self.emailed_password()))

    def test_employee_checks_in_and_out_and_employer_sees_the_shift(self):
        self.hire()
        employee = Employee.objects.get(email="aline@example.com")
        self.client.force_authenticate(employee.account.user)
        empty = self.client.get("/api/me/attendance/")
        self.assertEqual(empty.status_code, 200)
        self.assertIsNone(empty.data["attendance"])
        self.assertEqual(self.client.post("/api/me/attendance/", {"action": "check_out"}, format="json").status_code, 400)

        start = timezone.now().replace(hour=8, minute=0, second=0, microsecond=0)
        finish = start.replace(hour=16, minute=30)
        with patch("api.accounts.timezone.now", return_value=start):
            checked_in = self.client.post("/api/me/attendance/", {"action": "check_in"}, format="json")
        self.assertEqual(checked_in.status_code, 200, checked_in.data)
        self.assertIsNotNone(checked_in.data["attendance"]["check_in_at"])
        self.assertIsNone(checked_in.data["attendance"]["check_out_at"])
        self.assertEqual(self.client.post("/api/me/attendance/", {"action": "check_in"}, format="json").status_code, 400)

        with patch("api.accounts.timezone.now", return_value=finish):
            checked_out = self.client.post("/api/me/attendance/", {"action": "check_out"}, format="json")
        self.assertEqual(checked_out.status_code, 200, checked_out.data)
        self.assertEqual(checked_out.data["attendance"]["hours_worked"], "8.50")
        self.assertIsNotNone(checked_out.data["attendance"]["check_out_at"])
        self.assertEqual(self.client.post("/api/me/attendance/", {"action": "check_out"}, format="json").status_code, 400)

        self.client.force_authenticate(self.employer)
        employer_view = self.client.get("/api/attendance/")
        self.assertEqual(employer_view.status_code, 200)
        self.assertEqual(len(employer_view.data), 1)
        self.assertIsNotNone(employer_view.data[0]["check_in_at"])
        self.assertIsNotNone(employer_view.data[0]["check_out_at"])

    def test_account_identifies_signed_in_person_and_role(self):
        account = self.client.get("/api/account/")
        self.assertEqual(account.data["display_name"], "boss")
        self.assertEqual(account.data["role_label"], "Employer")
        self.hire()
        employee = Employee.objects.get(email="aline@example.com")
        self.client.force_authenticate(employee.account.user)
        account = self.client.get("/api/account/")
        self.assertEqual(account.data["display_name"], "Aline Uwase")
        self.assertEqual(account.data["role_label"], "Employee")

    def test_employee_requests_leave_and_employer_approval_updates_balance(self):
        self.hire()
        employee = Employee.objects.get(email="aline@example.com")
        self.client.force_authenticate(employee.account.user)
        balances = self.client.get("/api/me/leave/")
        self.assertEqual(balances.status_code, 200, balances.data)
        self.assertEqual({item["leave_type"] for item in balances.data["balances"]},
                         {"annual", "sick", "maternity", "unpaid"})
        annual = next(item for item in balances.data["balances"] if item["leave_type"] == "annual")
        self.assertEqual(annual["remaining_days"], Decimal("20.0"))

        start = timezone.localdate() + timedelta(days=1)
        while start.weekday() >= 5:
            start += timedelta(days=1)
        end = start + timedelta(days=1)
        requested = self.client.post("/api/me/leave/", {
            "leave_type": "annual", "start_date": start, "end_date": end,
            "reason": "Family trip",
        }, format="json")
        self.assertEqual(requested.status_code, 201, requested.data)
        self.assertEqual(requested.data["status"], "pending")
        self.assertEqual(requested.data["days_requested"], 2)

        self.client.force_authenticate(self.employer)
        employer_requests = self.client.get("/api/leave/")
        self.assertEqual(employer_requests.data[0]["employee_name"], "Aline Uwase")
        approved = self.client.patch(f'/api/leave/{requested.data["id"]}/', {
            "status": "approved", "decision_notes": "Approved",
        }, format="json")
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertTrue(approved.data["decided_by"])
        self.assertIsNotNone(approved.data["decided_at"])

        self.client.force_authenticate(employee.account.user)
        updated = self.client.get("/api/me/leave/")
        annual = next(item for item in updated.data["balances"] if item["leave_type"] == "annual")
        self.assertEqual(annual["used_days"], Decimal("2"))
        self.assertEqual(annual["remaining_days"], Decimal("18.0"))
        self.assertEqual(updated.data["requests"][0]["status"], "approved")
        self.assertEqual(self.client.delete(f'/api/me/leave/{requested.data["id"]}/').status_code, 400)

    def test_employee_signs_in_with_email_or_username(self):
        self.hire()
        password = self.emailed_password()
        employee = Employee.objects.get(email="aline@example.com")
        username = employee.account.user.username
        self.client.force_authenticate(None)
        for login in (username, "aline@example.com", "ALINE@example.com"):
            token = self.client.post("/api/token/", {"username": login, "password": password}, format="json")
            self.assertEqual(token.status_code, 200, f"{login}: {token.data}")

    def test_employer_writes_sends_and_employee_signs_digital_contract(self):
        self.hire()
        employee = Employee.objects.get(email="aline@example.com")
        mail.outbox = []
        created = self.client.post("/api/contracts/", {
            "employee": employee.pk,
            "title": "Employment agreement",
            "start_date": "2026-10-01",
            "status": "draft",
            "content": "<h1>Employment agreement</h1><p><strong>Welcome</strong>, Aline.</p><script>alert('x')</script>",
        }, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertNotIn("script", created.data["content"])
        self.assertNotIn("alert", created.data["content"])

        contract_id = created.data["id"]
        sent = self.client.post(f"/api/contracts/{contract_id}/send-for-signature/", {}, format="json")
        self.assertEqual(sent.status_code, 200, sent.data)
        self.assertEqual(sent.data["signature_status"], "sent")
        self.assertEqual(sent.data["employee_email"], "aline@example.com")
        self.assertTrue(sent.data["notification"]["email_sent"])
        self.assertIsNotNone(sent.data["notification_sent_at"])
        self.assertEqual(mail.outbox[0].to, ["aline@example.com"])
        self.assertIn(f"/account?contract={contract_id}#contracts", mail.outbox[0].body)
        resent = self.client.post(f"/api/contracts/{contract_id}/resend-signature-email/", {}, format="json")
        self.assertEqual(resent.status_code, 200, resent.data)
        self.assertTrue(resent.data["email_sent"])
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(self.client.patch(f"/api/contracts/{contract_id}/", {"title": "Changed"}, format="json").status_code, 400)
        self.assertEqual(self.client.delete(f"/api/contracts/{contract_id}/").status_code, 400)

        other_employee = Employee.objects.create(
            business=self.business, first_name="Other", last_name="Person", email="other-person@example.com",
            job_title="Designer", date_joined=timezone.localdate(),
        )
        other_user = User.objects.create_user("other-person", "other-person@example.com", self.password)
        AccountProfile.objects.create(user=other_user, role="employee", employee=other_employee)
        other_content = "<p>Private contract</p>"
        other_contract = Contract.objects.create(
            employee=other_employee, title="Private", start_date="2026-10-01", content=other_content,
            signature_status="sent", content_hash=sha256(other_content.encode()).hexdigest(),
        )

        self.client.force_authenticate(employee.account.user)
        inbox = self.client.get("/api/me/contracts/")
        self.assertEqual([row["id"] for row in inbox.data], [contract_id])
        image = BytesIO()
        Image.new("RGBA", (10, 2), "white").save(image, format="PNG")
        signature = "data:image/png;base64," + base64.b64encode(image.getvalue()).decode()
        signed = self.client.post(f"/api/me/contracts/{contract_id}/sign/", {
            "signer_name": "Aline Uwase", "signature_data": signature, "accepted": True,
        }, format="json")
        self.assertEqual(signed.status_code, 200, signed.data)
        self.assertEqual(signed.data["signature_status"], "signed")
        self.assertEqual(signed.data["signer_name"], "Aline Uwase")
        self.assertIsNotNone(signed.data["signed_at"])
        self.assertEqual(self.client.post(f"/api/me/contracts/{other_contract.pk}/sign/", {
            "signer_name": "Aline Uwase", "signature_data": signature, "accepted": True,
        }, format="json").status_code, 403)
        self.assertEqual(self.client.post(f"/api/me/contracts/{contract_id}/sign/", {
            "signer_name": "Aline Uwase", "signature_data": signature, "accepted": True,
        }, format="json").status_code, 400)

        self.client.force_authenticate(self.employer)
        correction = self.client.post(f"/api/contracts/{contract_id}/request-new-signature/", {
            "message": "Please sign again using your complete legal name.",
        }, format="json")
        self.assertEqual(correction.status_code, 201, correction.data)
        self.assertEqual(correction.data["signature_status"], "sent")
        self.assertEqual(correction.data["revision_of"], contract_id)
        self.assertEqual(correction.data["employer_message"], "Please sign again using your complete legal name.")
        self.assertTrue(correction.data["notification"]["email_sent"])
        self.assertIn("Please sign again using your complete legal name.", mail.outbox[-1].body)
        self.assertEqual(Contract.objects.get(pk=contract_id).signature_status, "signed")

        self.client.force_authenticate(employee.account.user)
        revised_inbox = self.client.get("/api/me/contracts/")
        self.assertEqual(revised_inbox.data[0]["id"], correction.data["id"])
        self.assertEqual(revised_inbox.data[0]["employer_message"],
                         "Please sign again using your complete legal name.")

    def test_first_sign_in_reports_the_forced_password_change(self):
        self.hire()
        password = self.emailed_password()
        self.client.force_authenticate(Employee.objects.get(email="aline@example.com").account.user)
        account = self.client.get("/api/account/")
        self.assertTrue(account.data["must_change_password"])
        self.assertTrue(account.data["has_employee_record"])
        self.assertEqual(account.data["business_name"], "Kigali Works")
        self.assertFalse(account.data["can_manage"])

        new_password = "Umbrella-Mountain-93"
        change = self.client.post("/api/account/password/", {
            "current_password": password, "new_password": new_password,
            "new_password_confirm": new_password}, format="json")
        self.assertEqual(change.status_code, 200, change.data)
        self.assertFalse(change.data["user"]["must_change_password"])
        self.assertIn("access", change.data)
        self.assertTrue(Employee.objects.get(email="aline@example.com").account.user.check_password(new_password))

    def test_password_change_rejects_a_wrong_current_password(self):
        self.hire()
        self.client.force_authenticate(Employee.objects.get(email="aline@example.com").account.user)
        result = self.client.post("/api/account/password/", {
            "current_password": "not-the-one", "new_password": "Umbrella-Mountain-93",
            "new_password_confirm": "Umbrella-Mountain-93"}, format="json")
        self.assertEqual(result.status_code, 400)
        self.assertIn("current_password", result.data)

    def test_employee_completes_personal_details_but_not_job_details(self):
        self.hire()
        employee = Employee.objects.get(email="aline@example.com")
        self.client.force_authenticate(employee.account.user)

        profile = self.client.get("/api/me/profile/")
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.data["business_name"], "Kigali Works")
        self.assertEqual(profile.data["job_title"], "Accountant")

        result = self.client.patch("/api/me/profile/", {
            "phone": "+250 788 000 000", "address": "12 Kicukiro", "emergency_contact": "Jean 0788111222",
            "job_title": "Chief Executive", "email": "hacker@example.com"}, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        employee.refresh_from_db()
        self.assertEqual(employee.phone, "+250 788 000 000")
        self.assertEqual(employee.address, "12 Kicukiro")
        # Employer-owned fields ignore anything the employee sends.
        self.assertEqual(employee.job_title, "Accountant")
        self.assertEqual(employee.email, "aline@example.com")

    def test_employee_cannot_reach_manager_endpoints(self):
        self.hire()
        self.client.force_authenticate(Employee.objects.get(email="aline@example.com").account.user)
        self.assertEqual(self.client.get("/api/employees/").status_code, 403)
        self.assertEqual(self.client.get("/api/reports/").status_code, 403)

    def test_deleting_an_employee_lets_the_same_email_be_hired_again(self):
        first = self.hire()
        self.assertTrue(first.data["invite"]["created"])
        employee_id = first.data["id"]
        username = first.data["invite"]["username"]
        self.assertEqual(self.client.delete(f"/api/employees/{employee_id}/").status_code, 204)
        self.assertFalse(User.objects.filter(username=username).exists())
        self.assertFalse(User.objects.filter(email__iexact="aline@example.com").exists())

        again = self.hire()
        self.assertEqual(again.status_code, 201, again.data)
        self.assertTrue(again.data["invite"]["created"])
        self.assertEqual(again.data["account_status"], "pending_first_sign_in")
        self.assertTrue(User.objects.filter(email="aline@example.com").exists())

    def test_deleting_an_employee_also_removes_an_orphaned_sign_in(self):
        leftover = User.objects.create_user("ndinayoeric66", "aline@example.com", self.password)
        AccountProfile.objects.create(user=leftover, role="employee")
        hired = self.hire()
        self.assertTrue(hired.data["invite"]["created"], hired.data)
        self.assertFalse(User.objects.filter(pk=leftover.pk).exists())
        self.assertEqual(self.client.delete(f"/api/employees/{hired.data['id']}/").status_code, 204)
        self.assertFalse(User.objects.filter(email__iexact="aline@example.com").exists())

    def test_hire_replaces_a_leftover_employee_sign_in_for_the_same_email(self):
        leftover = User.objects.create_user("someone", "aline@example.com", self.password)
        AccountProfile.objects.create(user=leftover, role="employee")
        result = self.hire()
        self.assertEqual(result.status_code, 201, result.data)
        self.assertTrue(result.data["invite"]["created"])
        self.assertFalse(User.objects.filter(pk=leftover.pk).exists())
        self.assertTrue(Employee.objects.get(email="aline@example.com").account.user.check_password(
            self.emailed_password()))

    def test_hire_does_not_replace_an_employer_who_uses_the_same_email(self):
        result = self.hire(email="boss@example.com")
        self.assertEqual(result.status_code, 201, result.data)
        self.assertFalse(result.data["invite"]["created"])
        self.assertTrue(User.objects.filter(username="boss").exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_self_signed_up_employee_has_no_employee_record(self):
        self.client.force_authenticate(None)
        signup = self.client.post("/api/signup/", {
            "username": "solo", "email": "solo@example.com", "role": "employee",
            "password": self.password, "password_confirm": self.password}, format="json")
        self.assertEqual(signup.status_code, 201, signup.data)
        self.assertFalse(signup.data["user"]["has_employee_record"])
        self.client.force_authenticate(User.objects.get(username="solo"))
        self.assertEqual(self.client.get("/api/me/profile/").status_code, 400)

    @override_settings(EMAIL_DELIVERS=False)
    def test_without_smtp_the_employer_is_told_no_email_was_sent(self):
        result = self.hire()
        invite = result.data["invite"]
        self.assertTrue(invite["created"])
        self.assertFalse(invite["email_sent"])
        self.assertIn("not set up", invite["detail"])
        self.assertIn("temporary_password", invite)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_DELIVERS=False)
    def test_hire_sends_mail_through_the_business_smtp_settings(self):
        self.business.email_host = "smtp.gmail.com"
        self.business.email_host_user = "boss@example.com"
        self.business.email_host_password = "app-password"
        self.business.save()
        result = self.hire()
        self.assertTrue(result.data["invite"]["email_sent"], result.data)
        self.assertNotIn("temporary_password", result.data["invite"])
        self.assertEqual(mail.outbox[0].to, ["aline@example.com"])
        self.assertEqual(mail.outbox[0].from_email, "boss@example.com")

    @override_settings(EMAIL_DELIVERS=False)
    def test_employer_saves_gmail_settings_and_sends_a_test_message(self):
        account = self.client.get("/api/account/")
        self.assertFalse(account.data["email_configured"])
        result = self.client.patch("/api/account/email/", {
            "email_host_user": "boss@example.com", "email_host_password": "app-password",
        }, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        self.assertTrue(result.data["email_configured"])
        self.assertNotIn("email_host_password", result.data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["boss@example.com"])
        sender = InvitationEmailSettings.objects.get(pk=1)
        self.assertEqual(sender.email_host_password, "app-password")
        self.assertEqual(sender.owner_business, self.business)
        self.assertTrue(self.client.get("/api/account/").data["email_configured"])

    def test_every_account_can_request_and_complete_a_password_reset(self):
        mail.outbox = []
        requested = self.client.post("/api/password-reset/", {"identifier": "boss@example.com"}, format="json")
        self.assertEqual(requested.status_code, 200, requested.data)
        self.assertNotIn("boss", requested.data["detail"].lower())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Username: boss", mail.outbox[0].body)
        match = re.search(r"reset-password\?uid=([^&\s]+)&token=([^\s]+)", mail.outbox[0].body)
        self.assertIsNotNone(match, mail.outbox[0].body)

        new_password = "Granite!Harbour-82-Cloud"
        reset = self.client.post("/api/password-reset/confirm/", {
            "uid": match.group(1), "token": match.group(2),
            "new_password": new_password, "new_password_confirm": new_password,
        }, format="json")
        self.assertEqual(reset.status_code, 200, reset.data)
        self.employer.refresh_from_db()
        self.assertTrue(self.employer.check_password(new_password))
        signed_in = self.client.post("/api/token/", {
            "username": "boss@example.com", "password": new_password,
        }, format="json")
        self.assertEqual(signed_in.status_code, 200, signed_in.data)
        reused = self.client.post("/api/password-reset/confirm/", {
            "uid": match.group(1), "token": match.group(2),
            "new_password": "Another!Password-73", "new_password_confirm": "Another!Password-73",
        }, format="json")
        self.assertEqual(reused.status_code, 400)

    def test_duplicate_email_sends_one_identified_reset_link_per_account(self):
        second = User.objects.create_user("second-account", "boss@example.com", self.password)
        AccountProfile.objects.create(user=second, role="employee")
        mail.outbox = []
        result = self.client.post("/api/password-reset/", {"identifier": "boss@example.com"}, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual({re.search(r"Username: (\S+)", item.body).group(1) for item in mail.outbox},
                         {"boss", "second-account"})

        mail.outbox = []
        missing = self.client.post("/api/password-reset/", {"identifier": "missing@example.com"}, format="json")
        self.assertEqual(missing.status_code, 200)
        self.assertEqual(missing.data["detail"], result.data["detail"])
        self.assertEqual(mail.outbox, [])

    @override_settings(EMAIL_DELIVERS=False)
    def test_saved_sender_is_automatically_shared_with_other_employers(self):
        saved = self.client.patch("/api/account/email/", {
            "email_host_user": "boss@example.com", "email_host_password": "app-password",
        }, format="json")
        self.assertEqual(saved.status_code, 200, saved.data)
        mail.outbox = []

        other_business = Business.objects.create(name="Other Company")
        other = User.objects.create_user("other-boss", "other@example.com", self.password)
        AccountProfile.objects.create(user=other, role="employer", business=other_business)
        self.client.force_authenticate(other)

        account = self.client.get("/api/account/")
        self.assertTrue(account.data["email_configured"])
        email_settings = self.client.get("/api/account/email/")
        self.assertFalse(email_settings.data["can_manage_email_settings"])
        overwrite = self.client.patch("/api/account/email/", {
            "email_host_user": "other@example.com", "email_host_password": "different-password",
        }, format="json")
        self.assertEqual(overwrite.status_code, 403)

        result = self.hire(email="newhire@example.com")
        self.assertEqual(result.status_code, 201, result.data)
        self.assertTrue(result.data["invite"]["email_sent"])
        self.assertEqual(mail.outbox[0].to, ["newhire@example.com"])
        self.assertEqual(mail.outbox[0].from_email, "boss@example.com")

    def test_failed_test_email_does_not_store_the_password(self):
        with patch("api.accounts.onboarding.send_test", return_value=False):
            result = self.client.patch("/api/account/email/", {
                "email_host_user": "boss@example.com", "email_host_password": "wrong",
            }, format="json")
        self.assertEqual(result.status_code, 400)
        self.assertFalse(InvitationEmailSettings.objects.exists())

    def test_employee_cannot_change_invitation_email_settings(self):
        self.hire()
        self.client.force_authenticate(Employee.objects.get(email="aline@example.com").account.user)
        self.assertEqual(self.client.get("/api/account/email/").status_code, 403)
        self.assertEqual(self.client.patch("/api/account/email/", {
            "email_host_user": "stolen@example.com", "email_host_password": "secret",
        }, format="json").status_code, 403)

    def test_hire_allows_an_email_used_by_another_business_or_legacy_record(self):
        # A pre-multi-tenant record (business NULL) must not block a new hire.
        Employee.objects.create(first_name="Old", last_name="Record", email="aline@example.com",
                                job_title="Clerk", date_joined=timezone.localdate())
        result = self.hire()
        self.assertEqual(result.status_code, 201, result.data)
        self.assertEqual(Employee.objects.filter(email="aline@example.com").count(), 2)

    def test_hire_rejects_a_duplicate_email_inside_the_same_business(self):
        self.hire()
        again = self.hire(first_name="Other")
        self.assertEqual(again.status_code, 400)
        self.assertIn("email", again.data)

    def test_email_shared_by_several_accounts_uses_password_to_select_account(self):
        shared = "shared@example.com"
        first_password = "Quartz!River-38-Lamp"
        second_password = "Copper!Forest-64-Star"
        User.objects.create_user("one", shared, first_password)
        User.objects.create_user("two", shared, second_password)
        self.client.force_authenticate(None)
        first = self.client.post("/api/token/", {"username": shared, "password": first_password}, format="json")
        second = self.client.post("/api/token/", {"username": shared, "password": second_password}, format="json")
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(second.status_code, 200, second.data)

    def test_shared_email_still_requires_username_when_password_is_also_shared(self):
        shared = "shared@example.com"
        User.objects.create_user("one", shared, self.password)
        User.objects.create_user("two", shared, self.password)
        self.client.force_authenticate(None)
        ambiguous = self.client.post("/api/token/", {
            "username": shared, "password": self.password,
        }, format="json")
        self.assertEqual(ambiguous.status_code, 400)
        self.assertIn("username", ambiguous.data)
        ok = self.client.post("/api/token/", {"username": "one", "password": self.password}, format="json")
        self.assertEqual(ok.status_code, 200, ok.data)
