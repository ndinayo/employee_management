from django.core.validators import FileExtensionValidator
from django.db import transaction
from django.utils.html import strip_tags
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from django.utils import timezone

from . import leave_management, onboarding
from .contract_content import sanitize_contract_html
from .models import (Employee, Contract, ContractTerminationRequest, Attendance,
                     LeaveBalance, LeaveRequest, Holiday, Announcement,
                     CalendarEvent, Salary, Payroll)
from .permissions import business_id_for
from .schema import InviteResultSerializer, LatestContractSerializer


def serializer_business_id(serializer):
    request = serializer.context.get("request")
    return business_id_for(request.user) if request else None


class EmployeeSerializer(serializers.ModelSerializer):
    photo = serializers.ImageField(write_only=True, required=False)
    photo_name = serializers.SerializerMethodField()
    contract_document = serializers.FileField(write_only=True, required=False)
    contract_title = serializers.CharField(write_only=True, required=False, allow_blank=True)
    latest_contract = serializers.SerializerMethodField()
    # Only names, job title and email are asked of the employer. The employee
    # fills in the rest from their own workspace.
    email = serializers.EmailField(max_length=254)
    department = serializers.CharField(max_length=100, required=False, allow_blank=True)
    date_joined = serializers.DateField(required=False, default=timezone.localdate)
    account_status = serializers.SerializerMethodField()
    invite = serializers.SerializerMethodField()

    @extend_schema_field(serializers.ChoiceField(
        choices=["none", "pending_first_sign_in", "active"],
        help_text="Whether this employee has a sign-in account yet, and whether they have used it."))
    def get_account_status(self, obj):
        account = getattr(obj, "account", None)
        if not account:
            return "none"
        return "pending_first_sign_in" if account.must_change_password else "active"

    @extend_schema_field(InviteResultSerializer(allow_null=True))
    def get_invite(self, obj):
        # Only ever populated on the response to the request that hired them.
        return getattr(obj, "_invite", None)

    def validate_email(self, value):
        duplicate = Employee.objects.filter(business_id=serializer_business_id(self), email__iexact=value)
        if self.instance:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise serializers.ValidationError("An employee with this email already exists in your business.")
        return value

    @extend_schema_field(OpenApiTypes.STR)
    def get_photo_name(self, obj):
        return obj.photo.name.rsplit("/", 1)[-1] if obj.photo else ""

    @extend_schema_field(LatestContractSerializer(allow_null=True))
    def get_latest_contract(self, obj):
        # Highest pk wins so a later upload still wins even if it reused the
        # joining date. Walk the prefetch cache instead of issuing a new query.
        contract = None
        for item in obj.contracts.all():
            if item.document and (contract is None or item.pk > contract.pk):
                contract = item
        if not contract:
            return None
        return {
            "id": contract.id, "employee": obj.id, "employee_name": str(obj),
            "title": contract.title, "document_name": contract.document.name.rsplit("/", 1)[-1],
            "start_date": contract.start_date, "end_date": contract.end_date, "status": contract.status,
        }

    def validate_photo(self, value):
        # The declared ImageField replaces the model field, so its extension
        # validator has to be applied here the way contract documents do it.
        FileExtensionValidator(["jpg", "jpeg", "png", "webp"])(value)
        if value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("Profile photos must be 5 MB or smaller.")
        return value

    def attach_contract(self, employee, document, title):
        """Create a contract for a document uploaded from the employee form.

        Validation and storage stay in ContractSerializer so the rules cannot
        drift from contracts created on the Contracts page.
        """
        contract = ContractSerializer(context=self.context, data={
            "employee": employee.pk, "title": title or "Employment contract",
            "department": employee.department, "start_date": employee.date_joined,
            "status": "active", "document": document,
        })
        contract.is_valid(raise_exception=True)
        contract.save()

    def pop_contract(self, validated_data):
        return validated_data.pop("contract_document", None), validated_data.pop("contract_title", "")

    def create(self, validated_data):
        document, title = self.pop_contract(validated_data)
        with transaction.atomic():
            employee = super().create(validated_data)
            if document:
                self.attach_contract(employee, document, title)
                employee = Employee.objects.prefetch_related("contracts").get(pk=employee.pk)
            employee._invite = self.open_account(employee)
        return employee

    def open_account(self, employee):
        """Create the employee's sign-in account and email their password.

        A failed send still leaves a usable account, so the employer is told
        what happened and can pass the password on themselves.
        """
        if onboarding.email_is_taken(employee.email) and not onboarding.reclaim_email(employee.email, employee):
            return {"created": False, "email_sent": False,
                    "detail": "An account already uses this email address, so no new sign-in was created."}
        user, password = onboarding.provision_account(employee)
        sent = onboarding.send_invite(employee, user, password)
        if sent:
            detail = f"Sign-in details were emailed to {employee.email}."
        elif onboarding.can_deliver(employee.business):
            detail = f"The account was created but the email to {employee.email} could not be sent."
        else:
            detail = ("Email sending is not set up, so no message was sent. "
                      f"Add a Gmail App Password in Settings, or give {employee.first_name} these sign-in details yourself.")
        if employee.invite_email_failed != (not sent):
            employee.invite_email_failed = not sent
            employee.save(update_fields=["invite_email_failed"])
        invite = {"created": True, "email_sent": sent, "username": user.username, "detail": detail}
        if not sent:
            # Nothing reached the employee, so the employer is the only way in.
            invite["temporary_password"] = password
        return invite

    def update(self, instance, validated_data):
        document, title = self.pop_contract(validated_data)
        with transaction.atomic():
            employee = super().update(instance, validated_data)
            if document:
                self.attach_contract(employee, document, title)
                employee = Employee.objects.prefetch_related("contracts").get(pk=employee.pk)
        return employee

    class Meta:
        model = Employee
        fields = [
            "id",
            "first_name",
            "last_name",
            "email",
            "department",
            "job_title",
            "date_joined",
            "phone", "address", "emergency_contact", "manager_name",
            "job_description", "employment_type", "is_active",
            "photo", "photo_name",
            "contract_document", "contract_title", "latest_contract",
            "account_status", "invite",
            "created_at",
        ]
        read_only_fields = ["id", "created_at", "account_status", "invite"]
        validators = []


class ManagerRecordSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.__str__", read_only=True)

    def get_fields(self):
        fields = super().get_fields()
        if "employee" in fields:
            fields["employee"].queryset = Employee.objects.filter(business_id=serializer_business_id(self))
        return fields

    def value(self, attrs, field, default=None):
        return attrs.get(field, getattr(self.instance, field, default))

    def validate_dates(self, attrs, start="start_date", end="end_date"):
        first, last = self.value(attrs, start), self.value(attrs, end)
        if first and last and last < first:
            raise serializers.ValidationError({end: "End date must be on or after the start date."})

    def validate_currency(self, value):
        value = value.upper()
        if value not in {"RWF", "ZAR", "USD", "EUR", "GBP", "BWP", "NAD", "LSL", "SZL", "KES", "NGN"}:
            raise serializers.ValidationError("Choose a supported currency.")
        return value


class ContractTerminationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContractTerminationRequest
        fields = [
            "id", "initiated_by", "reason", "proposed_last_working_date", "status",
            "response_notes", "created_at", "responded_at",
        ]


class ContractSerializer(ManagerRecordSerializer):
    document = serializers.FileField(write_only=True, required=False)
    document_name = serializers.SerializerMethodField()
    employee_email = serializers.EmailField(source="employee.email", read_only=True)
    termination = serializers.SerializerMethodField()

    @extend_schema_field(OpenApiTypes.STR)
    def get_document_name(self, obj):
        return obj.document.name.rsplit("/", 1)[-1] if obj.document else ""

    @extend_schema_field(ContractTerminationSerializer(allow_null=True))
    def get_termination(self, obj):
        request = obj.termination_requests.order_by("-created_at", "-id").first()
        return ContractTerminationSerializer(request).data if request else None

    def validate_document(self, value):
        from django.core.validators import FileExtensionValidator
        FileExtensionValidator(["pdf", "doc", "docx"])(value)
        if value.size > 10 * 1024 * 1024:
            raise serializers.ValidationError("Contract documents must be 10 MB or smaller.")
        return value

    def validate(self, attrs):
        if self.instance and self.instance.signature_status != "draft":
            raise serializers.ValidationError("A contract cannot be edited after it has been sent for signature.")
        self.validate_dates(attrs)
        return attrs

    def validate_content(self, value):
        clean = sanitize_contract_html(value)
        if len(strip_tags(clean)) > 100_000:
            raise serializers.ValidationError("Contract text must be 100,000 characters or fewer.")
        return clean

    def create(self, validated_data):
        contract = super().create(validated_data)
        if contract.department and contract.employee.department != contract.department:
            contract.employee.department = contract.department
            contract.employee.save(update_fields=["department"])
        return contract

    def update(self, instance, validated_data):
        contract = super().update(instance, validated_data)
        if contract.department and contract.employee.department != contract.department:
            contract.employee.department = contract.department
            contract.employee.save(update_fields=["department"])
        return contract

    class Meta:
        model = Contract
        fields = [
            "id", "employee", "employee_name", "employee_email", "revision_of", "employer_message", "title", "department", "start_date", "end_date", "status",
            "terms", "content", "document", "document_name", "signature_status", "sent_at",
            "notification_sent_at", "signed_at", "signer_name", "signature_data", "worker_approval_status",
            "worker_approved_at", "worker_approved_by", "termination", "created_at",
        ]
        read_only_fields = [
            "created_at", "revision_of", "employer_message", "signature_status", "sent_at", "notification_sent_at", "signed_at", "signer_name", "signature_data",
            "worker_approval_status", "worker_approved_at", "worker_approved_by",
        ]


