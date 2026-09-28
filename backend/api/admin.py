from django.contrib import admin

from .models import (AccountProfile, Business, Employee, Contract, Attendance,
                     InvitationEmailSettings, LeaveRequest, Holiday, Announcement,
                     CalendarEvent, Salary, Payroll)


@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)


@admin.register(InvitationEmailSettings)
class InvitationEmailSettingsAdmin(admin.ModelAdmin):
    list_display = ("email_host_user", "email_host", "email_port", "owner_business")
    exclude = ("email_host_password",)

    def has_add_permission(self, request):
        return not InvitationEmailSettings.objects.exists()


@admin.register(AccountProfile)
class AccountProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "business")
    list_filter = ("role",)
    readonly_fields = ("user", "role", "business")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = (
        "first_name",
        "last_name",
        "email",
        "department",
        "job_title",
        "date_joined",
        "business",
    )
    search_fields = ("first_name", "last_name", "email")
    list_filter = ("business", "department", "is_active", "employment_type")


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ("employee", "title", "department", "start_date", "end_date", "status", "signature_status", "worker_approval_status", "signed_at")
    list_filter = ("department", "status", "signature_status", "worker_approval_status")
    readonly_fields = ("sent_at", "notification_sent_at", "signed_at", "signer_name", "signature_data", "signed_ip", "content_hash", "worker_approved_at", "worker_approved_by")


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("employee", "date", "shift", "status", "hours_worked")
    list_filter = ("date", "status")


@admin.register(LeaveRequest)
class LeaveAdmin(admin.ModelAdmin):
    list_display = ("employee", "leave_type", "start_date", "end_date", "status")
    list_filter = ("status", "leave_type")


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ("name", "date", "business")


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "business", "created_by", "published_at")


@admin.register(CalendarEvent)
class CalendarEventAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "date", "end_date", "business")


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
