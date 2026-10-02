"""Platform administrator: every employer and every employee, across businesses."""
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (OpenApiExample, OpenApiParameter, OpenApiResponse,
                                   extend_schema, extend_schema_view)
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from . import onboarding
from .models import AccountProfile, Business, Employee, Holiday
from .permissions import IsAdmin
from .schema import (RESPONSE_401, RESPONSE_403_ADMIN, RESPONSE_404, AdminBusinessSerializer,
                     AdminEmployeeResponseSerializer,
                     EmployerResponseSerializer, with_errors)
from .serializers import EmployeeSerializer

# The platform endpoints are all administrator-only, so they share one set of
# error responses. Documentation only.
ADMIN_ID = OpenApiParameter(
    name="pk", type=OpenApiTypes.INT, location=OpenApiParameter.PATH, required=True,
    description="The record's numeric id.",
)


def admin_responses(success, **kwargs):
    return with_errors(success, forbidden=RESPONSE_403_ADMIN, **kwargs)


def account_status(employee):
    account = getattr(employee, "account", None)
    if not account:
        return "none"
    return "pending_first_sign_in" if account.must_change_password else "active"


def as_when(value):
    """The real timestamp, so the admin calendar day is not shifted by UTC."""
    if not value:
        return ""
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.isoformat()


class EmployerSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=128)
    business_name = serializers.CharField(max_length=200)
    is_active = serializers.BooleanField(required=False)
    employee_count = serializers.IntegerField(read_only=True)

    def validate(self, attrs):
        User = get_user_model()
        username = attrs.get("username") or (self.instance.username if self.instance else "")
        email = attrs.get("email") or (self.instance.email if self.instance else "")
        password = attrs.get("password") or ""
        if self.instance is None and not password:
            raise serializers.ValidationError({"password": "Enter a password for this employer."})
        if username and User.objects.filter(username__iexact=username).exclude(
                pk=getattr(self.instance, "pk", None)).exists():
            raise serializers.ValidationError({"username": "An account with this username already exists."})
        if email and User.objects.filter(email__iexact=email).exclude(
                pk=getattr(self.instance, "pk", None)).exists():
            if not onboarding.reclaim_email(email):
                raise serializers.ValidationError({"email": "An account already uses this email address."})
        if password:
            try:
                validate_password(password, User(username=username, email=email))
            except ValidationError as error:
                raise serializers.ValidationError({"password": error.messages})
        return attrs

    def to_representation(self, user):
        profile = user.account_profile
        business = profile.business
        employees = Employee.objects.filter(business=business)
        return {
            "id": user.pk, "username": user.username, "email": user.email,
            "business_id": profile.business_id, "business_name": business.name,
            "is_active": user.is_active,
            "date_joined": as_when(user.date_joined),
            "last_login": as_when(user.last_login),
            "workspace_started": as_when(business.created_at),
            "email_configured": onboarding.business_smtp(business),
            "employee_count": employees.count(),
            "active_employee_count": employees.filter(is_active=True).count(),
        }

    @transaction.atomic
    def create(self, validated_data):
        User = get_user_model()
        password = validated_data.pop("password")
        name = validated_data.pop("business_name").strip()
        business = Business.objects.create(name=name)
        user = User.objects.create_user(
            username=validated_data["username"], email=validated_data["email"], password=password)
        AccountProfile.objects.create(user=user, role="employer", business=business)
        return user

    @transaction.atomic
    def update(self, user, validated_data):
        if "username" in validated_data:
            user.username = validated_data["username"]
        if "email" in validated_data:
            user.email = validated_data["email"]
        if "is_active" in validated_data:
            user.is_active = validated_data["is_active"]
        if validated_data.get("password"):
            user.set_password(validated_data["password"])
        user.save()
        if "business_name" in validated_data:
            business = user.account_profile.business
            business.name = validated_data["business_name"].strip()
            business.save(update_fields=["name"])
        return user


class AdminEmployeeSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    business = serializers.PrimaryKeyRelatedField(queryset=Business.objects.all())
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100)
    job_title = serializers.CharField(max_length=100)
    email = serializers.EmailField()
    is_active = serializers.BooleanField(required=False)
    invite = serializers.DictField(read_only=True)

    def validate_email(self, value):
        business = self.initial_data.get("business") or getattr(getattr(self.instance, "business", None), "pk", None)
        duplicate = Employee.objects.filter(business_id=business, email__iexact=value)
        if self.instance:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise serializers.ValidationError("An employee with this email already exists in this business.")
        return value

    def to_representation(self, employee):
        account = getattr(employee, "account", None)
        data = {
            "id": employee.pk, "first_name": employee.first_name, "last_name": employee.last_name,
            "email": employee.email, "job_title": employee.job_title, "is_active": employee.is_active,
            "business": employee.business_id, "business_name": employee.business.name if employee.business_id else "",
            "account_status": account_status(employee),
            "username": account.user.username if account else "",
            "invite": getattr(employee, "_invite", None),
        }
        return data

    @transaction.atomic
    def create(self, validated_data):
        employee = Employee.objects.create(
            business=validated_data["business"], first_name=validated_data["first_name"],
            last_name=validated_data["last_name"], job_title=validated_data["job_title"],
            email=validated_data["email"], date_joined=timezone.localdate(),
            is_active=validated_data.get("is_active", True),
        )
        employee._invite = EmployeeSerializer().open_account(employee)
        return employee

    def update(self, employee, validated_data):
        for field in ("first_name", "last_name", "job_title", "email", "is_active"):
            if field in validated_data:
                setattr(employee, field, validated_data[field])
        if "business" in validated_data:
            employee.business = validated_data["business"]
        employee.save()
        return employee


@transaction.atomic
def set_company_status(business, status):
    """Move a company through its lifecycle.

    Suspending closes the workspace by deactivating the company's employer
    sign-ins, which is the same lever the per-employer switch uses; activating
    restores them. Nothing the company owns is deleted or edited.
    """
    if business.status == status:
        return business
    business.status = status
    business.status_changed_at = timezone.now()
    business.save(update_fields=["status", "status_changed_at"])
    if status in ("suspended", "active"):
        owners = AccountProfile.objects.filter(role="employer", business=business)
        get_user_model().objects.filter(
            pk__in=owners.values("user_id")).update(is_active=status == "active")
    return business


@transaction.atomic
def purge_business(business):
    """Remove a whole company: its employees, their accounts, its records and
    the employer sign-in that belongs to it. Business is the only unit the
    platform admin deletes; a company's employer is never removed on its own."""
    for employee in list(Employee.objects.filter(business=business)):
        onboarding.purge_employee(employee)
    Holiday.objects.filter(business=business).delete()
    # AccountProfile.business is one-to-one, so a company has at most one
    # employer, and it has to go before the business it protects.
    profile = getattr(business, "owner_profile", None)
    if profile:
        user = profile.user
        profile.delete()
        user.delete()
    business.delete()


@extend_schema(tags=["Platform administration"])
@extend_schema_view(
    get=extend_schema(
        operation_id="admin_employers_list",
        summary="List employers",
        description="Every employer account on the platform, with its business and employee "
                    "counts, ordered by username.",
        responses=admin_responses(
            {200: EmployerResponseSerializer(many=True)}, bad_request=False),
    ),
    post=extend_schema(
        operation_id="admin_employers_create",
        summary="Create an employer",
        description="Creates the business and the employer's sign-in account together. The "
                    "password is checked against Django's password validators.",
        request=EmployerSerializer,
        responses=admin_responses({201: EmployerResponseSerializer}),
        examples=[OpenApiExample(
            "New employer",
            request_only=True,
            value={"username": "kigali-books", "email": "owner@kigali-books.example",
                   "password": "S0me-strong-passphrase", "business_name": "Kigali Books Ltd"},
        )],
    ),
)
class EmployerListView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        users = get_user_model().objects.filter(account_profile__role="employer").select_related(
            "account_profile__business").order_by("username")
        return Response(EmployerSerializer(users, many=True).data)

    def post(self, request):
        serializer = EmployerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = serializer.save()
        except IntegrityError:
            raise serializers.ValidationError({"username": "An account with this username already exists."})
        return Response(EmployerSerializer(user).data, status=201)