class AttendanceSerializer(ManagerRecordSerializer):
    def validate(self, attrs):
        if self.instance and "shift" in attrs and attrs["shift"] != self.instance.shift:
            raise serializers.ValidationError({"shift": "A recorded shift cannot be changed."})
        employee, date = self.value(attrs, "employee"), self.value(attrs, "date")
        if date < employee.date_joined:
            raise serializers.ValidationError({"date": "Attendance cannot precede the employee's joining date."})
        status = self.value(attrs, "status", "present")
        if status == "absent" and self.value(attrs, "hours_worked", 0) != 0:
            raise serializers.ValidationError({"hours_worked": "Absent employees must have zero working hours."})
        if LeaveRequest.objects.filter(employee=employee, status="approved", start_date__lte=date, end_date__gte=date).exists():
            raise serializers.ValidationError("This employee has approved leave on this date. Update the leave before recording attendance.")
        return attrs

    class Meta:
        model = Attendance
        fields = "__all__"
        read_only_fields = ["check_in_at", "check_out_at"]


class LeaveSerializer(ManagerRecordSerializer):
    days_requested = serializers.SerializerMethodField()

    @extend_schema_field(serializers.FloatField(
        help_text="Monday-Friday days in the period, excluding this business's holidays."))
    def get_days_requested(self, obj):
        return leave_management.leave_days(obj.employee, obj.start_date, obj.end_date)

    def validate(self, attrs):
        if self.instance:
            protected = {"employee", "leave_type", "start_date", "end_date", "reason"}
            attempted = protected.intersection(attrs)
            if attempted:
                raise serializers.ValidationError(
                    "Employers cannot edit an employee's leave request. They may only approve or reject it.")
            next_status = attrs.get("status", self.instance.status)
            if self.instance.status != "pending" and next_status != self.instance.status:
                raise serializers.ValidationError("A completed leave decision cannot be changed.")
        self.validate_dates(attrs)
        employee = self.value(attrs, "employee")
        start, end = self.value(attrs, "start_date"), self.value(attrs, "end_date")
        status = self.value(attrs, "status", "pending")
        leave_type = self.value(attrs, "leave_type", "annual")
        if start < employee.date_joined:
            raise serializers.ValidationError({"start_date": "Leave cannot precede the employee's joining date."})
        if start.year != end.year:
            raise serializers.ValidationError({"end_date": "A leave request must stay within one calendar year."})
        requested = leave_management.leave_days(employee, start, end)
        if requested <= 0:
            raise serializers.ValidationError("This period contains no working days.")
        if status != "rejected":
            overlap = LeaveRequest.objects.filter(employee=employee, start_date__lte=end, end_date__gte=start).exclude(status="rejected")
            if self.instance:
                overlap = overlap.exclude(pk=self.instance.pk)
            if overlap.exists():
                raise serializers.ValidationError("This leave overlaps another pending or approved request.")
        if status == "approved" and Attendance.objects.filter(employee=employee, date__range=(start, end)).exists():
            raise serializers.ValidationError("Attendance already exists during this leave. Correct the attendance before approving it.")
        # Legacy records may still carry an older leave category. They remain
        # reviewable, but only the four current categories affect balances.
        if status == "approved" and leave_type in leave_management.LEAVE_TYPES and leave_type != "unpaid":
            balance = next(item for item in leave_management.ensure_leave_balances(employee, start.year)
                           if item.leave_type == leave_type)
            available = balance.days_allocated - leave_management.used_days(
                employee, leave_type, start.year, exclude=self.instance.pk if self.instance else None)
            if requested > available:
                raise serializers.ValidationError({
                    "status": f"Cannot approve {requested} working days; only {max(available, 0)} remain."
                })
        return attrs

    def save(self, **kwargs):
        next_status = self.validated_data.get("status", getattr(self.instance, "status", "pending"))
        previous_status = getattr(self.instance, "status", "pending")
        if next_status in {"approved", "rejected"} and next_status != previous_status:
            request = self.context.get("request")
            user = request.user if request else None
            kwargs["decided_at"] = timezone.now()
            kwargs["decided_by"] = user.get_full_name().strip() or user.username if user else "Manager"
        elif next_status == "pending" and previous_status != "pending":
            kwargs["decided_at"] = None
            kwargs["decided_by"] = ""
        return super().save(**kwargs)

    class Meta:
        model = LeaveRequest
        fields = "__all__"
        read_only_fields = ["requested_at", "decided_at", "decided_by"]


