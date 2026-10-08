import base64
import binascii
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
from io import BytesIO

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.password_validation import validate_password
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (OpenApiExample, OpenApiParameter, OpenApiResponse,
                                   extend_schema, extend_schema_field, extend_schema_view)
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from PIL import Image, UnidentifiedImageError

from . import leave_management, onboarding
from .models import (AccountProfile, Announcement, AnnouncementRead, Attendance, Business,
                     CalendarEvent, CalendarEventRead, Contract, ContractTerminationRequest, Employee,
                     InvitationEmailSettings, LeaveBalance, LeaveRequest)
from .permissions import can_manage, is_admin
from .schema import (RESPONSE_400, RESPONSE_401, RESPONSE_403_WORKSPACE, AccountSerializer,
                     AuthenticatedAccountSerializer, DetailSerializer,
                     EmailSettingsResponseSerializer, MyAttendanceStateSerializer,
                     MyLeaveOverviewSerializer, TokenPairSerializer, with_errors)
from .serializers import ContractTerminationSerializer, LeaveBalanceSerializer

# Documentation-only helpers. None of this takes part in handling a request.
RECORD_ID = OpenApiParameter(
    name="pk", type=OpenApiTypes.INT, location=OpenApiParameter.PATH, required=True,
    description="The record's numeric id.",
)
RESPONSE_429 = OpenApiResponse(
    response=DetailSerializer,
    description="Rate limit reached for this client address.",
    examples=[OpenApiExample("Throttled", value={
        "detail": "Request was throttled. Expected available in 3600 seconds."})],
)


def workspace_responses(success, **kwargs):
    """Error responses for the employee workspace, where 403 means not yet approved."""
    return with_errors(success, forbidden=RESPONSE_403_WORKSPACE, **kwargs)


def employee_record(user):
    """The Employee row an employer created for this account, if any."""
    profile = getattr(user, "account_profile", None)
    return profile.employee if profile and profile.employee_id else None


def employee_has_signed_contract(employee):
    return bool(employee and Contract.objects.filter(employee=employee, signature_status="signed").exists())


def employee_has_approved_contract(employee):
    return bool(employee and Contract.objects.filter(
        employee=employee, signature_status="signed", worker_approval_status="approved",
    ).exists())


def require_signed_contract(employee):
    if not employee_has_approved_contract(employee):
        raise PermissionDenied("Your employer must approve your signed contract before you can access the employee workspace.")
    return employee


def business_name_for(profile, employee):
    if profile and profile.business_id:
        return profile.business.name
    if employee and employee.business_id:
        return employee.business.name
    return ""


def account_data(user):
    profile = getattr(user, "account_profile", None)
    manager = can_manage(user)
    admin = is_admin(user)
    employee = employee_record(user)
    business = getattr(profile, "business", None) if profile else None
    role = profile.role if profile else ("manager" if manager else "employee")
    display_name = user.get_full_name().strip() or user.username
    role_label = {"admin": "Administrator", "employer": "Employer", "manager": "Manager",
                  "employee": "Employee"}.get(role, role.title())
    return {
        "id": user.pk, "username": user.username, "email": user.email,
        "role": role,
        "display_name": display_name,
        "role_label": role_label,
        "business_name": business_name_for(profile, employee),
        "can_manage": manager,
        "can_admin": admin,
        "must_change_password": bool(profile and profile.must_change_password),
        "has_employee_record": employee is not None,
        "has_signed_contract": employee_has_signed_contract(employee),
        "workspace_approved": employee_has_approved_contract(employee),
        "email_configured": onboarding.can_deliver(business) if manager else False,
    }


class SignupSerializer(serializers.ModelSerializer):
    role = serializers.ChoiceField(choices=["employee", "employer"])
    business_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)
    password_confirm = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)
    email = serializers.EmailField(max_length=254)

    class Meta:
        model = get_user_model()
        fields = ["username", "email", "password", "password_confirm", "role", "business_name"]

    def validate_email(self, value):
        if onboarding.email_is_taken(value):
            raise serializers.ValidationError("An account already uses this email address. Sign in instead.")
        return value

    def validate(self, attrs):
        errors = {}
        if attrs["password"] != attrs["password_confirm"]:
            errors["password_confirm"] = "Passwords do not match."
        if attrs["role"] == "employer" and not attrs.get("business_name"):
            errors["business_name"] = "Enter your business name to create an employer account."
        if attrs["role"] == "employee" and attrs.get("business_name"):
            errors["business_name"] = "Business names are only used for employer accounts."
        try:
            validate_password(attrs["password"], get_user_model()(username=attrs["username"], email=attrs["email"]))
        except ValidationError as error:
            errors["password"] = error.messages
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        role = validated_data.pop("role")
        name = validated_data.pop("business_name", "")
        validated_data.pop("password_confirm")
        user = get_user_model().objects.create_user(**validated_data)
        # A company that signed itself up has not been verified by the platform
        # owner yet. It is a queue for the administrator, not a lock: the
        # workspace stays open exactly as before.
        business = Business.objects.create(name=name, status="pending") if role == "employer" else None
        AccountProfile.objects.create(user=user, role=role, business=business)
        return user


class SignupThrottle(AnonRateThrottle):
    rate = "20/hour"


class PasswordResetThrottle(AnonRateThrottle):
    rate = "10/hour"


@extend_schema(
    tags=["Authentication"],
    summary="Create an account",
    description=(
        "Self-service sign-up. Choose `employer` to create a business workspace (then "
        "`business_name` is required), or `employee` to create a sign-in account that an "
        "employer can later attach to an employee record (then `business_name` must be "
        "omitted).\n\n"
        "On success a JWT pair is issued immediately, so no separate call to `/api/token/` is "
        "needed. The password is checked against Django's password validators.\n\n"
        "Rate limited to 20 requests per hour per client address."
    ),
    request=SignupSerializer,
    responses={
        201: AuthenticatedAccountSerializer,
        400: RESPONSE_400,
        429: RESPONSE_429,
    },
    examples=[
        OpenApiExample(
            "Employer", request_only=True,
            value={"username": "kigali-books", "email": "owner@kigali-books.example",
                   "password": "S0me-strong-passphrase", "password_confirm": "S0me-strong-passphrase",
                   "role": "employer", "business_name": "Kigali Books Ltd"},
        ),
        OpenApiExample(
            "Employee", request_only=True,
            value={"username": "amina", "email": "amina.uwase@example.com",
                   "password": "S0me-strong-passphrase", "password_confirm": "S0me-strong-passphrase",
                   "role": "employee"},
        ),
    ],
)
class SignupView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [SignupThrottle]

    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = serializer.save()
        except IntegrityError:
            # The unique username may have been claimed after validation.
            raise serializers.ValidationError({"username": "An account with this username already exists."})
        refresh = RefreshToken.for_user(user)
        return Response({"access": str(refresh.access_token), "refresh": str(refresh), "user": account_data(user)},
                        status=status.HTTP_201_CREATED)


