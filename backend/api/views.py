from calendar import monthrange
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.db.models.deletion import ProtectedError
from django.http import FileResponse, Http404
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Employee, Contract, Attendance, LeaveRequest, Holiday, Salary, Payroll
from .permissions import IsManager
from .serializers import (EmployeeSerializer, ContractSerializer, AttendanceSerializer,
                          LeaveSerializer, HolidaySerializer, SalarySerializer, PayrollSerializer)


class ManagerViewSet(viewsets.ModelViewSet):
    permission_classes = [IsManager]

    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError:
            raise serializers.ValidationError(
                "This employee has employment records. Mark their profile inactive to retain their history."
            )


class EmployeeViewSet(ManagerViewSet):
    queryset = Employee.objects.prefetch_related("contracts").order_by("last_name", "first_name", "id")
    serializer_class = EmployeeSerializer

    @action(detail=True, methods=["get"])
    def photo(self, request, pk=None):
        employee = self.get_object()
        if not employee.photo:
            raise Http404("No photo is attached to this profile.")
        try:
            image = employee.photo.open("rb")
        except FileNotFoundError:
            raise Http404("The profile photo could not be found.")
        response = FileResponse(image, filename=employee.photo.name.rsplit("/", 1)[-1])
        response["Cache-Control"] = "private, max-age=300"
        return response


class ContractViewSet(ManagerViewSet):
    queryset = Contract.objects.select_related("employee").order_by("-start_date", "-id")
    serializer_class = ContractSerializer

    @action(detail=True, methods=["get"])
    def document(self, request, pk=None):
        return self.document_response(as_download=True)

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        return self.document_response(as_download=False)

    def document_response(self, *, as_download):
        contract = self.get_object()
        if not contract.document:
            raise Http404("No document is attached to this contract.")
        try:
            document = contract.document.open("rb")
        except FileNotFoundError:
            raise Http404("The contract document could not be found.")
        filename = f"contract-{contract.pk}.{contract.document.name.rsplit('.', 1)[-1]}"
        response = FileResponse(document, as_attachment=as_download, filename=filename,
                                content_type=None if as_download else "application/octet-stream")
        if not as_download:
            # The app reads bytes into its own PDF renderer, without handing a
            # filename or attachment response to the browser's download handler.
            response.headers.pop("Content-Disposition", None)
        response["Cache-Control"] = "private, no-store"
        return response


class AttendanceViewSet(ManagerViewSet):
    queryset = Attendance.objects.select_related("employee").order_by("-date", "-id")
    serializer_class = AttendanceSerializer


class LeaveViewSet(ManagerViewSet):
    queryset = LeaveRequest.objects.select_related("employee").order_by("-start_date", "-id")
    serializer_class = LeaveSerializer


class HolidayViewSet(ManagerViewSet):
    queryset = Holiday.objects.order_by("-date", "-id")
    serializer_class = HolidaySerializer


class SalaryViewSet(ManagerViewSet):
    queryset = Salary.objects.select_related("employee").order_by("employee__last_name", "id")
    serializer_class = SalarySerializer

    @action(detail=True, methods=["post"])
    def mark_paid(self, request, pk=None):
        salary = self.get_object()
        if not salary.employee.is_active:
            raise serializers.ValidationError("This employee is inactive. Reactivate the profile before recording payment.")
        paid_date = request.data.get("paid_date") or timezone.localdate()
        month = request.data.get("month") or str(timezone.localdate())[:7]
        try:
            year, index = int(str(month)[:4]), int(str(month)[5:7])
            last_day = monthrange(year, index)[1]
        except (IndexError, TypeError, ValueError):
            raise serializers.ValidationError({"month": "Use a YYYY-MM month."})
        period_start, period_end = f"{year:04d}-{index:02d}-01", f"{year:04d}-{index:02d}-{last_day:02d}"
        if Payroll.objects.filter(employee=salary.employee, period_start__lte=period_end, period_end__gte=period_start).exists():
            raise serializers.ValidationError(
                {"detail": f"{salary.employee} already has a payroll record covering {month}. Open Payroll & payslips to review it."}
            )
        payroll = PayrollSerializer(data={
            "employee": salary.employee_id,
            "period_start": period_start, "period_end": period_end,
            "base_salary": salary.monthly_amount, "allowances": "0", "deductions": "0",
            "currency": salary.currency, "status": "paid", "paid_date": paid_date,
            "notes": f"Recorded from the salaries page using the monthly salary effective {salary.effective_date}.",
        })
        payroll.is_valid(raise_exception=True)
        with transaction.atomic():
            payroll.save()
        return Response(payroll.data, status=status.HTTP_201_CREATED)


