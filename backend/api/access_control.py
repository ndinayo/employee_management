"""Smart room access control: rooms, who may open them, and every unlock attempt.

An employer manages the rooms of their own business and grants individual
employees access by email. Unlocking always runs the full check here on the
server: who is asking, whether they belong to the room's business, whether
they were granted the room, and only then proximity and the door itself
through `door_hardware`. Every attempt is recorded, granted or not.
"""
import logging

from django.db import transaction
from django.db.models import Count, Q
from drf_spectacular.utils import (OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view,
                                   inline_serializer)
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from . import door_hardware
from .accounts import employee_has_approved_contract, employee_record, require_signed_contract, workspace_responses
from .models import Employee, Room, RoomAccessAttempt, RoomAccessGrant, RoomPermissionChange
from .permissions import IsManager, business_id_for, can_manage, is_admin
from .schema import RESPONSE_400, RESPONSE_401, RESPONSE_404, DetailSerializer, with_errors

logger = logging.getLogger(__name__)
TAGS = ["Access control"]
HISTORY_LIMIT = 500


def actor_name(user):
    return user.get_full_name().strip() or user.username


class IsBusinessEmployer(IsManager):
    message = "Room access control is managed by the employer of a business."

    def has_permission(self, request, view):
        return super().has_permission(request, view) and business_id_for(request.user) is not None


# --- Serializers ---------------------------------------------------------------

class RoomSerializer(serializers.ModelSerializer):
    business_name = serializers.CharField(source="business.name", read_only=True)
    authorized_users = serializers.SerializerMethodField(help_text="Employees granted this room.")
    device_status = serializers.SerializerMethodField(
        help_text="`not_configured` until a door hardware integration is connected; `simulator` while an "
                  "employer runs the Door Simulator for the room.")

    class Meta:
        model = Room
        fields = ["id", "business", "business_name", "name", "building", "floor", "door_identifier",
                  "created_by", "created_at", "authorized_users", "device_status"]
        read_only_fields = ["business", "created_by", "created_at"]

    def get_authorized_users(self, obj) -> int:
        count = getattr(obj, "grant_count", None)
        return obj.grants.count() if count is None else count

    def get_device_status(self, obj) -> str:
        return door_hardware.device_status(obj, self.context)

    def validate(self, attrs):
        business_id = self.context["business_id"]
        current = lambda name: attrs.get(name, getattr(self.instance, name, ""))
        others = Room.objects.filter(business_id=business_id).exclude(pk=getattr(self.instance, "pk", None))
        if others.filter(door_identifier__iexact=current("door_identifier")).exists():
            raise serializers.ValidationError({"door_identifier": "Another room already uses this door identifier."})
        if others.filter(name__iexact=current("name"), building__iexact=current("building"),
                         floor__iexact=current("floor")).exists():
            raise serializers.ValidationError({"name": "This building and floor already have a room with this name."})
        return attrs


def grantable_employees(business_id):
    """Only someone already working here, with a sign-in of their own, can be granted a door."""
    return Employee.objects.filter(business_id=business_id, is_active=True, account__role="employee",
                                   account__user__is_active=True)


