from django.contrib.auth.models import User
from django.core.validators import FileExtensionValidator
from django.db import transaction
from rest_framework import serializers
from django.utils import timezone

from .models import Employee, Contract, Attendance, LeaveRequest, Holiday, Salary, Payroll


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "password"]
        extra_kwargs = {"password": {"write_only": True}}

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class EmployeeSerializer(serializers.ModelSerializer):
    photo = serializers.ImageField(write_only=True, required=False)
    photo_name = serializers.SerializerMethodField()
    contract_document = serializers.FileField(write_only=True, required=False)
    contract_title = serializers.CharField(write_only=True, required=False, allow_blank=True)
    latest_contract = serializers.SerializerMethodField()

    def get_photo_name(self, obj):
        return obj.photo.name.rsplit("/", 1)[-1] if obj.photo else ""

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
        contract = ContractSerializer(data={
            "employee": employee.pk, "title": title or "Employment contract",
            "start_date": employee.date_joined, "status": "active", "document": document,
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
        return employee

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
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class ManagerRecordSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.__str__", read_only=True)

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


class ContractSerializer(ManagerRecordSerializer):
    document = serializers.FileField(write_only=True, required=False)
    document_name = serializers.SerializerMethodField()

    def get_document_name(self, obj):
        return obj.document.name.rsplit("/", 1)[-1] if obj.document else ""

    def validate_document(self, value):
        from django.core.validators import FileExtensionValidator
        FileExtensionValidator(["pdf", "doc", "docx"])(value)
        if value.size > 10 * 1024 * 1024:
            raise serializers.ValidationError("Contract documents must be 10 MB or smaller.")
        return value

    def validate(self, attrs):
        self.validate_dates(attrs)
        return attrs

    class Meta:
        model = Contract
        fields = "__all__"
        read_only_fields = ["created_at"]


class AttendanceSerializer(ManagerRecordSerializer):
    def validate(self, attrs):
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


class LeaveSerializer(ManagerRecordSerializer):
    def validate(self, attrs):
        self.validate_dates(attrs)
        employee = self.value(attrs, "employee")
        start, end = self.value(attrs, "start_date"), self.value(attrs, "end_date")
        status = self.value(attrs, "status", "pending")
        if start < employee.date_joined:
            raise serializers.ValidationError({"start_date": "Leave cannot precede the employee's joining date."})
        if status != "rejected":
            overlap = LeaveRequest.objects.filter(employee=employee, start_date__lte=end, end_date__gte=start).exclude(status="rejected")
            if self.instance:
                overlap = overlap.exclude(pk=self.instance.pk)
            if overlap.exists():
                raise serializers.ValidationError("This leave overlaps another pending or approved request.")
        if status == "approved" and Attendance.objects.filter(employee=employee, date__range=(start, end)).exists():
            raise serializers.ValidationError("Attendance already exists during this leave. Correct the attendance before approving it.")
        return attrs

    class Meta:
        model = LeaveRequest
        fields = "__all__"


class HolidaySerializer(serializers.ModelSerializer):
    class Meta:
        model = Holiday
        fields = "__all__"


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
