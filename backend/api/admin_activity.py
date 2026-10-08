"""How much each workspace is used, for the platform administrator. Counts only.

These summaries show that work is happening, not what it contains: no pay
amounts, advances, asset incidents, leave reasons, contract text or signatures,
locations or personal contact details. The records themselves are read through
admin_records. Every figure is a count of live rows.
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (Announcement, Attendance, Business, CalendarEvent, Contract, Employee,
                     LeaveRequest, Payroll, WorkplaceLocation)
from .permissions import IsAdmin
from .platform import _company, account_status
from .schema import RESPONSE_403_ADMIN, with_errors

UPCOMING_DAYS = 30


def activity_counts(business_id=None):
    """Today's activity across the platform, or inside one company."""
    today = timezone.localdate()
    first_of_month = today.replace(day=1)
    owned = {} if business_id is None else {"business_id": business_id}
    staff = {} if business_id is None else {"employee__business_id": business_id}
    checked_in = Attendance.objects.filter(date=today, check_in_at__isnull=False, **staff)
    contracts = Contract.objects.filter(**staff)
    return {
        "checked_in_today": checked_in.values("employee").distinct().count(),
        "on_shift_now": Attendance.objects.filter(
            date__gte=today - timedelta(days=1), check_in_at__isnull=False, check_out_at__isnull=True,
            **staff).values("employee").distinct().count(),
        "shifts_completed_today": checked_in.filter(check_out_at__isnull=False).count(),
        "on_leave_today": LeaveRequest.objects.filter(
            status="approved", start_date__lte=today, end_date__gte=today, **staff,
        ).values("employee").distinct().count(),
        "leave_requests_pending": LeaveRequest.objects.filter(status="pending", **staff).count(),
        "contracts_active": contracts.filter(status="active", signature_status="signed").count(),
        "contracts_awaiting_signature": contracts.filter(signature_status="sent").count(),
        "payslips_this_month": Payroll.objects.filter(
            status="paid", paid_date__gte=first_of_month, **staff).count(),
        "announcements_this_month": Announcement.objects.filter(
            published_at__date__gte=first_of_month, **owned).count(),
        "upcoming_events": CalendarEvent.objects.filter(
            date__gte=today, date__lte=today + timedelta(days=UPCOMING_DAYS), **owned).count(),
    }


class ActivityCountsSerializer(serializers.Serializer):
    checked_in_today = serializers.IntegerField(help_text="Employees who checked in today.")
    on_shift_now = serializers.IntegerField(help_text="Employees checked in and not yet checked out.")
    shifts_completed_today = serializers.IntegerField()
    on_leave_today = serializers.IntegerField(help_text="Employees on approved leave today.")
    leave_requests_pending = serializers.IntegerField()
    contracts_active = serializers.IntegerField(help_text="Signed contracts that are in force.")
    contracts_awaiting_signature = serializers.IntegerField()
    payslips_this_month = serializers.IntegerField(help_text="Salaries recorded as paid this month. No amounts.")
    announcements_this_month = serializers.IntegerField()
    upcoming_events = serializers.IntegerField(help_text=f"Calendar events in the next {UPCOMING_DAYS} days.")


class PlatformActivitySerializer(serializers.Serializer):
    date = serializers.DateField()
    counts = ActivityCountsSerializer()
    companies_with_workplace_location = serializers.IntegerField()


class DepartmentCountSerializer(serializers.Serializer):
    name = serializers.CharField()
    employees = serializers.IntegerField(help_text="Active employees in this department.")


class CompanyActivitySerializer(serializers.Serializer):
    date = serializers.DateField()
    company = serializers.DictField(help_text="The company as the Companies list shows it.")
    counts = ActivityCountsSerializer()
    departments = DepartmentCountSerializer(many=True)
    workplace_location_set = serializers.BooleanField()


TODAY_STATES = ["on_shift", "checked_out", "on_leave", "not_checked_in"]


def employee_today(employee, today):
    shifts = Attendance.objects.filter(employee=employee, date__gte=today - timedelta(days=1),
                                       check_in_at__isnull=False)
    if shifts.filter(check_out_at__isnull=True).exists():
        return "on_shift"
    if shifts.filter(date=today).exists():
        return "checked_out"
    if LeaveRequest.objects.filter(employee=employee, status="approved", start_date__lte=today,
                                   end_date__gte=today).exists():
        return "on_leave"
    return "not_checked_in"


