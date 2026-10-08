from decimal import Decimal

from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from . import payroll_rules
from .models import (EVIDENCE_EXTENSIONS, PAYMENT_METHODS, AdvanceRepayment, AssetIncident, Payroll,
                     PayrollCalculation, PayrollDeductionLine, PayrollPolicy, SalaryAdvance, SalaryAdvanceRequest)
from .serializers import ManagerRecordSerializer, serializer_business_id

MAX_EVIDENCE_BYTES = 10 * 1024 * 1024


def actor_name(serializer):
    request = serializer.context.get("request")
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return ""
    return user.get_full_name().strip() or user.username


def validate_evidence(value):
    from django.core.validators import FileExtensionValidator
    FileExtensionValidator(EVIDENCE_EXTENSIONS)(value)
    if value.size > MAX_EVIDENCE_BYTES:
        raise serializers.ValidationError("Evidence files must be 10 MB or smaller.")
    return value


def file_name(field):
    return field.name.rsplit("/", 1)[-1] if field else ""


# --- Payroll advance deductions ----------------------------------------------

class PayrollPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = PayrollPolicy
        fields = ["advance_deduction_limit_percent", "updated_at"]
        read_only_fields = ["updated_at"]


class PayrollDeductionLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayrollDeductionLine
        fields = ["kind", "name", "amount", "salary_advance", "asset_incident"]


class PayrollCalculationSerializer(serializers.ModelSerializer):
    lines = PayrollDeductionLineSerializer(many=True, read_only=True)
    employee = serializers.IntegerField(source="payroll.employee_id", read_only=True)
    employee_name = serializers.CharField(source="payroll.employee_name", read_only=True)
    period_start = serializers.DateField(source="payroll.period_start", read_only=True)
    period_end = serializers.DateField(source="payroll.period_end", read_only=True)
    currency = serializers.CharField(source="payroll.currency", read_only=True)
    payroll_status = serializers.CharField(source="payroll.status", read_only=True)
    is_current = serializers.SerializerMethodField()

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_current(self, obj):
        return payroll_rules.calculation_is_current(obj.payroll)

    class Meta:
        model = PayrollCalculation
        fields = ["id", "payroll", "employee", "employee_name", "period_start", "period_end", "currency",
                  "payroll_status", "gross_pay", "advance_deductions", "asset_deductions", "other_deductions",
                  "total_deductions",
                  "net_pay", "warnings", "lines", "is_current", "calculated_at", "calculated_by"]


class PayrollCalculationRequestSerializer(serializers.Serializer):
    payroll = serializers.PrimaryKeyRelatedField(queryset=Payroll.objects.none())
    other_deductions = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"),
                                                required=False)

    def get_fields(self):
        fields = super().get_fields()
        fields["payroll"].queryset = Payroll.objects.filter(employee__business_id=serializer_business_id(self))
        return fields


# --- Salary advances ---------------------------------------------------------

class AdvanceRepaymentSerializer(serializers.ModelSerializer):
    state = serializers.SerializerMethodField()
    payroll_period = serializers.SerializerMethodField()

    @extend_schema_field(OpenApiTypes.STR)
    def get_state(self, obj):
        if obj.payroll_id is None:
            return "repaid"
        if obj.payroll.status != "paid":
            return "scheduled"
        return "repaid" if payroll_rules.calculation_is_current(obj.payroll) else "not_applied"

    @extend_schema_field(OpenApiTypes.STR)
    def get_payroll_period(self, obj):
        return f"{obj.payroll.period_start} to {obj.payroll.period_end}" if obj.payroll_id else ""

    class Meta:
        model = AdvanceRepayment
        fields = ["id", "amount", "repaid_on", "source", "reference", "notes", "recorded_by", "payroll",
                  "payroll_period", "state", "created_at"]