@extend_schema(tags=["Platform administration"], parameters=[ADMIN_ID])
@extend_schema_view(
    get=extend_schema(
        operation_id="admin_employers_retrieve",
        summary="Retrieve an employer",
        description="One employer account with its business, employee counts, sign-in history and "
                    "whether invitation email is set up.",
        responses=admin_responses(
            {200: EmployerResponseSerializer}, bad_request=False, not_found=True),
    ),
    patch=extend_schema(
        operation_id="admin_employers_partial_update",
        summary="Update an employer",
        description="Send only the fields that change. A new `password` is validated and "
                    "replaces the old one; `is_active: false` suspends the account without "
                    "deleting anything.",
        request=EmployerSerializer,
        responses=admin_responses({200: EmployerResponseSerializer}, not_found=True),
        examples=[OpenApiExample("Suspend", request_only=True, value={"is_active": False})],
    ),
)
class EmployerDetailView(APIView):
    permission_classes = [IsAdmin]

    def get_user(self, pk):
        try:
            return get_user_model().objects.select_related("account_profile__business").get(
                pk=pk, account_profile__role="employer")
        except get_user_model().DoesNotExist:
            raise NotFound("That employer was not found.")

    def get(self, request, pk):
        return Response(EmployerSerializer(self.get_user(pk)).data)

    def patch(self, request, pk):
        user = self.get_user(pk)
        serializer = EmployerSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return Response(EmployerSerializer(serializer.save()).data)


@extend_schema(tags=["Platform administration"])
@extend_schema_view(
    get=extend_schema(
        operation_id="admin_employees_list",
        summary="List every employee",
        description="Employees across all businesses, ordered by surname.",
        responses=admin_responses(
            {200: AdminEmployeeResponseSerializer(many=True)}, bad_request=False),
    ),
    post=extend_schema(
        operation_id="admin_employees_create",
        summary="Add an employee to a business",
        description="Creates the employee in the named business and opens their sign-in "
                    "account, the same way an employer hiring them would. The result of the "
                    "invitation is in `invite`.",
        request=AdminEmployeeSerializer,
        responses=admin_responses({201: AdminEmployeeResponseSerializer}),
        examples=[OpenApiExample(
            "New employee",
            request_only=True,
            value={"business": 1, "first_name": "Amina", "last_name": "Uwase",
                   "job_title": "Accountant", "email": "amina.uwase@example.com"},
        )],
    ),
)
class AdminEmployeeListView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        rows = Employee.objects.select_related("business", "account__user").order_by("last_name", "first_name", "id")
        return Response(AdminEmployeeSerializer(rows, many=True).data)

    def post(self, request):
        serializer = AdminEmployeeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(AdminEmployeeSerializer(serializer.save()).data, status=201)


