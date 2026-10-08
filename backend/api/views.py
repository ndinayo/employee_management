from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256

from django.db import transaction
from django.db.models import Sum
from django.db.models.deletion import ProtectedError
from django.http import FileResponse, Http404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (OpenApiExample, OpenApiParameter, OpenApiResponse,
                                   extend_schema, extend_schema_view, inline_serializer)
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from . import leave_management, onboarding, payroll_rules
from .models import (AccountProfile, Employee, Contract, ContractTerminationRequest,
                     Attendance, LeaveBalance, LeaveRequest, Holiday, Announcement,
                     CalendarEvent, Salary, Payroll)
from .permissions import IsManager, business_id_for
from .schema import (RESPONSE_401, RESPONSE_403_MANAGER, RESPONSE_404, DetailSerializer,
                     ManagerReportsSerializer, NotificationSerializer, with_errors)
from .serializers import (EmployeeSerializer, ContractSerializer, AttendanceSerializer,
                          LeaveBalanceSerializer, LeaveSerializer, HolidaySerializer,
                          AnnouncementSerializer, CalendarEventSerializer,
                          SalarySerializer, PayrollSerializer)

# Shared pieces of the generated documentation. None of this affects request
# handling; it only tells drf-spectacular what the views already return.
FILE_RESPONSES = {
    401: RESPONSE_401,
    403: RESPONSE_403_MANAGER,
    404: OpenApiResponse(response=DetailSerializer,
                         description="No file is attached, or the stored file is missing."),
}


class ManagerViewSet(viewsets.ModelViewSet):
    permission_classes = [IsManager]

    def get_queryset(self):
        queryset = super().get_queryset()
        field = "business_id" if queryset.model in (Employee, Holiday, Announcement, CalendarEvent) else "employee__business_id"
        return queryset.filter(**{field: business_id_for(self.request.user)})

    def perform_create(self, serializer):
        if serializer.Meta.model in (Employee, Holiday, Announcement, CalendarEvent):
            extra = {"business_id": business_id_for(self.request.user)}
            if serializer.Meta.model in (Announcement, CalendarEvent):
                extra["created_by"] = self.request.user.get_full_name().strip() or self.request.user.username
            serializer.save(**extra)
        else:
            serializer.save()

    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError:
            raise serializers.ValidationError(
                "This employee has employment records. Mark their profile inactive to retain their history."
            )


@extend_schema(tags=["Employer · Employees"])
@extend_schema_view(
    list=extend_schema(
        summary="List employees",
        description="Every employee in the signed-in employer's own business, ordered by surname.",
        responses=with_errors({200: EmployeeSerializer(many=True)}, bad_request=False),
    ),
    retrieve=extend_schema(
        summary="Retrieve one employee",
        description="The full record for one employee, including the fields the employee "
                    "maintains themselves. Scoped to the employer's own business; another "
                    "business's record returns 404.",
        responses=with_errors({200: EmployeeSerializer}, bad_request=False, not_found=True),
    ),
    create=extend_schema(
        summary="Hire an employee",
        description=(
            "Adds an employee to the employer's business and opens a sign-in account for them "
            "in the same request. The temporary password is emailed when invitation email is "
            "configured; otherwise it comes back in `invite.temporary_password` so the employer "
            "can pass it on.\n\n"
            "Only `first_name`, `last_name`, `email` and `job_title` are required - the employee "
            "fills in the rest from their own workspace. Send `multipart/form-data` when "
            "attaching `photo` or `contract_document`."
        ),
        responses=with_errors({201: EmployeeSerializer}),
        examples=[OpenApiExample(
            "Minimum payload",
            request_only=True,
            value={"first_name": "Amina", "last_name": "Uwase",
                   "email": "amina.uwase@example.com", "job_title": "Accountant"},
        )],
    ),
    update=extend_schema(
        summary="Replace an employee",
        description="Every writable field must be supplied; use PATCH to change only some of "
                    "them. Scoped to the employer's own business; another business's record "
                    "returns 404.",
        responses=with_errors({200: EmployeeSerializer}, not_found=True),
    ),
    partial_update=extend_schema(
        summary="Update an employee",
        description="Send only the fields that change. Use this to set `is_active: false` "
                    "instead of deleting an employee who has employment records.",
        responses=with_errors({200: EmployeeSerializer}, not_found=True),
        examples=[OpenApiExample("Deactivate", request_only=True, value={"is_active": False})],
    ),
    destroy=extend_schema(
        summary="Delete an employee",
        description="Removes the employee, their sign-in account and their records. Deactivate "
                    "instead when the employment history must be kept.",
        responses=with_errors(
            {204: OpenApiResponse(description="Deleted. No body.")}, not_found=True),
    ),
    photo=extend_schema(
        summary="Download an employee's photo",
        description="Profile photos are stored privately and are only ever served through this "
                    "endpoint, never from a public media URL.",
        responses={(200, "image/*"): OpenApiTypes.BINARY, **FILE_RESPONSES},
    ),
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


class ContractTerminationInputSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=4000, trim_whitespace=True)
    proposed_last_working_date = serializers.DateField()


class ContractTerminationDecisionSerializer(serializers.Serializer):
    request_id = serializers.IntegerField()
    decision = serializers.ChoiceField(choices=["approved", "rejected"])
    response_notes = serializers.CharField(max_length=4000, required=False, allow_blank=True, trim_whitespace=True)


class ContractNotificationSerializer(ContractSerializer):
    """Documentation only: a contract plus the outcome of its notification email."""

    notification = NotificationSerializer(read_only=True)

    class Meta(ContractSerializer.Meta):
        fields = ContractSerializer.Meta.fields + ["notification"]