class PasswordResetRequestSerializer(serializers.Serializer):
    identifier = serializers.CharField(max_length=254, trim_whitespace=True)


@extend_schema(
    tags=["Authentication"],
    summary="Request a password reset link",
    description=(
        "Send either a username or an email address as `identifier`. A reset link pointing at "
        "the frontend is emailed to every matching active account that has an email address.\n\n"
        "The response is deliberately identical whether or not an account matched, so it cannot "
        "be used to discover which addresses are registered. Links expire after one hour. "
        "Rate limited to 10 requests per hour per client address."
    ),
    request=PasswordResetRequestSerializer,
    responses={200: DetailSerializer, 400: RESPONSE_400, 429: RESPONSE_429},
    examples=[OpenApiExample("By email", request_only=True,
                             value={"identifier": "owner@kigali-books.example"})],
)
class PasswordResetRequestView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetThrottle]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identifier = serializer.validated_data["identifier"]
        User = get_user_model()
        if "@" in identifier:
            users = User.objects.filter(email__iexact=identifier, is_active=True).order_by("pk")[:10]
        else:
            users = User.objects.filter(username__iexact=identifier, is_active=True)[:1]
        frontend = settings.FRONTEND_URL
        if frontend:
            for user in users:
                if not user.email:
                    continue
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                token = default_token_generator.make_token(user)
                onboarding.send_password_reset(
                    user, f"{frontend}/reset-password?uid={uid}&token={token}")
        return Response({
            "detail": "If a matching account has an email address, password reset instructions have been sent."
        })


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField(max_length=200)
    token = serializers.CharField(max_length=200)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)
    new_password_confirm = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)

    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError({"new_password_confirm": "Passwords do not match."})
        User = get_user_model()
        try:
            user_id = force_str(urlsafe_base64_decode(attrs["uid"]))
            user = User.objects.get(pk=user_id, is_active=True)
        except (ValueError, TypeError, OverflowError, User.DoesNotExist):
            raise serializers.ValidationError({"token": "This password reset link is invalid or has expired."})
        if not default_token_generator.check_token(user, attrs["token"]):
            raise serializers.ValidationError({"token": "This password reset link is invalid or has expired."})
        try:
            validate_password(attrs["new_password"], user)
        except ValidationError as error:
            raise serializers.ValidationError({"new_password": error.messages})
        attrs["user"] = user
        return attrs


@extend_schema(
    tags=["Authentication"],
    summary="Set a new password from a reset link",
    description=(
        "`uid` and `token` come from the query string of the emailed link "
        "(`/reset-password?uid=...&token=...`). An invalid or expired link is reported under "
        "`token`. A successful reset also clears `must_change_password`.\n\n"
        "Rate limited to 10 requests per hour per client address."
    ),
    request=PasswordResetConfirmSerializer,
    responses={200: DetailSerializer, 400: RESPONSE_400, 429: RESPONSE_429},
)
class PasswordResetConfirmView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetThrottle]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        with transaction.atomic():
            user.set_password(serializer.validated_data["new_password"])
            user.save(update_fields=["password"])
            profile = getattr(user, "account_profile", None)
            if profile and profile.must_change_password:
                profile.must_change_password = False
                profile.save(update_fields=["must_change_password"])
        return Response({"detail": "Your password has been reset. You can now sign in."})


@extend_schema(
    tags=["Account"],
    summary="Who am I",
    description="The signed-in account, its role, and the flags the frontend uses to decide "
                "which workspace to show. Call this first after obtaining a token.",
    responses={200: AccountSerializer, 401: RESPONSE_401},
)
class AccountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(account_data(request.user))


def email_settings_data(business, detail=""):
    sender = onboarding.shared_smtp()
    can_manage_settings = onboarding.can_manage_sender(business)
    data = {
        "email_configured": onboarding.can_deliver(),
        "email_host": (sender.email_host if sender else "smtp.gmail.com") or "smtp.gmail.com",
        "email_port": sender.email_port if sender else 587,
        "email_use_tls": sender.email_use_tls if sender else True,
        "email_host_user": onboarding.from_address() if onboarding.platform_mail()
                           else (sender.email_host_user if sender else ""),
        "can_manage_email_settings": can_manage_settings,
        "shared_sender": True,
    }
    if detail:
        data["detail"] = detail
    return data


class EmailSettingsSerializer(serializers.Serializer):
    email_host = serializers.CharField(max_length=200, required=False, allow_blank=True)
    email_port = serializers.IntegerField(required=False, min_value=1, max_value=65535)
    email_use_tls = serializers.BooleanField(required=False)
    email_host_user = serializers.EmailField(required=False, allow_blank=True)
    email_host_password = serializers.CharField(
        required=False, allow_blank=True, trim_whitespace=True, max_length=200, write_only=True)


