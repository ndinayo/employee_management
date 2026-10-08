"""The administrator sees how much each workspace is used, never what it holds."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import (AccountProfile, Attendance, Business, Contract, Employee, Holiday, LeaveRequest,
                     Payroll, Salary, WorkplaceLocation)


class AdminActivityTests(APITestCase):
    password = "Cedar!Lantern-47-River"

    def setUp(self):
        self.admin = User.objects.create_user("platform-admin", "admin@example.com", self.password)
        AccountProfile.objects.create(user=self.admin, role="admin")
        self.business = Business.objects.create(name="Kigali Works")
        self.employer = User.objects.create_user("boss", "boss@example.com", self.password)
        AccountProfile.objects.create(user=self.employer, role="employer", business=self.business)
        self.other = Business.objects.create(name="Other Ltd")
        self.today = timezone.localdate()
        self.client.force_authenticate(self.admin)

    def hire(self, business, email, department="Sales", **extra):
        return Employee.objects.create(business=business, first_name="Aline", last_name="Uwase", email=email,
                                       job_title="Accountant", department=department,
                                       date_joined=self.today - timedelta(days=30), phone="0788000000",
                                       address="12 Private Street", **extra)

    def test_counts_are_scoped_to_the_company_and_reveal_no_private_details(self):
        aline = self.hire(self.business, "aline@example.com")
        bosco = self.hire(self.business, "bosco@example.com", department="IT")
        outsider = self.hire(self.other, "out@example.com")
        now = timezone.now()
        Attendance.objects.create(employee=aline, date=self.today, check_in_at=now - timedelta(hours=3),
                                  check_out_at=now - timedelta(hours=1), check_in_latitude=Decimal("-1.944100"),
                                  check_in_longitude=Decimal("30.061900"))
        Attendance.objects.create(employee=bosco, date=self.today, check_in_at=now - timedelta(hours=2))
        Attendance.objects.create(employee=outsider, date=self.today, check_in_at=now)
        LeaveRequest.objects.create(employee=aline, leave_type="annual", start_date=self.today,
                                    end_date=self.today, reason="Family funeral", status="pending")
        Contract.objects.create(employee=aline, title="Employment", start_date=self.today,
                                signature_status="signed", content="Secret clause")
        Salary.objects.create(employee=aline, monthly_amount=Decimal("987654"), currency="RWF",
                              effective_date=self.today)
        Payroll.objects.create(employee=aline, period_start=self.today.replace(day=1), period_end=self.today,
                               base_salary=Decimal("987654"), status="paid", paid_date=self.today)
        WorkplaceLocation.objects.create(business=self.business, latitude=Decimal("-1.944100"),
                                         longitude=Decimal("30.061900"))

        company = self.client.get(f"/api/admin/businesses/{self.business.pk}/activity/")
        self.assertEqual(company.status_code, 200, company.data)
        counts = company.data["counts"]
        self.assertEqual((counts["checked_in_today"], counts["on_shift_now"], counts["shifts_completed_today"]),
                         (2, 1, 1))
        self.assertEqual((counts["leave_requests_pending"], counts["contracts_active"],
                          counts["payslips_this_month"]), (1, 1, 1))
        self.assertEqual(company.data["departments"], [{"name": "IT", "employees": 1},
                                                       {"name": "Sales", "employees": 1}])
        self.assertTrue(company.data["workplace_location_set"])

        platform = self.client.get("/api/admin/activity/")
        self.assertEqual(platform.data["counts"]["checked_in_today"], 3)
        self.assertEqual(platform.data["companies_with_workplace_location"], 1)

        employees = str(self.client.get("/api/admin/employees/").data)
        self.assertIn("Sales", employees)
        for payload in (str(company.data), str(platform.data), employees):
            for secret in ("987654", "Family funeral", "Secret clause", "-1.9441", "0788000000",
                           "Private Street"):
                self.assertNotIn(secret, payload)

    def test_employee_details_show_work_and_activity_without_private_records(self):
        aline = self.hire(self.business, "aline@example.com", manager_name="Grace", emergency_contact="Mum 0788111111")
        now = timezone.now()
        Attendance.objects.create(employee=aline, date=self.today, check_in_at=now - timedelta(hours=2),
                                  hours_worked=Decimal("0.00"))
        LeaveRequest.objects.create(employee=aline, leave_type="sick", start_date=self.today,
                                    end_date=self.today, reason="Hospital visit", status="approved")
        Contract.objects.create(employee=aline, title="Employment", start_date=self.today,
                                signature_status="sent", content="Secret clause")
        Payroll.objects.create(employee=aline, period_start=self.today.replace(day=1), period_end=self.today,
                               base_salary=Decimal("987654"), status="paid", paid_date=self.today)

        details = self.client.get(f"/api/admin/employees/{aline.pk}/activity/")
        self.assertEqual(details.status_code, 200, details.data)
        self.assertEqual(details.data["today"], "on_shift")
        self.assertEqual(details.data["employee"]["manager_name"], "Grace")
        self.assertEqual(details.data["days_worked_this_month"], 1)
        self.assertEqual(details.data["leave_requests_this_year"]["approved"], 1)
        self.assertEqual(details.data["contract"]["signature"], "Awaiting signature")
        self.assertEqual(details.data["payslips_this_year"], 1)
        for secret in ("987654", "Hospital visit", "Secret clause", "0788000000", "Private Street", "Mum"):
            self.assertNotIn(secret, str(details.data))

    def test_admin_reads_every_record_type_read_only_and_filtered(self):
        from .admin_records import SOURCES
        aline = self.hire(self.business, "aline@example.com")
        outsider = self.hire(self.other, "out@example.com")
        Salary.objects.create(employee=aline, monthly_amount=Decimal("987654"), currency="RWF",
                              effective_date=self.today)
        Salary.objects.create(employee=outsider, monthly_amount=Decimal("111111"), currency="RWF",
                              effective_date=self.today)
        LeaveRequest.objects.create(employee=aline, leave_type="annual", start_date=self.today,
                                    end_date=self.today, reason="Family funeral")
        for resource in SOURCES:
            listed = self.client.get(f"/api/admin/records/{resource}/")
            self.assertEqual(listed.status_code, 200, (resource, listed.data))

        everyone = self.client.get("/api/admin/records/salaries/").data
        self.assertEqual(len(everyone), 2)
        mine = self.client.get(f"/api/admin/records/salaries/?business={self.business.pk}").data
        self.assertEqual([row["monthly_amount"] for row in mine], ["987654.00"])
        self.assertEqual(len(self.client.get(f"/api/admin/records/salaries/?employee={outsider.pk}").data), 1)
        self.assertEqual(self.client.get(f"/api/admin/records/leave/?employee={aline.pk}").data[0]["reason"],
                         "Family funeral")
        self.assertEqual(self.client.get(f"/api/admin/records/employees/?employee={aline.pk}").data[0]["phone"],
                         "0788000000")

        Holiday.objects.create(business=self.other, name="Elsewhere", date=self.today)
        self.assertEqual(self.client.get(f"/api/admin/records/holidays/?employee={aline.pk}").data, [])
        self.assertEqual(self.client.get("/api/admin/records/salaries/?business=x").status_code, 404)
        self.assertEqual(self.client.post("/api/admin/records/salaries/", {}, format="json").status_code, 405)
        self.assertEqual(self.client.get("/api/admin/records/passwords/").status_code, 404)
        self.client.force_authenticate(self.employer)
        self.assertEqual(self.client.get("/api/admin/records/salaries/").status_code, 403)

    def test_only_an_administrator_can_read_activity(self):
        aline = self.hire(self.business, "aline@example.com")
        self.assertEqual(self.client.get("/api/admin/businesses/9999/activity/").status_code, 404)
        self.assertEqual(self.client.get("/api/admin/employees/9999/activity/").status_code, 404)
        self.client.force_authenticate(self.employer)
        self.assertEqual(self.client.get("/api/admin/activity/").status_code, 403)
        self.assertEqual(self.client.get(f"/api/admin/businesses/{self.business.pk}/activity/").status_code, 403)
        self.assertEqual(self.client.get(f"/api/admin/employees/{aline.pk}/activity/").status_code, 403)
