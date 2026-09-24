from unittest.mock import patch
from tempfile import TemporaryDirectory

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import override_settings
from rest_framework.test import APITestCase

from .models import AccountProfile, Attendance, Business, Contract, Employee, Holiday, LeaveRequest, Payroll, Salary


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
