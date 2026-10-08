from datetime import date
from decimal import Decimal
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import (AccountProfile, AdvanceRepayment, AssetIncident, Business, Contract, Employee, Payroll,
                     PayrollCalculation, Salary, SalaryAdvance, SalaryAdvanceRequest)


class PayrollFeatureTestCase(APITestCase):
    def setUp(self):
        self.business, self.employer = self.make_business("Kigali Works", "boss")
        self.employee = self.make_employee(self.business, "aline@example.com", "Aline", "Uwase")
        self.client.force_authenticate(self.employer)

    def make_business(self, name, username):
        business = Business.objects.create(name=name)
        user = User.objects.create_user(username, f"{username}@example.com", "Cedar!Lantern-47-River")
        AccountProfile.objects.create(user=user, role="employer", business=business)
        return business, user

    def make_employee(self, business, email, first="Jean", last="Mugisha", with_account=True):
        employee = Employee.objects.create(business=business, first_name=first, last_name=last, email=email,
                                           job_title="Accountant", date_joined="2026-01-01")
        if with_account:
            user = User.objects.create_user(email, email, "Cedar!Lantern-47-River")
            AccountProfile.objects.create(user=user, role="employee", employee=employee)
            Contract.objects.create(employee=employee, title="Signed employment contract",
                                    start_date=date(2026, 1, 1), status="active", signature_status="signed",
                                    worker_approval_status="approved")
        return employee

    def payroll(self, base="300000", employee=None, start="2026-09-01", end="2026-09-30", currency="RWF",
                status="draft", allowances="0", deductions="0"):
        employee = employee or self.employee
        payroll = Payroll.objects.create(employee=employee, period_start=start, period_end=end, base_salary=base,
                                         allowances=allowances, deductions=deductions, currency=currency,
                                         status=status, paid_date=end if status == "paid" else None,
                                         employee_name=str(employee), employee_email=employee.email)
        payroll.refresh_from_db()
        return payroll

    def calculate(self, payroll, **extra):
        return self.client.post("/api/payroll-calculations/", {"payroll": payroll.pk, **extra}, format="json")

    def mark_paid(self, payroll):
        Payroll.objects.filter(pk=payroll.pk).update(status="paid", paid_date=payroll.period_end)
        payroll.refresh_from_db()

    def advance(self, amount="100000", installment="40000", disburse=True, **extra):
        response = self.client.post("/api/salary-advances/", {
            "employee": self.employee.pk, "amount": amount, "currency": "RWF", "issue_date": "2026-08-20",
            "reason": "School fees", "installment_amount": installment, "first_repayment_month": "2026-09-01",
            **extra}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        if disburse:
            result = self.client.post(f"/api/salary-advances/{response.data['id']}/disburse/", {
                "disbursed_on": "2026-08-21", "disbursement_method": "mobile_money",
                "disbursement_reference": f"MM-{response.data['id']}"}, format="json")
            self.assertEqual(result.status_code, 200, result.data)
            return result.data
        return response.data


class PayrollDeductionTests(PayrollFeatureTestCase):
    def test_calculation_only_applies_advances_and_other_deductions(self):
        self.advance(amount="100000", installment="40000")
        payroll = self.payroll(base="250000", allowances="50000", deductions="2500")
        response = self.calculate(payroll)
        self.assertEqual(response.status_code, 201, response.data)
        data = response.data
        self.assertEqual([line["kind"] for line in data["lines"]], ["advance", "other"])
        self.assertEqual(Decimal(data["advance_deductions"]), Decimal("40000"))
        self.assertEqual(Decimal(data["other_deductions"]), Decimal("2500"))
        self.assertEqual(Decimal(data["total_deductions"]), Decimal("42500"))
        self.assertEqual(Decimal(data["net_pay"]), Decimal("257500"))
        for removed in ("paye", "employee_contributions", "employer_contributions", "taxable_income"):
            self.assertNotIn(removed, data)
        payroll.refresh_from_db()
        self.assertEqual(payroll.deductions, Decimal("42500.00"))

    def test_recalculation_preserves_other_deductions_and_rejects_paid_payroll(self):
        payroll = self.payroll(base="100000", deductions="2500")
        first = self.calculate(payroll).data
        second = self.calculate(payroll).data
        self.assertEqual(Decimal(second["other_deductions"]), Decimal("2500"))
        self.assertEqual(Decimal(second["total_deductions"]), Decimal(first["total_deductions"]))
        self.assertEqual(PayrollCalculation.objects.count(), 1)
        self.mark_paid(payroll)
        self.assertEqual(self.calculate(payroll).status_code, 400)

    def test_deductions_above_gross_are_rejected(self):
        response = self.calculate(self.payroll(base="1000"), other_deductions="5000")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(PayrollCalculation.objects.exists())


class SalaryPaymentTests(PayrollFeatureTestCase):
    def setUp(self):
        super().setUp()
        self.salary = Salary.objects.create(employee=self.employee, monthly_amount=Decimal("300000"),
                                            effective_date="2026-01-01")

    def resolved_incident(self, recovery, status="resolved", **changes):
        created = self.client.post("/api/asset-incidents/", {
            "employee": self.employee.pk, "asset_name": "Laptop", "incident_type": "damaged",
            "estimated_loss": "400000", "description": "Screen cracked", "incident_date": "2026-09-10",
            **changes}, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        if status == "reported":
            update = {"recovery_amount": recovery, "recovery_authorization": "Signed agreement 12/09"}
        else:
            update = {"status": status, "resolution": "Employee agreed to repay", "recovery_amount": recovery,
                      "recovery_authorization": "Signed agreement 12/09"}
        updated = self.client.patch(f"/api/asset-incidents/{created.data['id']}/", update, format="json")
        self.assertEqual(updated.status_code, 200, updated.data)
        return updated.data

    def preview(self, month="2026-09"):
        response = self.client.get(f"/api/salaries/{self.salary.pk}/payment_preview/", {"month": month})
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def pay(self, month="2026-09"):
        return self.client.post(f"/api/salaries/{self.salary.pk}/mark_paid/", {"month": month}, format="json")

    def test_preview_matches_payment_and_balances_update(self):
        advance = self.advance(amount="100000", installment="40000")
        incident = self.resolved_incident("50000")
        before = self.preview()
        self.assertEqual(Decimal(before["monthly_salary"]), Decimal("300000"))
        self.assertEqual(Decimal(before["advance_deductions"]), Decimal("40000"))
        self.assertEqual(Decimal(before["asset_deductions"]), Decimal("50000"))
        self.assertEqual(Decimal(before["total_deductions"]), Decimal("90000"))
        self.assertEqual(Decimal(before["net_salary"]), Decimal("210000"))
        self.assertFalse(before["already_paid"])
        self.assertFalse(AdvanceRepayment.objects.exists())

        paid = self.pay()
        self.assertEqual(paid.status_code, 201, paid.data)
        self.assertEqual(paid.data["status"], "paid")
        self.assertEqual(Decimal(paid.data["deductions"]), Decimal("90000"))
        self.assertEqual(Decimal(paid.data["net_pay"]), Decimal("210000"))
        self.assertTrue(self.preview()["already_paid"])
        advance_now = self.client.get(f"/api/salary-advances/{advance['id']}/").data
        self.assertEqual(Decimal(advance_now["total_repaid"]), Decimal("40000"))
        incident_now = self.client.get(f"/api/asset-incidents/{incident['id']}/").data
        self.assertEqual(Decimal(incident_now["recovered_amount"]), Decimal("50000"))
        self.assertEqual(Decimal(incident_now["outstanding_recovery"]), Decimal("0"))

        self.assertEqual(self.pay().status_code, 400)
        self.assertEqual(Payroll.objects.count(), 1)
        october = self.preview("2026-10")
        self.assertEqual(Decimal(october["advance_deductions"]), Decimal("40000"))
        self.assertEqual(Decimal(october["asset_deductions"]), Decimal("0"))
        self.assertEqual(self.client.patch(f"/api/asset-incidents/{incident['id']}/", {"recovery_amount": "1000"},
                                           format="json").status_code, 400)

    def test_combined_deductions_respect_the_limit_and_carry_over(self):
        self.advance(amount="90000", installment="90000")
        incident = self.resolved_incident("50000", status="closed")
        september = self.preview()
        self.assertEqual(Decimal(september["advance_deductions"]), Decimal("90000"))
        self.assertEqual(Decimal(september["asset_deductions"]), Decimal("9990.00"))
        self.assertTrue(any("limit" in warning for warning in september["warnings"]))
        self.assertEqual(self.pay().status_code, 201)
        october = self.preview("2026-10")
        self.assertEqual(Decimal(october["advance_deductions"]), Decimal("0"))
        self.assertEqual(Decimal(october["asset_deductions"]), Decimal("40010.00"))
        self.assertEqual(self.pay("2026-10").status_code, 201)
        detail = self.client.get(f"/api/asset-incidents/{incident['id']}/").data
        self.assertEqual(Decimal(detail["recovered_amount"]), Decimal("50000"))

    def test_open_incidents_are_deducted_within_the_limit(self):
        self.resolved_incident("50000", status="under_review")
        phone = self.client.post("/api/asset-incidents/", {
            "employee": self.employee.pk, "asset_name": "Phone", "estimated_loss": "90000",
            "description": "Lost", "incident_date": "2026-09-12"}, format="json").data
        self.client.post("/api/asset-incidents/", {
            "employee": self.employee.pk, "asset_name": "Tablet", "estimated_loss": "5000",
            "description": "Reported next month", "incident_date": "2026-10-02"}, format="json")
        data = self.preview()
        self.assertEqual([Decimal(line["amount"]) for line in data["lines"]], [Decimal("50000"), Decimal("49990")])
        self.assertEqual(Decimal(data["total_deductions"]), Decimal("99990"))
        self.assertTrue(any("limit" in warning for warning in data["warnings"]))
        paid = self.pay()
        self.assertEqual(Decimal(paid.data["net_pay"]), Decimal("200010"))
        self.assertEqual(Decimal(self.client.get(f"/api/asset-incidents/{phone['id']}/").data["outstanding_recovery"]),
                         Decimal("40010"))
        self.assertEqual(self.client.patch(f"/api/asset-incidents/{phone['id']}/", {"estimated_loss": "1000"},
                                           format="json").status_code, 400)
        october = self.preview("2026-10")
        self.assertEqual(Decimal(october["asset_deductions"]), Decimal("45010"))

    def test_complete_workflow_shows_net_before_paying_and_deducts_once(self):
        advance = self.advance(amount="60000", installment="25000")
        incident = self.resolved_incident("30000")
        before = self.preview()
        self.assertEqual(before["status"], "unpaid")
        self.assertEqual(Decimal(before["monthly_salary"]), Decimal("300000"))
        self.assertEqual(Decimal(before["advance_deductions"]), Decimal("25000"))
        self.assertEqual(Decimal(before["asset_deductions"]), Decimal("30000"))
        self.assertEqual(Decimal(before["total_deductions"]), Decimal("55000"))
        self.assertEqual(Decimal(before["net_salary"]), Decimal("245000"))
        self.assertEqual(self.client.get(f"/api/salary-advances/{advance['id']}/").data["total_repaid"], "0.00")

        paid = self.pay()
        self.assertEqual(paid.status_code, 201, paid.data)
        self.assertEqual(Decimal(paid.data["net_pay"]), Decimal("245000"))

        saved = self.preview()
        self.assertEqual(saved["status"], "paid")
        self.assertTrue(saved["already_paid"])
        self.assertEqual(saved["payroll"], paid.data["id"])
        for key in ("monthly_salary", "advance_deductions", "asset_deductions", "total_deductions", "net_salary"):
            self.assertEqual(Decimal(saved[key]), Decimal(before[key]), key)
        self.assertEqual({line["kind"] for line in saved["lines"]}, {"advance", "asset"})

        self.assertEqual(self.pay().status_code, 400)
        for _ in range(2):
            self.preview()
        advance_now = self.client.get(f"/api/salary-advances/{advance['id']}/").data
        self.assertEqual(Decimal(advance_now["total_repaid"]), Decimal("25000"))
        self.assertEqual(Decimal(advance_now["outstanding_balance"]), Decimal("35000"))
        incident_now = self.client.get(f"/api/asset-incidents/{incident['id']}/").data
        self.assertEqual(Decimal(incident_now["recovered_amount"]), Decimal("30000"))
        self.assertEqual(AdvanceRepayment.objects.count(), 1)
        self.assertEqual(Payroll.objects.count(), 1)

        october = self.preview("2026-10")
        self.assertEqual(october["status"], "unpaid")
        self.assertEqual(Decimal(october["advance_deductions"]), Decimal("25000"))
        self.assertEqual(Decimal(october["asset_deductions"]), Decimal("0"))

    def test_history_lists_paid_and_unpaid_months_and_keeps_legacy_records(self):
        legacy = self.payroll(base="200000", start="2026-08-01", end="2026-08-31", status="paid")
        self.advance(amount="60000", installment="25000")
        history = self.client.get(f"/api/salaries/{self.salary.pk}/payment_history/")
        self.assertEqual(history.status_code, 200, history.data)
        months = {row["month"]: row for row in history.data["months"]}
        self.assertEqual(history.data["months"][0]["month"], str(timezone.localdate())[:7])
        self.assertEqual(months["2026-01"]["status"], "unpaid")
        self.assertIsNone(months["2026-01"]["net_salary"])
        self.assertEqual(months["2026-08"]["status"], "paid")
        self.assertEqual(Decimal(months["2026-08"]["monthly_salary"]), Decimal("200000"))
        self.assertEqual(Decimal(months["2026-08"]["total_deductions"]), Decimal("0"))

        saved = self.preview("2026-08")
        self.assertEqual(saved["status"], "paid")
        self.assertEqual(Decimal(saved["monthly_salary"]), Decimal("200000"))
        self.assertEqual(Decimal(saved["advance_deductions"]), Decimal("0"))
        self.assertEqual(saved["warnings"], [])
        self.assertEqual(self.pay("2026-08").status_code, 400)
        legacy.refresh_from_db()
        self.assertEqual((legacy.base_salary, legacy.deductions, legacy.status), (Decimal("200000.00"), Decimal("0.00"), "paid"))
        self.assertFalse(PayrollCalculation.objects.filter(payroll=legacy).exists())
        self.assertFalse(AdvanceRepayment.objects.exists())

    def test_recorded_advance_and_reported_incident_are_both_deducted(self):
        advance = self.advance(amount="20000", installment="20000", disburse=False)
        self.client.post("/api/asset-incidents/", {
            "employee": self.employee.pk, "asset_name": "Laptop", "estimated_loss": "270",
            "description": "Yesterday", "incident_date": "2026-09-29"}, format="json")
        data = self.preview()
        self.assertEqual(Decimal(data["advance_deductions"]), Decimal("20000"))
        self.assertEqual(Decimal(data["asset_deductions"]), Decimal("270"))
        self.assertEqual(Decimal(data["net_salary"]), Decimal("279730"))
        self.assertEqual(data["warnings"], [])
        self.assertEqual(self.pay().status_code, 201)
        detail = self.client.get(f"/api/salary-advances/{advance['id']}/").data
        self.assertEqual(detail["status"], "repaid")
        self.assertEqual(Decimal(detail["outstanding_balance"]), Decimal("0"))
        self.assertEqual(Decimal(self.preview("2026-10")["advance_deductions"]), Decimal("0"))

    def test_preview_is_scoped_to_the_employer(self):
        _, rival = self.make_business("Rival Ltd", "rival")
        self.client.force_authenticate(rival)
        self.assertEqual(self.client.get(f"/api/salaries/{self.salary.pk}/payment_preview/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/salaries/{self.salary.pk}/payment_history/").status_code, 404)
        self.client.force_authenticate(self.employee.account.user)
        self.assertEqual(self.client.get(f"/api/salaries/{self.salary.pk}/payment_preview/").status_code, 403)
        self.assertEqual(self.client.get(f"/api/salaries/{self.salary.pk}/payment_history/").status_code, 403)


class RemovedFeatureTests(PayrollFeatureTestCase):
    def test_insurance_taxes_and_payment_verification_endpoints_are_gone(self):
        for path in ["/api/insurance-types/", "/api/contribution-rates/", "/api/paye-bands/",
                     "/api/insurance-enrollments/", "/api/statutory-preview/", "/api/payment-records/"]:
            self.assertEqual(self.client.get(path).status_code, 404, path)
        self.client.force_authenticate(self.employee.account.user)
        self.assertEqual(self.client.get("/api/me/payments/").status_code, 404)


class PermissionAndIsolationTests(PayrollFeatureTestCase):
    ENDPOINTS = ["payroll-calculations", "salary-advances", "asset-incidents", "salary-advance-requests"]

    def test_employer_endpoints_require_an_employer(self):
        for resource in self.ENDPOINTS + ["payroll-policy"]:
            self.client.force_authenticate(None)
            self.assertEqual(self.client.get(f"/api/{resource}/").status_code, 401, resource)
            self.client.force_authenticate(self.employee.account.user)
            self.assertEqual(self.client.get(f"/api/{resource}/").status_code, 403, resource)
            self.client.force_authenticate(self.employer)
            self.assertEqual(self.client.get(f"/api/{resource}/").status_code, 200, resource)

    def test_another_employer_cannot_see_or_touch_records(self):
        advance = self.advance()
        incident = self.client.post("/api/asset-incidents/", {
            "employee": self.employee.pk, "asset_name": "Laptop", "incident_date": "2026-09-10",
            "description": "Lost"}, format="json").data
        draft = self.payroll(start="2026-10-01", end="2026-10-31")
        self.calculate(draft)

        _, rival = self.make_business("Rival Ltd", "rival")
        self.client.force_authenticate(rival)
        for resource in self.ENDPOINTS:
            self.assertEqual(self.client.get(f"/api/{resource}/").data, [], resource)
        self.assertEqual(self.client.get(f"/api/salary-advances/{advance['id']}/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/asset-incidents/{incident['id']}/").status_code, 404)
        self.assertEqual(self.calculate(draft).status_code, 400)
        self.assertEqual(self.client.post("/api/salary-advances/", {
            "employee": self.employee.pk, "amount": "1000", "issue_date": "2026-08-20", "reason": "x",
            "installment_amount": "500", "first_repayment_month": "2026-09-01"}, format="json").status_code, 400)
        self.assertEqual(SalaryAdvance.objects.count(), 1)


class SalaryAdvanceTests(PayrollFeatureTestCase):
    def test_advance_is_deducted_once_even_when_payroll_is_recalculated(self):
        advance = self.advance()
        payroll = self.payroll()
        for _ in range(3):
            data = self.calculate(payroll).data
        self.assertEqual(Decimal(data["advance_deductions"]), Decimal("40000"))
        self.assertEqual(AdvanceRepayment.objects.filter(advance_id=advance["id"]).count(), 1)
        detail = self.client.get(f"/api/salary-advances/{advance['id']}/").data
        self.assertEqual(detail["status"], "disbursed")
        self.assertEqual(Decimal(detail["scheduled_deductions"]), Decimal("40000"))
        self.assertEqual(Decimal(detail["total_repaid"]), Decimal("0"))

    def test_installments_never_exceed_outstanding_balance_and_status_progresses(self):
        advance = self.advance(amount="50000", installment="40000")
        september = self.payroll()
        self.calculate(september)
        self.mark_paid(september)
        detail = self.client.get(f"/api/salary-advances/{advance['id']}/").data
        self.assertEqual(detail["status"], "partially_repaid")
        self.assertEqual(Decimal(detail["outstanding_balance"]), Decimal("10000"))
        self.assertEqual(Decimal(detail["next_installment"]), Decimal("10000"))

        october = self.payroll(start="2026-10-01", end="2026-10-31")
        self.assertEqual(Decimal(self.calculate(october).data["advance_deductions"]), Decimal("10000"))
        self.mark_paid(october)
        detail = self.client.get(f"/api/salary-advances/{advance['id']}/").data
        self.assertEqual(detail["status"], "repaid")
        self.assertEqual(Decimal(detail["total_repaid"]), Decimal("50000"))
        self.assertEqual(Decimal(detail["outstanding_balance"]), Decimal("0"))

        november = self.payroll(start="2026-11-01", end="2026-11-30")
        self.assertEqual(Decimal(self.calculate(november).data["advance_deductions"]), Decimal("0"))

    def test_deduction_limit_caps_the_installment(self):
        self.advance(amount="100000", installment="40000")
        data = self.calculate(self.payroll(base="70000", deductions="4000")).data
        # Pay after other deductions: 70,000 - 4,000 = 66,000; 33.33% of it is 21,997.80.
        self.assertEqual(Decimal(data["advance_deductions"]), Decimal("21997.80"))
        self.assertTrue(any("limit" in warning for warning in data["warnings"]))

        policy = self.client.patch("/api/payroll-policy/", {"advance_deduction_limit_percent": "50"}, format="json")
        self.assertEqual(policy.status_code, 200, policy.data)
        data = self.calculate(Payroll.objects.get(base_salary="70000")).data
        self.assertEqual(Decimal(data["advance_deductions"]), Decimal("33000.00"))
        self.assertEqual(self.client.patch("/api/payroll-policy/", {"advance_deduction_limit_percent": "120"},
                                           format="json").status_code, 400)

    def test_recorded_advance_is_given_without_a_disbursement_step(self):
        response = self.client.post("/api/salary-advances/", {
            "employee": self.employee.pk, "amount": "50000", "issue_date": "2026-09-05"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        advance = response.data
        self.assertEqual(advance["status"], "disbursed")
        self.assertEqual(advance["first_repayment_month"], "2026-09-01")
        self.assertEqual(Decimal(advance["next_installment"]), Decimal("50000"))
        self.assertEqual(self.client.post(f"/api/salary-advances/{advance['id']}/repayments/", {
            "amount": "1000", "repaid_on": "2026-09-06"}, format="json").status_code, 201)
        self.assertEqual(self.client.delete(f"/api/salary-advances/{advance['id']}/").status_code, 400)
        self.assertEqual(self.client.patch(f"/api/salary-advances/{advance['id']}/", {"amount": "70000"},
                                           format="json").status_code, 400)

        unused = self.advance(amount="2000", installment="2000", disburse=False)
        self.assertEqual(Decimal(self.calculate(self.payroll()).data["advance_deductions"]), Decimal("51000"))
        other = self.client.post("/api/salary-advances/", {
            "employee": self.employee.pk, "amount": "3000", "issue_date": "2026-09-05"}, format="json").data
        self.assertEqual(self.client.delete(f"/api/salary-advances/{other['id']}/").status_code, 204)
        self.assertEqual(unused["status"], "disbursed")

    def test_advance_without_installment_or_reason_is_repaid_within_the_limit(self):
        response = self.client.post("/api/salary-advances/", {
            "employee": self.employee.pk, "amount": "150000", "currency": "RWF", "issue_date": "2026-08-20",
            "first_repayment_month": "2026-09-01"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["reason"], "")
        self.assertEqual(Decimal(response.data["installment_amount"]), Decimal("150000"))
        advance_id = response.data["id"]
        self.client.post(f"/api/salary-advances/{advance_id}/disburse/", {
            "disbursed_on": "2026-08-21", "disbursement_method": "cash"}, format="json")
        september = self.payroll()
        # 33.33% of 300,000 is 99,990; the remainder carries over to October.
        self.assertEqual(Decimal(self.calculate(september).data["advance_deductions"]), Decimal("99990.00"))
        self.mark_paid(september)
        october = self.payroll(start="2026-10-01", end="2026-10-31")
        self.assertEqual(Decimal(self.calculate(october).data["advance_deductions"]), Decimal("50010.00"))

        custom = self.advance(amount="90000", installment="30000", disburse=False)
        edited = self.client.patch(f"/api/salary-advances/{custom['id']}/", {"amount": "60000"}, format="json")
        self.assertEqual(edited.status_code, 200, edited.data)
        self.assertEqual(Decimal(edited.data["installment_amount"]), Decimal("30000"))
        self.assertEqual(edited.data["reason"], "School fees")

    def test_advance_validation(self):
        base = {"employee": self.employee.pk, "amount": "1000", "issue_date": "2026-08-20", "reason": "Rent",
                "installment_amount": "2000", "first_repayment_month": "2026-09-01"}
        self.assertEqual(self.client.post("/api/salary-advances/", base, format="json").status_code, 400)
        self.assertEqual(self.client.post("/api/salary-advances/", {
            **base, "installment_amount": "500", "first_repayment_month": "2026-07-01"}, format="json").status_code, 400)
        self.assertEqual(self.client.post("/api/salary-advances/", {
            **base, "amount": "-5", "installment_amount": "1"}, format="json").status_code, 400)

    def test_manual_repayment_is_capped_and_schedule_has_no_interest(self):
        advance = self.advance(amount="100000", installment="30000")
        self.assertEqual([row["amount"] for row in advance["schedule"]],
                         ["30000.00", "30000.00", "30000.00", "10000.00"])
        too_much = self.client.post(f"/api/salary-advances/{advance['id']}/repayments/", {
            "amount": "100000.01", "repaid_on": "2026-09-05"}, format="json")
        self.assertEqual(too_much.status_code, 400)
        paid = self.client.post(f"/api/salary-advances/{advance['id']}/repayments/", {
            "amount": "100000", "repaid_on": "2026-09-05", "reference": "CASH-1"}, format="json")
        self.assertEqual(paid.status_code, 201, paid.data)
        self.assertEqual(paid.data["status"], "repaid")
        self.assertEqual(Decimal(self.calculate(self.payroll()).data["advance_deductions"]), Decimal("0"))

    def test_edited_deductions_do_not_count_as_advance_repayment(self):
        advance = self.advance()
        payroll = self.payroll()
        self.calculate(payroll)
        Payroll.objects.filter(pk=payroll.pk).update(deductions="0", status="paid")
        detail = self.client.get(f"/api/salary-advances/{advance['id']}/").data
        self.assertEqual(Decimal(detail["total_repaid"]), Decimal("0"))
        self.assertEqual(detail["repayments"][0]["state"], "not_applied")


class AssetIncidentTests(PayrollFeatureTestCase):
    def incident(self, **changes):
        payload = {"employee": self.employee.pk, "asset_name": "Laptop", "asset_tag": "LT-01",
                   "incident_type": "damaged", "incident_date": "2026-09-10",
                   "description": "Screen cracked", "estimated_loss": "400000", "currency": "RWF", **changes}
        return self.client.post("/api/asset-incidents/", payload, format="multipart")

    def test_incident_lifecycle_with_evidence(self):
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            created = self.incident(evidence=SimpleUploadedFile("photo.png", b"png-bytes", content_type="image/png"))
            self.assertEqual(created.status_code, 201, created.data)
            self.assertEqual(created.data["status"], "reported")
            self.assertTrue(created.data["evidence_name"].endswith(".png"))
            download = self.client.get(f"/api/asset-incidents/{created.data['id']}/evidence/")
            self.assertEqual(download.status_code, 200)
            self.assertEqual(download["Cache-Control"], "private, no-store")
            download.close()

            pk = created.data["id"]
            review = self.client.patch(f"/api/asset-incidents/{pk}/", {
                "status": "under_review", "investigation_findings": "Dropped in transit",
                "employee_response": "It fell from the desk"}, format="json")
            self.assertEqual(review.status_code, 200, review.data)
            no_resolution = self.client.patch(f"/api/asset-incidents/{pk}/", {"status": "resolved"}, format="json")
            self.assertEqual(no_resolution.status_code, 400)
            resolved = self.client.patch(f"/api/asset-incidents/{pk}/", {
                "status": "resolved", "resolution": "Repaired by vendor"}, format="json")
            self.assertEqual(resolved.status_code, 200, resolved.data)
            self.assertIsNotNone(resolved.data["resolved_at"])
            self.assertEqual(self.client.delete(f"/api/asset-incidents/{pk}/").status_code, 400)
            closed = self.client.patch(f"/api/asset-incidents/{pk}/", {"status": "closed"}, format="json")
            self.assertEqual(closed.status_code, 200, closed.data)
            locked = self.client.patch(f"/api/asset-incidents/{pk}/", {"description": "Changed"}, format="json")
            self.assertEqual(locked.status_code, 400)

    def test_incident_validation(self):
        self.assertEqual(self.incident(incident_date="2999-01-01").status_code, 400)
        self.assertEqual(self.incident(recovery_amount="500000").status_code, 400)
        self.assertEqual(self.incident(recovery_amount="1000").status_code, 400)
        allowed = self.incident(recovery_amount="1000", recovery_authorization="Signed employee agreement 12/09")
        self.assertEqual(allowed.status_code, 201, allowed.data)
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            bad = self.incident(evidence=SimpleUploadedFile("run.exe", b"x", content_type="application/octet-stream"))
            self.assertEqual(bad.status_code, 400)

    def test_recorded_incidents_are_recovered_and_history_is_summarised(self):
        self.incident(recovery_amount="1000", recovery_authorization="Court order 4/2026")
        self.incident(asset_name="Phone", estimated_loss="100000")
        payroll = self.payroll()
        data = self.calculate(payroll).data
        self.assertEqual([(line["kind"], Decimal(line["amount"])) for line in data["lines"]],
                         [("asset", Decimal("1000")), ("asset", Decimal("98990"))])
        self.assertEqual(Decimal(data["total_deductions"]), Decimal("99990"))

        summary = self.client.get("/api/asset-incidents/summary/").data
        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0]["incidents"], 2)
        self.assertEqual(summary[0]["open_incidents"], 2)
        self.assertEqual(Decimal(summary[0]["total_loss"]), Decimal("500000"))
        self.assertEqual(Decimal(summary[0]["total_recovery"]), Decimal("1000"))

    def test_simplified_form_fills_in_date_status_and_currency(self):
        created = self.client.post("/api/asset-incidents/", {
            "employee": self.employee.pk, "asset_name": "Projector", "incident_type": "lost",
            "estimated_loss": "0", "description": "Missing after the workshop"}, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["incident_date"], str(timezone.localdate()))
        self.assertEqual(created.data["status"], "reported")
        self.assertEqual(created.data["currency"], "RWF")
        self.assertEqual(created.data["asset_tag"], "")
        self.assertEqual(created.data["reported_by"], self.employer.username)
        forced = self.incident(status="closed", resolution="Done")
        self.assertEqual(forced.status_code, 201, forced.data)
        self.assertEqual(forced.data["status"], "reported")

    def test_simplified_form_still_requires_core_fields_and_scopes_employees(self):
        base = {"employee": self.employee.pk, "asset_name": "Projector", "incident_type": "lost",
                "estimated_loss": "0", "description": "Missing"}
        for field in ("employee", "asset_name", "description"):
            payload = {key: value for key, value in base.items() if key != field}
            self.assertEqual(self.client.post("/api/asset-incidents/", payload, format="json").status_code, 400, field)
        self.assertEqual(self.client.post("/api/asset-incidents/", {**base, "estimated_loss": "-1"},
                                          format="json").status_code, 400)
        _, rival = self.make_business("Rival Ltd", "rival")
        self.client.force_authenticate(rival)
        self.assertEqual(self.client.post("/api/asset-incidents/", base, format="json").status_code, 400)
        self.assertFalse(AssetIncident.objects.exists())

    def test_only_reported_incidents_can_be_deleted(self):
        created = self.incident()
        self.assertEqual(self.client.delete(f"/api/asset-incidents/{created.data['id']}/").status_code, 204)


class ExistingPurgeTests(PayrollFeatureTestCase):
    def test_company_purge_still_removes_everything(self):
        from .platform import purge_business

        self.advance()
        self.calculate(self.payroll())
        self.client.post("/api/asset-incidents/", {"employee": self.employee.pk, "asset_name": "Phone",
                                                   "incident_date": "2026-09-01", "description": "Lost"}, format="json")
        purge_business(self.business)
        self.assertFalse(Business.objects.filter(pk=self.business.pk).exists())
        for model in (SalaryAdvance, AdvanceRepayment, PayrollCalculation, AssetIncident):
            self.assertFalse(model.objects.exists(), model.__name__)


class ExistingPayrollTests(PayrollFeatureTestCase):
    def test_existing_payroll_endpoint_is_unchanged(self):
        response = self.client.post("/api/payroll/", {
            "employee": self.employee.pk, "period_start": "2026-09-01", "period_end": "2026-09-30",
            "base_salary": "10000.00", "allowances": "500.00", "deductions": "1500.00", "currency": "RWF"},
            format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Decimal(response.data["deductions"]), Decimal("1500.00"))
        self.assertNotIn("calculation", response.data)
        self.assertFalse(PayrollCalculation.objects.exists())
        listing = self.client.get("/api/payroll/")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(set(listing.data[0]), set(response.data))

        paid = self.client.patch(f"/api/payroll/{response.data['id']}/", {
            "status": "paid", "paid_date": str(timezone.localdate())}, format="json")
        self.assertEqual(paid.status_code, 200, paid.data)
        self.assertEqual(Decimal(paid.data["deductions"]), Decimal("1500.00"))


class EmployeePayrollTests(PayrollFeatureTestCase):
    def setUp(self):
        super().setUp()
        self.salary = Salary.objects.create(employee=self.employee, monthly_amount=Decimal("300000"),
                                            effective_date="2026-09-01")
        self.worker = self.employee.account.user

    def as_worker(self):
        self.client.force_authenticate(self.worker)

    def as_employer(self):
        self.client.force_authenticate(self.employer)

    def request_advance(self, amount="50000", reason="Rent"):
        return self.client.post("/api/me/salary-advance-requests/", {"amount": amount, "reason": reason}, format="json")

    def test_employee_sees_salary_history_deductions_and_payslips(self):
        self.advance(amount="100000", installment="40000")
        self.assertEqual(self.client.post(f"/api/salaries/{self.salary.pk}/mark_paid/", {"month": "2026-09"},
                                          format="json").status_code, 201)
        self.payroll(start="2026-10-01", end="2026-10-31")

        self.as_worker()
        response = self.client.get("/api/me/payroll/")
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data
        self.assertEqual(Decimal(data["salary"]["monthly_amount"]), Decimal("300000"))
        months = {row["month"]: row for row in data["months"]}
        self.assertEqual(months["2026-09"]["status"], "paid")
        self.assertEqual(Decimal(months["2026-09"]["advance_deductions"]), Decimal("40000"))
        self.assertEqual(Decimal(months["2026-09"]["net_salary"]), Decimal("260000"))
        self.assertEqual(months["2026-10"]["status"], "unpaid")
        self.assertIsNone(months["2026-10"]["net_salary"])
        self.assertEqual(len(data["payslips"]), 1)
        payslip = data["payslips"][0]
        self.assertEqual(payslip["id"], months["2026-09"]["payroll"])
        self.assertEqual([(line["kind"], Decimal(line["amount"])) for line in payslip["lines"]],
                         [("advance", Decimal("40000"))])
        self.assertNotIn("notes", payslip)
        self.assertEqual(Decimal(data["advances"][0]["outstanding_balance"]), Decimal("60000"))

    def test_employee_request_is_approved_and_deducted_automatically(self):
        self.as_worker()
        created = self.request_advance()
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual((created.data["status"], created.data["currency"]), ("pending", "RWF"))
        self.assertEqual(self.request_advance("1000").status_code, 400)
        self.assertFalse(SalaryAdvance.objects.exists())

        self.as_employer()
        listing = self.client.get("/api/salary-advance-requests/").data
        self.assertEqual([row["employee_name"] for row in listing], ["Aline Uwase"])
        approved = self.client.post(f"/api/salary-advance-requests/{created.data['id']}/approve/", {}, format="json")
        self.assertEqual(approved.status_code, 200, approved.data)
        self.assertEqual(approved.data["status"], "approved")
        advance = SalaryAdvance.objects.get()
        self.assertEqual(approved.data["advance"], advance.pk)
        self.assertEqual((advance.amount, advance.installment_amount, advance.issue_date, advance.reason),
                         (Decimal("50000.00"), Decimal("50000.00"), timezone.localdate(), "Rent"))
        self.assertEqual(self.client.post(f"/api/salary-advance-requests/{created.data['id']}/approve/", {},
                                          format="json").status_code, 400)
        self.assertTrue(self.client.get(f"/api/salary-advances/{advance.pk}/").data["from_request"])
        self.assertEqual(self.client.patch(f"/api/salary-advances/{advance.pk}/", {"amount": "1000"},
                                           format="json").status_code, 400)
        self.assertEqual(self.client.delete(f"/api/salary-advances/{advance.pk}/").status_code, 400)
        month = str(timezone.localdate())[:7]
        preview = self.client.get(f"/api/salaries/{self.salary.pk}/payment_preview/", {"month": month}).data
        self.assertEqual(Decimal(preview["advance_deductions"]), Decimal("50000"))

        self.as_worker()
        data = self.client.get("/api/me/payroll/").data
        self.assertEqual(data["requests"][0]["status"], "approved")
        self.assertTrue(data["requests"][0]["decided_by"])
        self.assertIsNotNone(data["requests"][0]["decided_at"])
        self.assertEqual(Decimal(data["advances"][0]["amount"]), Decimal("50000"))
        self.assertEqual(self.client.delete(f"/api/me/salary-advance-requests/{created.data['id']}/").status_code, 400)

    def test_rejection_cancellation_and_access_rules(self):
        self.as_worker()
        first = self.request_advance()
        self.assertEqual(self.client.delete(f"/api/me/salary-advance-requests/{first.data['id']}/").status_code, 204)
        second = self.request_advance("20000")
        self.assertEqual(self.request_advance("0").status_code, 400)
        self.assertEqual(self.client.get("/api/salary-advance-requests/").status_code, 403)

        _, rival = self.make_business("Rival Ltd", "rival")
        self.client.force_authenticate(rival)
        self.assertEqual(self.client.get("/api/salary-advance-requests/").data, [])
        self.assertEqual(self.client.post(f"/api/salary-advance-requests/{second.data['id']}/approve/", {},
                                          format="json").status_code, 404)
        self.assertEqual(self.client.get("/api/me/payroll/").status_code, 403)

        other = self.make_employee(self.business, "bosco@example.com", "Bosco", "Habimana")
        self.client.force_authenticate(other.account.user)
        self.assertEqual(self.client.delete(f"/api/me/salary-advance-requests/{second.data['id']}/").status_code, 403)
        self.assertEqual(self.request_advance().status_code, 400)

        self.as_employer()
        rejected = self.client.post(f"/api/salary-advance-requests/{second.data['id']}/reject/",
                                    {"decision_notes": "Budget closed this month"}, format="json")
        self.assertEqual(rejected.status_code, 200, rejected.data)
        self.assertFalse(SalaryAdvance.objects.exists())
        self.as_worker()
        request = self.client.get("/api/me/payroll/").data["requests"][0]
        self.assertEqual((request["status"], request["decision_notes"]), ("rejected", "Budget closed this month"))
        self.assertEqual(SalaryAdvanceRequest.objects.count(), 1)