@extend_schema(tags=["Account"])
@extend_schema_view(
    get=extend_schema(
        summary="Read the shared invitation sender",
        description="Employers only. One SMTP sender serves the whole platform; "
                    "`can_manage_email_settings` is false when another business already owns it.",
        responses={200: EmailSettingsResponseSerializer, 401: RESPONSE_401,
                   403: OpenApiResponse(response=DetailSerializer,
                                        description="Only an employer can set up invitation email.")},
    ),
    patch=extend_schema(
        summary="Configure the shared invitation sender",
        description=(
            "Employers only. Saves the sender **only if a test message can actually be "
            "delivered** with it, so a bad App Password is rejected with 400 rather than "
            "stored. For Gmail, `email_host_password` must be an App Password.\n\n"
            "Sending an empty `email_host_user` turns invitation email off. Omitting "
            "`email_host_password` keeps the password already stored."
        ),
        request=EmailSettingsSerializer,
        responses={200: EmailSettingsResponseSerializer, 400: RESPONSE_400, 401: RESPONSE_401,
                   403: OpenApiResponse(
                       response=DetailSerializer,
                       description="Not an employer, or invitation email is owned by another business.")},
        examples=[OpenApiExample(
            "Gmail App Password", request_only=True,
            value={"email_host": "smtp.gmail.com", "email_port": 587, "email_use_tls": True,
                   "email_host_user": "hr@kigali-books.example",
                   "email_host_password": "abcd efgh ijkl mnop"},
        )],
    ),
)
class EmailSettingsView(APIView):
    """Let an employer send invitations from their own Gmail account."""
    permission_classes = [IsAuthenticated]

    def business(self, request):
        profile = getattr(request.user, "account_profile", None)
        if not profile or profile.role != "employer" or not profile.business_id:
            raise PermissionDenied("Only an employer can set up invitation email.")
        return profile.business

    def get(self, request):
        return Response(email_settings_data(self.business(request)))

    def patch(self, request):
        business = self.business(request)
        if onboarding.platform_mail():
            raise PermissionDenied("Invitation email is managed by the platform and already works for your employees.")
        existing = onboarding.shared_smtp()
        if existing and not onboarding.can_manage_sender(business):
            raise PermissionDenied("Invitation email is managed by the platform and already works for your employees.")
        serializer = EmailSettingsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = data.get("email_host_user", existing.email_host_user if existing else "").strip()
        password = "".join(data.get("email_host_password", "").split())
        if not user:
            InvitationEmailSettings.objects.update_or_create(pk=1, defaults={
                "owner_business": business, "email_host_user": "", "email_host_password": "",
            })
            return Response(email_settings_data(business, "Invitation email has been turned off."))
        if not password:
            password = existing.email_host_password if existing else ""
        if not password:
            raise serializers.ValidationError({"email_host_password": "Enter the Gmail App Password."})
        sender = InvitationEmailSettings(
            pk=1,
            owner_business=business,
            email_host=data.get("email_host") or (existing.email_host if existing else "smtp.gmail.com"),
            email_port=data.get("email_port", existing.email_port if existing else 587),
            email_use_tls=data.get("email_use_tls", existing.email_use_tls if existing else True),
            email_host_user=user,
            email_host_password=password,
        )
        if not onboarding.send_test(business, user, sender=sender):
            raise serializers.ValidationError({
                "email_host_password": "Could not send a test email. Check the address and App Password.",
            })
        sender.save()
        return Response(email_settings_data(business, f"A test message was sent to {user}."))


class EmailOrUsernameTokenSerializer(TokenObtainPairSerializer):
    """Employees never chose a username, so let them sign in with their email."""

    def validate(self, attrs):
        login = attrs.get(self.username_field) or ""
        if "@" in login:
            matches = list(get_user_model().objects.filter(email__iexact=login, is_active=True)[:10])
            if len(matches) == 1:
                attrs[self.username_field] = matches[0].get_username()
            elif len(matches) > 1:
                # Legacy data can contain the same email on several accounts.
                # The password safely disambiguates those accounts in the usual
                # case, including after one of them completes a password reset.
                password_matches = [user for user in matches if user.check_password(attrs.get("password"))]
                if len(password_matches) == 1:
                    attrs[self.username_field] = password_matches[0].get_username()
                elif len(password_matches) > 1:
                    raise serializers.ValidationError({
                        self.username_field: "This email belongs to more than one account. Sign in with your username."
                    })
        return super().validate(attrs)


@extend_schema(
    tags=["Authentication"],
    # SimpleJWT leaves permission_classes empty, so say outright that this
    # endpoint needs no credentials rather than letting it be inferred.
    auth=[{}],
    summary="Obtain a JWT pair (sign in)",
    description=(
        "Send `username` and `password`. The `username` field also accepts an **email "
        "address**, because employees never choose a username - their account is created for "
        "them. If one email somehow belongs to several accounts, the password disambiguates "
        "them; if it still cannot, sign in with the username instead.\n\n"
        "Paste the returned `access` token into the **Authorize** dialog at the top of this "
        "page to try the protected endpoints."
    ),
    responses={
        200: TokenPairSerializer,
        400: RESPONSE_400,
        401: OpenApiResponse(
            response=DetailSerializer,
            description="The credentials did not match an active account.",
            examples=[OpenApiExample("Rejected", value={
                "detail": "No active account found with the given credentials"})]),
    },
    examples=[
        OpenApiExample("By username", request_only=True,
                       value={"username": "kigali-books", "password": "S0me-strong-passphrase"}),
        OpenApiExample("By email", request_only=True,
                       value={"username": "amina.uwase@example.com", "password": "S0me-strong-passphrase"}),
    ],
)
class TokenView(TokenObtainPairView):
    serializer_class = EmailOrUsernameTokenSerializer


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(trim_whitespace=False, max_length=128)
    new_password = serializers.CharField(trim_whitespace=False, max_length=128)
    new_password_confirm = serializers.CharField(trim_whitespace=False, max_length=128)

    def validate(self, attrs):
        user = self.context["request"].user
        errors = {}
        if not user.check_password(attrs["current_password"]):
            errors["current_password"] = "That password is incorrect."
        if attrs["new_password"] != attrs["new_password_confirm"]:
            errors["new_password_confirm"] = "Passwords do not match."
        if attrs["new_password"] == attrs["current_password"]:
            errors["new_password"] = "Choose a password different from your current one."
        try:
            validate_password(attrs["new_password"], user)
        except ValidationError as error:
            errors["new_password"] = error.messages
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