@extend_schema(tags=["Employer · Contracts"])
@extend_schema_view(
    list=extend_schema(
        summary="List contracts",
        description="Every contract belonging to the employer's own employees, newest start "
                    "date first.",
        responses=with_errors({200: ContractSerializer(many=True)}, bad_request=False),
    ),
    retrieve=extend_schema(
        summary="Retrieve one contract",
        description="One contract with its signature state, worker approval state and any "
                    "termination request attached to it. Scoped to the employer's own business; "
                    "another business's record returns 404.",
        responses=with_errors({200: ContractSerializer}, bad_request=False, not_found=True),
    ),
    create=extend_schema(
        summary="Create a contract",
        description=(
            "Creates a contract in `signature_status: draft`. Write the signable text into "
            "`content` (a small allow-list of HTML tags survives sanitising) and/or attach a "
            "PDF/DOC/DOCX of up to 10 MB as `document` using `multipart/form-data`.\n\n"
            "Setting `department` also updates the employee's department."
        ),
        responses=with_errors({201: ContractSerializer}),
        examples=[OpenApiExample(
            "Draft contract",
            request_only=True,
            value={"employee": 1, "title": "Accountant - permanent", "department": "Finance",
                   "start_date": "2026-01-05", "end_date": None, "status": "active",
                   "content": "<p>This agreement is made between...</p>"},
        )],
    ),
    update=extend_schema(
        summary="Replace a draft contract",
        description="Rejected with 400 once the contract has been sent for signature.",
        responses=with_errors({200: ContractSerializer}, not_found=True),
    ),
    partial_update=extend_schema(
        summary="Update a draft contract",
        description="Rejected with 400 once the contract has been sent for signature.",
        responses=with_errors({200: ContractSerializer}, not_found=True),
    ),
    destroy=extend_schema(
        summary="Delete a draft contract",
        description="Only a contract still in `signature_status: draft` can be deleted.",
        responses=with_errors(
            {204: OpenApiResponse(description="Deleted. No body.")}, not_found=True),
    ),
    send_for_signature=extend_schema(
        summary="Send a contract for signature",
        description=(
            "Moves a draft to `signature_status: sent`, fingerprints `content` so later edits "
            "invalidate the signature, and emails the employee. Requires non-empty `content` "
            "and an employee who already has a sign-in account.\n\n"
            "The response is the contract plus a `notification` object saying whether the email "
            "actually left the server. Takes no request body."
        ),
        request=None,
        responses=with_errors({200: ContractNotificationSerializer}, not_found=True),
    ),
    resend_signature_email=extend_schema(
        summary="Email the signature request again",
        description="Only valid while `signature_status` is `sent`. An optional `message` is "
                    "stored on the contract and included in the email.",
        request=ContractMessageSerializer,
        responses=with_errors(
            {200: NotificationSerializer,
             503: OpenApiResponse(
                 response=DetailSerializer,
                 description="The email could not be sent. The contract is still available in "
                             "the employee's dashboard.")},
            not_found=True),
        examples=[OpenApiExample("With a note", request_only=True,
                                 value={"message": "Please sign before Friday."})],
    ),
    request_new_signature=extend_schema(
        summary="Request a corrected signature",
        description="Copies a **signed** contract into a new one linked by `revision_of` and "
                    "sends that copy for signature. Rejected while an earlier correction is "
                    "still awaiting the employee.",
        request=ContractMessageSerializer,
        responses=with_errors({201: ContractNotificationSerializer}, not_found=True),
    ),
    approve_worker=extend_schema(
        summary="Approve the worker to start",
        description="The final onboarding step. Requires a signed contract with `status: "
                    "active`. Until this succeeds, every `/api/me/...` endpoint returns 403 "
                    "for that employee.",
        request=None,
        responses=with_errors({200: ContractNotificationSerializer}, not_found=True),
    ),
    initiate_termination=extend_schema(
        summary="Start an employer-led termination",
        description="Opens a termination request in `awaiting_acknowledgement` and notifies the "
                    "employee. Only one open request per contract, and the date cannot be in "
                    "the past.",
        request=ContractTerminationInputSerializer,
        responses=with_errors({201: ContractSerializer}, not_found=True),
        examples=[OpenApiExample(
            "Notice period",
            request_only=True,
            value={"reason": "Restructuring of the finance team.",
                   "proposed_last_working_date": "2026-11-30"},
        )],
    ),
    termination_decision=extend_schema(
        summary="Approve or reject an employee's termination request",
        description="Answers a termination the **employee** raised, named by `request_id`. "
                    "Approving sets the contract to `terminated_mutual` and moves `end_date` to "
                    "the proposed last working date.",
        request=ContractTerminationDecisionSerializer,
        responses=with_errors({200: ContractSerializer}, not_found=True),
        examples=[OpenApiExample(
            "Approve",
            request_only=True,
            value={"request_id": 7, "decision": "approved",
                   "response_notes": "Agreed, thank you for the notice."},
        )],
    ),
    document=extend_schema(
        summary="Download the attached contract file",
        description="Returns the stored PDF/DOC/DOCX as an attachment.",
        responses={(200, "application/octet-stream"): OpenApiTypes.BINARY, **FILE_RESPONSES},
    ),
    preview=extend_schema(
        summary="Stream the attached contract file for preview",
        description="The same bytes as `document`, but without a `Content-Disposition` header "
                    "so the app can render them in its own PDF viewer.",
        responses={(200, "application/octet-stream"): OpenApiTypes.BINARY, **FILE_RESPONSES},
    ),
)
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
                department=original.department,
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

    @action(detail=True, methods=["post"], url_path="approve-worker")
    def approve_worker(self, request, pk=None):
        with transaction.atomic():
            contract = Contract.objects.select_for_update().get(pk=self.get_object().pk)
            if contract.signature_status != "signed":
                raise serializers.ValidationError("The employee must sign this contract before approval.")
            if contract.status != "active":
                raise serializers.ValidationError("Only an active contract can approve a worker.")
            if contract.worker_approval_status == "approved":
                raise serializers.ValidationError("This worker has already been approved.")
            contract.worker_approval_status = "approved"
            contract.worker_approved_at = timezone.now()
            contract.worker_approved_by = request.user.get_full_name().strip() or request.user.username
            contract.save(update_fields=["worker_approval_status", "worker_approved_at", "worker_approved_by"])
        emailed = onboarding.send_contract_worker_approval_notification(contract, "approved")
        data = self.get_serializer(contract).data
        data["notification"] = {
            "email_sent": emailed,
            "detail": (f"{contract.employee} was approved and received a congratulations email." if emailed else
                       f"{contract.employee} was approved, but the congratulations email could not be sent."),
        }
        return Response(data)

    @action(detail=True, methods=["post"], url_path="initiate-termination")
    def initiate_termination(self, request, pk=None):
        payload = ContractTerminationInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        with transaction.atomic():
            contract = Contract.objects.select_for_update().get(pk=self.get_object().pk)
            if contract.signature_status != "signed" or contract.worker_approval_status != "approved" or contract.status != "active":
                raise serializers.ValidationError("Only an active signed contract can be terminated.")
            if payload.validated_data["proposed_last_working_date"] < timezone.localdate():
                raise serializers.ValidationError({"proposed_last_working_date": "Choose today or a future date."})
            if contract.termination_requests.filter(status__in=["pending", "awaiting_acknowledgement"]).exists():
                raise serializers.ValidationError("This contract already has a pending termination request.")
            termination = ContractTerminationRequest.objects.create(
                contract=contract,
                initiated_by="employer",
                status="awaiting_acknowledgement",
                **payload.validated_data,
            )
        onboarding.send_contract_termination_notification(termination, "employer_initiated")
        return Response(self.get_serializer(contract).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="termination-decision")
    def termination_decision(self, request, pk=None):
        payload = ContractTerminationDecisionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        with transaction.atomic():
            contract = Contract.objects.select_for_update().get(pk=self.get_object().pk)
            termination = contract.termination_requests.select_for_update().filter(
                pk=payload.validated_data["request_id"], initiated_by="employee", status="pending",
            ).first()
            if not termination:
                raise serializers.ValidationError("This employee termination request is no longer pending.")
            termination.status = payload.validated_data["decision"]
            termination.response_notes = payload.validated_data.get("response_notes", "")
            termination.responded_at = timezone.now()
            termination.save(update_fields=["status", "response_notes", "responded_at"])
            if termination.status == "approved":
                contract.status = "terminated_mutual"
                contract.end_date = termination.proposed_last_working_date
                contract.save(update_fields=["status", "end_date"])
        onboarding.send_contract_termination_notification(termination, f"employer_{termination.status}")
        return Response(self.get_serializer(contract).data)

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


