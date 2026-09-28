from decimal import Decimal
from datetime import time
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.validators import FileExtensionValidator, MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models.signals import pre_save
from django.dispatch import receiver


def contract_path(instance, filename):
    return f"contracts/{uuid4().hex}{Path(filename).suffix.lower()}"


def photo_path(instance, filename):
    return f"photos/{uuid4().hex}{Path(filename).suffix.lower()}"


def money_field(**kwargs):
    return models.DecimalField(max_digits=12, decimal_places=2,
                               validators=[MinValueValidator(Decimal('0'))], **kwargs)


class Business(models.Model):
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    # Optional per-business SMTP. When set, invitation email is sent from here
    # instead of the server console (which never reaches a real inbox).
    email_host = models.CharField(max_length=200, blank=True)
    email_port = models.PositiveIntegerField(default=587)
    email_use_tls = models.BooleanField(default=True)
    email_host_user = models.EmailField(blank=True)
    email_host_password = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return self.name


class InvitationEmailSettings(models.Model):
    """The single SMTP sender used for invitations across the platform."""

    owner_business = models.ForeignKey(
        Business, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="owned_invitation_email_settings",
    )
    email_host = models.CharField(max_length=200, default="smtp.gmail.com")
    email_port = models.PositiveIntegerField(default=587)
    email_use_tls = models.BooleanField(default=True)
    email_host_user = models.EmailField(blank=True)
    email_host_password = models.CharField(max_length=200, blank=True)

    def save(self, *args, **kwargs):
        # There can only be one shared sender configuration.
        self.pk = 1
        return super().save(*args, **kwargs)


class AccountProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="account_profile")
    role = models.CharField(max_length=10, choices=[
        ("employee", "Employee"), ("employer", "Employer"), ("admin", "Admin")])
    business = models.OneToOneField(Business, on_delete=models.PROTECT, null=True, blank=True, related_name="owner_profile")
    # Set when an employer creates the employee; self-signed-up employees have
    # no record until an employer hires them.
    employee = models.OneToOneField("Employee", on_delete=models.SET_NULL, null=True, blank=True, related_name="account")
    must_change_password = models.BooleanField(default=False)

    class Meta:
        constraints = [models.CheckConstraint(
            condition=(
                models.Q(role="employee", business__isnull=True)
                | models.Q(role="employer", business__isnull=False)
                | models.Q(role="admin", business__isnull=True)
            ),
            name="account_role_matches_business",
        )]


class Employee(models.Model):
    # Existing records remain in the original managers' workspace (business=NULL).
    business = models.ForeignKey(Business, on_delete=models.PROTECT, null=True, blank=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    department = models.CharField(max_length=100, blank=True)
    job_title = models.CharField(max_length=100)
    date_joined = models.DateField()
    phone = models.CharField(max_length=40, blank=True)
    address = models.TextField(blank=True)
    emergency_contact = models.CharField(max_length=200, blank=True)
    manager_name = models.CharField(max_length=200, blank=True)
    job_description = models.TextField(blank=True)
    employment_type = models.CharField(max_length=20, default="full_time", choices=[
        ("full_time", "Full time"), ("part_time", "Part time"),
        ("contract", "Contract"), ("intern", "Intern")])
    photo = models.ImageField(upload_to=photo_path, blank=True,
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp"])])
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["business", "email"], name="unique_business_employee_email"),
            models.UniqueConstraint(fields=["email"], condition=models.Q(business__isnull=True), name="unique_legacy_employee_email"),
        ]


class Contract(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="contracts")
    revision_of = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="revisions")
    title = models.CharField(max_length=200)
    department = models.CharField(max_length=100, blank=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, default="active", choices=[
        ("draft", "Draft"), ("active", "Active"), ("ended", "Ended"),
        ("terminated_mutual", "Terminated by Mutual Agreement")])
    terms = models.TextField(blank=True)
    content = models.TextField(blank=True)
    document = models.FileField(upload_to=contract_path, blank=True,
        validators=[FileExtensionValidator(["pdf", "doc", "docx"])])
    signature_status = models.CharField(max_length=20, default="draft", choices=[
        ("draft", "Draft"), ("sent", "Awaiting signature"), ("signed", "Signed")])
    worker_approval_status = models.CharField(max_length=20, default="pending", choices=[
        ("pending", "Awaiting employer approval"), ("approved", "Approved to start work")])
    worker_approved_at = models.DateTimeField(null=True, blank=True)
    worker_approved_by = models.CharField(max_length=200, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    notification_sent_at = models.DateTimeField(null=True, blank=True)
    employer_message = models.TextField(blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    signer_name = models.CharField(max_length=200, blank=True)
    signature_data = models.TextField(blank=True)
    signed_ip = models.GenericIPAddressField(null=True, blank=True)
    content_hash = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ContractTerminationRequest(models.Model):
    contract = models.ForeignKey(Contract, on_delete=models.PROTECT, related_name="termination_requests")
    initiated_by = models.CharField(max_length=20, choices=[("employee", "Employee"), ("employer", "Employer")])
    reason = models.TextField()
    proposed_last_working_date = models.DateField()
    status = models.CharField(max_length=30, default="pending", choices=[
        ("pending", "Awaiting employer review"),
        ("awaiting_acknowledgement", "Awaiting employee acknowledgement"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("acknowledged", "Acknowledged"),
    ])
    response_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)


class Attendance(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="attendance")
    date = models.DateField()
    shift = models.CharField(max_length=20, default="day", choices=[
        ("day", "Day"), ("night", "Night")])
    status = models.CharField(max_length=20, default="present", choices=[
        ("present", "Present"), ("remote", "Remote"), ("absent", "Absent")])
    hours_worked = models.DecimalField(max_digits=4, decimal_places=2, default=0,
        validators=[MinValueValidator(0), MaxValueValidator(24)])
    check_in_at = models.DateTimeField(null=True, blank=True)
    check_out_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["employee", "date", "shift"], name="unique_employee_attendance_shift")]


