"""Door Simulator: an employer's laptop acting as a room's door for testing.

While the simulator page is open it checks in every second. For that time the
room's unlock requests go to `SimulatorGateway` instead of the hardware
integration. The simulator screen shows a door code of `CODE_DIGITS` digits
that changes every `CODE_PERIOD` seconds. Reading it off the door screen is
what stands in for being at the door, so an employee with access types it into
their phone to unlock. A granted unlock opens the virtual door for
`UNLOCK_SECONDS`.
"""
import hmac
import secrets
import time
from datetime import timedelta
from hashlib import sha256

from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .access_control import IsBusinessEmployer, RoomAccessAttemptSerializer
from .door_hardware import DoorGateway
from .models import Room, RoomAccessAttempt, SimulatedDoor
from .permissions import business_id_for
from .schema import with_errors

UNLOCK_SECONDS = 5
CODE_DIGITS = 4
# Short enough that a code seen earlier is useless, long enough to read and type.
CODE_PERIOD = 30
# A simulator that stops checking in is treated as switched off.
HEARTBEAT_TIMEOUT = timedelta(seconds=15)
TAGS = ["Access control"]


def door_code(secret, window):
    digest = hmac.new(secret.encode(), str(window).encode(), sha256).digest()
    return f"{int.from_bytes(digest[-4:], 'big') % 10 ** CODE_DIGITS:0{CODE_DIGITS}d}"


def code_matches(door, proof):
    """True for the code showing now, and for the one just before it so a slow typist still gets in."""
    window = int(time.time() // CODE_PERIOD)
    typed = "".join((proof or "").split())
    return any(hmac.compare_digest(door_code(door.secret, step), typed) for step in (window, window - 1))


def active_doors():
    return SimulatedDoor.objects.filter(last_seen_at__gte=timezone.now() - HEARTBEAT_TIMEOUT)


def active_room_ids():
    return set(active_doors().values_list("room_id", flat=True))


class SimulatorGateway(DoorGateway):
    def __init__(self, door):
        self.door = door

    def device_status(self, room):
        return "simulator"

    def verify_proximity(self, room, user, method, proof):
        return method == "door_code" and code_matches(self.door, proof)

    def unlock(self, room, user):
        self.door.unlocked_until = timezone.now() + timedelta(seconds=UNLOCK_SECONDS)
        self.door.save(update_fields=["unlocked_until"])
        return True


def state(door):
    now = timezone.now()
    open_for = (door.unlocked_until - now).total_seconds() if door.unlocked_until else 0
    room = door.room
    recent = RoomAccessAttempt.objects.filter(room=room, created_at__gte=door.started_at).select_related("business")[:5]
    seconds = time.time()
    return {
        "room": room.pk, "room_name": room.name, "building": room.building, "floor": room.floor,
        "locked": open_for <= 0, "relocks_in": max(0, round(open_for, 1)),
        "door_code": door_code(door.secret, int(seconds // CODE_PERIOD)),
        "code_changes_in": round(CODE_PERIOD - seconds % CODE_PERIOD),
        "started_by": door.started_by, "started_at": door.started_at,
        "recent": RoomAccessAttemptSerializer(recent, many=True).data,
    }


SimulatorStateSerializer = inline_serializer(name="DoorSimulatorState", fields={
    "room": serializers.IntegerField(), "room_name": serializers.CharField(), "building": serializers.CharField(),
    "floor": serializers.CharField(), "locked": serializers.BooleanField(),
    "relocks_in": serializers.FloatField(help_text="Seconds until the door locks again; 0 when locked."),
    "door_code": serializers.CharField(help_text="Show this on the door screen only; it is what an employee "
                                                 "standing at the door reads and types in."),
    "code_changes_in": serializers.IntegerField(help_text="Seconds until the door code changes."),
    "started_by": serializers.CharField(),
    "started_at": serializers.DateTimeField(), "recent": serializers.ListField(child=serializers.DictField()),
})


def employer_room(request, pk):
    return Room.objects.filter(pk=pk, business_id=business_id_for(request.user)).first()


def not_found():
    return Response({"detail": "No room matches the given query."}, status=status.HTTP_404_NOT_FOUND)


@extend_schema(tags=TAGS)
class DoorSimulatorView(APIView):
    permission_classes = [IsBusinessEmployer]

    @extend_schema(summary="Start the door simulator for a room",
                   description="Turns this browser into the room's door until it stops checking in. A new door "
                               "secret is issued each time, so earlier door codes stop working.",
                   request=None, responses=with_errors({200: SimulatorStateSerializer}, bad_request=False,
                                                       not_found=True))
    def post(self, request, pk):
        room = employer_room(request, pk)
        if room is None:
            return not_found()
        now = timezone.now()
        door, _ = SimulatedDoor.objects.update_or_create(room=room, defaults={
            "secret": secrets.token_hex(32), "started_at": now, "last_seen_at": now, "unlocked_until": None,
            "started_by": request.user.get_full_name().strip() or request.user.username})
        return Response(state(door))

    @extend_schema(summary="Read the simulated door",
                   description="Polled every second by the simulator page; each call keeps the simulator running.",
                   responses=with_errors({200: SimulatorStateSerializer}, bad_request=False, not_found=True))
    def get(self, request, pk):
        room = employer_room(request, pk)
        door = SimulatedDoor.objects.filter(room=room).first() if room else None
        if door is None:
            return not_found()
        door.last_seen_at = timezone.now()
        door.save(update_fields=["last_seen_at"])
        return Response(state(door))

    @extend_schema(summary="Stop the door simulator",
                   responses=with_errors({204: OpenApiResponse(description="Stopped.")}, bad_request=False,
                                         not_found=True))
    def delete(self, request, pk):
        room = employer_room(request, pk)
        if room is None:
            return not_found()
        SimulatedDoor.objects.filter(room=room).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
