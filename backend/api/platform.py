"""Platform administrator: every employer and every employee, across businesses."""
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from . import onboarding
from .models import AccountProfile, Business, Employee, Holiday
from .permissions import IsAdmin
from .serializers import EmployeeSerializer


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
def purge_employer(user):
    profile = user.account_profile
    business = profile.business
    for employee in list(Employee.objects.filter(business=business)):
        onboarding.purge_employee(employee)
    Holiday.objects.filter(business=business).delete()
    profile.delete()
    user.delete()
    business.delete()


class AdminOverviewView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        employees = Employee.objects.all()
        return Response({
            "businesses": Business.objects.count(),
            "employers": AccountProfile.objects.filter(role="employer").count(),
            "employees": employees.count(),
            "active_employees": employees.filter(is_active=True).count(),
            "invited_employees": AccountProfile.objects.filter(role="employee", must_change_password=True).count(),
        })


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

    def delete(self, request, pk):
        purge_employer(self.get_user(pk))
        return Response(status=204)


class AdminEmployeeListView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        rows = Employee.objects.select_related("business", "account__user").order_by("last_name", "first_name", "id")
        return Response(AdminEmployeeSerializer(rows, many=True).data)

    def post(self, request):
        serializer = AdminEmployeeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(AdminEmployeeSerializer(serializer.save()).data, status=201)


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


class AdminBusinessListView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        return Response([{"id": row.pk, "name": row.name} for row in Business.objects.order_by("name")])