@extend_schema(tags=["Employer · Attendance"])
@extend_schema_view(
    list=extend_schema(
        summary="List attendance records",
        description="Attendance for the employer's own employees, most recent date first. "
                    "Includes both employer-entered rows and rows employees clocked themselves.",
        responses=with_errors({200: AttendanceSerializer(many=True)}, bad_request=False),
    ),
    retrieve=extend_schema(
        summary="Retrieve one attendance record",
        description="One attendance row, whether the employer entered it or the employee clocked "
                    "it. Scoped to the employer's own business; another business's record returns "
                    "404.",
        responses=with_errors({200: AttendanceSerializer}, bad_request=False, not_found=True),
    ),
    create=extend_schema(
        summary="Record attendance",
        description="One row per employee, date and shift. The date cannot precede the "
                    "employee's joining date, `absent` requires `hours_worked: 0`, and a date "
                    "already covered by approved leave is rejected.",
        responses=with_errors({201: AttendanceSerializer}),
        examples=[OpenApiExample(
            "A full day",
            request_only=True,
            value={"employee": 1, "date": "2026-10-01", "shift": "day",
                   "status": "present", "hours_worked": "8.00", "notes": ""},
        )],
    ),
    update=extend_schema(
        summary="Replace an attendance record",
        description="Every writable field must be supplied, and `shift` must keep its recorded "
                    "value. Use PATCH to correct one field. Scoped to the employer's own "
                    "business; another business's record returns 404.",
        responses=with_errors({200: AttendanceSerializer}, not_found=True),
    ),
    partial_update=extend_schema(
        summary="Correct an attendance record",
        description="`shift` is fixed once recorded and cannot be changed.",
        responses=with_errors({200: AttendanceSerializer}, not_found=True),
    ),
    destroy=extend_schema(
        summary="Delete an attendance record",
        description="Removes the row completely. Reports for that date are recalculated from what "
                    "is left. Scoped to the employer's own business; another business's record "
                    "returns 404.",
        responses=with_errors(
            {204: OpenApiResponse(description="Deleted. No body.")}, not_found=True),
    ),
)
class AttendanceViewSet(ManagerViewSet):
    queryset = Attendance.objects.select_related("employee").order_by("-date", "-id")
    serializer_class = AttendanceSerializer