class SalaryAdvanceSerializer(ManagerRecordSerializer):
    repayments = AdvanceRepaymentSerializer(many=True, read_only=True)
    status = serializers.SerializerMethodField()
    total_repaid = serializers.SerializerMethodField()
    scheduled_deductions = serializers.SerializerMethodField()
    outstanding_balance = serializers.SerializerMethodField()
    next_installment = serializers.SerializerMethodField()
    schedule = serializers.SerializerMethodField()
    from_request = serializers.SerializerMethodField()

    @extend_schema_field(serializers.BooleanField(help_text=(
        "Approved from the employee's own request. Such an advance is locked.")))
    def get_from_request(self, obj):
        return hasattr(obj, "request")

    def figures(self, obj):
        cache = self.context.setdefault("_advance_figures", {})
        if obj.pk not in cache:
            cache[obj.pk] = payroll_rules.advance_figures(obj)
        return cache[obj.pk]

    @extend_schema_field(OpenApiTypes.STR)
    def get_status(self, obj):
        return self.figures(obj)["status"]

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_total_repaid(self, obj):
        return str(self.figures(obj)["total_repaid"])

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_scheduled_deductions(self, obj):
        return str(self.figures(obj)["scheduled_deductions"])

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_outstanding_balance(self, obj):
        return str(self.figures(obj)["outstanding_balance"])

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_next_installment(self, obj):
        return str(self.figures(obj)["next_installment"])

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_schedule(self, obj):
        """The planned monthly installments, from the first repayment month."""
        rows, left = [], obj.amount
        year, month = obj.first_repayment_month.year, obj.first_repayment_month.month
        while left > 0 and len(rows) < 120:
            amount = min(obj.installment_amount, left)
            rows.append({"month": f"{year:04d}-{month:02d}", "amount": str(amount)})
            left -= amount
            month += 1
            if month > 12:
                year, month = year + 1, 1
        return rows

    def validate_first_repayment_month(self, value):
        return value.replace(day=1)

    def validate(self, attrs):
        instance = self.instance
        if instance is not None and hasattr(instance, "request"):
            raise serializers.ValidationError(
                "This advance was approved from the employee's request and can no longer be changed.")
        if instance is not None:
            figures = payroll_rules.advance_figures(instance)
            if figures["status"] == "repaid":
                raise serializers.ValidationError("This advance is fully repaid and can no longer be changed.")
            if instance.repayments.exists():
                locked = [name for name in ("employee", "amount", "currency", "issue_date")
                          if name in attrs and attrs[name] != getattr(instance, name)]
                if locked:
                    raise serializers.ValidationError(
                        {locked[0]: "This cannot change after repayments have been recorded."})
        if instance is None and "first_repayment_month" not in attrs and attrs.get("issue_date"):
            attrs["first_repayment_month"] = attrs["issue_date"].replace(day=1)
        if "installment_amount" not in attrs and attrs.get("amount") is not None:
            # Without an explicit installment the whole advance is due at once; the deduction limit spreads it.
            if instance is None or instance.installment_amount >= instance.amount \
                    or instance.installment_amount > attrs["amount"]:
                attrs["installment_amount"] = attrs["amount"]
        amount = self.value(attrs, "amount")
        installment = self.value(attrs, "installment_amount")
        issue_date = self.value(attrs, "issue_date")
        first_month = self.value(attrs, "first_repayment_month")
        if amount is not None and amount <= 0:
            raise serializers.ValidationError({"amount": "The advance amount must be greater than zero."})
        if installment is not None and installment <= 0:
            raise serializers.ValidationError({"installment_amount": "The monthly installment must be greater than zero."})
        if amount and installment and installment > amount:
            raise serializers.ValidationError({"installment_amount": "The monthly installment cannot exceed the advance amount."})
        if issue_date and first_month and first_month < issue_date.replace(day=1):
            raise serializers.ValidationError({"first_repayment_month": "Repayment cannot start before the month the advance is issued."})
        employee = self.value(attrs, "employee")
        if employee is not None and not employee.is_active and instance is None:
            raise serializers.ValidationError({"employee": "Advances can only be issued to active employees."})
        return attrs

    def create(self, validated_data):
        return super().create({**validated_data, "approved_by": actor_name(self)})

    class Meta:
        model = SalaryAdvance
        fields = ["id", "employee", "employee_name", "amount", "currency", "issue_date", "reason",
                  "installment_amount", "first_repayment_month", "notes", "disbursed_on",
                  "disbursement_method", "disbursement_reference", "approved_by", "created_at", "status",
                  "total_repaid", "scheduled_deductions", "outstanding_balance", "next_installment",
                  "schedule", "repayments", "from_request"]
        read_only_fields = ["disbursed_on", "disbursement_method", "disbursement_reference", "approved_by",
                            "created_at"]
        extra_kwargs = {"installment_amount": {"required": False}, "first_repayment_month": {"required": False},
                        "reason": {"allow_blank": True, "default": ""}}


class AdvanceRequestSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.__str__", read_only=True)

    class Meta:
        model = SalaryAdvanceRequest
        fields = ["id", "employee", "employee_name", "amount", "currency", "reason", "status", "decision_notes",
                  "decided_by", "decided_at", "advance", "requested_at"]
        read_only_fields = fields


class AdvanceRequestDecisionSerializer(serializers.Serializer):
    decision_notes = serializers.CharField(required=False, allow_blank=True, default="")


class MyAdvanceRequestSerializer(serializers.ModelSerializer):
    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("The amount must be greater than zero.")
        return value

    class Meta:
        model = SalaryAdvanceRequest
        fields = ["id", "amount", "currency", "reason", "status", "decision_notes", "decided_by", "decided_at",
                  "advance", "requested_at"]
        read_only_fields = ["currency", "status", "decision_notes", "decided_by", "decided_at", "advance",
                            "requested_at"]
        extra_kwargs = {"reason": {"required": False, "allow_blank": True}}


class MyPayslipSerializer(serializers.ModelSerializer):
    gross_pay = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    net_pay = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    contract_title = serializers.CharField(source="contract.title", read_only=True, default=None)
    lines = serializers.SerializerMethodField()

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_lines(self, obj):
        if not payroll_rules.calculation_is_current(obj):
            return []
        return [{"kind": line.kind, "name": line.name, "amount": str(line.amount)}
                for line in obj.calculation.lines.all() if line.amount > 0]

    class Meta:
        model = Payroll
        fields = ["id", "period_start", "period_end", "employee_name", "employee_email", "job_title", "department",
                  "contract_title", "base_salary", "allowances", "gross_pay", "deductions", "net_pay", "currency",
                  "status", "paid_date", "lines"]
        read_only_fields = fields


class AdvanceDisbursementSerializer(serializers.Serializer):
    disbursed_on = serializers.DateField(default=timezone.localdate)
    disbursement_method = serializers.ChoiceField(choices=PAYMENT_METHODS)
    disbursement_reference = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        advance = self.context["advance"]
        if attrs["disbursed_on"] > timezone.localdate():
            raise serializers.ValidationError({"disbursed_on": "The disbursement date cannot be in the future."})
        if attrs["disbursed_on"] < advance.issue_date:
            raise serializers.ValidationError({"disbursed_on": "The advance cannot be disbursed before it was issued."})
        reference = attrs["disbursement_reference"].strip()
        if attrs["disbursement_method"] != "cash" and not reference:
            raise serializers.ValidationError({"disbursement_reference": "Enter the bank or mobile money transaction reference."})
        if reference and SalaryAdvance.objects.filter(
            employee__business_id=advance.employee.business_id, disbursement_method=attrs["disbursement_method"],
            disbursement_reference__iexact=reference,
        ).exclude(pk=advance.pk).exists():
            raise serializers.ValidationError({"disbursement_reference": "This transaction reference is already recorded for another advance."})
        attrs["disbursement_reference"] = reference
        return attrs


class AdvanceManualRepaymentSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    repaid_on = serializers.DateField(default=timezone.localdate)
    reference = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        advance = self.context["advance"]
        figures = payroll_rules.advance_figures(advance)
        if attrs["amount"] <= 0:
            raise serializers.ValidationError({"amount": "The repayment must be greater than zero."})
        if attrs["amount"] > figures["available_to_deduct"]:
            raise serializers.ValidationError({"amount": (
                f"The repayment cannot exceed the {figures['available_to_deduct']} still owed "
                "after scheduled payroll deductions.")})
        if attrs["repaid_on"] > timezone.localdate():
            raise serializers.ValidationError({"repaid_on": "The repayment date cannot be in the future."})
        return attrs


