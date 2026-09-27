from calendar import monthrange
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256

from django.db import transaction
from django.db.models import Sum
from django.db.models.deletion import ProtectedError
from django.http import FileResponse, Http404
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from . import leave_management, onboarding
from .models import AccountProfile, Employee, Contract, Attendance, LeaveBalance, LeaveRequest, Holiday, Salary, Payroll
from .permissions import IsManager, business_id_for
from .serializers import (EmployeeSerializer, ContractSerializer, AttendanceSerializer,
                          LeaveBalanceSerializer, LeaveSerializer, HolidaySerializer,
                          SalarySerializer, PayrollSerializer)


class ManagerViewSet(viewsets.ModelViewSet):
    permission_classes = [IsManager]

    def get_queryset(self):
        queryset = super().get_queryset()
        field = "business_id" if queryset.model in (Employee, Holiday) else "employee__business_id"
        return queryset.filter(**{field: business_id_for(self.request.user)})

    def perform_create(self, serializer):
        if serializer.Meta.model in (Employee, Holiday):
            serializer.save(business_id=business_id_for(self.request.user))
        else:
            serializer.save()

    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError:
            raise serializers.ValidationError(
                "This employee has employment records. Mark their profile inactive to retain their history."
            )


class EmployeeViewSet(ManagerViewSet):
    queryset = Employee.objects.select_related("account").prefetch_related("contracts").order_by("last_name", "first_name", "id")
    serializer_class = EmployeeSerializer

    def perform_destroy(self, instance):
        onboarding.purge_employee(instance)

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


class ContractMessageSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=2000, required=False, allow_blank=True, trim_whitespace=True)