class RoomAccessGrantSerializer(serializers.ModelSerializer):
    room = serializers.PrimaryKeyRelatedField(queryset=Room.objects.all())
    email = serializers.EmailField(write_only=True, help_text="The employee's registered email address.")
    room_name = serializers.CharField(source="room.name", read_only=True)
    building = serializers.CharField(source="room.building", read_only=True)
    floor = serializers.CharField(source="room.floor", read_only=True)
    employee_name = serializers.SerializerMethodField()
    employee_email = serializers.EmailField(source="employee.email", read_only=True)

    class Meta:
        model = RoomAccessGrant
        fields = ["id", "room", "room_name", "building", "floor", "employee", "employee_name", "employee_email",
                  "email", "granted_by", "granted_at"]
        read_only_fields = ["employee", "granted_by", "granted_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "business_id" in self.context:
            self.fields["room"].queryset = Room.objects.filter(business_id=self.context["business_id"])

    def get_employee_name(self, obj) -> str:
        return str(obj.employee)

    def validate(self, attrs):
        email = attrs.pop("email").strip()
        matches = list(grantable_employees(self.context["business_id"]).filter(
            Q(email__iexact=email) | Q(account__user__email__iexact=email)).distinct()[:2])
        if len(matches) != 1:
            raise serializers.ValidationError({"email": (
                "No active employee with a sign-in account in your business uses this email address."
                if not matches else "More than one employee uses this email address.")})
        attrs["employee"] = matches[0]
        if RoomAccessGrant.objects.filter(room=attrs["room"], employee=matches[0]).exists():
            raise serializers.ValidationError({"email": f"{matches[0]} already has access to this room."})
        return attrs


class BulkGrantSerializer(serializers.Serializer):
    employees = serializers.PrimaryKeyRelatedField(many=True, queryset=Employee.objects.none(), allow_empty=False,
                                                   help_text="Employee ids from your business.")
    rooms = serializers.PrimaryKeyRelatedField(many=True, queryset=Room.objects.none(), allow_empty=False,
                                               help_text="Room ids from your business.")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        business_id = self.context.get("business_id")
        self.fields["employees"].child_relation.queryset = grantable_employees(business_id)
        self.fields["rooms"].child_relation.queryset = Room.objects.filter(business_id=business_id)


class RoomPermissionChangeSerializer(serializers.ModelSerializer):
    change_label = serializers.CharField(source="get_change_display", read_only=True)

    class Meta:
        model = RoomPermissionChange
        fields = ["id", "business", "room", "room_name", "employee", "employee_name", "employee_email",
                  "change", "change_label", "changed_by", "note", "created_at"]


class RoomAccessAttemptSerializer(serializers.ModelSerializer):
    business_name = serializers.CharField(source="business.name", read_only=True)
    access_method_label = serializers.CharField(source="get_access_method_display", read_only=True)
    denial_reason_label = serializers.CharField(source="get_denial_reason_display", read_only=True)
    unlock_status_label = serializers.CharField(source="get_unlock_status_display", read_only=True)

    class Meta:
        model = RoomAccessAttempt
        fields = ["id", "business", "business_name", "room", "room_name", "building", "floor", "employee",
                  "user_name", "user_email", "user_role", "access_method", "access_method_label", "result",
                  "denial_reason", "denial_reason_label", "unlock_status", "unlock_status_label", "created_at"]


class MyRoomSerializer(serializers.ModelSerializer):
    can_unlock = serializers.SerializerMethodField(help_text="True when your employer granted you this room.")
    device_status = serializers.SerializerMethodField()

    class Meta:
        model = Room
        fields = ["id", "name", "building", "floor", "can_unlock", "device_status"]

    def get_can_unlock(self, obj) -> bool:
        return obj.pk in self.context["granted"]

    def get_device_status(self, obj) -> str:
        return door_hardware.device_status(obj, self.context)


class UnlockRequestSerializer(serializers.Serializer):
    access_method = serializers.ChoiceField(
        choices=[choice for choice in RoomAccessAttempt.METHODS if choice[0] != "range"])
    proximity_proof = serializers.CharField(
        required=False, allow_blank=True, max_length=4096,
        help_text="The challenge response read from the door's NFC tag or Bluetooth beacon, or the door code "
                  "shown on a Door Simulator screen. Verified by the server, never by the client.")
    distance_cm = serializers.FloatField(
        required=False, min_value=0, max_value=10000,
        help_text="How far the phone measured itself from the door. Required by doors with a range limit.")


UnlockResultSerializer = inline_serializer(name="UnlockResult", fields={
    "detail": serializers.CharField(),
    "result": serializers.ChoiceField(choices=["granted"]),
    "unlock_status": serializers.ChoiceField(choices=["confirmed", "unconfirmed"]),
})


# --- Employer -------------------------------------------------------------------

class BusinessScoped:
    permission_classes = [IsBusinessEmployer]

    def business_id(self):
        return business_id_for(self.request.user)

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "business_id": self.business_id()}