@extend_schema(tags=["Employer · Leave"])
@extend_schema_view(
    list=extend_schema(
        summary="List leave requests",
        description="Leave requests from the employer's own employees, newest start date first.",
        responses=with_errors({200: LeaveSerializer(many=True)}, bad_request=False),
    ),
    retrieve=extend_schema(
        summary="Retrieve one leave request",
        description="One leave request with its status, day count and the decision recorded "
                    "against it. Scoped to the employer's own business; another business's record "
                    "returns 404.",
        responses=with_errors({200: LeaveSerializer}, bad_request=False, not_found=True),
    ),
    create=extend_schema(
        summary="Not available to employers",
        description="**Always returns 400.** Only the employee may raise leave, through "
                    "`POST /api/me/leave/`. The route exists because the viewset is a full "
                    "ModelViewSet.",
        request=LeaveSerializer,
        responses={400: OpenApiResponse(
            response=DetailSerializer,
            description="Employers cannot create employee leave requests.",
            examples=[OpenApiExample("Refused", value={
                "employee": "Employers cannot create employee leave requests. The employee "
                            "must submit the request."})]),
            401: RESPONSE_401, 403: RESPONSE_403_MANAGER},
    ),
    update=extend_schema(
        summary="Decide a leave request",
        description="Only `status` and `decision_notes` may change; touching `employee`, "
                    "`leave_type`, `start_date`, `end_date` or `reason` is rejected, and a "
                    "decision cannot be revisited once made.\n\n"
                    "Approving checks the remaining balance, and emails the employee.",
        responses=with_errors({200: LeaveSerializer}, not_found=True),
    ),
    partial_update=extend_schema(
        summary="Approve or reject a leave request",
        description="The usual way to decide leave. `decided_at` and `decided_by` are stamped "
                    "automatically and the employee is emailed.",
        responses=with_errors({200: LeaveSerializer}, not_found=True),
        examples=[OpenApiExample(
            "Approve",
            request_only=True,
            value={"status": "approved", "decision_notes": "Enjoy the break."},
        )],
    ),
    destroy=extend_schema(
        summary="Not available to employers",
        description="**Always returns 400.** Employers may approve or reject leave but never "
                    "delete it; the employee cancels their own pending request instead.",
        responses={400: OpenApiResponse(
            response=DetailSerializer,
            description="Employers cannot delete employee leave requests."),
            401: RESPONSE_401, 403: RESPONSE_403_MANAGER, 404: RESPONSE_404},
    ),
)
class LeaveViewSet(ManagerViewSet):
    queryset = LeaveRequest.objects.select_related("employee").order_by("-start_date", "-id")
    serializer_class = LeaveSerializer

    def create(self, request, *args, **kwargs):
        raise serializers.ValidationError({
            "employee": "Employers cannot create employee leave requests. The employee must submit the request."
        })

    def destroy(self, request, *args, **kwargs):
        self.get_object()
        raise serializers.ValidationError(
            "Employers cannot delete employee leave requests. They may only approve or reject them.")

    def perform_update(self, serializer):
        previous_status = serializer.instance.status
        leave = serializer.save()
        if leave.status in {"approved", "rejected"} and leave.status != previous_status:
            onboarding.send_leave_notification(leave, leave.status)


@extend_schema(tags=["Employer · Leave"])
@extend_schema_view(
    list=extend_schema(
        summary="List leave balances",
        description="Yearly allocations for every employee, with `used_days` and "
                    "`remaining_days` computed from approved leave. Listing also creates this "
                    "year's four default balances (annual 20, sick 10, maternity 90, unpaid 0) "
                    "for any employee still missing them.",
        responses=with_errors({200: LeaveBalanceSerializer(many=True)}, bad_request=False),
    ),
    retrieve=extend_schema(
        summary="Retrieve one leave balance",
        description="One employee's allocation for a leave type and year, with the days already "
                    "taken. Scoped to the employer's own business; another business's record "
                    "returns 404.",
        responses=with_errors({200: LeaveBalanceSerializer}, bad_request=False, not_found=True),
    ),
    create=extend_schema(
        summary="Create a leave balance",
        description="One row per employee, leave type and year.",
        responses=with_errors({201: LeaveBalanceSerializer}),
        examples=[OpenApiExample(
            "Extra annual leave",
            request_only=True,
            value={"employee": 1, "leave_type": "annual", "year": 2026, "days_allocated": "25.0"},
        )],
    ),
    update=extend_schema(
        summary="Replace a leave balance",
        description="Every writable field must be supplied; use PATCH to change only the "
                    "allocation. Scoped to the employer's own business; another business's record "
                    "returns 404.",
        responses=with_errors({200: LeaveBalanceSerializer}, not_found=True),
    ),
    partial_update=extend_schema(
        summary="Change an allocation",
        description="Send only `allocated_days`. Lowering it below the days already approved is "
                    "rejected. Scoped to the employer's own business; another business's record "
                    "returns 404.",
        responses=with_errors({200: LeaveBalanceSerializer}, not_found=True),
        examples=[OpenApiExample("Raise the allocation", request_only=True,
                                 value={"days_allocated": "24.0"})],
    ),
    destroy=extend_schema(
        summary="Delete a leave balance",
        description="Removes the allocation. Leave already approved against it is left untouched. "
                    "Scoped to the employer's own business; another business's record returns "
                    "404.",
        responses=with_errors(
            {204: OpenApiResponse(description="Deleted. No body.")}, not_found=True),
    ),
)
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


