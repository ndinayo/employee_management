"""The employee's own payroll: salary, paid months, payslips and advance requests.

Read-only views of the employer's payroll records, plus advance requests that
the employer approves or rejects on the Salary Advances page.
"""
from django.db import transaction
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view, inline_serializer
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import payroll_rules
from .accounts import RECORD_ID, employee_record, require_signed_contract, workspace_responses
from .models import Employee, Payroll, Salary, SalaryAdvance, SalaryAdvanceRequest
from .payroll_serializers import MyPayslipSerializer, MyAdvanceRequestSerializer
from .views import PAYMENT_BREAKDOWN_FIELDS, SalaryViewSet

TAGS = ["Employee workspace"]
MONEY = {"max_digits": 14, "decimal_places": 2}


def my_employee(request):
    employee = employee_record(request.user)
    if not employee:
        raise PermissionDenied("Your account is not linked to an employee record.")
    return require_signed_contract(employee)


def advance_summary(advance):
    figures = payroll_rules.advance_figures(advance)
    return {"id": advance.pk, "amount": str(advance.amount), "currency": advance.currency,
            "issue_date": advance.issue_date, "status": figures["status"],
            "total_repaid": str(figures["total_repaid"]), "outstanding_balance": str(figures["outstanding_balance"]),
            "next_installment": str(figures["next_installment"])}


@extend_schema(
    tags=TAGS, summary="Read your payroll",
    description="Your current salary, one row per month since it took effect (paid months carry the saved "
                "breakdown; months not yet paid carry none), your payslips, your salary advances and your "
                "advance requests. Draft payroll the employer is still preparing is not shown.",
    responses=workspace_responses({200: inline_serializer(name="MyPayroll", fields={
        "salary": inline_serializer(name="MySalary", allow_null=True, fields={
            "monthly_amount": serializers.DecimalField(**MONEY), "currency": serializers.CharField(),
            "effective_date": serializers.DateField()}),
        "months": inline_serializer(name="MyPaymentMonth", many=True, fields={
            "month": serializers.CharField(), **PAYMENT_BREAKDOWN_FIELDS}),
        "payslips": MyPayslipSerializer(many=True),
        "advances": inline_serializer(name="MySalaryAdvance", many=True, fields={
            "id": serializers.IntegerField(), "amount": serializers.DecimalField(**MONEY),
            "currency": serializers.CharField(), "issue_date": serializers.DateField(),
            "status": serializers.CharField(), "total_repaid": serializers.DecimalField(**MONEY),
            "outstanding_balance": serializers.DecimalField(**MONEY),
            "next_installment": serializers.DecimalField(**MONEY)}),
        "requests": MyAdvanceRequestSerializer(many=True),
    })}, bad_request=False),
)
class MyPayrollView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        employee = my_employee(request)
        salary = Salary.objects.filter(employee=employee).first()
        payslips = (Payroll.objects.filter(employee=employee, status="paid").select_related("calculation", "contract")
                    .prefetch_related("calculation__lines").order_by("-period_start"))
        advances = SalaryAdvance.objects.filter(employee=employee).prefetch_related("repayments__payroll__calculation")
        months = SalaryViewSet.monthly_payments(employee, salary.effective_date, paid_only=True) if salary else [
            {"month": f"{row.period_start:%Y-%m}", **SalaryViewSet.saved_payment(row)} for row in payslips]
        return Response({
            "salary": {"monthly_amount": str(salary.monthly_amount), "currency": salary.currency,
                       "effective_date": salary.effective_date} if salary else None,
            "months": months,
            "payslips": MyPayslipSerializer(payslips, many=True).data,
            "advances": [advance_summary(advance) for advance in advances],
            "requests": MyAdvanceRequestSerializer(
                SalaryAdvanceRequest.objects.filter(employee=employee), many=True).data,
        })


@extend_schema(tags=TAGS)
@extend_schema_view(post=extend_schema(
    summary="Request a salary advance",
    description="Sent to your employer as `pending`. Once approved it becomes a salary advance that is "
                "deducted automatically from your salary. Only one request can be pending at a time, and "
                "your employer must have set your salary first.",
    request=MyAdvanceRequestSerializer,
    responses=workspace_responses({201: MyAdvanceRequestSerializer}),
))
class MySalaryAdvanceRequestsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        employee = my_employee(request)
        if not employee.is_active:
            raise PermissionDenied("Your employee profile is inactive.")
        salary = Salary.objects.filter(employee=employee).first()
        if not salary:
            raise serializers.ValidationError("Your employer has not set your salary yet, so an advance cannot be requested.")
        serializer = MyAdvanceRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            Employee.objects.select_for_update().filter(pk=employee.pk).first()
            if SalaryAdvanceRequest.objects.filter(employee=employee, status="pending").exists():
                raise serializers.ValidationError(
                    "You already have a pending advance request. Wait for your employer's decision or cancel it first.")
            record = serializer.save(employee=employee, currency=salary.currency, status="pending")
        return Response(MyAdvanceRequestSerializer(record).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=TAGS, parameters=[RECORD_ID])
@extend_schema_view(delete=extend_schema(
    summary="Cancel your pending salary advance request",
    description="Only a request still in `pending` can be cancelled.",
    responses=workspace_responses({204: OpenApiResponse(description="Cancelled. No body.")}),
))
class MySalaryAdvanceRequestDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        employee = my_employee(request)
        with transaction.atomic():
            record = SalaryAdvanceRequest.objects.select_for_update().filter(pk=pk, employee=employee).first()
            if not record:
                raise PermissionDenied("You cannot access this advance request.")
            if record.status != "pending":
                raise serializers.ValidationError("Only pending requests can be cancelled.")
            record.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