@extend_schema(tags=TAGS)
@extend_schema_view(
    list=extend_schema(summary="List your rooms", responses=with_errors({200: RoomSerializer(many=True)},
                                                                        bad_request=False)),
    retrieve=extend_schema(summary="Read one room", responses=with_errors({200: RoomSerializer},
                                                                          bad_request=False, not_found=True)),
    create=extend_schema(summary="Add a room", responses=with_errors({201: RoomSerializer})),
    update=extend_schema(summary="Replace a room", responses=with_errors({200: RoomSerializer}, not_found=True)),
    partial_update=extend_schema(summary="Update a room",
                                 responses=with_errors({200: RoomSerializer}, not_found=True)),
    destroy=extend_schema(summary="Delete a room",
                          description="Every access granted to the room is revoked and recorded as revoked. "
                                      "Past unlock attempts stay in the access history.",
                          responses=with_errors({204: OpenApiResponse(description="Deleted.")},
                                                bad_request=False, not_found=True)),
)
class RoomViewSet(BusinessScoped, viewsets.ModelViewSet):
    serializer_class = RoomSerializer
    queryset = Room.objects.select_related("business").annotate(grant_count=Count("grants"))

    def get_queryset(self):
        return super().get_queryset().filter(business_id=self.business_id())

    def perform_create(self, serializer):
        serializer.save(business_id=self.business_id(), created_by=actor_name(self.request.user))

    @transaction.atomic
    def perform_destroy(self, instance):
        for grant in instance.grants.select_related("employee"):
            log_change(grant, "revoked", self.request.user, note="Room deleted")
        instance.delete()


def log_change(grant, change, user, note=""):
    RoomPermissionChange.objects.create(
        business_id=grant.room.business_id, room=grant.room, room_name=grant.room.name,
        employee=grant.employee, employee_name=str(grant.employee), employee_email=grant.employee.email,
        change=change, changed_by=actor_name(user), note=note)


ROOM_FILTER = OpenApiParameter("room", int, description="Only this room.")


@extend_schema(tags=TAGS)
@extend_schema_view(
    list=extend_schema(summary="List room access permissions", parameters=[ROOM_FILTER],
                       responses=with_errors({200: RoomAccessGrantSerializer(many=True)}, bad_request=False)),
    create=extend_schema(
        summary="Grant an employee access to a room",
        description="`email` must belong to an active employee of your business who has a sign-in account. "
                    "The change is recorded in the permission history.",
        responses=with_errors({201: RoomAccessGrantSerializer})),
    destroy=extend_schema(summary="Revoke access", description="Recorded in the permission history.",
                          responses=with_errors({204: OpenApiResponse(description="Revoked.")},
                                                bad_request=False, not_found=True)),
)
class RoomAccessGrantViewSet(BusinessScoped, mixins.ListModelMixin, mixins.CreateModelMixin,
                             mixins.DestroyModelMixin, viewsets.GenericViewSet):
    serializer_class = RoomAccessGrantSerializer
    queryset = RoomAccessGrant.objects.select_related("room", "employee")

    def get_queryset(self):
        queryset = super().get_queryset().filter(room__business_id=self.business_id())
        return filter_by_room(queryset, self.request)

    @transaction.atomic
    def perform_create(self, serializer):
        log_change(serializer.save(granted_by=actor_name(self.request.user)), "granted", self.request.user)

    @transaction.atomic
    def perform_destroy(self, instance):
        log_change(instance, "revoked", self.request.user)
        instance.delete()

    @extend_schema(
        summary="Grant several employees several rooms at once",
        description="Gives every listed employee access to every listed room. Pairs that already have access "
                    "are left as they are. Each new permission is recorded in the permission history.",
        request=BulkGrantSerializer,
        responses=with_errors({201: inline_serializer(name="BulkGrantResult", fields={
            "granted": serializers.IntegerField(), "already_had_access": serializers.IntegerField(),
            "grants": RoomAccessGrantSerializer(many=True)})}))
    @action(detail=False, methods=["post"], url_path="bulk")
    def bulk(self, request):
        serializer = BulkGrantSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        employees = list({row.pk: row for row in serializer.validated_data["employees"]}.values())
        rooms = list({row.pk: row for row in serializer.validated_data["rooms"]}.values())
        existing = set(RoomAccessGrant.objects.filter(employee__in=employees, room__in=rooms)
                       .values_list("employee_id", "room_id"))
        created = []
        with transaction.atomic():
            for room in rooms:
                for employee in employees:
                    if (employee.pk, room.pk) in existing:
                        continue
                    grant = RoomAccessGrant.objects.create(room=room, employee=employee,
                                                           granted_by=actor_name(request.user))
                    log_change(grant, "granted", request.user)
                    created.append(grant)
        return Response({"granted": len(created), "already_had_access": len(existing),
                         "grants": RoomAccessGrantSerializer(created, many=True).data},
                        status=status.HTTP_201_CREATED)