class ContractViewSet(ManagerViewSet):
    queryset = Contract.objects.select_related("employee").order_by("-start_date", "-id")
    serializer_class = ContractSerializer

    def perform_destroy(self, instance):
        if instance.signature_status != "draft":
            raise serializers.ValidationError("A contract cannot be deleted after it has been sent for signature.")
        super().perform_destroy(instance)

    @action(detail=True, methods=["post"], url_path="send-for-signature")
    def send_for_signature(self, request, pk=None):
        with transaction.atomic():
            # Lock only the contract row. PostgreSQL rejects FOR UPDATE when a
            # select_related() join includes Employee.business, because that
            # relationship is nullable and therefore uses an outer join.
            contract = Contract.objects.select_for_update().get(pk=self.get_object().pk)
            if contract.signature_status != "draft":
                raise serializers.ValidationError("Only a draft contract can be sent for signature.")
            if not contract.content.strip():
                raise serializers.ValidationError({"content": "Write the digital contract before sending it."})
            if not AccountProfile.objects.filter(employee=contract.employee, role="employee").exists():
                raise serializers.ValidationError("This employee does not have a linked sign-in account.")
            contract.signature_status = "sent"
            contract.sent_at = timezone.now()
            contract.content_hash = sha256(contract.content.encode("utf-8")).hexdigest()
            contract.save(update_fields=["signature_status", "sent_at", "content_hash"])
        emailed = onboarding.send_contract_notification(contract)
        if emailed:
            contract.notification_sent_at = timezone.now()
            contract.save(update_fields=["notification_sent_at"])
        data = self.get_serializer(contract).data
        data["notification"] = {
            "email_sent": emailed,
            "detail": (f"Contract sent to {contract.employee.email}." if emailed else
                       "Contract is ready in the employee dashboard, but the notification email could not be sent."),
        }
        return Response(data)

    @action(detail=True, methods=["post"], url_path="resend-signature-email")
    def resend_signature_email(self, request, pk=None):
        contract = self.get_object()
        if contract.signature_status != "sent":
            raise serializers.ValidationError("Only a contract awaiting signature can be emailed again.")
        serializer = ContractMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = serializer.validated_data.get("message", "")
        contract.employer_message = message
        contract.save(update_fields=["employer_message"])
        emailed = onboarding.send_contract_notification(contract, message)
        if not emailed:
            return Response({
                "detail": "The contract is still available in the employee dashboard, but the email could not be sent. Check the shared email settings and try again."
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        contract.notification_sent_at = timezone.now()
        contract.save(update_fields=["notification_sent_at"])
        return Response({"email_sent": True, "detail": f"Signature email sent again to {contract.employee.email}."})

    @action(detail=True, methods=["post"], url_path="request-new-signature")
    def request_new_signature(self, request, pk=None):
        serializer = ContractMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = serializer.validated_data.get("message", "")
        with transaction.atomic():
            original = Contract.objects.select_for_update().get(pk=self.get_object().pk)
            if original.signature_status != "signed":
                raise serializers.ValidationError("A new signature can only be requested for a signed contract.")
            if original.revisions.filter(signature_status="sent").exists():
                raise serializers.ValidationError(
                    "A corrected signature is already awaiting this employee. Resend that request instead."
                )
            replacement = Contract.objects.create(
                employee=original.employee,
                revision_of=original,
                employer_message=message,
                title=original.title,
                start_date=original.start_date,
                end_date=original.end_date,
                status=original.status,
                terms=original.terms,
                content=original.content,
                document=original.document.name if original.document else "",
                signature_status="sent",
                sent_at=timezone.now(),
                content_hash=sha256(original.content.encode("utf-8")).hexdigest(),
            )
        emailed = onboarding.send_contract_notification(replacement, message)
        if emailed:
            replacement.notification_sent_at = timezone.now()
            replacement.save(update_fields=["notification_sent_at"])
        data = self.get_serializer(replacement).data
        data["notification"] = {
            "email_sent": emailed,
            "detail": (f"A new signature was requested from {replacement.employee.email}." if emailed else
                       "The new signing request is in the employee dashboard, but its email could not be sent."),
        }
        return Response(data, status=status.HTTP_201_CREATED)

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


class LeaveBalanceViewSet(ManagerViewSet):
    queryset = LeaveBalance.objects.select_related("employee").order_by(
        "-year", "employee__last_name", "employee__first_name", "leave_type")
    serializer_class = LeaveBalanceSerializer

    def get_queryset(self):
        business_id = business_id_for(self.request.user)
        year = timezone.localdate().year
        for employee in Employee.objects.filter(business_id=business_id):
            leave_management.ensure_leave_balances(employee, year)
        return super().get_queryset()


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
        payroll = PayrollSerializer(context=self.get_serializer_context(), data={
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
        business_id = business_id_for(request.user)
        business_employees = Employee.objects.filter(business_id=business_id)
        employees = business_employees.filter(is_active=True, date_joined__lte=date).order_by("last_name", "first_name")
        attendance = Attendance.objects.filter(date=date, employee__in=employees).select_related("employee")
        on_leave = LeaveRequest.objects.filter(status="approved", start_date__lte=date, end_date__gte=date,
                                               employee__in=employees).select_related("employee")
        recorded_ids = set(attendance.values_list("employee_id", flat=True))
        leave_ids = set(on_leave.values_list("employee_id", flat=True))
        holidays = Holiday.objects.filter(date=date, business_id=business_id)
        working_day = date.weekday() < 5 and not holidays.exists()
        unrecorded = employees.exclude(id__in=recorded_ids | leave_ids) if working_day else employees.none()
        contracts = Contract.objects.filter(employee__in=business_employees, status="active", employee__is_active=True, end_date__range=(date, until)).select_related("employee").order_by("end_date")
        expired = Contract.objects.filter(employee__in=business_employees, status="active", employee__is_active=True, end_date__lt=date).select_related("employee").order_by("end_date")
        hours = Attendance.objects.filter(employee__in=business_employees, date__range=(month_start, date)).values(
            "employee_id", "employee__first_name", "employee__last_name"
        ).annotate(hours=Sum("hours_worked")).order_by("employee__last_name")
        totals = {}
        for item in Payroll.objects.filter(employee__in=business_employees, period_end__range=(month_start, date)):
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
            "pending_leave_count": LeaveRequest.objects.filter(employee__in=business_employees, status="pending").count(),
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
