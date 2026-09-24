from django.contrib import admin

from .models import Employee, Contract, Attendance, LeaveRequest, Holiday, Salary, Payroll


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = (
        "first_name",
        "last_name",
        "email",
        "department",
        "job_title",
        "date_joined",
    )
    search_fields = ("first_name", "last_name", "email")
    list_filter = ("department", "is_active", "employment_type")


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ("employee", "title", "start_date", "end_date", "status")
    list_filter = ("status",)


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("employee", "date", "status", "hours_worked")
    list_filter = ("date", "status")


@admin.register(LeaveRequest)
class LeaveAdmin(admin.ModelAdmin):
    list_display = ("employee", "leave_type", "start_date", "end_date", "status")
    list_filter = ("status", "leave_type")


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ("name", "date")


@admin.register(Salary)
class SalaryAdmin(admin.ModelAdmin):
    list_display = ("employee", "monthly_amount", "currency", "effective_date")


@admin.register(Payroll)
class PayrollAdmin(admin.ModelAdmin):
    list_display = ("employee", "period_start", "period_end", "currency", "net_pay", "status")
    # Use the manager dashboard for validated payroll changes and payslip snapshots.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