# --- Asset misuse ------------------------------------------------------------

class AssetIncidentSerializer(ManagerRecordSerializer):
    evidence = serializers.FileField(write_only=True, required=False)
    evidence_name = serializers.SerializerMethodField()
    recovered_amount = serializers.SerializerMethodField()
    scheduled_recovery = serializers.SerializerMethodField()
    outstanding_recovery = serializers.SerializerMethodField()

    def figures(self, obj):
        cache = self.context.setdefault("_recovery_figures", {})
        if obj.pk not in cache:
            cache[obj.pk] = payroll_rules.asset_recovery_figures(obj)
        return cache[obj.pk]

    @extend_schema_field(OpenApiTypes.STR)
    def get_evidence_name(self, obj):
        return file_name(obj.evidence)

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_recovered_amount(self, obj):
        return str(self.figures(obj)["recovered_amount"])

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_scheduled_recovery(self, obj):
        return str(self.figures(obj)["scheduled_recovery"])

    @extend_schema_field(OpenApiTypes.DECIMAL)
    def get_outstanding_recovery(self, obj):
        return str(self.figures(obj)["outstanding_recovery"])

    def validate_evidence(self, value):
        return validate_evidence(value)

    def validate(self, attrs):
        if self.instance and self.instance.status == "closed":
            raise serializers.ValidationError("Closed incidents are kept as a record and can no longer be changed.")
        if self.instance is None:
            attrs["status"] = "reported"
            attrs.setdefault("incident_date", timezone.localdate())
        incident_date = self.value(attrs, "incident_date")
        if incident_date and incident_date > timezone.localdate():
            raise serializers.ValidationError({"incident_date": "The incident date cannot be in the future."})
        loss = self.value(attrs, "estimated_loss", Decimal("0")) or Decimal("0")
        recovery = self.value(attrs, "recovery_amount", Decimal("0")) or Decimal("0")
        if recovery > loss:
            raise serializers.ValidationError({"recovery_amount": "The recovery amount cannot exceed the estimated loss."})
        if self.instance is not None and ("recovery_amount" in attrs or "estimated_loss" in attrs):
            used = payroll_rules.asset_recovery_figures(self.instance)
            deducted = used["recovered_amount"] + used["scheduled_recovery"]
            field = "recovery_amount" if recovery > 0 else "estimated_loss"
            if (recovery if recovery > 0 else loss) < deducted:
                raise serializers.ValidationError({field: (
                    f"{deducted} has already been deducted through payroll. This amount cannot be lower.")})
        if recovery > 0 and not (self.value(attrs, "recovery_authorization") or "").strip():
            raise serializers.ValidationError({"recovery_authorization": (
                "Record the legal basis or the employee's written agreement before recording a recovery amount.")})
        if self.value(attrs, "status", "reported") in ("resolved", "closed") and not (self.value(attrs, "resolution") or "").strip():
            raise serializers.ValidationError({"resolution": "Describe the resolution before resolving or closing the incident."})
        return attrs

    def save(self, **kwargs):
        status = self.validated_data.get("status", getattr(self.instance, "status", "reported"))
        if status in ("resolved", "closed") and not getattr(self.instance, "resolved_at", None):
            kwargs["resolved_at"] = timezone.now()
        elif status in ("reported", "under_review"):
            kwargs["resolved_at"] = None
        if self.instance is None:
            kwargs["reported_by"] = actor_name(self)
        return super().save(**kwargs)

    class Meta:
        model = AssetIncident
        fields = ["id", "employee", "employee_name", "asset_name", "asset_tag", "incident_type", "incident_date",
                  "description", "estimated_loss", "currency", "evidence", "evidence_name", "status",
                  "investigation_findings", "employee_response", "resolution", "recovery_amount",
                  "recovery_authorization", "recovered_amount", "scheduled_recovery", "outstanding_recovery",
                  "reported_by", "resolved_at", "created_at", "updated_at"]
        read_only_fields = ["reported_by", "resolved_at", "created_at", "updated_at"]
        extra_kwargs = {"incident_date": {"required": False}}