@extend_schema(tags=["Platform administration"], parameters=[ADMIN_ID])
@extend_schema_view(
    get=extend_schema(
        operation_id="admin_employees_retrieve",
        summary="Retrieve an employee",
        description="One employee from any business on the platform, with their business and the "
                    "state of their sign-in account.",
        responses=admin_responses(
            {200: AdminEmployeeResponseSerializer}, bad_request=False, not_found=True),
    ),
    patch=extend_schema(
        operation_id="admin_employees_partial_update",
        summary="Update an employee",
        description="Send only the fields that change. `business` may be used to move the "
                    "employee to another business.",
        request=AdminEmployeeSerializer,
        responses=admin_responses({200: AdminEmployeeResponseSerializer}, not_found=True),
        examples=[OpenApiExample("Deactivate", request_only=True, value={"is_active": False})],
    ),
    delete=extend_schema(
        operation_id="admin_employees_destroy",
        summary="Delete an employee",
        description="Removes the employee, their sign-in account and all of their records.",
        responses=admin_responses(
            {204: OpenApiResponse(description="Deleted. No body.")},
            bad_request=False, not_found=True),
    ),
)
class AdminEmployeeDetailView(APIView):
    permission_classes = [IsAdmin]

    def get_employee(self, pk):
        try:
            return Employee.objects.select_related("business", "account__user").get(pk=pk)
        except Employee.DoesNotExist:
            raise NotFound("That employee was not found.")

    def get(self, request, pk):
        return Response(AdminEmployeeSerializer(self.get_employee(pk)).data)

    def patch(self, request, pk):
        employee = self.get_employee(pk)
        serializer = AdminEmployeeSerializer(employee, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return Response(AdminEmployeeSerializer(serializer.save()).data)

    def delete(self, request, pk):
        onboarding.purge_employee(self.get_employee(pk))
        return Response(status=204)


@extend_schema(
    tags=["Platform administration"],
    summary="List companies",
    description="Every company on the platform, ordered by name, with its employer and "
                "employee counts. Also fills in the `business` field when creating an employee.",
    responses=admin_responses({200: AdminBusinessSerializer(many=True)}, bad_request=False),
)
class AdminBusinessListView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        rows = Business.objects.select_related("owner_profile__user").order_by("name")
        employees = Employee.objects.values("business_id", "is_active")
        counts = {}
        for row in employees:
            total, active = counts.get(row["business_id"], (0, 0))
            counts[row["business_id"]] = (total + 1, active + (1 if row["is_active"] else 0))
        return Response([_company(row, *counts.get(row.pk, (0, 0))) for row in rows])


def _company(business, employee_count, active_employee_count):
    profile = getattr(business, "owner_profile", None)
    return {
        "id": business.pk, "name": business.name,
        "status": business.status,
        "status_changed_at": as_when(business.status_changed_at),
        "created_at": as_when(business.created_at),
        "employer_username": profile.user.username if profile else "",
        "employer_email": profile.user.email if profile else "",
        "employer_is_active": bool(profile and profile.user.is_active),
        "employee_count": employee_count,
        "active_employee_count": active_employee_count,
        "last_login_at": as_when(profile.user.last_login) if profile else "",
    }


class BusinessStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Business.STATUSES)


@extend_schema(tags=["Platform administration"], parameters=[ADMIN_ID])
@extend_schema_view(
    patch=extend_schema(
        operation_id="admin_businesses_partial_update",
        summary="Change a company's status",
        description="Moves the company through its lifecycle. `suspended` also deactivates "
                    "its employer sign-ins, so the workspace closes immediately; moving back "
                    "to `active` restores them. `pending` marks a company as awaiting "
                    "verification and is a queue for the administrator; it does not close the "
                    "workspace. Nothing in the company's records is touched either way.",
        request=BusinessStatusSerializer,
        responses=admin_responses({200: AdminBusinessSerializer}, not_found=True),
        examples=[OpenApiExample("Suspend a company", request_only=True,
                                 value={"status": "suspended"})],
    ),
    delete=extend_schema(
        operation_id="admin_businesses_destroy",
        summary="Delete a company",
        description="Permanently removes the company, its employer sign-in, every employee in "
                    "it and all of their records. This is the only deletion the platform admin "
                    "performs at this level: an employer account cannot be deleted on its own, "
                    "only suspended. There is no undo.",
        responses=admin_responses(
            {204: OpenApiResponse(description="Deleted. No body.")},
            bad_request=False, not_found=True),
    ),
)
class AdminBusinessDetailView(APIView):
    permission_classes = [IsAdmin]

    def get_business(self, pk):
        try:
            return Business.objects.select_related("owner_profile__user").get(pk=pk)
        except Business.DoesNotExist:
            raise NotFound("That company was not found.")

    def patch(self, request, pk):
        business = self.get_business(pk)
        serializer = BusinessStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        set_company_status(business, serializer.validated_data["status"])
        employees = Employee.objects.filter(business=business)
        return Response(_company(business, employees.count(),
                                 employees.filter(is_active=True).count()))

    def delete(self, request, pk):
        purge_business(self.get_business(pk))
        return Response(status=204)
