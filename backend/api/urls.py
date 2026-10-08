from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (EmployeeViewSet, ContractViewSet, AttendanceViewSet, LeaveBalanceViewSet, LeaveViewSet,
                    HolidayViewSet, AnnouncementViewSet, CalendarEventViewSet,
                    SalaryViewSet, PayrollViewSet, ManagerReportsView)
from .payroll_views import (AssetIncidentViewSet, PayrollCalculationViewSet, PayrollPolicyView,
                            SalaryAdvanceRequestViewSet, SalaryAdvanceViewSet)

router = DefaultRouter()
router.register("employees", EmployeeViewSet)
router.register("contracts", ContractViewSet)
router.register("attendance", AttendanceViewSet)
router.register("leave", LeaveViewSet)
router.register("leave-balances", LeaveBalanceViewSet)
router.register("holidays", HolidayViewSet)
router.register("announcements", AnnouncementViewSet)
router.register("calendar-events", CalendarEventViewSet)
router.register("salaries", SalaryViewSet)
router.register("payroll", PayrollViewSet)
router.register("payroll-calculations", PayrollCalculationViewSet, basename="payroll-calculation")
router.register("salary-advances", SalaryAdvanceViewSet)
router.register("salary-advance-requests", SalaryAdvanceRequestViewSet, basename="salary-advance-request")
router.register("asset-incidents", AssetIncidentViewSet)

urlpatterns = [path("reports/", ManagerReportsView.as_view(), name="manager-reports"),
               path("payroll-policy/", PayrollPolicyView.as_view(), name="payroll-policy"),
               path("", include(router.urls))]
