import os
from calendar import monthrange
from datetime import date
from decimal import Decimal
from tempfile import TemporaryDirectory

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import Employee, Contract, Attendance, LeaveRequest, Holiday, Salary, Payroll


class ManagerWorkflowTests(APITestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username="manager", password="test-password")
        self.manager.groups.add(Group.objects.get(name="Managers"))
        self.client.force_authenticate(self.manager)
        self.employee = Employee.objects.create(first_name="Ada", last_name="Dube", email="ada@example.com",
            department="Operations", job_title="Analyst", date_joined="2026-01-01")
        self.employee.refresh_from_db()

    def approved_contract(self, employee=None, **fields):
        return Contract.objects.create(**{"employee": employee or self.employee, "title": "Employment",
                                          "start_date": "2026-01-01", "signature_status": "signed",
                                          "worker_approval_status": "approved", **fields})

    def payroll_data(self, **overrides):
        return {"employee": self.employee.id, "period_start": "2026-09-01", "period_end": "2026-09-30",
                "base_salary": "10000.00", "allowances": "500.50", "deductions": "1500.25",
                "currency": "ZAR", **overrides}

    def test_every_manager_endpoint_requires_authentication_and_role(self):
        member = User.objects.create_user(username="member")
        for resource in ["employees", "contracts", "attendance", "leave", "holidays", "salaries", "payroll", "reports"]:
            self.client.force_authenticate(None)
            self.assertEqual(self.client.get(f"/api/{resource}/").status_code, 401, resource)
            self.client.force_authenticate(member)
            self.assertEqual(self.client.get(f"/api/{resource}/").status_code, 403, resource)
            self.assertEqual(self.client.post(f"/api/{resource}/", {}, format="json").status_code, 403, resource)
            self.client.force_authenticate(self.manager)
            self.assertEqual(self.client.get(f"/api/{resource}/").status_code, 200, resource)

    def test_staff_admin_retains_access(self):
        self.client.force_authenticate(User.objects.create_user(username="admin", is_staff=True))
        self.assertEqual(self.client.get("/api/employees/").status_code, 200)

    def test_employee_profile_and_job_details_persist(self):
        data = {"phone": "0123456789", "address": "Cape Town", "emergency_contact": "Sam 0123456780",
                "manager_name": "Alex", "job_description": "Reporting", "employment_type": "part_time"}
        result = self.client.patch(f"/api/employees/{self.employee.id}/", data, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        for key, value in data.items():
            self.assertEqual(result.data[key], value)

    def png_bytes(self, fmt="PNG"):
        from io import BytesIO
        from PIL import Image
        buffer = BytesIO()
        Image.new("RGB", (4, 4), "red").save(buffer, format=fmt)
        return buffer.getvalue()

    def test_employee_photo_upload_download_and_private_access(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            original = self.png_bytes()
            result = self.client.patch(f"/api/employees/{self.employee.id}/",
                {"photo": SimpleUploadedFile("face.png", original, content_type="image/png")}, format="multipart")
            self.assertEqual(result.status_code, 200, result.data)
            self.assertNotIn("photo", result.data)
            self.assertTrue(result.data["photo_name"].endswith(".png"))
            url = f"/api/employees/{self.employee.id}/photo/"
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b"".join(response.streaming_content), original)
            response.close()
            self.client.force_authenticate(User.objects.create_user(username="photo-outsider"))
            self.assertEqual(self.client.get(url).status_code, 403)
            self.client.force_authenticate(None)
            self.assertEqual(self.client.get(url).status_code, 401)

    def test_employee_photo_rejects_non_images_and_unlisted_formats(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            url = f"/api/employees/{self.employee.id}/"
            disguised = SimpleUploadedFile("face.png", b"<script>bad</script>", content_type="image/png")
            self.assertEqual(self.client.patch(url, {"photo": disguised}, format="multipart").status_code, 400)
            gif = SimpleUploadedFile("face.gif", self.png_bytes("GIF"), content_type="image/gif")
            self.assertEqual(self.client.patch(url, {"photo": gif}, format="multipart").status_code, 400)
            self.employee.refresh_from_db()
            self.assertFalse(self.employee.photo)

    def test_employee_created_with_photo_in_one_multipart_request(self):
        # Mirrors what the add-employee form posts: optional fields as empty
        # strings and the checkbox as "true", all inside multipart.
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            result = self.client.post("/api/employees/", {
                "first_name": "Zola", "last_name": "Mbeki", "email": "zola@example.com",
                "department": "Design", "job_title": "Designer", "date_joined": "2026-03-01",
                "employment_type": "full_time", "is_active": "true", "phone": "", "manager_name": "",
                "address": "", "emergency_contact": "", "job_description": "",
                "photo": SimpleUploadedFile("zola.png", self.png_bytes(), content_type="image/png"),
            }, format="multipart")
            self.assertEqual(result.status_code, 201, result.data)
            self.assertIs(result.data["is_active"], True)
            self.assertEqual(result.data["phone"], "")
            self.assertTrue(result.data["photo_name"].endswith(".png"))
            served = self.client.get(f'/api/employees/{result.data["id"]}/photo/')
            self.assertEqual(served.status_code, 200)
            served.close()

    def test_replacing_a_photo_removes_only_the_previous_file(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            url = f"/api/employees/{self.employee.id}/"
            for name in ["first.png", "second.png"]:
                result = self.client.patch(url, {"photo": SimpleUploadedFile(name, self.png_bytes(), content_type="image/png")}, format="multipart")
                self.assertEqual(result.status_code, 200, result.data)
                self.employee.refresh_from_db()
                if name == "first.png":
                    original = self.employee.photo.path
                    self.assertTrue(os.path.exists(original))
            replacement = self.employee.photo.path
            self.assertNotEqual(original, replacement)
            self.assertFalse(os.path.exists(original))
            self.assertTrue(os.path.exists(replacement))

    def test_saving_an_employee_without_a_new_photo_keeps_the_file(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            url = f"/api/employees/{self.employee.id}/"
            self.client.patch(url, {"photo": SimpleUploadedFile("keep.png", self.png_bytes(), content_type="image/png")}, format="multipart")
            self.employee.refresh_from_db()
            stored = self.employee.photo.path
            self.assertEqual(self.client.patch(url, {"phone": "0780000000"}, format="json").status_code, 200)
            self.employee.refresh_from_db()
            self.assertEqual(self.employee.photo.path, stored)
            self.assertTrue(os.path.exists(stored))

    def test_deleting_a_contract_retains_its_document(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            created = self.client.post("/api/contracts/", {"employee": self.employee.id, "title": "Agreement",
                "start_date": "2026-01-01", "document": SimpleUploadedFile("deal.pdf", b"%PDF-1.4 keep", content_type="application/pdf")}, format="multipart")
            self.assertEqual(created.status_code, 201, created.data)
            stored = Contract.objects.get(pk=created.data["id"]).document.path
            self.assertTrue(os.path.exists(stored))
            self.assertEqual(self.client.delete(f'/api/contracts/{created.data["id"]}/').status_code, 204)
            self.assertTrue(os.path.exists(stored))

    def test_employee_form_can_attach_a_contract_document(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            result = self.client.patch(f"/api/employees/{self.employee.id}/", {
                "contract_title": "Permanent agreement",
                "contract_document": SimpleUploadedFile("deal.pdf", b"%PDF-1.4 employee form", content_type="application/pdf"),
            }, format="multipart")
            self.assertEqual(result.status_code, 200, result.data)
            self.assertNotIn("contract_document", result.data)
            self.assertEqual(result.data["latest_contract"]["title"], "Permanent agreement")
            self.assertTrue(result.data["latest_contract"]["document_name"].endswith(".pdf"))
            contract = Contract.objects.get(employee=self.employee)
            self.assertEqual(contract.title, "Permanent agreement")
            self.assertEqual(contract.status, "active")
            self.assertEqual(str(contract.start_date), str(self.employee.date_joined))
            served = self.client.get(f"/api/contracts/{contract.id}/document/")
            self.assertEqual(served.status_code, 200)
            self.assertEqual(served["Content-Type"], "application/pdf")
            self.assertTrue(served["Content-Disposition"].startswith("attachment"), served["Content-Disposition"])
            self.assertEqual(b"".join(served.streaming_content), b"%PDF-1.4 employee form")
            served.close()

    def test_attached_contract_defaults_its_title_and_validates_the_file(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            url = f"/api/employees/{self.employee.id}/"
            blank = self.client.patch(url, {"contract_title": "",
                "contract_document": SimpleUploadedFile("deal.pdf", b"%PDF-1.4 x", content_type="application/pdf")}, format="multipart")
            self.assertEqual(blank.status_code, 200, blank.data)
            self.assertEqual(Contract.objects.get(employee=self.employee).title, "Employment contract")
            rejected = self.client.patch(url, {
                "contract_document": SimpleUploadedFile("deal.html", b"<script>bad</script>", content_type="text/html")}, format="multipart")
            self.assertEqual(rejected.status_code, 400, rejected.data)
            self.assertEqual(Contract.objects.count(), 1)

    def test_creating_an_employee_with_photo_and_contract_is_atomic(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            payload = {
                "first_name": "Nia", "last_name": "Keza", "email": "nia@example.com",
                "department": "Legal", "job_title": "Counsel", "date_joined": "2026-04-01",
                "employment_type": "full_time", "is_active": "true",
                "photo": SimpleUploadedFile("nia.png", self.png_bytes(), content_type="image/png"),
                "contract_document": SimpleUploadedFile("nia.pdf", b"%PDF-1.4 nia", content_type="application/pdf"),
            }
            created = self.client.post("/api/employees/", payload, format="multipart")
            self.assertEqual(created.status_code, 201, created.data)
            self.assertTrue(created.data["photo_name"].endswith(".png"))
            self.assertEqual(Contract.objects.filter(employee_id=created.data["id"]).count(), 1)
            # a rejected contract must not leave a half-created employee behind
            payload["email"] = "other@example.com"
            payload["photo"] = SimpleUploadedFile("o.png", self.png_bytes(), content_type="image/png")
            payload["contract_document"] = SimpleUploadedFile("o.txt", b"not a contract", content_type="text/plain")
            failed = self.client.post("/api/employees/", payload, format="multipart")
            self.assertEqual(failed.status_code, 400, failed.data)
            self.assertFalse(Employee.objects.filter(email="other@example.com").exists())

    def test_missing_photo_returns_not_found(self):
        self.assertEqual(self.client.get(f"/api/employees/{self.employee.id}/photo/").status_code, 404)

    def test_deleting_an_employee_removes_their_records(self):
        Attendance.objects.create(employee=self.employee, date="2026-09-24", hours_worked=8)
        self.assertEqual(self.client.delete(f"/api/employees/{self.employee.id}/").status_code, 204)
        self.assertFalse(Employee.objects.filter(pk=self.employee.id).exists())
        self.assertEqual(Attendance.objects.count(), 0)

    def test_contract_upload_download_and_private_access(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            result = self.client.post("/api/contracts/", {"employee": self.employee.id, "title": "Permanent agreement",
                "start_date": "2026-01-01", "document": SimpleUploadedFile("contract.pdf", b"%PDF-1.4 test", content_type="application/pdf")}, format="multipart")
            self.assertEqual(result.status_code, 201, result.data)
            self.assertNotIn("document", result.data)
            self.assertTrue(result.data["document_name"].endswith(".pdf"))
            url = f'/api/contracts/{result.data["id"]}/document/'
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "application/pdf")
            self.assertTrue(response["Content-Disposition"].startswith("attachment;"))
            self.assertEqual(b"".join(response.streaming_content), b"%PDF-1.4 test")
            response.close()
            self.client.force_authenticate(User.objects.create_user(username="unauthorized"))
            self.assertEqual(self.client.get(url).status_code, 403)
            self.client.force_authenticate(None)
            self.assertEqual(self.client.get(url).status_code, 401)

    def test_contract_preview_returns_private_bytes_without_a_download_header(self):
        contents = b"%PDF-1.4 preview bytes"
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            contract = Contract.objects.create(employee=self.employee, title="Agreement", start_date="2026-01-01",
                document=SimpleUploadedFile("agreement.pdf", contents, content_type="application/pdf"))
            url = f"/api/contracts/{contract.id}/preview/"
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "application/octet-stream")
            self.assertNotIn("Content-Disposition", response)
            self.assertEqual(response["Cache-Control"], "private, no-store")
            self.assertEqual(b"".join(response.streaming_content), contents)
            response.close()
            self.client.force_authenticate(User.objects.create_user(username="preview_non_manager"))
            self.assertEqual(self.client.get(url).status_code, 403)
            self.client.force_authenticate(None)
            self.assertEqual(self.client.get(url).status_code, 401)

    def test_contract_preview_reports_missing_documents(self):
        contract = Contract.objects.create(employee=self.employee, title="Agreement", start_date="2026-01-01")
        self.assertEqual(self.client.get(f"/api/contracts/{contract.id}/preview/").status_code, 404)
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            contract.document = "contracts/missing.pdf"
            contract.save()
            self.assertEqual(self.client.get(f"/api/contracts/{contract.id}/preview/").status_code, 404)

    def test_contract_rejects_invalid_dates_and_file(self):
        data = {"employee": self.employee.id, "title": "Agreement", "start_date": "2026-09-24", "end_date": "2026-09-01"}
        self.assertEqual(self.client.post("/api/contracts/", data).status_code, 400)
        data["end_date"] = "2026-09-30"
        data["document"] = SimpleUploadedFile("contract.html", b"<script>bad</script>")
        self.assertEqual(self.client.post("/api/contracts/", data, format="multipart").status_code, 400)

    def test_contract_partial_update_checks_existing_dates(self):
        contract = Contract.objects.create(employee=self.employee, title="Agreement", start_date="2026-09-01", end_date="2026-09-30")
        result = self.client.patch(f"/api/contracts/{contract.id}/", {"start_date": "2026-10-01"}, format="json")
        self.assertEqual(result.status_code, 400)

    def test_attendance_hours_duplicates_and_absence_rules(self):
        data = {"employee": self.employee.id, "date": "2026-09-24", "status": "remote", "hours_worked": "7.50"}
        created = self.client.post("/api/attendance/", data)
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(self.client.post("/api/attendance/", data).status_code, 400)
        url = f'/api/attendance/{created.data["id"]}/'
        for change in [{"hours_worked": "25"}, {"hours_worked": "-1"}, {"status": "absent"}]:
            self.assertEqual(self.client.patch(url, change, format="json").status_code, 400)
        result = self.client.patch(url, {"status": "absent", "hours_worked": "0"}, format="json")
        self.assertEqual(result.status_code, 200)

    def test_attendance_cannot_precede_employment(self):
        result = self.client.post("/api/attendance/", {"employee": self.employee.id, "date": "2025-01-01"})
        self.assertEqual(result.status_code, 400)

    def test_leave_review_overlap_and_attendance_conflict(self):
        data = {"employee": self.employee.id, "start_date": "2026-09-24", "end_date": "2026-09-25", "leave_type": "annual"}
        self.assertEqual(self.client.post("/api/leave/", data).status_code, 400)
        leave = LeaveRequest.objects.create(employee=self.employee, start_date="2026-09-24", end_date="2026-09-25")
        self.assertEqual(leave.status, "pending")
        url = f"/api/leave/{leave.id}/"
        approved = self.client.patch(url, {"status": "approved", "decision_notes": "Approved by manager"}, format="json")
        self.assertEqual(approved.status_code, 200, approved.data)
        attendance = self.client.post("/api/attendance/", {"employee": self.employee.id, "date": "2026-09-24", "status": "absent"})
        self.assertEqual(attendance.status_code, 400)
        overlapping = LeaveRequest.objects.create(employee=self.employee, start_date="2026-09-25", end_date="2026-09-25")
        overlap_url = f"/api/leave/{overlapping.id}/"
        self.assertEqual(self.client.patch(overlap_url, {"status": "approved"}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(overlap_url, {"status": "rejected"}, format="json").status_code, 200)

    def test_leave_cannot_be_approved_over_existing_attendance(self):
        Attendance.objects.create(employee=self.employee, date="2026-09-24", hours_worked=8)
        response = self.client.post("/api/leave/", {"employee": self.employee.id, "start_date": "2026-09-24", "end_date": "2026-09-24", "status": "approved"})
        self.assertEqual(response.status_code, 400)

    def test_holiday_crud_and_unique_date(self):
        data = {"name": "Company holiday", "date": "2026-09-24"}
        response = self.client.post("/api/holidays/", data)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(self.client.post("/api/holidays/", data).status_code, 400)
        url = f'/api/holidays/{response.data["id"]}/'
        self.assertEqual(self.client.patch(url, {"name": "Updated holiday"}, format="json").status_code, 200)
        self.assertEqual(self.client.delete(url).status_code, 204)

    def test_salary_is_unique_per_employee_and_validated(self):
        data = {"employee": self.employee.id, "monthly_amount": "10000.00", "effective_date": "2026-01-01", "currency": "zar"}
        response = self.client.post("/api/salaries/", data)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["currency"], "ZAR")
        self.assertEqual(self.client.post("/api/salaries/", data).status_code, 400)
        for data in [{"monthly_amount": "-5"}, {"currency": "BAD"}]:
            self.assertEqual(self.client.patch(f'/api/salaries/{response.data["id"]}/', data, format="json").status_code, 400)

    def test_decided_leave_cannot_be_edited(self):
        leave = LeaveRequest.objects.create(employee=self.employee, start_date="2026-09-21", end_date="2026-09-22",
                                            status="approved", decision_notes="Enjoy")
        for change in [{"decision_notes": "Changed"}, {"status": "approved"}, {"status": "rejected"}]:
            self.assertEqual(self.client.patch(f"/api/leave/{leave.pk}/", change, format="json").status_code, 400)
        self.assertEqual(LeaveRequest.objects.get(pk=leave.pk).decision_notes, "Enjoy")

    def test_payroll_needs_a_signed_and_approved_contract_covering_the_period(self):
        self.assertEqual(self.client.post("/api/payroll/", self.payroll_data()).status_code, 400)
        self.approved_contract(end_date="2026-08-31")
        self.assertEqual(self.client.post("/api/payroll/", self.payroll_data()).status_code, 400)
        Contract.objects.create(employee=self.employee, title="Unsigned", start_date="2026-09-01")
        self.assertEqual(self.client.post("/api/payroll/", self.payroll_data()).status_code, 400)
        current = self.approved_contract(title="Current", start_date="2026-09-01", monthly_salary=Decimal("10000"))
        created = self.client.post("/api/payroll/", self.payroll_data())
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["contract"], current.pk)
        self.assertEqual(created.data["contract_title"], "Current")

    def test_salary_and_payroll_default_to_rwf(self):
        self.approved_contract()
        salary = self.client.post("/api/salaries/", {"employee": self.employee.id, "monthly_amount": "450000.00", "effective_date": "2026-01-01"})
        self.assertEqual(salary.status_code, 201, salary.data)
        self.assertEqual(salary.data["currency"], "RWF")
        payroll = self.client.post("/api/payroll/", {"employee": self.employee.id, "period_start": "2026-09-01",
                                                     "period_end": "2026-09-30", "base_salary": "450000.00"})
        self.assertEqual(payroll.status_code, 201, payroll.data)
        self.assertEqual(payroll.data["currency"], "RWF")

    def test_mark_paid_records_payroll_from_the_salary(self):
        self.approved_contract()
        salary = Salary.objects.create(employee=self.employee, monthly_amount=Decimal("450000.00"), effective_date="2026-01-01")
        response = self.client.post(f"/api/salaries/{salary.id}/mark_paid/")
        self.assertEqual(response.status_code, 201, response.data)
        current = timezone.localdate()
        self.assertEqual(response.data["status"], "paid")
        self.assertEqual(response.data["currency"], "RWF")
        self.assertEqual(response.data["paid_date"], str(current))
        self.assertEqual(response.data["period_start"], str(current.replace(day=1)))
        self.assertEqual(response.data["period_end"], str(current.replace(day=monthrange(current.year, current.month)[1])))
        self.assertEqual(Decimal(response.data["base_salary"]), Decimal("450000.00"))
        self.assertEqual(Decimal(response.data["net_pay"]), Decimal("450000.00"))
        self.assertEqual(response.data["employee_name"], "Ada Dube")
        self.assertEqual(response.data["department"], "Operations")
        self.assertEqual(Payroll.objects.count(), 1)
        url = f'/api/payroll/{response.data["id"]}/'
        self.assertEqual(self.client.delete(url).status_code, 400)
        self.assertEqual(self.client.patch(url, {"base_salary": "1"}, format="json").status_code, 400)

    def test_mark_paid_accepts_a_month_and_refuses_to_pay_twice(self):
        self.approved_contract()
        salary = Salary.objects.create(employee=self.employee, monthly_amount=Decimal("100000.00"), effective_date="2026-01-01")
        first = self.client.post(f"/api/salaries/{salary.id}/mark_paid/", {"month": "2026-08"}, format="json")
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(first.data["period_start"], "2026-08-01")
        self.assertEqual(first.data["period_end"], "2026-08-31")
        self.assertEqual(self.client.post(f"/api/salaries/{salary.id}/mark_paid/", {"month": "2026-08"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(f"/api/salaries/{salary.id}/mark_paid/", {"month": "nonsense"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(f"/api/salaries/{salary.id}/mark_paid/", {"month": "2026-13"}, format="json").status_code, 400)
        self.assertEqual(Payroll.objects.count(), 1)

    def test_mark_paid_skips_inactive_employees_and_enforces_the_manager_role(self):
        salary = Salary.objects.create(employee=self.employee, monthly_amount=Decimal("100000.00"), effective_date="2026-01-01")
        Employee.objects.filter(pk=self.employee.pk).update(is_active=False)
        self.assertEqual(self.client.post(f"/api/salaries/{salary.id}/mark_paid/").status_code, 400)
        Employee.objects.filter(pk=self.employee.pk).update(is_active=True)
        self.client.force_authenticate(User.objects.create_user(username="not-a-manager"))
        self.assertEqual(self.client.post(f"/api/salaries/{salary.id}/mark_paid/").status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(f"/api/salaries/{salary.id}/mark_paid/").status_code, 401)
        self.assertEqual(Payroll.objects.count(), 0)

    def test_payroll_decimal_totals_snapshot_and_paid_lock(self):
        self.approved_contract()
        response = self.client.post("/api/payroll/", self.payroll_data())
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["gross_pay"], "10500.50")
        self.assertEqual(response.data["net_pay"], "9000.25")
        url = f'/api/payroll/{response.data["id"]}/'
        paid = self.client.patch(url, {"status": "paid", "paid_date": "2026-09-20"}, format="json")
        self.assertEqual(paid.status_code, 200, paid.data)
        self.employee.first_name = "Changed"
        self.employee.save()
        Salary.objects.create(employee=self.employee, monthly_amount=20000, effective_date="2026-10-01")
        persisted = self.client.get(url)
        self.assertEqual(persisted.data["employee_name"], "Ada Dube")
        self.assertEqual(persisted.data["base_salary"], "10000.00")
        self.assertEqual(self.client.patch(url, {"base_salary": "1"}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(url, {"status": "draft"}, format="json").status_code, 400)
        self.assertEqual(self.client.delete(url).status_code, 400)

    def test_payroll_rejects_invalid_money_dates_status_and_overlaps(self):
        self.approved_contract()
        for overrides in [{"base_salary": "-1"}, {"deductions": "20000"}, {"period_end": "2026-08-31"},
                          {"status": "paid"}, {"paid_date": "2026-09-20"},
                          {"status": "paid", "paid_date": "2999-01-01"}]:
            response = self.client.post("/api/payroll/", self.payroll_data(**overrides))
            self.assertEqual(response.status_code, 400, response.data)
        created = self.client.post("/api/payroll/", self.payroll_data())
        self.assertEqual(created.status_code, 201)
        self.assertEqual(self.client.post("/api/payroll/", self.payroll_data()).status_code, 400)
        self.assertEqual(self.client.post("/api/payroll/", self.payroll_data(period_start="2026-09-20", period_end="2026-10-10")).status_code, 400)
        self.assertEqual(self.client.delete(f'/api/payroll/{created.data["id"]}/').status_code, 204)

    def test_reports_distinguish_absent_leave_missing_and_hours(self):
        other = Employee.objects.create(first_name="Ben", last_name="Molefe", email="ben@example.com", department="HR", job_title="Lead", date_joined="2026-01-01")
        missing = Employee.objects.create(first_name="Cleo", last_name="Nkosi", email="cleo@example.com", department="HR", job_title="Assistant", date_joined="2026-01-01")
        Attendance.objects.create(employee=self.employee, date="2026-09-23", status="remote", hours_worked=Decimal("7.50"))
        Attendance.objects.create(employee=self.employee, date="2026-09-24", status="absent", hours_worked=0)
        LeaveRequest.objects.create(employee=other, start_date="2026-09-24", end_date="2026-09-25", status="approved")
        response = self.client.get("/api/reports/?date=2026-09-24")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["absent"][0]["employee"], self.employee.id)
        self.assertEqual(response.data["on_leave"][0]["employee"], other.id)
        self.assertEqual([row["id"] for row in response.data["unrecorded"]], [missing.id])
        self.assertEqual(Decimal(response.data["working_hours"][0]["hours"]), Decimal("7.50"))
        Holiday.objects.create(name="Holiday", date="2026-09-24")
        self.assertEqual(self.client.get("/api/reports/?date=2026-09-24").data["unrecorded"], [])
        self.assertEqual(self.client.get("/api/reports/?date=2026-09-26").data["unrecorded"], [])

    def test_report_contract_boundaries_and_currency_totals(self):
        for end in ["2026-09-23", "2026-09-24", "2026-10-24", "2026-10-25"]:
            self.approved_contract(title=end, end_date=end)
        self.client.post("/api/payroll/", self.payroll_data(period_end="2026-09-20"))
        second = Employee.objects.create(first_name="Other", last_name="Person", email="other@example.com", department="HR", job_title="Lead", date_joined="2026-01-01")
        self.approved_contract(second)
        self.client.post("/api/payroll/", self.payroll_data(employee=second.id, currency="USD", period_end="2026-09-20"))
        response = self.client.get("/api/reports/?date=2026-09-24&days=30")
        self.assertEqual([row["end_date"] for row in response.data["expiring_contracts"]], ["2026-09-24", "2026-10-24"])
        self.assertEqual(len(response.data["expired_contracts"]), 1)
        self.assertEqual({row["currency"] for row in response.data["payroll_totals"]}, {"ZAR", "USD"})
        for row in response.data["payroll_totals"]:
            self.assertEqual(Decimal(row["net"]), Decimal("9000.25"))

    def test_report_rejects_invalid_query(self):
        for query in ["date=invalid", "days=0", "days=366", "days=bad"]:
            self.assertEqual(self.client.get(f"/api/reports/?{query}").status_code, 400)
