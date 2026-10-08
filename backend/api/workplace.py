"""GPS attendance verification: the employer's saved workplace and the distance check.

The browser only reports coordinates. Whether a check-in or check-out happened
inside the office area is always decided here, against the saved workplace.
"""
from decimal import ROUND_HALF_UP, Decimal
from math import asin, cos, radians, sin, sqrt

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import WorkplaceLocation
from .permissions import IsManager, business_id_for

EARTH_RADIUS_M = 6_371_000
SIX_PLACES = Decimal("0.000001")


def coordinate(value):
    return Decimal(str(value)).quantize(SIX_PLACES, rounding=ROUND_HALF_UP)


def distance_m(lat1, lon1, lat2, lon2):
    """Great-circle (haversine) distance in metres."""
    lat1, lon1, lat2, lon2 = map(lambda value: radians(float(value)), (lat1, lon1, lat2, lon2))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(h))


def blank_location(prefix):
    return {f"{prefix}_location_status": "", f"{prefix}_latitude": None, f"{prefix}_longitude": None,
            f"{prefix}_distance_m": None, f"{prefix}_accuracy_m": None}


def location_fields(business_id, prefix, position):
    """The attendance fields for one check-in or check-out.

    `position` is the validated {latitude, longitude, accuracy} or None when the
    device did not share it. Without a saved workplace nothing is verified.
    """
    workplace = WorkplaceLocation.objects.filter(business_id=business_id).first()
    fields = blank_location(prefix)
    if position:
        fields[f"{prefix}_latitude"] = coordinate(position["latitude"])
        fields[f"{prefix}_longitude"] = coordinate(position["longitude"])
        if position.get("accuracy") is not None:
            fields[f"{prefix}_accuracy_m"] = round(position["accuracy"])
    if workplace is None:
        return fields
    if not position:
        fields[f"{prefix}_location_status"] = "unavailable"
        return fields
    distance = round(distance_m(workplace.latitude, workplace.longitude,
                                position["latitude"], position["longitude"]))
    fields[f"{prefix}_distance_m"] = distance
    fields[f"{prefix}_location_status"] = "inside" if distance <= workplace.radius_m else "outside"
    return fields


class PositionSerializer(serializers.Serializer):
    """Coordinates reported by the employee's device. Both or neither."""
    latitude = serializers.FloatField(min_value=-90, max_value=90, required=False, allow_null=True)
    longitude = serializers.FloatField(min_value=-180, max_value=180, required=False, allow_null=True)
    accuracy = serializers.FloatField(min_value=0, required=False, allow_null=True,
                                      help_text="Reported accuracy in metres.")

    def validate(self, attrs):
        if (attrs.get("latitude") is None) != (attrs.get("longitude") is None):
            raise serializers.ValidationError("Send both latitude and longitude, or neither.")
        return attrs


class WorkplaceLocationSerializer(serializers.ModelSerializer):
    latitude = serializers.FloatField(min_value=-90, max_value=90)
    longitude = serializers.FloatField(min_value=-180, max_value=180)
    radius_m = serializers.IntegerField(min_value=10, max_value=5000, default=100)

    class Meta:
        model = WorkplaceLocation
        fields = ["latitude", "longitude", "radius_m", "updated_by", "updated_at"]
        read_only_fields = ["updated_by", "updated_at"]


class WorkplaceRadiusSerializer(serializers.Serializer):
    radius_m = serializers.IntegerField(min_value=10, max_value=5000)


@extend_schema(tags=["Employer · Attendance"])
class WorkplaceLocationView(APIView):
    permission_classes = [IsManager]

    def body(self, workplace):
        if workplace is None:
            return {"configured": False, "latitude": None, "longitude": None, "radius_m": 100,
                    "updated_by": "", "updated_at": None}
        return {"configured": True, **WorkplaceLocationSerializer(workplace).data}

    def workplace(self, request):
        return WorkplaceLocation.objects.filter(business_id=business_id_for(request.user)).first()

    @extend_schema(summary="Read the workplace location used to verify attendance",
                   responses=WorkplaceLocationSerializer)
    def get(self, request):
        return Response(self.body(self.workplace(request)))

    @extend_schema(summary="Save the workplace location",
                   description="Usually the employer's current position. Check-ins and check-outs within "
                               "`radius_m` (default 100) of this point count as inside the office area.",
                   request=WorkplaceLocationSerializer, responses=WorkplaceLocationSerializer)
    def put(self, request):
        serializer = WorkplaceLocationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        workplace, _ = WorkplaceLocation.objects.update_or_create(
            business_id=business_id_for(request.user),
            defaults={"latitude": coordinate(data["latitude"]), "longitude": coordinate(data["longitude"]),
                      "radius_m": data["radius_m"],
                      "updated_by": request.user.get_full_name().strip() or request.user.username})
        return Response(self.body(workplace))

    @extend_schema(summary="Change the allowed radius", request=WorkplaceRadiusSerializer,
                   responses=WorkplaceLocationSerializer)
    def patch(self, request):
        workplace = self.workplace(request)
        if workplace is None:
            raise serializers.ValidationError("Save the workplace location first.")
        serializer = WorkplaceRadiusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        workplace.radius_m = serializer.validated_data["radius_m"]
        workplace.updated_by = request.user.get_full_name().strip() or request.user.username
        workplace.save(update_fields=["radius_m", "updated_by", "updated_at"])
        return Response(self.body(workplace))
