"""Every company's records, read-only, for the platform administrator.

Each resource is listed exactly as its employer sees it, across all companies or
filtered to one company or employee. The administrator can read but never change
these records; changes stay with each employer.
"""
from django.db.models import Count, Q
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from .access_control import (RoomAccessAttemptSerializer, RoomAccessGrantSerializer, RoomPermissionChangeSerializer,
                             RoomSerializer)
from .models import (Announcement, CalendarEvent, Employee, Holiday, Room, RoomAccessAttempt, RoomAccessGrant,
                     RoomPermissionChange, SalaryAdvanceRequest, WorkplaceLocation)
from .payroll_serializers import AdvanceRequestSerializer
from .payroll_views import AssetIncidentViewSet, SalaryAdvanceViewSet
from .permissions import IsAdmin
from .schema import RESPONSE_403_ADMIN, with_errors
from .views import (AnnouncementViewSet, AttendanceViewSet, CalendarEventViewSet, ContractViewSet,
                    EmployeeViewSet, HolidayViewSet, LeaveBalanceViewSet, LeaveViewSet, PayrollViewSet,
                    SalaryViewSet)


class WorkplaceLocationRecordSerializer(serializers.ModelSerializer):
    business_name = serializers.CharField(source="business.name", read_only=True)

    class Meta:
        model = WorkplaceLocation
        fields = ["id", "business", "business_name", "latitude", "longitude", "radius_m", "updated_by", "updated_at"]


def from_viewset(viewset):
    return viewset.queryset, viewset.serializer_class


SOURCES = {
    "employees": from_viewset(EmployeeViewSet),
    "contracts": from_viewset(ContractViewSet),
    "attendance": from_viewset(AttendanceViewSet),
    "leave": from_viewset(LeaveViewSet),
    "leave-balances": from_viewset(LeaveBalanceViewSet),
    "salaries": from_viewset(SalaryViewSet),
    "payroll": from_viewset(PayrollViewSet),
    "salary-advances": from_viewset(SalaryAdvanceViewSet),
    "salary-advance-requests": (SalaryAdvanceRequest.objects.select_related("employee").order_by("-requested_at"),
                                AdvanceRequestSerializer),
    "asset-incidents": from_viewset(AssetIncidentViewSet),
    "announcements": from_viewset(AnnouncementViewSet),
    "calendar-events": from_viewset(CalendarEventViewSet),
    "holidays": from_viewset(HolidayViewSet),
    "workplace-locations": (WorkplaceLocation.objects.select_related("business"), WorkplaceLocationRecordSerializer),
    "rooms": (Room.objects.select_related("business").annotate(grant_count=Count("grants")), RoomSerializer),
    "room-access-grants": (RoomAccessGrant.objects.select_related("room", "employee"), RoomAccessGrantSerializer),
    "room-permission-changes": (RoomPermissionChange.objects.all(), RoomPermissionChangeSerializer),
    "room-access-history": (RoomAccessAttempt.objects.select_related("business"), RoomAccessAttemptSerializer),
}
BUSINESS_OWNED = (Employee, Holiday, Announcement, CalendarEvent, WorkplaceLocation, Room, RoomPermissionChange,
                  RoomAccessAttempt)
# Business-owned records that also name one employee.
EMPLOYEE_NAMED = (RoomPermissionChange, RoomAccessAttempt)


@extend_schema(
    tags=["Platform administration"], summary="Read any company's records",
    description="Lists one kind of record exactly as its employer sees it. Read-only. Filter with "
                "`business` and, for employee records, `employee`.",
    parameters=[
        OpenApiParameter("resource", str, OpenApiParameter.PATH, enum=list(SOURCES)),
        OpenApiParameter("business", int, description="Only this company's records."),
        OpenApiParameter("employee", int, description="Only this employee's records."),
    ],
    responses=with_errors({200: OpenApiTypes.OBJECT}, forbidden=RESPONSE_403_ADMIN, bad_request=False,
                          not_found=True),
)
class AdminRecordsView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request, resource):
        if resource not in SOURCES:
            raise NotFound("Unknown record type.")
        queryset, serializer_class = SOURCES[resource]
        queryset = queryset.all()
        owned = queryset.model in BUSINESS_OWNED
        business, employee = request.query_params.get("business"), request.query_params.get("employee")
        if not all(value.isdigit() for value in (business, employee) if value):
            raise NotFound("Unknown company or employee.")
        if business:
            queryset = queryset.filter(**{"business_id" if owned else "employee__business_id": business})
        if employee:
            if queryset.model is Employee:
                queryset = queryset.filter(pk=employee)
            elif queryset.model is CalendarEvent:
                queryset = queryset.filter(Q(invited_employees=employee) | Q(all_employees=True, business__employee=employee))
            elif owned and queryset.model not in EMPLOYEE_NAMED:
                queryset = queryset.filter(business__employee=employee)
            else:
                queryset = queryset.filter(employee_id=employee)
        return Response(serializer_class(queryset.distinct(), many=True, context={"request": request}).data)