class LeaveBalanceSerializer(ManagerRecordSerializer):
    used_days = serializers.SerializerMethodField()
    remaining_days = serializers.SerializerMethodField()
    unlimited = serializers.SerializerMethodField()

    def summary(self, obj):
        if not hasattr(obj, "_balance_summary"):
            obj._balance_summary = leave_management.balance_summary(obj)
        return obj._balance_summary

    @extend_schema_field(serializers.FloatField(
        help_text="Working days already taken under approved requests this year."))
    def get_used_days(self, obj):
        return self.summary(obj)["used_days"]

    @extend_schema_field(serializers.FloatField(
        allow_null=True, help_text="`days_allocated` minus `used_days`, or null for unpaid leave."))
    def get_remaining_days(self, obj):
        return self.summary(obj)["remaining_days"]

    @extend_schema_field(serializers.BooleanField(
        help_text="True for unpaid leave, which is not capped by an allocation."))
    def get_unlimited(self, obj):
        return self.summary(obj)["unlimited"]

    def validate_year(self, value):
        if not 2000 <= value <= 2100:
            raise serializers.ValidationError("Choose a year between 2000 and 2100.")
        return value

    class Meta:
        model = LeaveBalance
        fields = ["id", "employee", "employee_name", "leave_type", "year", "days_allocated",
                  "used_days", "remaining_days", "unlimited"]
        read_only_fields = ["used_days", "remaining_days", "unlimited"]


class HolidaySerializer(serializers.ModelSerializer):
    def validate_date(self, value):
        duplicate = Holiday.objects.filter(business_id=serializer_business_id(self), date=value)
        if self.instance:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise serializers.ValidationError("A holiday already exists on this date in your business.")
        return value

    class Meta:
        model = Holiday
        fields = ["id", "name", "date", "notes"]
        validators = []