class PayrollViewSet(ManagerViewSet):
    queryset = Payroll.objects.select_related("employee").order_by("-period_end", "-id")
    serializer_class = PayrollSerializer

    def perform_destroy(self, instance):
        if instance.status == "paid":
            raise serializers.ValidationError("Paid payroll records cannot be deleted.")
        super().perform_destroy(instance)


class ReportQuerySerializer(serializers.Serializer):
    date = serializers.DateField(default=timezone.localdate)
    days = serializers.IntegerField(default=30, min_value=1, max_value=365)


class ManagerReportsView(APIView):
    permission_classes = [IsManager]

    def get(self, request):
        query = ReportQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        date, days = query.validated_data["date"], query.validated_data["days"]
        until = date + timedelta(days=days)
        month_start = date.replace(day=1)
        employees = Employee.objects.filter(is_active=True, date_joined__lte=date).order_by("last_name", "first_name")
        attendance = Attendance.objects.filter(date=date, employee__in=employees).select_related("employee")
        on_leave = LeaveRequest.objects.filter(status="approved", start_date__lte=date, end_date__gte=date,
                                               employee__in=employees).select_related("employee")
        recorded_ids = set(attendance.values_list("employee_id", flat=True))
        leave_ids = set(on_leave.values_list("employee_id", flat=True))
        holidays = Holiday.objects.filter(date=date)
        working_day = date.weekday() < 5 and not holidays.exists()
        unrecorded = employees.exclude(id__in=recorded_ids | leave_ids) if working_day else employees.none()
        contracts = Contract.objects.filter(status="active", employee__is_active=True, end_date__range=(date, until)).select_related("employee").order_by("end_date")
        expired = Contract.objects.filter(status="active", employee__is_active=True, end_date__lt=date).select_related("employee").order_by("end_date")
        hours = Attendance.objects.filter(date__range=(month_start, date)).values(
            "employee_id", "employee__first_name", "employee__last_name"
        ).annotate(hours=Sum("hours_worked")).order_by("employee__last_name")
        totals = {}
        for item in Payroll.objects.filter(period_end__range=(month_start, date)):
            total = totals.setdefault(item.currency, {"currency": item.currency, "gross": Decimal("0"),
                "deductions": Decimal("0"), "net": Decimal("0"), "paid": Decimal("0"), "draft": Decimal("0")})
            total["gross"] += item.gross_pay
            total["deductions"] += item.deductions
            total["net"] += item.net_pay
            total[item.status] += item.net_pay
        return Response({
            "date": date, "contract_window_end": until, "month_start": month_start,
            "working_day": working_day, "active_employees": employees.count(),
            "departments": employees.values("department").distinct().count(),
            "present_count": attendance.filter(status__in=["present", "remote"]).count(),
            "pending_leave_count": LeaveRequest.objects.filter(status="pending").count(),
            "absent": AttendanceSerializer(attendance.filter(status="absent"), many=True).data,
            "on_leave": LeaveSerializer(on_leave, many=True).data,
            "unrecorded": EmployeeSerializer(unrecorded, many=True).data,
            "holidays": HolidaySerializer(holidays, many=True).data,
            "expiring_contracts": ContractSerializer(contracts, many=True).data,
            "expired_contracts": ContractSerializer(expired, many=True).data,
            "working_hours": [{"employee_id": row["employee_id"],
                "employee_name": f'{row["employee__first_name"]} {row["employee__last_name"]}',
                "hours": f'{row["hours"]:.2f}'} for row in hours],
            "payroll_totals": [{key: str(value) for key, value in total.items()} for total in totals.values()],
        })
