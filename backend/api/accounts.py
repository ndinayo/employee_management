from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import AccountProfile, Business
from .permissions import can_manage


def account_data(user):
    profile = getattr(user, "account_profile", None)
    manager = can_manage(user)
    return {
        "id": user.pk, "username": user.username, "email": user.email,
        "role": profile.role if profile else ("manager" if manager else "employee"),
        "business_name": profile.business.name if profile and profile.business_id else "",
        "can_manage": manager,
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


class AccountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(account_data(request.user))