@extend_schema(tags=["Employer · Holidays"])
@extend_schema_view(
    list=extend_schema(
        summary="List company holidays",
        description="Holidays for the employer's business. These dates are skipped when leave "
                    "days are counted and make a date a non-working day in reports.",
        responses=with_errors({200: HolidaySerializer(many=True)}, bad_request=False),
    ),
    retrieve=extend_schema(
        summary="Retrieve one holiday",
        description="One company holiday. Holidays are excluded from leave day counts and from "
                    "absence reporting. Scoped to the employer's own business; another business's "
                    "record returns 404.",
        responses=with_errors({200: HolidaySerializer}, bad_request=False, not_found=True),
    ),
    create=extend_schema(
        summary="Add a holiday",
        description="At most one holiday per date per business.",
        responses=with_errors({201: HolidaySerializer}),
        examples=[OpenApiExample(
            "Public holiday",
            request_only=True,
            value={"name": "Independence Day", "date": "2026-07-04", "notes": "Offices closed"},
        )],
    ),
    update=extend_schema(
        summary="Replace a holiday",
        description="Every writable field must be supplied; use PATCH to change only some of "
                    "them. Scoped to the employer's own business; another business's record "
                    "returns 404.",
        responses=with_errors({200: HolidaySerializer}, not_found=True),
    ),
    partial_update=extend_schema(
        summary="Update a holiday",
        description="Send only the fields that change. Two holidays cannot share a date in the "
                    "same business. Scoped to the employer's own business; another business's "
                    "record returns 404.",
        responses=with_errors({200: HolidaySerializer}, not_found=True),
    ),
    destroy=extend_schema(
        summary="Delete a holiday",
        description="Removes the holiday, so that date counts as an ordinary working day again. "
                    "Scoped to the employer's own business; another business's record returns "
                    "404.",
        responses=with_errors(
            {204: OpenApiResponse(description="Deleted. No body.")}, not_found=True),
    ),
)
class HolidayViewSet(ManagerViewSet):
    queryset = Holiday.objects.order_by("-date", "-id")
    serializer_class = HolidaySerializer


@extend_schema(tags=["Employer · Announcements"])
@extend_schema_view(
    list=extend_schema(
        summary="List announcements",
        description="Announcements published to the employer's business, newest first. "
                    "`read_count` is how many employees have opened each one.",
        responses=with_errors({200: AnnouncementSerializer(many=True)}, bad_request=False),
    ),
    retrieve=extend_schema(
        summary="Retrieve one announcement",
        description="One announcement with how many employees have opened it. Scoped to the "
                    "employer's own business; another business's record returns 404.",
        responses=with_errors({200: AnnouncementSerializer}, bad_request=False, not_found=True),
    ),
    create=extend_schema(
        summary="Publish an announcement",
        description="Goes out to every employee in the business. `created_by` and "
                    "`published_at` are filled in from the signed-in employer.",
        responses=with_errors({201: AnnouncementSerializer}),
        examples=[OpenApiExample(
            "Office closure",
            request_only=True,
            value={"title": "Office closed on Friday",
                   "message": "The office will be closed for maintenance."},
        )],
    ),
    update=extend_schema(
        summary="Replace an announcement",
        description="Every writable field must be supplied; use PATCH to change only some of "
                    "them. Employees who already opened it keep their read mark. Scoped to the "
                    "employer's own business; another business's record returns 404.",
        responses=with_errors({200: AnnouncementSerializer}, not_found=True),
    ),
    partial_update=extend_schema(
        summary="Edit an announcement",
        description="Send only the fields that change. Scoped to the employer's own business; "
                    "another business's record returns 404.",
        responses=with_errors({200: AnnouncementSerializer}, not_found=True),
    ),
    destroy=extend_schema(
        summary="Delete an announcement",
        description="Removes the announcement and every read mark against it. Scoped to the "
                    "employer's own business; another business's record returns 404.",
        responses=with_errors(
            {204: OpenApiResponse(description="Deleted. No body.")}, not_found=True),
    ),
)
class AnnouncementViewSet(ManagerViewSet):
    queryset = Announcement.objects.prefetch_related("reads").all()
    serializer_class = AnnouncementSerializer


@extend_schema(tags=["Employer · Calendar"])
@extend_schema_view(
    list=extend_schema(
        summary="List calendar events",
        description="Company calendar events for the employer's business, in date order.",
        responses=with_errors({200: CalendarEventSerializer(many=True)}, bad_request=False),
    ),
    retrieve=extend_schema(
        summary="Retrieve one calendar event",
        description="One company calendar event, including who it was addressed to. Scoped to the "
                    "employer's own business; another business's record returns 404.",
        responses=with_errors({200: CalendarEventSerializer}, bad_request=False, not_found=True),
    ),
    create=extend_schema(
        summary="Create a calendar event",
        description="Leave `all_employees` true to invite the whole business, or set it to "
                    "false and list the invitees in `employee_ids`. For a single-day event the "
                    "end time must be later than the start time.",
        responses=with_errors({201: CalendarEventSerializer}),
        examples=[
            OpenApiExample(
                "Everyone",
                request_only=True,
                value={"title": "All-hands meeting", "category": "meeting", "date": "2026-10-15",
                       "start_time": "09:00:00", "end_time": "10:00:00",
                       "location": "Main boardroom", "all_employees": True},
            ),
            OpenApiExample(
                "Named invitees",
                request_only=True,
                value={"title": "Payroll training", "category": "training", "date": "2026-10-20",
                       "start_time": "14:00:00", "end_time": "16:00:00",
                       "all_employees": False, "employee_ids": [1, 2]},
            ),
        ],
    ),
    update=extend_schema(
        summary="Replace a calendar event",
        description="Every writable field must be supplied; use PATCH to change only some of "
                    "them. Scoped to the employer's own business; another business's record "
                    "returns 404.",
        responses=with_errors({200: CalendarEventSerializer}, not_found=True),
    ),
    partial_update=extend_schema(
        summary="Update a calendar event",
        description="Send only the fields that change. Scoped to the employer's own business; "
                    "another business's record returns 404.",
        responses=with_errors({200: CalendarEventSerializer}, not_found=True),
    ),
    destroy=extend_schema(
        summary="Delete a calendar event",
        description="Removes the event from the company calendar for everyone it was addressed "
                    "to. Scoped to the employer's own business; another business's record returns "
                    "404.",
        responses=with_errors(
            {204: OpenApiResponse(description="Deleted. No body.")}, not_found=True),
    ),
)
class CalendarEventViewSet(ManagerViewSet):
    queryset = CalendarEvent.objects.all()
    serializer_class = CalendarEventSerializer


