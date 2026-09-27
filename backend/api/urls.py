from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (EmployeeViewSet, ContractViewSet, AttendanceViewSet, LeaveBalanceViewSet, LeaveViewSet,
                    HolidayViewSet, SalaryViewSet, PayrollViewSet, ManagerReportsView)

router = DefaultRouter()
router.register("employees", EmployeeViewSet)
router.register("contracts", ContractViewSet)
router.register("attendance", AttendanceViewSet)
router.register("leave", LeaveViewSet)
router.register("leave-balances", LeaveBalanceViewSet)
router.register("holidays", HolidayViewSet)
router.register("salaries", SalaryViewSet)
router.register("payroll", PayrollViewSet)

urlpatterns = [path("reports/", ManagerReportsView.as_view(), name="manager-reports"),
               path("", include(router.urls))]