@extend_schema(
    tags=["Account"],
    summary="Change your own password",
    description=(
        "Requires the current password. The new password must differ from it and pass "
        "Django's password validators.\n\n"
        "This is the endpoint an invited account uses to clear `must_change_password`. A fresh "
        "JWT pair is returned so the client is not left holding a token minted against the "
        "temporary password - replace the stored tokens with these."
    ),
    request=PasswordChangeSerializer,
    responses={200: AuthenticatedAccountSerializer, 400: RESPONSE_400, 401: RESPONSE_401},
    examples=[OpenApiExample(
        "Replace a temporary password", request_only=True,
        value={"current_password": "Tmp-4h7Kq2", "new_password": "S0me-strong-passphrase",
               "new_password_confirm": "S0me-strong-passphrase"},
    )],
)
class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = request.user
        with transaction.atomic():
            user.set_password(serializer.validated_data["new_password"])
            user.save(update_fields=["password"])
            profile = getattr(user, "account_profile", None)
            if profile and profile.must_change_password:
                profile.must_change_password = False
                profile.save(update_fields=["must_change_password"])
        # Reissue so the client is not left holding a token minted against the
        # temporary password.
        refresh = RefreshToken.for_user(user)
        return Response({"access": str(refresh.access_token), "refresh": str(refresh),
                         "user": account_data(user)})


class MyProfileSerializer(serializers.ModelSerializer):
    """The employee's own view of their record.

    Job details belong to the employer and stay read-only here. The personal
    details an employer should not have to guess are the editable half.
    """
    business_name = serializers.SerializerMethodField()
    photo = serializers.ImageField(write_only=True, required=False)
    photo_name = serializers.SerializerMethodField()

    @extend_schema_field(OpenApiTypes.STR)
    def get_business_name(self, obj):
        return obj.business.name if obj.business_id else ""

    @extend_schema_field(OpenApiTypes.STR)
    def get_photo_name(self, obj):
        return obj.photo.name.rsplit("/", 1)[-1] if obj.photo else ""

    def validate_photo(self, value):
        FileExtensionValidator(["jpg", "jpeg", "png", "webp"])(value)
        if value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("Profile photos must be 5 MB or smaller.")
        return value

    class Meta:
        model = Employee
        fields = ["id", "first_name", "last_name", "email", "business_name",
                  "department", "job_title", "date_joined", "employment_type",
                  "manager_name", "job_description", "is_active",
                  "phone", "address", "emergency_contact", "photo", "photo_name"]
        read_only_fields = ["id", "first_name", "last_name", "email", "business_name",
                            "department", "job_title", "date_joined", "employment_type",
                            "manager_name", "job_description", "is_active"]


