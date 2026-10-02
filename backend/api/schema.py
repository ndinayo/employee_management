"""Documentation-only helpers for the generated OpenAPI schema.

Nothing in this module takes part in handling a request. The serializers here
exist so drf-spectacular can describe responses that the views build as plain
dictionaries, and the hook at the bottom adds the one endpoint that is a plain
Django view rather than a DRF one.
"""
from drf_spectacular.extensions import OpenApiViewExtension
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework import serializers

from .models import Business, Contract, LeaveRequest

# Several models use a field called "status" with different choices, which would
# otherwise leave the generator naming two of them after a hash. Read straight
# off the models so these names cannot drift from the choices they describe;
# settings.SPECTACULAR_SETTINGS["ENUM_NAME_OVERRIDES"] points here.
CONTRACT_STATUS_CHOICES = Contract._meta.get_field("status").choices
LEAVE_STATUS_CHOICES = LeaveRequest._meta.get_field("status").choices
COMPANY_STATUS_CHOICES = Business.STATUSES


# --- Shared error shapes -----------------------------------------------------

class DetailSerializer(serializers.Serializer):
    """The single-message shape DRF uses for errors and simple confirmations."""

    detail = serializers.CharField(help_text="Human-readable message.")


class ValidationErrorSerializer(serializers.Serializer):
    """Rejected fields, as `{"field": ["message", ...]}`.

    Problems that belong to the whole object come back under `detail` instead.
    """

    field_name = serializers.ListField(
        child=serializers.CharField(),
        help_text="One entry per rejected field; the key is the field's own name.",
    )


# --- Accounts ----------------------------------------------------------------

class AccountSerializer(serializers.Serializer):
    """The signed-in account, as returned by `GET /api/account/`."""

    id = serializers.IntegerField()
    username = serializers.CharField()
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=["admin", "employer", "manager", "employee"])
    display_name = serializers.CharField(help_text="Full name when set, otherwise the username.")
    role_label = serializers.CharField(help_text="The role spelled out for display, e.g. Employer.")
    business_name = serializers.CharField(allow_blank=True)
    can_manage = serializers.BooleanField(help_text="True for employers and legacy staff managers.")
    can_admin = serializers.BooleanField(help_text="True only for platform administrators.")
    must_change_password = serializers.BooleanField(
        help_text="True until an invited account replaces its temporary password.")
    has_employee_record = serializers.BooleanField(
        help_text="True when an employer has linked this account to an Employee row.")
    has_signed_contract = serializers.BooleanField()
    workspace_approved = serializers.BooleanField(
        help_text="True once the employer approves the signed contract. The /api/me/... "
                  "endpoints stay 403 until this is true.")
    email_configured = serializers.BooleanField(
        help_text="Employers only: whether invitation email can actually be delivered.")


class TokenPairSerializer(serializers.Serializer):
    """A freshly issued JWT pair."""

    access = serializers.CharField(
        help_text="Send as `Authorization: Bearer <access>`. Valid for 30 minutes.")
    refresh = serializers.CharField(
        help_text="Exchange at /api/token/refresh/ for a new access token. Valid for 1 day.")


class AuthenticatedAccountSerializer(TokenPairSerializer):
    """A JWT pair plus the account it was issued for."""

    user = AccountSerializer()


class EmailSettingsResponseSerializer(serializers.Serializer):
    """The shared invitation-email sender, as returned by /api/account/email/."""

    email_configured = serializers.BooleanField(
        help_text="Whether invitation email can be delivered right now.")
    email_host = serializers.CharField()
    email_port = serializers.IntegerField()
    email_use_tls = serializers.BooleanField()
    email_host_user = serializers.EmailField(allow_blank=True)
    can_manage_email_settings = serializers.BooleanField(
        help_text="False when another business already owns the shared sender.")
    shared_sender = serializers.BooleanField(
        help_text="Always true: a single sender serves the whole platform.")
    detail = serializers.CharField(required=False, help_text="Present only after a successful PATCH.")


class LatestContractSerializer(serializers.Serializer):
    """The most recently uploaded contract document for an employee."""

    id = serializers.IntegerField()
    employee = serializers.IntegerField()
    employee_name = serializers.CharField()
    title = serializers.CharField()
    document_name = serializers.CharField(help_text="The stored file name, without its directory.")
    start_date = serializers.DateField()
    end_date = serializers.DateField(allow_null=True)
    status = serializers.CharField()


# --- Platform administration -------------------------------------------------