def filter_by_room(queryset, request):
    room = request.query_params.get("room")
    if not room:
        return queryset
    if not room.isdigit():
        raise NotFound("Unknown room.")
    return queryset.filter(room_id=room)


@extend_schema(tags=TAGS)
@extend_schema_view(list=extend_schema(
    summary="Room permission history",
    description=f"Every grant and revocation in your business, newest first (latest {HISTORY_LIMIT}).",
    parameters=[ROOM_FILTER],
    responses=with_errors({200: RoomPermissionChangeSerializer(many=True)}, bad_request=False)))
class RoomPermissionChangeViewSet(BusinessScoped, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = RoomPermissionChangeSerializer
    queryset = RoomPermissionChange.objects.all()

    def get_queryset(self):
        return filter_by_room(super().get_queryset().filter(business_id=self.business_id()),
                              self.request)[:HISTORY_LIMIT]


@extend_schema(tags=TAGS)
@extend_schema_view(list=extend_schema(
    summary="Room access history",
    description=f"Every unlock attempt on your business's doors, newest first (latest {HISTORY_LIMIT}).",
    parameters=[ROOM_FILTER, OpenApiParameter("result", str, enum=["granted", "denied"])],
    responses=with_errors({200: RoomAccessAttemptSerializer(many=True)}, bad_request=False)))
class RoomAccessHistoryViewSet(BusinessScoped, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = RoomAccessAttemptSerializer
    queryset = RoomAccessAttempt.objects.select_related("business")

    def get_queryset(self):
        queryset = filter_by_room(super().get_queryset().filter(business_id=self.business_id()), self.request)
        result = self.request.query_params.get("result")
        if result:
            queryset = queryset.filter(result=result)
        return queryset[:HISTORY_LIMIT]


# --- Unlocking ------------------------------------------------------------------

class UnlockThrottle(UserRateThrottle):
    scope = "door_unlock"
    rate = "20/min"


DENIAL_MESSAGES = {
    "admin_no_policy": "Platform administrators cannot unlock doors without an explicit authorization policy.",
    "inactive": "Your employee profile is inactive.",
    "not_approved": "Your employer must approve your signed contract before you can unlock doors.",
    "password_change_required": "Replace your temporary password before unlocking doors.",
    "no_permission": "Your employer has not granted you access to this room.",
    "proximity_failed": "Your presence at this door could not be verified. Hold your phone to the door reader "
                        "and try again.",
}


def denial_reason(user, room):
    """Why `user` may not open `room`, or None when they may."""
    if is_admin(user):
        return "admin_no_policy"
    if can_manage(user):
        return None if business_id_for(user) == room.business_id else "not_member"
    employee = employee_record(user)
    if employee is None or employee.business_id != room.business_id:
        return "not_member"
    if user.account_profile.must_change_password:
        return "password_change_required"
    if not employee.is_active:
        return "inactive"
    if not employee_has_approved_contract(employee):
        return "not_approved"
    if not RoomAccessGrant.objects.filter(room=room, employee=employee).exists():
        return "no_permission"
    return None


@extend_schema(
    tags=TAGS, summary="Unlock a door",
    description=(
        "For the room's employer, and for employees their employer granted this room. In order: the "
        "account must belong to the room's business, an employee needs an approved contract and a grant "
        "for this room, then the door hardware integration verifies the `proximity_proof` and opens the "
        "door. Every request is recorded in the access history, whatever the outcome.\n\n"
        "Until a door hardware integration is configured the answer is **503** and nothing is unlocked; "
        "a successful unlock is never simulated. Platform administrators are always refused."),
    request=UnlockRequestSerializer,
    responses={
        200: UnlockResultSerializer,
        400: RESPONSE_400,
        401: RESPONSE_401,
        403: OpenApiResponse(DetailSerializer, description="Not permitted, or proximity not verified."),
        404: RESPONSE_404,
        429: OpenApiResponse(DetailSerializer, description="Too many unlock requests."),
        502: OpenApiResponse(DetailSerializer, description="The door controller did not respond."),
        503: OpenApiResponse(DetailSerializer, description="No door hardware integration is configured."),
    },
)
class RoomUnlockView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [UnlockThrottle]

    def post(self, request, pk):
        serializer = UnlockRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        method = serializer.validated_data["access_method"]
        proof = serializer.validated_data.get("proximity_proof", "")
        room = Room.objects.select_related("business").filter(pk=pk).first()
        if room is None:
            raise NotFound("No room matches the given query.")
        user = request.user
        profile = getattr(user, "account_profile", None)

        def record(result, reason="", unlock_status=""):
            RoomAccessAttempt.objects.create(
                business_id=room.business_id, room=room, room_name=room.name, building=room.building,
                floor=room.floor, user=user, employee=employee_record(user), user_name=actor_name(user),
                user_email=user.email, user_role=profile.role if profile else "manager",
                access_method=method, result=result, denial_reason=reason, unlock_status=unlock_status,
                ip_address=request.META.get("REMOTE_ADDR") or None)

        def deny(reason, status_code=status.HTTP_403_FORBIDDEN, message=None):
            record("denied", reason)
            return Response({"detail": message or DENIAL_MESSAGES[reason]}, status=status_code)

        reason = denial_reason(user, room)
        if reason == "not_member":
            record("denied", reason)
            raise NotFound("No room matches the given query.")
        if reason:
            return deny(reason)
        gateway = door_hardware.gateway_for(room)
        if not gateway.configured:
            return deny("hardware_not_configured", status.HTTP_503_SERVICE_UNAVAILABLE,
                        "Door hardware integration is not configured for this room. No unlock command was sent.")
        max_distance = gateway.max_distance_cm
        distance = serializer.validated_data.get("distance_cm")
        if max_distance is not None and (distance is None or distance > max_distance):
            return deny("too_far", message="Get closer to the door.")
        if not proof or not gateway.verify_proximity(room, user, method, proof):
            return deny("proximity_failed", message="That door code is not right. Check the code on the door "
                        "screen and try again." if method == "door_code" else None)
        try:
            confirmed = gateway.unlock(room, user)
        except Exception:
            logger.exception("Door controller failed to unlock room %s", room.pk)
            record("granted", unlock_status="failed")
            return Response({"detail": "Access was granted, but the door controller did not respond. "
                                       "The door may still be locked."}, status=status.HTTP_502_BAD_GATEWAY)
        unlock_status = "confirmed" if confirmed else "unconfirmed"
        record("granted", unlock_status=unlock_status)
        return Response({"detail": "Door unlocked." if confirmed else "Unlock sent to the door.",
                         "result": "granted", "unlock_status": unlock_status})


# --- Employee ------------------------------------------------------------------

MY_TAGS = ["Employee workspace"]


@extend_schema(tags=MY_TAGS, summary="Your employer's rooms",
               description="Every room of your employer. `can_unlock` marks the rooms you were granted.",
               responses=workspace_responses({200: MyRoomSerializer(many=True)}, bad_request=False))
class MyRoomsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        employee = my_employee(request)
        granted = set(RoomAccessGrant.objects.filter(employee=employee).values_list("room_id", flat=True))
        rooms = Room.objects.filter(business_id=employee.business_id)
        return Response(MyRoomSerializer(rooms, many=True, context={"granted": granted}).data)


@extend_schema(tags=MY_TAGS, summary="Your door access history",
               description=f"Your own unlock attempts, newest first (latest {HISTORY_LIMIT}).",
               responses=workspace_responses({200: RoomAccessAttemptSerializer(many=True)}, bad_request=False))
class MyAccessHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        my_employee(request)
        attempts = RoomAccessAttempt.objects.filter(user=request.user).select_related("business")[:HISTORY_LIMIT]
        return Response(RoomAccessAttemptSerializer(attempts, many=True).data)


def my_employee(request):
    employee = employee_record(request.user)
    if not employee:
        raise PermissionDenied("Your account is not linked to an employee record.")
    return require_signed_contract(employee)