class AnnouncementSerializer(serializers.ModelSerializer):
    read_count = serializers.IntegerField(source="reads.count", read_only=True)

    class Meta:
        model = Announcement
        fields = ["id", "title", "message", "created_by", "published_at", "read_count"]
        read_only_fields = ["created_by", "published_at", "read_count"]


class CalendarEventSerializer(serializers.ModelSerializer):
    employee_ids = serializers.PrimaryKeyRelatedField(
        source="invited_employees", many=True, queryset=Employee.objects.none(), required=False)

    def get_fields(self):
        fields = super().get_fields()
        fields["employee_ids"].child_relation.queryset = Employee.objects.filter(
            business_id=serializer_business_id(self), is_active=True)
        return fields

    def validate(self, attrs):
        start = attrs.get("date", getattr(self.instance, "date", None))
        end = attrs.get("end_date", getattr(self.instance, "end_date", None))
        if start and end and end < start:
            raise serializers.ValidationError({"end_date": "End date must be on or after the start date."})
        start_time = attrs.get("start_time", getattr(self.instance, "start_time", None))
        end_time = attrs.get("end_time", getattr(self.instance, "end_time", None))
        if start and (not end or end == start) and start_time and end_time and end_time <= start_time:
            raise serializers.ValidationError({"end_time": "End time must be later than the start time."})
        all_employees = attrs.get("all_employees", getattr(self.instance, "all_employees", True))
        invited = attrs.get("invited_employees", None)
        has_invited = bool(invited) if invited is not None else bool(self.instance and self.instance.invited_employees.exists())
        if not all_employees and not has_invited:
            raise serializers.ValidationError({"employee_ids": "Select at least one employee."})
        return attrs

    class Meta:
        model = CalendarEvent
        fields = ["id", "title", "category", "date", "end_date", "start_time", "end_time", "location",
                  "description", "all_employees", "employee_ids", "created_by", "created_at"]
        read_only_fields = ["created_by", "created_at"]


class SalarySerializer(ManagerRecordSerializer):
    class Meta:
        model = Salary
        fields = "__all__"


class PayrollSerializer(ManagerRecordSerializer):
    employee_name = serializers.CharField(read_only=True)
    gross_pay = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    net_pay = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    def validate(self, attrs):
        if self.instance and self.instance.status == "paid":
            raise serializers.ValidationError("Paid payroll records are locked to preserve issued payslips.")
        self.validate_dates(attrs, "period_start", "period_end")
        employee = self.value(attrs, "employee")
        start, end = self.value(attrs, "period_start"), self.value(attrs, "period_end")
        overlap = Payroll.objects.filter(employee=employee, period_start__lte=end, period_end__gte=start)
        if self.instance:
            overlap = overlap.exclude(pk=self.instance.pk)
        if overlap.exists():
            raise serializers.ValidationError("A payroll record already covers part or all of this period.")
        gross = self.value(attrs, "base_salary", 0) + self.value(attrs, "allowances", 0)
        if self.value(attrs, "deductions", 0) > gross:
            raise serializers.ValidationError({"deductions": "Deductions cannot exceed gross pay."})
        paid_date = self.value(attrs, "paid_date")
        if self.value(attrs, "status", "draft") == "paid":
            if not paid_date:
                raise serializers.ValidationError({"paid_date": "Enter the payment date before marking payroll as paid."})
            if paid_date > timezone.localdate():
                raise serializers.ValidationError({"paid_date": "The payment date cannot be in the future."})
        elif paid_date:
            raise serializers.ValidationError({"paid_date": "Only paid payroll records may have a payment date."})
        return attrs

    def create(self, validated_data):
        employee = validated_data["employee"]
        return super().create({**validated_data, "employee_name": str(employee),
            "employee_email": employee.email, "department": employee.department, "job_title": employee.job_title})

    def update(self, instance, validated_data):
        employee = validated_data.get("employee", instance.employee)
        validated_data.update(employee_name=str(employee), employee_email=employee.email,
                              department=employee.department, job_title=employee.job_title)
        return super().update(instance, validated_data)

    class Meta:
        model = Payroll
        fields = "__all__"
        read_only_fields = ["employee_email", "department", "job_title", "created_at"]