class AdminBusinessSerializer(serializers.Serializer):
    """A company, as listed for the administrator."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    created_at = serializers.CharField(help_text="When the company was opened. Empty if unknown.")
    employer_username = serializers.CharField(help_text="The company's employer sign-in. Empty if it has none.")
    employer_email = serializers.CharField()
    employer_is_active = serializers.BooleanField(help_text="False while the employer is suspended.")
    employee_count = serializers.IntegerField()
    active_employee_count = serializers.IntegerField()


class EmployerResponseSerializer(serializers.Serializer):
    """An employer account and its workspace. Richer than the write payload."""

    id = serializers.IntegerField(help_text="The Django user id, which is also the path id.")
    username = serializers.CharField()
    email = serializers.EmailField()
    business_id = serializers.IntegerField()
    business_name = serializers.CharField()
    is_active = serializers.BooleanField()
    date_joined = serializers.CharField(help_text="Local-time ISO 8601 timestamp, or an empty string.")
    last_login = serializers.CharField(
        help_text="Local-time ISO 8601 timestamp, or an empty string if they have never signed in.")
    workspace_started = serializers.CharField(help_text="When the business was created.")
    email_configured = serializers.BooleanField()
    employee_count = serializers.IntegerField()
    active_employee_count = serializers.IntegerField()


class InviteResultSerializer(serializers.Serializer):
    """What happened to a new employee's sign-in account and invitation email."""

    created = serializers.BooleanField()
    email_sent = serializers.BooleanField()
    username = serializers.CharField(required=False)
    detail = serializers.CharField()
    temporary_password = serializers.CharField(
        required=False,
        help_text="Returned only when the invitation email could not be sent, so the "
                  "employer can pass the password on themselves.")


class AdminEmployeeResponseSerializer(serializers.Serializer):
    """An employee row as the administrator sees it, across all businesses."""

    id = serializers.IntegerField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    email = serializers.EmailField()
    job_title = serializers.CharField()
    is_active = serializers.BooleanField()
    business = serializers.IntegerField()
    business_name = serializers.CharField(allow_blank=True)
    account_status = serializers.ChoiceField(
        choices=["none", "pending_first_sign_in", "active"],
        help_text="`none` when no sign-in account exists yet.")
    username = serializers.CharField(allow_blank=True)
    invite = InviteResultSerializer(
        allow_null=True, help_text="Populated only on the POST that created the employee.")


# --- Employer: contract actions ---------------------------------------------

class NotificationSerializer(serializers.Serializer):
    """Whether the matching notification email left the server."""

    email_sent = serializers.BooleanField()
    detail = serializers.CharField()


# --- Employee workspace ------------------------------------------------------

class MyAttendanceStateSerializer(serializers.Serializer):
    """The signed-in employee's clock state for one workday."""

    date = serializers.DateField(help_text="The workday the shifts below belong to.")
    attendance = serializers.DictField(
        allow_null=True,
        help_text="The selected shift's record, or null before the first check-in.")
    shifts = serializers.ListField(
        child=serializers.DictField(), help_text="Every shift recorded on `date`.")
    total_hours = serializers.CharField(
        help_text="Hours across all shifts on `date`, as a 2-decimal string.")


class MyLeaveOverviewSerializer(serializers.Serializer):
    """This year's allocations plus the employee's own leave requests."""

    year = serializers.IntegerField()
    balances = serializers.ListField(child=serializers.DictField())
    requests = serializers.ListField(child=serializers.DictField())


# --- Employer: reports -------------------------------------------------------

class PayrollTotalSerializer(serializers.Serializer):
    """Month-to-date payroll totals for one currency. Every amount is a string."""

    currency = serializers.CharField()
    gross = serializers.CharField()
    deductions = serializers.CharField()
    net = serializers.CharField()
    paid = serializers.CharField()
    draft = serializers.CharField()


class WorkingHoursSerializer(serializers.Serializer):
    """Hours one employee has worked since the start of the month."""

    employee_id = serializers.IntegerField()
    employee_name = serializers.CharField()
    hours = serializers.CharField(help_text="A 2-decimal string.")


class ManagerReportsSerializer(serializers.Serializer):
    """The manager dashboard roll-up for a single date."""

    date = serializers.DateField(help_text="The date the report was built for.")
    contract_window_end = serializers.DateField(
        help_text="`date` plus `days`; the end of the contract-expiry window.")
    month_start = serializers.DateField()
    working_day = serializers.BooleanField(help_text="False at weekends and on company holidays.")
    active_employees = serializers.IntegerField()
    departments = serializers.IntegerField()
    present_count = serializers.IntegerField(help_text="Distinct employees recorded present or remote.")
    pending_leave_count = serializers.IntegerField()
    absent = serializers.ListField(child=serializers.DictField(), help_text="Attendance marked absent.")
    on_leave = serializers.ListField(child=serializers.DictField(), help_text="Approved leave covering `date`.")
    unrecorded = serializers.ListField(
        child=serializers.DictField(),
        help_text="Active employees with neither attendance nor leave on a working day.")
    holidays = serializers.ListField(child=serializers.DictField())
    expiring_contracts = serializers.ListField(child=serializers.DictField())
    expired_contracts = serializers.ListField(child=serializers.DictField())
    working_hours = WorkingHoursSerializer(many=True)
    payroll_totals = PayrollTotalSerializer(many=True)