def employee_details(employee):
    today = timezone.localdate()
    first_of_month = today.replace(day=1)
    first_of_year = today.replace(month=1, day=1)
    account = getattr(employee, "account", None)
    month = Attendance.objects.filter(employee=employee, date__gte=first_of_month).exclude(status="absent")
    leave = LeaveRequest.objects.filter(employee=employee, start_date__gte=first_of_year)
    contract = employee.contracts.order_by("-start_date", "-id").first()
    return {
        "date": today,
        "employee": {
            "id": employee.pk, "first_name": employee.first_name, "last_name": employee.last_name,
            "email": employee.email, "business": employee.business_id,
            "business_name": employee.business.name if employee.business_id else "",
            "job_title": employee.job_title, "department": employee.department,
            "employment_type": employee.employment_type, "date_joined": employee.date_joined,
            "manager_name": employee.manager_name, "is_active": employee.is_active,
            "account_status": account_status(employee),
            "username": account.user.username if account else "",
            "last_login_at": account.user.last_login if account else None,
        },
        "today": employee_today(employee, today),
        "days_worked_this_month": month.values("date").distinct().count(),
        "hours_worked_this_month": f"{month.aggregate(total=Sum('hours_worked'))['total'] or Decimal('0'):.2f}",
        "leave_requests_this_year": {
            "approved": leave.filter(status="approved").count(),
            "pending": leave.filter(status="pending").count(),
            "rejected": leave.filter(status="rejected").count(),
        },
        "contract": None if contract is None else {
            "title": contract.title, "status": contract.get_status_display(),
            "signature": contract.get_signature_status_display(),
            "worker_approved": contract.worker_approval_status == "approved",
            "start_date": contract.start_date, "end_date": contract.end_date,
        },
        "payslips_this_year": Payroll.objects.filter(employee=employee, status="paid",
                                                     paid_date__gte=first_of_year).count(),
    }


class AdminEmployeeWorkSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    email = serializers.EmailField()
    business = serializers.IntegerField(allow_null=True)
    business_name = serializers.CharField(allow_blank=True)
    job_title = serializers.CharField()
    department = serializers.CharField(allow_blank=True)
    employment_type = serializers.CharField()
    date_joined = serializers.DateField()
    manager_name = serializers.CharField(allow_blank=True)
    is_active = serializers.BooleanField()
    account_status = serializers.ChoiceField(choices=["none", "pending_first_sign_in", "active"])
    username = serializers.CharField(allow_blank=True)
    last_login_at = serializers.DateTimeField(allow_null=True)


class LeaveRequestCountsSerializer(serializers.Serializer):
    approved = serializers.IntegerField()
    pending = serializers.IntegerField()
    rejected = serializers.IntegerField()


class ContractSummarySerializer(serializers.Serializer):
    title = serializers.CharField()
    status = serializers.CharField()
    signature = serializers.CharField()
    worker_approved = serializers.BooleanField()
    start_date = serializers.DateField()
    end_date = serializers.DateField(allow_null=True)


class EmployeeActivitySerializer(serializers.Serializer):
    date = serializers.DateField()
    employee = AdminEmployeeWorkSerializer()
    today = serializers.ChoiceField(choices=TODAY_STATES)
    days_worked_this_month = serializers.IntegerField()
    hours_worked_this_month = serializers.CharField(help_text="2-decimal string.")
    leave_requests_this_year = LeaveRequestCountsSerializer()
    contract = ContractSummarySerializer(allow_null=True, help_text="The latest contract's status only, never its text.")
    payslips_this_year = serializers.IntegerField(help_text="Salaries recorded as paid this year. No amounts.")


@extend_schema(tags=["Platform administration"], summary="One employee's work details",
               description="Work details and activity counts. Never pay amounts, leave reasons, "
                           "contract text, locations or personal contact details.",
               parameters=[OpenApiParameter("pk", int, OpenApiParameter.PATH, description="Employee id.")],
               responses=with_errors({200: EmployeeActivitySerializer}, forbidden=RESPONSE_403_ADMIN,
                                     bad_request=False, not_found=True))
class AdminEmployeeActivityView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request, pk):
        employee = Employee.objects.select_related("business", "account__user").filter(pk=pk).first()
        if employee is None:
            raise NotFound("That employee was not found.")
        return Response(employee_details(employee))


@extend_schema(tags=["Platform administration"], summary="Activity across every company",
               description="How much the platform is being used today, as counts only.",
               responses=with_errors({200: PlatformActivitySerializer}, forbidden=RESPONSE_403_ADMIN,
                                     bad_request=False))
class AdminActivityView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        return Response({
            "date": timezone.localdate(),
            "counts": activity_counts(),
            "companies_with_workplace_location": WorkplaceLocation.objects.count(),
        })


@extend_schema(tags=["Platform administration"], summary="One company's activity",
               description="The company, its departments and how much its workspace is used, as "
                           "counts only.",
               parameters=[OpenApiParameter("pk", int, OpenApiParameter.PATH, description="Company id.")],
               responses=with_errors({200: CompanyActivitySerializer}, forbidden=RESPONSE_403_ADMIN,
                                     bad_request=False, not_found=True))
class AdminCompanyActivityView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request, pk):
        business = Business.objects.select_related("owner_profile__user").filter(pk=pk).first()
        if business is None:
            raise NotFound("That company was not found.")
        employees = Employee.objects.filter(business=business)
        departments = (employees.filter(is_active=True).exclude(department="")
                       .values("department").annotate(employees=Count("id")).order_by("-employees", "department"))
        return Response({
            "date": timezone.localdate(),
            "company": _company(business, employees.count(), employees.filter(is_active=True).count()),
            "counts": activity_counts(business.pk),
            "departments": [{"name": row["department"], "employees": row["employees"]} for row in departments],
            "workplace_location_set": WorkplaceLocation.objects.filter(business=business).exists(),
        })