@extend_schema(tags=["Employee workspace"])
@extend_schema_view(
    get=extend_schema(
        summary="Read your own profile",
        description="The employee's own record. Job details belong to the employer and are "
                    "read-only here.",
        responses=workspace_responses({200: MyProfileSerializer}, bad_request=True),
    ),
    patch=extend_schema(
        summary="Complete your own profile",
        description="Only the personal half is writable: `phone`, `address`, "
                    "`emergency_contact` and `photo`. Send `multipart/form-data` to upload a "
                    "photo (JPG/JPEG/PNG/WEBP, 5 MB or smaller).",
        request=MyProfileSerializer,
        responses=workspace_responses({200: MyProfileSerializer}),
        examples=[OpenApiExample(
            "Contact details", request_only=True,
            value={"phone": "+250 788 123 456", "address": "KN 4 Ave, Kigali",
                   "emergency_contact": "Jean Uwase, +250 788 654 321"},
        )],
    ),
)
class MyProfileView(APIView):
    """Read and complete your own employee profile."""
    permission_classes = [IsAuthenticated]

    def get_record(self, request):
        employee = employee_record(request.user)
        if not employee:
            raise serializers.ValidationError(
                "Your account is not linked to an employee record. Ask your employer to add you to their workspace.")
        return employee

    def get(self, request):
        return Response(MyProfileSerializer(require_signed_contract(self.get_record(request))).data)

    def patch(self, request):
        employee = require_signed_contract(self.get_record(request))
        serializer = MyProfileSerializer(employee, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


@extend_schema(
    tags=["Employee workspace"],
    summary="Download your own profile photo",
    description="Profile photos are never served from a public media URL; this is the only "
                "way an employee can read their own.",
    responses={
        (200, "image/*"): OpenApiTypes.BINARY,
        400: RESPONSE_400,
        401: RESPONSE_401,
        403: RESPONSE_403_WORKSPACE,
        404: OpenApiResponse(response=DetailSerializer,
                             description="No photo is attached, or the stored file is missing."),
    },
)
class MyPhotoView(APIView):
    """Serve the employee their own profile photo, which is otherwise private."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.http import FileResponse, Http404

        employee = require_signed_contract(MyProfileView().get_record(request))
        if not employee.photo:
            raise Http404("No photo is attached to this profile.")
        try:
            image = employee.photo.open("rb")
        except FileNotFoundError:
            raise Http404("The profile photo could not be found.")
        response = FileResponse(image, filename=employee.photo.name.rsplit("/", 1)[-1])
        response["Cache-Control"] = "private, max-age=300"
        return response


class MyAnnouncementSerializer(serializers.ModelSerializer):
    is_read = serializers.SerializerMethodField()

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_read(self, obj):
        employee = self.context["employee"]
        return any(item.employee_id == employee.id for item in obj.reads.all())

    class Meta:
        model = Announcement
        fields = ["id", "title", "message", "created_by", "published_at", "is_read"]


@extend_schema(
    tags=["Employee workspace"],
    summary="List announcements for you",
    description="Every announcement published in your business, newest first, each flagged "
                "with whether you have already read it.",
    responses=workspace_responses({200: MyAnnouncementSerializer(many=True)}, bad_request=False),
)
class MyAnnouncementsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        employee = require_signed_contract(employee_record(request.user))
        rows = Announcement.objects.filter(business=employee.business).prefetch_related("reads")
        return Response(MyAnnouncementSerializer(rows, many=True, context={"employee": employee}).data)


@extend_schema(
    tags=["Employee workspace"],
    parameters=[RECORD_ID],
    summary="Mark an announcement as read",
    description="Idempotent: marking an already-read announcement simply returns it again. "
                "Takes no request body.",
    request=None,
    responses=workspace_responses({200: MyAnnouncementSerializer}, bad_request=False),
)
class MyAnnouncementReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        employee = require_signed_contract(employee_record(request.user))
        announcement = Announcement.objects.filter(pk=pk, business=employee.business).first()
        if not announcement:
            raise PermissionDenied("You cannot access this announcement.")
        AnnouncementRead.objects.get_or_create(announcement=announcement, employee=employee)
        return Response(MyAnnouncementSerializer(
            announcement, context={"employee": employee}).data)


@extend_schema(
    tags=["Employee workspace"],
    summary="Mark every announcement as read",
    description="Clears the whole announcements badge in one call, for when there are too "
                "many to open one by one. Idempotent, takes no request body, and returns the "
                "full list as it now stands. Nothing is deleted: the announcements stay, they "
                "are simply no longer new to you.",
    request=None,
    responses=workspace_responses({200: MyAnnouncementSerializer(many=True)}, bad_request=False),
)
class MyAnnouncementReadAllView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        employee = require_signed_contract(employee_record(request.user))
        rows = Announcement.objects.filter(business=employee.business).prefetch_related("reads")
        already = set(AnnouncementRead.objects.filter(employee=employee).values_list(
            "announcement_id", flat=True))
        AnnouncementRead.objects.bulk_create(
            [AnnouncementRead(announcement=row, employee=employee)
             for row in rows if row.pk not in already],
            ignore_conflicts=True)
        rows = Announcement.objects.filter(business=employee.business).prefetch_related("reads")
        return Response(MyAnnouncementSerializer(
            rows, many=True, context={"employee": employee}).data)


class MyCalendarEventSerializer(serializers.ModelSerializer):
    is_read = serializers.SerializerMethodField()

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_read(self, obj):
        employee = self.context["employee"]
        return any(item.employee_id == employee.id for item in obj.reads.all())

    class Meta:
        model = CalendarEvent
        fields = ["id", "title", "category", "date", "end_date", "start_time", "end_time",
                  "location", "description", "created_by", "created_at", "is_read"]


@extend_schema(
    tags=["Employee workspace"],
    summary="List calendar events for you",
    description="Company calendar events in your business that are either open to everyone "
                "or that you were invited to, in date order, each flagged with whether you "
                "have already read it.",
    responses=workspace_responses({200: MyCalendarEventSerializer(many=True)}, bad_request=False),
)
class MyCalendarView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        employee = require_signed_contract(employee_record(request.user))
        events = CalendarEvent.objects.filter(business=employee.business).filter(
            Q(all_employees=True) | Q(invited_employees=employee)
        ).distinct().prefetch_related("reads")
        return Response(MyCalendarEventSerializer(events, many=True, context={"employee": employee}).data)


@extend_schema(
    tags=["Employee workspace"],
    parameters=[RECORD_ID],
    summary="Mark a calendar event as read",
    description="Idempotent, and only works for an event you were invited to. Takes no "
                "request body.",
    request=None,
    responses=workspace_responses({200: MyCalendarEventSerializer}, bad_request=False),
)
class MyCalendarEventReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        employee = require_signed_contract(employee_record(request.user))
        event = CalendarEvent.objects.filter(pk=pk, business=employee.business).filter(
            Q(all_employees=True) | Q(invited_employees=employee)
        ).distinct().prefetch_related("reads").first()
        if not event:
            raise PermissionDenied("You cannot access this calendar event.")
        CalendarEventRead.objects.get_or_create(event=event, employee=employee)
        event = CalendarEvent.objects.prefetch_related("reads").get(pk=event.pk)
        return Response(MyCalendarEventSerializer(event, context={"employee": employee}).data)


@extend_schema(
    tags=["Employee workspace"],
    summary="Mark every calendar event as read",
    description="Clears the whole calendar badge in one call. Idempotent, takes no request "
                "body, and returns your events as they now stand. The events themselves are "
                "untouched.",
    request=None,
    responses=workspace_responses({200: MyCalendarEventSerializer(many=True)}, bad_request=False),
)
class MyCalendarReadAllView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        employee = require_signed_contract(employee_record(request.user))
        visible = CalendarEvent.objects.filter(business=employee.business).filter(
            Q(all_employees=True) | Q(invited_employees=employee)).distinct()
        already = set(CalendarEventRead.objects.filter(employee=employee).values_list(
            "event_id", flat=True))
        CalendarEventRead.objects.bulk_create(
            [CalendarEventRead(event=row, employee=employee)
             for row in visible if row.pk not in already],
            ignore_conflicts=True)
        events = CalendarEvent.objects.filter(business=employee.business).filter(
            Q(all_employees=True) | Q(invited_employees=employee)
        ).distinct().prefetch_related("reads")
        return Response(MyCalendarEventSerializer(
            events, many=True, context={"employee": employee}).data)


class MyAttendanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attendance
        fields = ["id", "date", "shift", "status", "hours_worked", "check_in_at", "check_out_at"]


class AttendanceClockSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["check_in", "check_out"])
    shift = serializers.ChoiceField(choices=["day", "night"], default="day")
    time = serializers.TimeField()


@extend_schema(tags=["Employee workspace"])
@extend_schema_view(
    get=extend_schema(
        summary="Read your clock state",
        description="Returns the shift you are currently clocked into if there is one "
                    "(including a night shift that began yesterday), otherwise today.",
        responses=workspace_responses({200: MyAttendanceStateSerializer}, bad_request=False),
    ),
    post=extend_schema(
        summary="Clock in or out",
        description=(
            "`action` is `check_in` or `check_out`, `shift` is `day` or `night`, and `time` is "
            "the wall-clock time to record in the server time zone.\n\n"
            "One check-in and one check-out per shift. You cannot start a second shift while "
            "another is still open, clock in before your joining date, or clock in on a day "
            "covered by approved leave. A night-shift check-out earlier than its check-in is "
            "treated as the next morning. `hours_worked` is computed on check-out and capped "
            "at 24."
        ),
        request=AttendanceClockSerializer,
        responses=workspace_responses({200: MyAttendanceStateSerializer}),
        examples=[
            OpenApiExample("Check in", request_only=True,
                           value={"action": "check_in", "shift": "day", "time": "08:30:00"}),
            OpenApiExample("Check out", request_only=True,
                           value={"action": "check_out", "shift": "day", "time": "17:00:00"}),
        ],
    ),
)
class MyAttendanceView(APIView):
    """Let a linked employee clock in and out once per local workday."""
    permission_classes = [IsAuthenticated]

    def employee(self, request):
        employee = employee_record(request.user)
        if not employee:
            raise PermissionDenied("Your account is not linked to an employee record.")
        if not employee.is_active:
            raise PermissionDenied("Your employee profile is inactive.")
        return require_signed_contract(employee)

    def response_data(self, employee, date, selected_shift="day"):
        shifts = list(Attendance.objects.filter(employee=employee, date=date).order_by("id"))
        attendance = next((item for item in shifts if item.shift == selected_shift), None)
        total = sum((item.hours_worked for item in shifts), Decimal("0.00"))
        return {
            "date": date,
            "attendance": MyAttendanceSerializer(attendance).data if attendance else None,
            "shifts": MyAttendanceSerializer(shifts, many=True).data,
            "total_hours": f"{total:.2f}",
        }

    def get(self, request):
        employee = self.employee(request)
        date = timezone.localdate()
        active = Attendance.objects.filter(
            employee=employee,
            date__gte=date - timedelta(days=1),
            check_in_at__isnull=False,
            check_out_at__isnull=True,
        ).order_by("-date", "-id").first()
        return Response(self.response_data(employee, active.date if active else date, active.shift if active else "day"))

    def post(self, request):
        employee = self.employee(request)
        serializer = AttendanceClockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action = serializer.validated_data["action"]
        shift = serializer.validated_data["shift"]
        selected_time = serializer.validated_data["time"]
        now = timezone.now()
        date = timezone.localdate(now)
        if action == "check_in" and date < employee.date_joined:
            raise serializers.ValidationError("You cannot check in before your employment start date.")
        if action == "check_in" and LeaveRequest.objects.filter(
            employee=employee, status="approved", start_date__lte=date, end_date__gte=date,
        ).exists():
            raise serializers.ValidationError("You are recorded as being on approved leave today.")
        with transaction.atomic():
            attendance = Attendance.objects.select_for_update().filter(employee=employee, date=date, shift=shift).first()
            if action == "check_out" and attendance is None and shift == "night":
                attendance = Attendance.objects.select_for_update().filter(
                    employee=employee,
                    date=date - timedelta(days=1),
                    shift="night",
                    check_in_at__isnull=False,
                    check_out_at__isnull=True,
                ).first()
            if action == "check_in":
                if attendance and attendance.check_in_at:
                    raise serializers.ValidationError(f"You have already checked in for the {shift} shift.")
                # Matches GET: a shift left open before yesterday no longer blocks a new one.
                active = Attendance.objects.select_for_update().filter(
                    employee=employee, date__gte=date - timedelta(days=1),
                    check_in_at__isnull=False, check_out_at__isnull=True,
                ).first()
                if active:
                    raise serializers.ValidationError(f"Check out of the {active.shift} shift before starting another shift.")
                if attendance is None:
                    attendance = Attendance(employee=employee, date=date, shift=shift)
                recorded_at = timezone.make_aware(datetime.combine(date, selected_time), timezone.get_current_timezone())
                attendance.status = "present"
                attendance.hours_worked = Decimal("0.00")
                attendance.check_in_at = recorded_at
                attendance.check_out_at = None
                attendance.save()
            else:
                if not attendance or not attendance.check_in_at:
                    raise serializers.ValidationError(f"Check in to the {shift} shift before checking out.")
                if attendance.check_out_at:
                    raise serializers.ValidationError(f"You have already checked out of the {shift} shift.")
                recorded_at = timezone.make_aware(datetime.combine(attendance.date, selected_time), timezone.get_current_timezone())
                if shift == "night" and recorded_at <= attendance.check_in_at:
                    recorded_at += timedelta(days=1)
                if recorded_at <= attendance.check_in_at:
                    raise serializers.ValidationError("Check-out time must be later than check-in time.")
                seconds = (recorded_at - attendance.check_in_at).total_seconds()
                attendance.check_out_at = recorded_at
                attendance.status = "present"
                attendance.hours_worked = min(
                    Decimal("24.00"),
                    (Decimal(str(seconds)) / Decimal("3600")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                )
                attendance.save(update_fields=["check_out_at", "status", "hours_worked"])
        return Response(self.response_data(employee, attendance.date, shift))


class MyLeaveRequestSerializer(serializers.ModelSerializer):
    days_requested = serializers.SerializerMethodField()

    @extend_schema_field(serializers.FloatField(
        help_text="Monday-Friday days in the period, excluding your business's holidays."))
    def get_days_requested(self, obj):
        return leave_management.leave_days(obj.employee, obj.start_date, obj.end_date)

    def validate(self, attrs):
        employee = self.context["employee"]
        start = attrs.get("start_date", self.instance.start_date if self.instance else None)
        end = attrs.get("end_date", self.instance.end_date if self.instance else None)
        if end < start:
            raise serializers.ValidationError({"end_date": "End date must be on or after the start date."})
        if start < timezone.localdate():
            raise serializers.ValidationError({"start_date": "New leave requests cannot start in the past."})
        if start < employee.date_joined:
            raise serializers.ValidationError({"start_date": "Leave cannot precede your employment start date."})
        if start.year != end.year:
            raise serializers.ValidationError({"end_date": "A leave request must stay within one calendar year."})
        if leave_management.leave_days(employee, start, end) <= 0:
            raise serializers.ValidationError("This period contains no working days.")
        overlap = LeaveRequest.objects.filter(
            employee=employee, start_date__lte=end, end_date__gte=start,
        ).exclude(status="rejected")
        if self.instance:
            overlap = overlap.exclude(pk=self.instance.pk)
        if overlap.exists():
            raise serializers.ValidationError("This leave overlaps another pending or approved request.")
        return attrs

    class Meta:
        model = LeaveRequest
        fields = ["id", "leave_type", "start_date", "end_date", "days_requested", "reason",
                  "status", "decision_notes", "requested_at", "decided_at", "decided_by"]
        read_only_fields = ["status", "decision_notes", "requested_at", "decided_at", "decided_by"]


@extend_schema(tags=["Employee workspace"])
@extend_schema_view(
    get=extend_schema(
        summary="Read your leave balances and requests",
        description="This year's four allocations (annual, sick, maternity, unpaid), created "
                    "on first read if they are missing, plus all of your own leave requests.",
        responses=workspace_responses({200: MyLeaveOverviewSerializer}, bad_request=False),
    ),
    post=extend_schema(
        summary="Request leave",
        description=(
            "Created as `pending` and emailed to the employer. The period must start today or "
            "later, stay within one calendar year, not precede your joining date, contain at "
            "least one working day, and not overlap another pending or approved request."
        ),
        request=MyLeaveRequestSerializer,
        responses=workspace_responses({201: MyLeaveRequestSerializer}),
        examples=[OpenApiExample(
            "A week of annual leave", request_only=True,
            value={"leave_type": "annual", "start_date": "2026-12-21",
                   "end_date": "2026-12-25", "reason": "Family holiday"},
        )],
    ),
)
class MyLeaveView(APIView):
    permission_classes = [IsAuthenticated]

    def employee(self, request):
        employee = employee_record(request.user)
        if not employee:
            raise PermissionDenied("Your account is not linked to an employee record.")
        return require_signed_contract(employee)

    def get(self, request):
        employee = self.employee(request)
        year = timezone.localdate().year
        balances = leave_management.ensure_leave_balances(employee, year)
        requests = LeaveRequest.objects.filter(employee=employee).order_by("-start_date", "-id")
        return Response({
            "year": year,
            "balances": LeaveBalanceSerializer(balances, many=True).data,
            "requests": MyLeaveRequestSerializer(requests, many=True).data,
        })

    def post(self, request):
        employee = self.employee(request)
        if not employee.is_active:
            raise PermissionDenied("Your employee profile is inactive.")
        serializer = MyLeaveRequestSerializer(data=request.data, context={"employee": employee})
        serializer.is_valid(raise_exception=True)
        request_record = serializer.save(employee=employee, status="pending")
        onboarding.send_leave_notification(request_record, "created")
        return Response(MyLeaveRequestSerializer(request_record).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["Employee workspace"], parameters=[RECORD_ID])
@extend_schema_view(
    patch=extend_schema(
        summary="Change your pending leave request",
        description="Only a request still in `pending` can be changed; the employer is "
                    "emailed about the update. The same date rules as creation apply.",
        request=MyLeaveRequestSerializer,
        responses=workspace_responses({200: MyLeaveRequestSerializer}),
    ),
    delete=extend_schema(
        summary="Cancel your pending leave request",
        description="Only a request still in `pending` can be cancelled; the employer is "
                    "emailed about the cancellation.",
        responses=workspace_responses(
            {204: OpenApiResponse(description="Cancelled. No body.")}),
    ),
)
class MyLeaveDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def record(self, request, pk):
        employee = employee_record(request.user)
        require_signed_contract(employee)
        record = LeaveRequest.objects.select_related("employee", "employee__business").filter(pk=pk, employee=employee).first()
        if not record:
            raise PermissionDenied("You cannot access this leave request.")
        if record.status != "pending":
            raise serializers.ValidationError("Only pending leave requests can be changed.")
        return record

    def patch(self, request, pk):
        record = self.record(request, pk)
        serializer = MyLeaveRequestSerializer(record, data=request.data, partial=True,
                                               context={"employee": record.employee})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        onboarding.send_leave_notification(record, "updated")
        return Response(serializer.data)

    def delete(self, request, pk):
        record = self.record(request, pk)
        onboarding.send_leave_notification(record, "cancelled")
        record.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MyContractSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.__str__", read_only=True)
    business_name = serializers.CharField(source="employee.business.name", read_only=True)
    termination = serializers.SerializerMethodField()

    @extend_schema_field(ContractTerminationSerializer(allow_null=True))
    def get_termination(self, obj):
        request = obj.termination_requests.order_by("-created_at", "-id").first()
        return ContractTerminationSerializer(request).data if request else None

    class Meta:
        model = Contract
        fields = [
            "id", "employee_name", "business_name", "title", "department", "start_date", "end_date", "status",
            "content", "employer_message", "signature_status", "sent_at", "signed_at", "signer_name", "signature_data",
            "worker_approval_status", "worker_approved_at", "worker_approved_by",
            "termination",
        ]


@extend_schema(
    tags=["Employee workspace"],
    summary="List your contracts",
    description=(
        "Contracts that have been sent to you or that you have already signed, newest first. "
        "Unlike the rest of this section, this endpoint does **not** require an approved "
        "contract - it is how a new employee finds the contract waiting to be signed. An "
        "account with no employee record gets an empty list rather than an error."
    ),
    responses={200: MyContractSerializer(many=True), 401: RESPONSE_401},
)
class MyContractsView(APIView):
    """Contracts sent to the signed-in employee."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        employee = employee_record(request.user)
        if not employee:
            return Response([])
        contracts = Contract.objects.filter(
            employee=employee, signature_status__in=["sent", "signed"],
        ).select_related("employee", "employee__business").order_by("-sent_at", "-id")
        return Response(MyContractSerializer(contracts, many=True).data)


class ContractSignatureSerializer(serializers.Serializer):
    signer_name = serializers.CharField(max_length=200, trim_whitespace=True)
    signature_data = serializers.CharField(max_length=500_000, trim_whitespace=False)
    accepted = serializers.BooleanField()

    def validate_accepted(self, value):
        if not value:
            raise serializers.ValidationError("Confirm that you have read and agree to the contract.")
        return value

    def validate_signature_data(self, value):
        prefix = "data:image/png;base64,"
        if not value.startswith(prefix):
            raise serializers.ValidationError("Draw your signature in the signature box.")
        try:
            image = base64.b64decode(value[len(prefix):], validate=True)
        except (ValueError, binascii.Error):
            raise serializers.ValidationError("The drawn signature is invalid.")
        if len(image) > 300 * 1024:
            raise serializers.ValidationError("The signature must be a PNG image no larger than 300 KB.")
        try:
            with Image.open(BytesIO(image)) as signature:
                dimensions = signature.size
                image_format = signature.format
                signature.verify()
        except (UnidentifiedImageError, OSError):
            raise serializers.ValidationError("The drawn signature is not a valid image.")
        if image_format != "PNG" or dimensions[0] > 2000 or dimensions[1] > 800:
            raise serializers.ValidationError("The signature must be a PNG image no larger than 2000 by 800 pixels.")
        return value


@extend_schema(
    tags=["Employee workspace"],
    parameters=[RECORD_ID],
    summary="Sign a contract",
    description=(
        "Signs a contract that is awaiting your signature. `signer_name` must match your "
        "recorded full name (case-insensitively), `accepted` must be true, and "
        "`signature_data` must be a drawn PNG as a data URL - at most 300 KB and 2000 by 800 "
        "pixels.\n\n"
        "The contract text is re-fingerprinted before signing, so a contract edited after it "
        "was sent is refused and must be resent. Signing records the time and your IP address, "
        "sets the contract to `active`, and leaves `worker_approval_status: pending` until the "
        "employer approves you."
    ),
    request=ContractSignatureSerializer,
    responses={200: MyContractSerializer, 400: RESPONSE_400, 401: RESPONSE_401,
               403: OpenApiResponse(response=DetailSerializer,
                                    description="Not your contract, or no employee record is linked.")},
    examples=[OpenApiExample(
        "Signature", request_only=True,
        value={"signer_name": "Amina Uwase", "accepted": True,
               "signature_data": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg..."},
    )],
)
class MyContractSignView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        employee = employee_record(request.user)
        if not employee:
            raise PermissionDenied("Your account is not linked to an employee record.")
        serializer = ContractSignatureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected_name = f"{employee.first_name} {employee.last_name}".strip()
        signer_name = " ".join(serializer.validated_data["signer_name"].split())
        if signer_name.casefold() != expected_name.casefold():
            raise serializers.ValidationError({"signer_name": f"Enter your full name exactly as {expected_name}."})
        with transaction.atomic():
            contract = Contract.objects.select_for_update().filter(pk=pk, employee=employee).first()
            if not contract:
                raise PermissionDenied("You cannot access this contract.")
            if contract.signature_status != "sent":
                raise serializers.ValidationError("This contract is not awaiting your signature.")
            if sha256(contract.content.encode("utf-8")).hexdigest() != contract.content_hash:
                raise serializers.ValidationError("This contract changed after it was sent. Ask your employer to resend it.")
            contract.signature_status = "signed"
            contract.status = "active"
            contract.worker_approval_status = "pending"
            contract.worker_approved_at = None
            contract.worker_approved_by = ""
            contract.signed_at = timezone.now()
            contract.signer_name = signer_name
            contract.signature_data = serializer.validated_data["signature_data"]
            contract.signed_ip = request.META.get("REMOTE_ADDR") or None
            contract.save(update_fields=[
                "signature_status", "status", "worker_approval_status", "worker_approved_at", "worker_approved_by",
                "signed_at", "signer_name", "signature_data", "signed_ip",
            ])
        onboarding.send_contract_worker_approval_notification(contract, "signed")
        return Response(MyContractSerializer(contract).data)


class ContractTerminationRequestSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=4000, trim_whitespace=True)
    proposed_last_working_date = serializers.DateField()


@extend_schema(
    tags=["Employee workspace"],
    parameters=[RECORD_ID],
    summary="Ask to end your contract",
    description="Opens a termination request in `pending` for the employer to approve or "
                "reject. Only an active, signed, approved contract qualifies, the date cannot "
                "be in the past, and only one request may be open at a time.",
    request=ContractTerminationRequestSerializer,
    responses={201: MyContractSerializer, 400: RESPONSE_400, 401: RESPONSE_401,
               403: OpenApiResponse(response=DetailSerializer,
                                    description="Not your contract, or no employee record is linked.")},
    examples=[OpenApiExample(
        "Resignation", request_only=True,
        value={"reason": "I have accepted a role closer to home.",
               "proposed_last_working_date": "2026-11-30"},
    )],
)
class MyContractTerminationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        employee = employee_record(request.user)
        if not employee:
            raise PermissionDenied("Your account is not linked to an employee record.")
        payload = ContractTerminationRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        with transaction.atomic():
            contract = Contract.objects.select_for_update().filter(pk=pk, employee=employee).first()
            if not contract:
                raise PermissionDenied("You cannot access this contract.")
            if contract.signature_status != "signed" or contract.worker_approval_status != "approved" or contract.status != "active":
                raise serializers.ValidationError("Only an active signed contract can be terminated.")
            if payload.validated_data["proposed_last_working_date"] < timezone.localdate():
                raise serializers.ValidationError({"proposed_last_working_date": "Choose today or a future date."})
            if contract.termination_requests.filter(status__in=["pending", "awaiting_acknowledgement"]).exists():
                raise serializers.ValidationError("This contract already has a pending termination request.")
            termination = ContractTerminationRequest.objects.create(
                contract=contract,
                initiated_by="employee",
                status="pending",
                **payload.validated_data,
            )
        onboarding.send_contract_termination_notification(termination, "employee_requested")
        return Response(MyContractSerializer(contract).data, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["Employee workspace"],
    parameters=[RECORD_ID],
    summary="Acknowledge an employer termination",
    description="Confirms a termination the **employer** started. The contract becomes "
                "`terminated_mutual` and its `end_date` moves to the proposed last working "
                "date. Takes no request body.",
    request=None,
    responses={200: MyContractSerializer, 400: RESPONSE_400, 401: RESPONSE_401,
               403: OpenApiResponse(response=DetailSerializer,
                                    description="Not your contract, or no employee record is linked.")},
)
class MyContractTerminationAcknowledgeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        employee = employee_record(request.user)
        if not employee:
            raise PermissionDenied("Your account is not linked to an employee record.")
        with transaction.atomic():
            contract = Contract.objects.select_for_update().filter(pk=pk, employee=employee).first()
            if not contract:
                raise PermissionDenied("You cannot access this contract.")
            termination = contract.termination_requests.select_for_update().filter(
                initiated_by="employer", status="awaiting_acknowledgement",
            ).order_by("-created_at", "-id").first()
            if not termination:
                raise serializers.ValidationError("There is no employer termination awaiting acknowledgement.")
            termination.status = "acknowledged"
            termination.responded_at = timezone.now()
            termination.save(update_fields=["status", "responded_at"])
            contract.status = "terminated_mutual"
            contract.end_date = termination.proposed_last_working_date
            contract.save(update_fields=["status", "end_date"])
        onboarding.send_contract_termination_notification(termination, "employee_acknowledged")
        return Response(MyContractSerializer(contract).data)