# --- Reusable error responses ------------------------------------------------

RESPONSE_400 = OpenApiResponse(
    response=ValidationErrorSerializer,
    description="The payload was rejected. Field errors are keyed by field name; "
                "whole-object errors come back under `detail`.",
)
RESPONSE_401 = OpenApiResponse(
    response=DetailSerializer,
    description="No access token was sent, or it has expired. Obtain one from /api/token/.",
    examples=[OpenApiExample(
        "Missing token", value={"detail": "Authentication credentials were not provided."})],
)
RESPONSE_403_MANAGER = OpenApiResponse(
    response=DetailSerializer,
    description="The signed-in account is not an employer or manager.",
    examples=[OpenApiExample(
        "Wrong role", value={"detail": "Employer or manager access is required."})],
)
RESPONSE_403_ADMIN = OpenApiResponse(
    response=DetailSerializer,
    description="The signed-in account is not a platform administrator.",
    examples=[OpenApiExample(
        "Wrong role", value={"detail": "Administrator access is required."})],
)
RESPONSE_403_WORKSPACE = OpenApiResponse(
    response=DetailSerializer,
    description="The account has no linked employee record, or the employer has not yet "
                "approved its signed contract.",
    examples=[OpenApiExample("Not approved yet", value={
        "detail": "Your employer must approve your signed contract before you can access "
                  "the employee workspace."})],
)
RESPONSE_404 = OpenApiResponse(
    response=DetailSerializer,
    description="No such record, or it belongs to another business.",
    examples=[OpenApiExample("Not found", value={"detail": "No Employee matches the given query."})],
)


def with_errors(success, *, forbidden=RESPONSE_403_MANAGER, bad_request=True, not_found=False):
    """Merge the shared error responses into an operation's success responses.

    `success` maps status code to response, e.g. `{200: EmployeeSerializer(many=True)}`.
    """
    responses = dict(success)
    if bad_request:
        responses[400] = RESPONSE_400
    responses[401] = RESPONSE_401
    if forbidden is not None:
        responses[403] = forbidden
    if not_found:
        responses[404] = RESPONSE_404
    return responses


# --- Non-DRF endpoints -------------------------------------------------------

HEALTH_PATH = {
    "/api/health/": {
        "get": {
            "operationId": "health_retrieve",
            "tags": ["Health"],
            "summary": "Service readiness",
            "description": (
                "Readiness probe. Runs `SELECT 1` against the database and is exempt from the "
                "HTTPS redirect so a load balancer can reach it over plain HTTP.\n\n"
                "This is a plain Django view rather than a DRF one, so it is described by hand "
                "here instead of being introspected."
            ),
            "security": [{}],
            "responses": {
                "200": {
                    "description": "The database answered.",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"status": {"type": "string", "enum": ["ok"]}},
                            },
                            "example": {"status": "ok"},
                        }
                    },
                },
                "503": {
                    "description": "The database could not be reached.",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"status": {"type": "string", "enum": ["unavailable"]}},
                            },
                            "example": {"status": "unavailable"},
                        }
                    },
                },
            },
        }
    }
}


class TokenRefreshDocumentation(OpenApiViewExtension):
    """Group and describe SimpleJWT's refresh view without subclassing it in urls.py.

    The view is wired up straight from `rest_framework_simplejwt.views`, so this
    extension swaps in an annotated subclass during schema generation only.
    """

    target_class = "rest_framework_simplejwt.views.TokenRefreshView"

    def view_replacement(self):
        @extend_schema(
            tags=["Authentication"],
            # As with the sign-in view, SimpleJWT declares no permissions.
            auth=[{}],
            summary="Refresh an access token",
            description=(
                "Exchange the `refresh` token from `/api/token/` (or `/api/signup/`) for a new "
                "`access` token. Access tokens last 30 minutes and refresh tokens one day, so "
                "once the refresh token expires the account has to sign in again."
            ),
            responses={
                200: TokenPairSerializer,
                400: RESPONSE_400,
                401: OpenApiResponse(
                    response=DetailSerializer,
                    description="The refresh token is invalid or has expired.",
                    examples=[OpenApiExample("Expired", value={
                        "detail": "Token is invalid or expired", "code": "token_not_valid"})]),
            },
        )
        class Fixed(self.target_class):  # type: ignore[misc]
            pass

        return Fixed


def add_non_drf_paths(result, generator, request, public):
    """Postprocessing hook: describe the endpoints the generator cannot see.

    `/api/health/` is a `@require_GET` Django view, so it never reaches
    drf-spectacular's DRF-based introspection.
    """
    paths = result.setdefault("paths", {})
    for path, operations in HEALTH_PATH.items():
        paths.setdefault(path, {}).update(operations)
    return result
