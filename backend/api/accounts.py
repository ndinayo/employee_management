import base64
import binascii
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
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
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
from .models import (AccountProfile, Attendance, Business, Contract, Employee,
                     InvitationEmailSettings, LeaveBalance, LeaveRequest)
from .permissions import can_manage, is_admin
from .serializers import LeaveBalanceSerializer


def employee_record(user):
    """The Employee row an employer created for this account, if any."""
    profile = getattr(user, "account_profile", None)
    return profile.employee if profile and profile.employee_id else None


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
        business = Business.objects.create(name=name) if role == "employer" else None
        AccountProfile.objects.create(user=user, role=role, business=business)
        return user


class SignupThrottle(AnonRateThrottle):
    rate = "20/hour"


class PasswordResetThrottle(AnonRateThrottle):
    rate = "10/hour"


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
        "email_host_user": sender.email_host_user if sender else "",
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

    def get_business_name(self, obj):
        return obj.business.name if obj.business_id else ""

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
        return Response(MyProfileSerializer(self.get_record(request)).data)

    def patch(self, request):
        serializer = MyProfileSerializer(self.get_record(request), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class MyPhotoView(APIView):
    """Serve the employee their own profile photo, which is otherwise private."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.http import FileResponse, Http404

        employee = MyProfileView().get_record(request)
        if not employee.photo:
            raise Http404("No photo is attached to this profile.")
        try:
            image = employee.photo.open("rb")
        except FileNotFoundError:
            raise Http404("The profile photo could not be found.")
        response = FileResponse(image, filename=employee.photo.name.rsplit("/", 1)[-1])
        response["Cache-Control"] = "private, max-age=300"
        return response


class MyAttendanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attendance
        fields = ["id", "date", "status", "hours_worked", "check_in_at", "check_out_at"]


class AttendanceClockSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["check_in", "check_out"])


class MyAttendanceView(APIView):
    """Let a linked employee clock in and out once per local workday."""
    permission_classes = [IsAuthenticated]

    def employee(self, request):
        employee = employee_record(request.user)
        if not employee:
            raise PermissionDenied("Your account is not linked to an employee record.")
        if not employee.is_active:
            raise PermissionDenied("Your employee profile is inactive.")
        return employee

    def response_data(self, employee, date):
        attendance = Attendance.objects.filter(employee=employee, date=date).first()
        return {"date": date, "attendance": MyAttendanceSerializer(attendance).data if attendance else None}

    def get(self, request):
        employee = self.employee(request)
        return Response(self.response_data(employee, timezone.localdate()))

    def post(self, request):
        employee = self.employee(request)
        serializer = AttendanceClockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action = serializer.validated_data["action"]
        now = timezone.now()
        date = timezone.localdate(now)
        if date < employee.date_joined:
            raise serializers.ValidationError("You cannot check in before your employment start date.")
        if LeaveRequest.objects.filter(
            employee=employee, status="approved", start_date__lte=date, end_date__gte=date,
        ).exists():
            raise serializers.ValidationError("You are recorded as being on approved leave today.")
        with transaction.atomic():
            attendance = Attendance.objects.select_for_update().filter(employee=employee, date=date).first()
            if action == "check_in":
                if attendance and attendance.check_in_at:
                    raise serializers.ValidationError("You have already checked in today.")
                if attendance is None:
                    attendance = Attendance(employee=employee, date=date)
                attendance.status = "present"
                attendance.hours_worked = Decimal("0.00")
                attendance.check_in_at = now
                attendance.check_out_at = None
                attendance.save()
            else:
                if not attendance or not attendance.check_in_at:
                    raise serializers.ValidationError("Check in before checking out.")
                if attendance.check_out_at:
                    raise serializers.ValidationError("You have already checked out today.")
                seconds = max(0, (now - attendance.check_in_at).total_seconds())
                attendance.check_out_at = now
                attendance.status = "present"
                attendance.hours_worked = min(
                    Decimal("24.00"),
                    (Decimal(str(seconds)) / Decimal("3600")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                )
                attendance.save(update_fields=["check_out_at", "status", "hours_worked"])
        return Response(self.response_data(employee, date))


class MyLeaveRequestSerializer(serializers.ModelSerializer):
    days_requested = serializers.SerializerMethodField()

    def get_days_requested(self, obj):
        return leave_management.leave_days(obj.employee, obj.start_date, obj.end_date)

    def validate(self, attrs):
        employee = self.context["employee"]
        start, end = attrs["start_date"], attrs["end_date"]
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
        if LeaveRequest.objects.filter(
            employee=employee, start_date__lte=end, end_date__gte=start,
        ).exclude(status="rejected").exists():
            raise serializers.ValidationError("This leave overlaps another pending or approved request.")
        return attrs

    class Meta:
        model = LeaveRequest
        fields = ["id", "leave_type", "start_date", "end_date", "days_requested", "reason",
                  "status", "decision_notes", "requested_at", "decided_at", "decided_by"]
        read_only_fields = ["status", "decision_notes", "requested_at", "decided_at", "decided_by"]


class MyLeaveView(APIView):
    permission_classes = [IsAuthenticated]

    def employee(self, request):
        employee = employee_record(request.user)
        if not employee:
            raise PermissionDenied("Your account is not linked to an employee record.")
        return employee

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
        return Response(MyLeaveRequestSerializer(request_record).data, status=status.HTTP_201_CREATED)


class MyLeaveDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        employee = employee_record(request.user)
        record = LeaveRequest.objects.filter(pk=pk, employee=employee).first()
        if not record:
            raise PermissionDenied("You cannot access this leave request.")
        if record.status != "pending":
            raise serializers.ValidationError("Only pending leave requests can be cancelled.")
        record.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MyContractSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.__str__", read_only=True)
    business_name = serializers.CharField(source="employee.business.name", read_only=True)

    class Meta:
        model = Contract
        fields = [
            "id", "employee_name", "business_name", "title", "start_date", "end_date",
            "content", "employer_message", "signature_status", "sent_at", "signed_at", "signer_name", "signature_data",
        ]


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
            contract.signed_at = timezone.now()
            contract.signer_name = signer_name
            contract.signature_data = serializer.validated_data["signature_data"]
            contract.signed_ip = request.META.get("REMOTE_ADDR") or None
            contract.save(update_fields=[
                "signature_status", "status", "signed_at", "signer_name", "signature_data", "signed_ip",
            ])
        return Response(MyContractSerializer(contract).data)
