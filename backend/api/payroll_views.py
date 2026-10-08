"""Salary advances and asset misuse.

These endpoints sit beside the existing payroll endpoints and never change
their responses. They are scoped to the signed-in employer's business.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import FileResponse, Http404
from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_view, inline_serializer
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from . import payroll_rules
from .models import AdvanceRepayment, AssetIncident, PayrollCalculation, SalaryAdvance, SalaryAdvanceRequest
from .payroll_serializers import (AdvanceDisbursementSerializer, AdvanceManualRepaymentSerializer,
                                  AdvanceRequestDecisionSerializer, AssetIncidentSerializer,
                                  PayrollCalculationRequestSerializer, PayrollCalculationSerializer,
                                  PayrollPolicySerializer, AdvanceRequestSerializer, SalaryAdvanceSerializer)
from .permissions import IsManager, business_id_for
from .views import ManagerViewSet

ADVANCES = ["Employer · Salary advances"]
ASSETS = ["Employer · Asset misuse"]


def user_name(user):
    return user.get_full_name().strip() or user.username


def private_file(field, missing_message):
    if not field:
        raise Http404("No evidence is attached to this record.")
    try:
        handle = field.open("rb")
    except FileNotFoundError:
        raise Http404(missing_message)
    response = FileResponse(handle, as_attachment=True, filename=field.name.rsplit("/", 1)[-1])
    response["Cache-Control"] = "private, no-store"
    return response


# --- Payroll advance deductions ----------------------------------------------

@extend_schema(tags=ADVANCES)
class PayrollPolicyView(APIView):
    permission_classes = [IsManager]

    @extend_schema(summary="Read the salary advance deduction limit", responses=PayrollPolicySerializer)
    def get(self, request):
        policy = payroll_rules.payroll_policy(business_id_for(request.user))
        return Response(PayrollPolicySerializer(policy).data)

    @extend_schema(summary="Update the salary advance deduction limit", request=PayrollPolicySerializer,
                   responses=PayrollPolicySerializer)
    def patch(self, request):
        policy = payroll_rules.payroll_policy(business_id_for(request.user))
        serializer = PayrollPolicySerializer(policy, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


@extend_schema(tags=ADVANCES)
@extend_schema_view(
    list=extend_schema(summary="List payroll advance deduction calculations"),
    retrieve=extend_schema(summary="Retrieve one payroll advance deduction calculation"),
    create=extend_schema(summary="Apply salary advance deductions to a draft payroll record",
                         request=PayrollCalculationRequestSerializer, responses=PayrollCalculationSerializer),
)
class PayrollCalculationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                                viewsets.GenericViewSet):
    """Calculating (POST) is safe to repeat: it replaces the previous result."""
    permission_classes = [IsManager]
    serializer_class = PayrollCalculationSerializer

    def get_queryset(self):
        queryset = (PayrollCalculation.objects.filter(payroll__employee__business_id=business_id_for(self.request.user))
                    .select_related("payroll").prefetch_related("lines").order_by("-payroll__period_end", "-id"))
        params = self.request.query_params
        if params.get("employee"):
            queryset = queryset.filter(payroll__employee_id=params["employee"])
        if params.get("month"):
            year, _, month = params["month"].partition("-")
            if year.isdigit() and month.isdigit():
                queryset = queryset.filter(payroll__period_end__year=int(year), payroll__period_end__month=int(month))
        return queryset

    def create(self, request, *args, **kwargs):
        payload = PayrollCalculationRequestSerializer(data=request.data, context={"request": request})
        payload.is_valid(raise_exception=True)
        _, calculation = payroll_rules.apply_payroll_calculation(
            payload.validated_data["payroll"].pk,
            other_deductions=payload.validated_data.get("other_deductions"),
            calculated_by=user_name(request.user),
        )
        calculation = self.get_queryset().get(pk=calculation.pk)
        return Response(self.get_serializer(calculation).data, status=status.HTTP_201_CREATED)



# --- Salary advances ---------------------------------------------------------

@extend_schema(tags=ADVANCES)
class SalaryAdvanceViewSet(ManagerViewSet):
    queryset = SalaryAdvance.objects.select_related("employee", "request").prefetch_related("repayments__payroll__calculation")
    serializer_class = SalaryAdvanceSerializer

    def perform_destroy(self, instance):
        if hasattr(instance, "request"):
            raise serializers.ValidationError(
                "This advance was approved from the employee's request and cannot be deleted.")
        if instance.repayments.exists():
            raise serializers.ValidationError(
                "Advances with recorded repayments are kept as a financial record and cannot be deleted.")
        instance.delete()

    def locked_advance(self):
        advance = self.get_object()
        return SalaryAdvance.objects.select_for_update().get(pk=advance.pk)

    @extend_schema(summary="Record the disbursement of an advance", request=AdvanceDisbursementSerializer,
                   responses=SalaryAdvanceSerializer)
    @action(detail=True, methods=["post"])
    def disburse(self, request, pk=None):
        with transaction.atomic():
            advance = self.locked_advance()
            if advance.disbursed_on:
                raise serializers.ValidationError("This advance has already been disbursed.")
            payload = AdvanceDisbursementSerializer(data=request.data, context={"advance": advance})
            payload.is_valid(raise_exception=True)
            for field, value in payload.validated_data.items():
                setattr(advance, field, value)
            advance.save(update_fields=list(payload.validated_data))
        return Response(self.get_serializer(self.get_queryset().get(pk=advance.pk)).data)

    @extend_schema(summary="Record a direct repayment outside payroll", request=AdvanceManualRepaymentSerializer,
                   responses=SalaryAdvanceSerializer)
    @action(detail=True, methods=["post"])
    def repayments(self, request, pk=None):
        with transaction.atomic():
            advance = self.locked_advance()
            payload = AdvanceManualRepaymentSerializer(data=request.data, context={"advance": advance})
            payload.is_valid(raise_exception=True)
            AdvanceRepayment.objects.create(advance=advance, source="manual", recorded_by=user_name(request.user),
                                            **payload.validated_data)
        return Response(self.get_serializer(self.get_queryset().get(pk=advance.pk)).data,
                        status=status.HTTP_201_CREATED)


@extend_schema(tags=ADVANCES)
@extend_schema_view(
    list=extend_schema(summary="List salary advance requests from employees"),
    retrieve=extend_schema(summary="Retrieve one salary advance request"),
)
class SalaryAdvanceRequestViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Approving creates a salary advance that payroll deducts automatically."""
    permission_classes = [IsManager]
    serializer_class = AdvanceRequestSerializer

    def get_queryset(self):
        return SalaryAdvanceRequest.objects.filter(
            employee__business_id=business_id_for(self.request.user)).select_related("employee")

    def pending_request(self):
        record = SalaryAdvanceRequest.objects.select_for_update().select_related("employee").get(pk=self.get_object().pk)
        if record.status != "pending":
            raise serializers.ValidationError("This request has already been decided.")
        return record

    def decide(self, record, status_value, notes, advance=None):
        record.status, record.decision_notes, record.advance = status_value, notes, advance
        record.decided_by, record.decided_at = user_name(self.request.user), timezone.now()
        record.save(update_fields=["status", "decision_notes", "advance", "decided_by", "decided_at"])
        return Response(self.get_serializer(record).data)

    @extend_schema(summary="Approve a request and record the salary advance",
                   request=AdvanceRequestDecisionSerializer, responses=AdvanceRequestSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        payload = AdvanceRequestDecisionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        with transaction.atomic():
            record = self.pending_request()
            advance = SalaryAdvanceSerializer(data={
                "employee": record.employee_id, "amount": record.amount, "currency": record.currency,
                "issue_date": timezone.localdate(), "reason": record.reason,
                "notes": f"Requested by the employee on {timezone.localtime(record.requested_at):%Y-%m-%d}.",
            }, context=self.get_serializer_context())
            advance.is_valid(raise_exception=True)
            advance.save()
            return self.decide(record, "approved", payload.validated_data["decision_notes"], advance.instance)

    @extend_schema(summary="Reject a salary advance request",
                   request=AdvanceRequestDecisionSerializer, responses=AdvanceRequestSerializer)
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        payload = AdvanceRequestDecisionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        with transaction.atomic():
            return self.decide(self.pending_request(), "rejected", payload.validated_data["decision_notes"])


# --- Asset misuse ------------------------------------------------------------

@extend_schema(tags=ASSETS)
class AssetIncidentViewSet(ManagerViewSet):
    queryset = AssetIncident.objects.select_related("employee").prefetch_related(
        "payroll_deductions__calculation__payroll__calculation")
    serializer_class = AssetIncidentSerializer

    def perform_destroy(self, instance):
        if instance.status != "reported":
            raise serializers.ValidationError(
                "Only incidents still in Reported status can be deleted. Close the incident instead.")
        if instance.payroll_deductions.exists():
            raise serializers.ValidationError(
                "This incident has payroll recoveries on record and cannot be deleted. Close it instead.")
        if instance.evidence:
            instance.evidence.delete(save=False)
        instance.delete()

    @extend_schema(summary="Incident totals per employee", responses=inline_serializer(
        "AssetIncidentSummary", many=True, fields={
            "employee": serializers.IntegerField(), "employee_name": serializers.CharField(),
            "incidents": serializers.IntegerField(), "open_incidents": serializers.IntegerField(),
            "total_loss": serializers.DecimalField(max_digits=14, decimal_places=2),
            "total_recovery": serializers.DecimalField(max_digits=14, decimal_places=2),
        }))
    @action(detail=False, methods=["get"])
    def summary(self, request):
        rows = (self.get_queryset().values("employee", "employee__first_name", "employee__last_name", "currency")
                .annotate(incidents=Count("id"),
                          open_incidents=Count("id", filter=Q(status__in=["reported", "under_review"])),
                          total_loss=Sum("estimated_loss"), total_recovery=Sum("recovery_amount"))
                .order_by("employee__last_name", "employee__first_name", "currency"))
        return Response([{
            "employee": row["employee"],
            "employee_name": f'{row["employee__first_name"]} {row["employee__last_name"]}'.strip(),
            "currency": row["currency"], "incidents": row["incidents"], "open_incidents": row["open_incidents"],
            "total_loss": str(row["total_loss"] or Decimal("0.00")),
            "total_recovery": str(row["total_recovery"] or Decimal("0.00")),
        } for row in rows])

    @extend_schema(summary="Download incident evidence", responses={(200, "application/octet-stream"): bytes})
    @action(detail=True, methods=["get"])
    def evidence(self, request, pk=None):
        return private_file(self.get_object().evidence, "The evidence file could not be found.")