def _money_field():
    return serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)


PAYMENT_BREAKDOWN_FIELDS = {
    "status": serializers.CharField(help_text="unpaid, draft or paid."),
    "payroll": serializers.IntegerField(allow_null=True),
    "paid_date": serializers.DateField(allow_null=True),
    "monthly_salary": _money_field(), "advance_deductions": _money_field(), "asset_deductions": _money_field(),
    "other_deductions": _money_field(), "total_deductions": _money_field(), "net_salary": _money_field(),
    "lines": serializers.ListField(child=serializers.DictField()),
}


@extend_schema(tags=["Employer · Payroll"])
@extend_schema_view(
    list=extend_schema(
        summary="List monthly salaries",
        description="One salary per employee. Supported currencies: RWF, ZAR, USD, EUR, GBP, "
                    "BWP, NAD, LSL, SZL, KES, NGN.",
        responses=with_errors({200: SalarySerializer(many=True)}, bad_request=False),
    ),
    retrieve=extend_schema(
        summary="Retrieve one salary",
        description="One employee's salary record for a month, with its components and whether it "
                    "has been marked paid. Scoped to the employer's own business; another "
                    "business's record returns 404.",
        responses=with_errors({200: SalarySerializer}, bad_request=False, not_found=True),
    ),
    create=extend_schema(
        summary="Set an employee's salary",
        description="Each employee has at most one salary record.",
        responses=with_errors({201: SalarySerializer}),
        examples=[OpenApiExample(
            "Monthly salary",
            request_only=True,
            value={"employee": 1, "monthly_amount": "850000.00", "currency": "RWF",
                   "effective_date": "2026-01-01", "notes": ""},
        )],
    ),
    update=extend_schema(
        summary="Replace a salary",
        description="Every writable field must be supplied; use PATCH to change only some of "
                    "them. Scoped to the employer's own business; another business's record "
                    "returns 404.",
        responses=with_errors({200: SalarySerializer}, not_found=True),
    ),
    partial_update=extend_schema(
        summary="Update a salary",
        description="Send only the fields that change. Scoped to the employer's own business; "
                    "another business's record returns 404.",
        responses=with_errors({200: SalarySerializer}, not_found=True),
    ),
    destroy=extend_schema(
        summary="Delete a salary",
        description="Removes the salary record. Any payslip already generated from it is removed "
                    "with it. Scoped to the employer's own business; another business's record "
                    "returns 404.",
        responses=with_errors(
            {204: OpenApiResponse(description="Deleted. No body.")}, not_found=True),
    ),
    mark_paid=extend_schema(
        summary="Pay a month from the salary record",
        description="Creates a **paid** payroll record covering a whole calendar month, using "
                    "this salary as the base pay. Both fields are optional: `month` defaults to "
                    "the current month and `paid_date` to today. The deductions shown by "
                    "**payment_preview** are applied automatically and their balances updated. "
                    "Rejected if payroll already covers any part of that month, or if the "
                    "employee is inactive.",
        request=inline_serializer(
            name="SalaryMarkPaidRequest",
            fields={
                "month": serializers.CharField(
                    required=False, help_text="The month to pay, as YYYY-MM. Defaults to this month."),
                "paid_date": serializers.DateField(
                    required=False, help_text="The payment date. Defaults to today."),
            },
        ),
        responses=with_errors({201: PayrollSerializer}, not_found=True),
        examples=[OpenApiExample("Pay October 2026", request_only=True,
                                 value={"month": "2026-10", "paid_date": "2026-10-28"})],
    ),
    payment_preview=extend_schema(
        summary="Preview a month's salary payment",
        description="For an unpaid month, the automatic deductions **mark_paid** would apply: "
                    "salary advance installments and authorized recoveries for resolved asset "
                    "incidents, together capped by the business's deduction limit. Nothing is "
                    "saved. For a month a payroll record already covers, the saved breakdown of "
                    "that record is returned unchanged.",
        parameters=[OpenApiParameter("month", str, description="The month as YYYY-MM. Defaults to this month.")],
        responses=with_errors({200: inline_serializer(name="SalaryPaymentPreview", fields={
            "employee": serializers.IntegerField(), "employee_name": serializers.CharField(),
            "month": serializers.CharField(), "currency": serializers.CharField(),
            **PAYMENT_BREAKDOWN_FIELDS,
            "limit_percent": serializers.DecimalField(max_digits=5, decimal_places=2),
            "warnings": serializers.ListField(child=serializers.CharField()),
            "already_paid": serializers.BooleanField(),
        })}, not_found=True),
    ),
    payment_history=extend_schema(
        summary="Monthly payment history for a salary",
        description="One row per month, newest first, from the salary's effective month (or the "
                    "employee's earliest payroll record) to the current month. Paid and draft "
                    "months carry their saved breakdown; unpaid months carry none.",
        responses=with_errors({200: inline_serializer(name="SalaryPaymentHistory", fields={
            "employee": serializers.IntegerField(), "employee_name": serializers.CharField(),
            "currency": serializers.CharField(),
            "months": inline_serializer(name="SalaryPaymentMonth", many=True, fields={
                "month": serializers.CharField(), **PAYMENT_BREAKDOWN_FIELDS}),
        })}, bad_request=False, not_found=True),
    ),
)
class SalaryViewSet(ManagerViewSet):
    queryset = Salary.objects.select_related("employee").order_by("employee__last_name", "id")
    serializer_class = SalarySerializer

    @staticmethod
    def pay_period(month):
        try:
            year, index = int(str(month)[:4]), int(str(month)[5:7])
            last_day = monthrange(year, index)[1]
        except (IndexError, TypeError, ValueError):
            raise serializers.ValidationError({"month": "Use a YYYY-MM month."})
        return f"{year:04d}-{index:02d}-01", f"{year:04d}-{index:02d}-{last_day:02d}"

    @staticmethod
    def saved_payment(payroll):
        """The breakdown stored with a payroll record. Never recalculated."""
        calculation = getattr(payroll, "calculation", None)
        zero = Decimal("0.00")
        if calculation is not None and payroll_rules.calculation_is_current(payroll):
            advance, asset = calculation.advance_deductions, calculation.asset_deductions
            lines = [{"kind": line.kind, "name": line.name, "amount": str(line.amount)}
                     for line in calculation.lines.all() if line.amount > 0]
        else:
            advance = asset = zero
            lines = [{"kind": "other", "name": "Deductions", "amount": str(payroll.deductions)}] if payroll.deductions else []
        return {
            "status": payroll.status, "payroll": payroll.pk, "paid_date": payroll.paid_date,
            "monthly_salary": str(payroll.gross_pay), "advance_deductions": str(advance),
            "asset_deductions": str(asset), "other_deductions": str(payroll.deductions - advance - asset),
            "total_deductions": str(payroll.deductions), "net_salary": str(payroll.net_pay), "lines": lines,
        }

    @action(detail=True, methods=["get"])
    def payment_preview(self, request, pk=None):
        salary = self.get_object()
        month = request.query_params.get("month") or str(timezone.localdate())[:7]
        period_start, period_end = self.pay_period(month)
        policy = payroll_rules.payroll_policy(salary.employee.business_id)
        body = {"employee": salary.employee_id, "employee_name": str(salary.employee), "month": month[:7],
                "limit_percent": str(policy.advance_deduction_limit_percent)}
        existing = (Payroll.objects.filter(employee=salary.employee, period_start__lte=period_end,
                                           period_end__gte=period_start)
                    .select_related("calculation").prefetch_related("calculation__lines").order_by("period_start").first())
        if existing is not None:
            return Response({**body, "currency": existing.currency, **self.saved_payment(existing),
                             "warnings": [], "already_paid": existing.status == "paid"})
        payroll = Payroll(employee=salary.employee, period_start=date.fromisoformat(period_start),
                          period_end=date.fromisoformat(period_end), base_salary=salary.monthly_amount,
                          allowances=Decimal("0"), deductions=Decimal("0"), currency=salary.currency)
        result = payroll_rules.calculate_payroll(payroll, Decimal("0"))
        return Response({
            **body, "currency": salary.currency, "status": "unpaid", "payroll": None, "paid_date": None,
            "monthly_salary": str(result["gross_pay"]), "asset_deductions": str(result["asset_deductions"]),
            "advance_deductions": str(result["advance_deductions"]), "other_deductions": "0.00",
            "total_deductions": str(result["total_deductions"]), "net_salary": str(result["net_pay"]),
            "lines": [{"kind": line["kind"], "name": line["name"], "amount": str(line["amount"])}
                      for line in result["lines"]],
            "warnings": result["warnings"],
            "already_paid": False,
        })

    @classmethod
    def monthly_payments(cls, employee, since, paid_only=False):
        """One row per month, newest first, from `since` to the latest of today and any payroll."""
        payrolls = Payroll.objects.filter(employee=employee)
        if paid_only:
            payrolls = payrolls.filter(status="paid")
        payrolls = list(payrolls.select_related("calculation").prefetch_related("calculation__lines")
                        .order_by("period_start"))
        first = min([since] + [row.period_start for row in payrolls]).replace(day=1)
        cursor = max([timezone.localdate()] + [row.period_end for row in payrolls]).replace(day=1)
        months = []
        while cursor >= first and len(months) < 120:
            end = cursor.replace(day=monthrange(cursor.year, cursor.month)[1])
            covering = next((row for row in payrolls if row.period_start <= end and row.period_end >= cursor), None)
            months.append({"month": f"{cursor:%Y-%m}", **(cls.saved_payment(covering) if covering else {
                "status": "unpaid", "payroll": None, "paid_date": None, "monthly_salary": None,
                "advance_deductions": None, "asset_deductions": None, "other_deductions": None,
                "total_deductions": None, "net_salary": None, "lines": []})})
            cursor = (cursor - timedelta(days=1)).replace(day=1)
        return months

    @action(detail=True, methods=["get"])
    def payment_history(self, request, pk=None):
        salary = self.get_object()
        return Response({"employee": salary.employee_id, "employee_name": str(salary.employee),
                         "currency": salary.currency,
                         "months": self.monthly_payments(salary.employee, salary.effective_date)})

    @action(detail=True, methods=["post"])
    def mark_paid(self, request, pk=None):
        salary = self.get_object()
        if not salary.employee.is_active:
            raise serializers.ValidationError("This employee is inactive. Reactivate the profile before recording payment.")
        paid_date = request.data.get("paid_date") or timezone.localdate()
        month = request.data.get("month") or str(timezone.localdate())[:7]
        period_start, period_end = self.pay_period(month)
        data = {
            "employee": salary.employee_id,
            "period_start": period_start, "period_end": period_end,
            "base_salary": salary.monthly_amount, "allowances": "0", "deductions": "0",
            "currency": salary.currency, "status": "paid", "paid_date": paid_date,
            "notes": f"Recorded from the salaries page using the monthly salary effective {salary.effective_date}.",
        }
        context = self.get_serializer_context()
        with transaction.atomic():
            # Serialises concurrent payments for the same employee so a month is never paid twice.
            Employee.objects.select_for_update().filter(pk=salary.employee_id).first()
            if Payroll.objects.filter(employee=salary.employee, period_start__lte=period_end, period_end__gte=period_start).exists():
                raise serializers.ValidationError(
                    {"detail": f"{salary.employee} already has a payroll record covering {month}. Open Payroll to review it."}
                )
            checked = PayrollSerializer(context=context, data=data)
            checked.is_valid(raise_exception=True)
            draft = PayrollSerializer(context=context, data={**data, "status": "draft", "paid_date": None})
            draft.is_valid(raise_exception=True)
            draft.save()
            payroll, _ = payroll_rules.apply_payroll_calculation(
                draft.instance.pk, other_deductions=Decimal("0"),
                calculated_by=request.user.get_full_name().strip() or request.user.username)
            payroll.status, payroll.paid_date = "paid", checked.validated_data["paid_date"]
            payroll.save(update_fields=["status", "paid_date"])
        return Response(PayrollSerializer(payroll, context=context).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["Employer · Payroll"])