class LeaveRequest(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="leave_requests")
    leave_type = models.CharField(max_length=20, default="annual", choices=[
        ("annual", "Annual"), ("sick", "Sick"), ("maternity", "Maternity"),
        ("unpaid", "Unpaid")])
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, default="pending", choices=[
        ("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")])
    decision_notes = models.TextField(blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.CharField(max_length=200, blank=True)


class LeaveBalance(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="leave_balances")
    leave_type = models.CharField(max_length=20, choices=[
        ("annual", "Annual"), ("sick", "Sick"), ("maternity", "Maternity"),
        ("unpaid", "Unpaid")])
    year = models.PositiveIntegerField()
    days_allocated = models.DecimalField(max_digits=5, decimal_places=1, default=0,
        validators=[MinValueValidator(0), MaxValueValidator(366)])

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["employee", "leave_type", "year"], name="unique_employee_leave_balance")]


class Holiday(models.Model):
    business = models.ForeignKey(Business, on_delete=models.PROTECT, null=True, blank=True)
    name = models.CharField(max_length=200)
    date = models.DateField()
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["business", "date"], name="unique_business_holiday_date"),
            models.UniqueConstraint(fields=["date"], condition=models.Q(business__isnull=True), name="unique_legacy_holiday_date"),
        ]


class Announcement(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="announcements")
    title = models.CharField(max_length=200)
    message = models.TextField()
    created_by = models.CharField(max_length=200, blank=True)
    published_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-published_at", "-id"]


class AnnouncementRead(models.Model):
    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE, related_name="reads")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="announcement_reads")
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["announcement", "employee"], name="unique_employee_announcement_read")]


class CalendarEvent(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="calendar_events")
    all_employees = models.BooleanField(default=True)
    invited_employees = models.ManyToManyField(Employee, blank=True, related_name="calendar_events")
    title = models.CharField(max_length=200)
    category = models.CharField(max_length=30, default="other", choices=[
        ("holiday", "Holiday"), ("presentation", "Presentation"),
        ("meeting", "Meeting"), ("training", "Training"), ("other", "Other")])
    date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    start_time = models.TimeField(default=time(9, 0))
    end_time = models.TimeField(default=time(10, 0))
    location = models.CharField(max_length=250, blank=True)
    description = models.TextField(blank=True)
    created_by = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "id"]


class CalendarEventRead(models.Model):
    event = models.ForeignKey(CalendarEvent, on_delete=models.CASCADE, related_name="reads")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="calendar_event_reads")
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["event", "employee"], name="unique_employee_calendar_event_read")]


class Salary(models.Model):
    employee = models.OneToOneField(Employee, on_delete=models.PROTECT, related_name="salary")
    monthly_amount = money_field()
    currency = models.CharField(max_length=3, default="RWF")
    effective_date = models.DateField()
    notes = models.TextField(blank=True)


class Payroll(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="payroll")
    period_start = models.DateField()
    period_end = models.DateField()
    base_salary = money_field()
    allowances = money_field(default=0)
    deductions = money_field(default=0)
    currency = models.CharField(max_length=3, default="RWF")
    status = models.CharField(max_length=20, default="draft", choices=[("draft", "Draft"), ("paid", "Paid")])
    paid_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    employee_name = models.CharField(max_length=201, editable=False)
    employee_email = models.EmailField(editable=False)
    department = models.CharField(max_length=100, editable=False)
    job_title = models.CharField(max_length=100, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def gross_pay(self):
        return self.base_salary + self.allowances

    @property
    def net_pay(self):
        return self.gross_pay - self.deductions

    class Meta:
        constraints = [models.UniqueConstraint(fields=["employee", "period_start", "period_end"], name="unique_employee_pay_period")]


def discard_replaced_file(model, instance, field):
    """Delete the stored file a save is about to replace.

    Files belonging to deleted rows are deliberately left on disk, so this only
    runs when an existing row points at a different file than the one saved.
    """
    if not instance.pk:
        return
    try:
        previous = getattr(model.objects.get(pk=instance.pk), field)
    except model.DoesNotExist:
        return
    if previous and previous.name != getattr(instance, field).name:
        previous.delete(save=False)


@receiver(pre_save, sender=Employee)
def discard_replaced_photo(sender, instance, **kwargs):
    discard_replaced_file(sender, instance, "photo")


@receiver(pre_save, sender=Contract)
def discard_replaced_document(sender, instance, **kwargs):
    discard_replaced_file(sender, instance, "document")