@extend_schema_view(
    list=extend_schema(
        summary="List payroll records",
        description="Payslip records for the employer's own employees, most recent period "
                    "first. `gross_pay` and `net_pay` are computed, and the employee's name, "
                    "email, department and job title are snapshotted when the record is written.",
        responses=with_errors({200: PayrollSerializer(many=True)}, bad_request=False),
    ),
    retrieve=extend_schema(
        summary="Retrieve one payroll record",
        description="One payroll run for an employee and month, with the payslip figures it was "
                    "generated from. Scoped to the employer's own business; another business's "
                    "record returns 404.",
        responses=with_errors({200: PayrollSerializer}, bad_request=False, not_found=True),
    ),
    create=extend_schema(
        summary="Create a payroll record",
        description="Periods may not overlap for the same employee, deductions may not exceed "
                    "gross pay, and `paid_date` is required when `status` is `paid` (and "
                    "forbidden when it is `draft`).",
        responses=with_errors({201: PayrollSerializer}),
        examples=[OpenApiExample(
            "Draft payslip",
            request_only=True,
            value={"employee": 1, "period_start": "2026-10-01", "period_end": "2026-10-31",
                   "base_salary": "850000.00", "allowances": "50000.00",
                   "deductions": "120000.00", "currency": "RWF", "status": "draft"},
        )],
    ),
    update=extend_schema(
        summary="Replace a draft payroll record",
        description="A record with `status: paid` is locked to preserve the issued payslip.",
        responses=with_errors({200: PayrollSerializer}, not_found=True),
    ),
    partial_update=extend_schema(
        summary="Update a draft payroll record",
        description="A record with `status: paid` is locked to preserve the issued payslip.",
        responses=with_errors({200: PayrollSerializer}, not_found=True),
        examples=[OpenApiExample("Mark as paid", request_only=True,
                                 value={"status": "paid", "paid_date": "2026-10-28"})],
    ),
    destroy=extend_schema(
        summary="Delete a draft payroll record",
        description="Paid records cannot be deleted.",
        responses=with_errors(
            {204: OpenApiResponse(description="Deleted. No body.")}, not_found=True),
    ),
)
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


@extend_schema(
    tags=["Employer · Reports"],
    summary="Manager dashboard report",
    description=(
        "One roll-up for a single date: who is absent, who is on leave, who has no record at "
        "all, which contracts are expiring or already expired, month-to-date working hours per "
        "employee, and month-to-date payroll totals per currency.\n\n"
        "Every figure is scoped to the signed-in employer's business."
    ),
    parameters=[
        OpenApiParameter(
            name="date", type=OpenApiTypes.DATE, location=OpenApiParameter.QUERY,
            required=False,
            description="The day to report on. Defaults to today in the server time zone.",
            examples=[OpenApiExample("Today", value="2026-10-02")],
        ),
        OpenApiParameter(
            name="days", type=OpenApiTypes.INT, location=OpenApiParameter.QUERY,
            required=False,
            description="How many days ahead to look for expiring contracts. 1-365, default 30.",
            examples=[OpenApiExample("Next 30 days", value=30)],
        ),
    ],
    responses=with_errors({200: ManagerReportsSerializer}),
)
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
            "present_count": attendance.filter(status__in=["present", "remote"]).values("employee_id").distinct().count(),
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
