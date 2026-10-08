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


def evidence_path(instance, filename):
    return f"asset_evidence/{uuid4().hex}{Path(filename).suffix.lower()}"


EVIDENCE_EXTENSIONS = ["pdf", "jpg", "jpeg", "png", "webp", "doc", "docx"]


def money_field(**kwargs):
    return models.DecimalField(max_digits=12, decimal_places=2,
                               validators=[MinValueValidator(Decimal('0'))], **kwargs)


class Business(models.Model):
    # Where this company stands with the platform owner. "pending" is a company
    # that signed itself up and has not been verified yet; it is a queue for the
    # administrator and does not restrict the workspace. "suspended" does: it
    # deactivates the company's employer sign-ins.
    STATUSES = [("pending", "Awaiting verification"), ("active", "Active"),
                ("suspended", "Suspended")]

    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, default="active", choices=STATUSES, db_index=True)
    # When the status last moved, so the dashboard can show what changed recently.
    status_changed_at = models.DateTimeField(null=True, blank=True)
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
    # True when a sign-in was created but the invitation email did not go out.
    # Counted platform-wide so the administrator can see mail problems; no
    # employee detail is reported from it.
    invite_email_failed = models.BooleanField(default=False)
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
    # The pay this contract agrees to. Older contracts predate it and fall back
    # to the employee's Salary record.
    monthly_salary = money_field(null=True, blank=True)
    salary_currency = models.CharField(max_length=3, default="RWF")
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


LOCATION_STATUSES = [("inside", "Inside office area"), ("outside", "Outside allowed area"),
                     ("unavailable", "Location unavailable")]


def coordinate_field():
    return models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)


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
    # Where the employee clocked in and out, checked against the workplace on
    # the server. A blank status means no check was made (no workplace saved,
    # or the record predates location checks).
    check_in_location_status = models.CharField(max_length=12, blank=True, choices=LOCATION_STATUSES)
    check_in_latitude = coordinate_field()
    check_in_longitude = coordinate_field()
    check_in_distance_m = models.PositiveIntegerField(null=True, blank=True)
    check_in_accuracy_m = models.PositiveIntegerField(null=True, blank=True)
    check_out_location_status = models.CharField(max_length=12, blank=True, choices=LOCATION_STATUSES)
    check_out_latitude = coordinate_field()
    check_out_longitude = coordinate_field()
    check_out_distance_m = models.PositiveIntegerField(null=True, blank=True)
    check_out_accuracy_m = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["employee", "date", "shift"], name="unique_employee_attendance_shift")]


class WorkplaceLocation(models.Model):
    """The office an employer saved; attendance within `radius_m` counts as inside."""

    business = models.OneToOneField(Business, on_delete=models.CASCADE, related_name="workplace_location")
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    radius_m = models.PositiveIntegerField(default=100, validators=[MinValueValidator(10), MaxValueValidator(5000)])
    updated_by = models.CharField(max_length=200, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


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
    contract = models.ForeignKey(Contract, on_delete=models.PROTECT, null=True, blank=True, related_name="payroll")
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


PAYMENT_METHODS = [("bank_transfer", "Bank transfer"), ("mobile_money", "Mobile money"), ("cash", "Cash")]
RATE_VALIDATORS = [MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))]


def rate_field(**kwargs):
    return models.DecimalField(max_digits=5, decimal_places=2, validators=RATE_VALIDATORS, **kwargs)


class PayrollPolicy(models.Model):
    """Per-business salary advance settings."""

    business = models.OneToOneField(Business, on_delete=models.CASCADE, null=True, blank=True,
                                    related_name="payroll_policy")
    # Share of the pay left after other deductions that salary advance
    # installments and asset recoveries may take together in one payroll.
    advance_deduction_limit_percent = rate_field(default=Decimal("33.33"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class PayrollCalculation(models.Model):
    """The automatic deductions applied to one payroll record.

    Amounts are a snapshot, so the payslip keeps showing what was deducted.
    """

    payroll = models.OneToOneField(Payroll, on_delete=models.CASCADE, related_name="calculation")
    gross_pay = money_field()
    advance_deductions = money_field()
    asset_deductions = money_field(default=0)
    other_deductions = money_field()
    total_deductions = money_field()
    net_pay = money_field()
    warnings = models.JSONField(default=list, blank=True)
    calculated_at = models.DateTimeField(auto_now=True)
    calculated_by = models.CharField(max_length=200, blank=True)


class PayrollDeductionLine(models.Model):
    KINDS = [("advance", "Salary advance repayment"), ("asset", "Asset misuse recovery"), ("other", "Other deductions")]

    calculation = models.ForeignKey(PayrollCalculation, on_delete=models.CASCADE, related_name="lines")
    kind = models.CharField(max_length=20, choices=KINDS)
    salary_advance = models.ForeignKey("SalaryAdvance", on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name="+")
    # The ledger of payroll recoveries for an incident.
    asset_incident = models.ForeignKey("AssetIncident", on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name="payroll_deductions")
    name = models.CharField(max_length=150)
    amount = money_field(default=0)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]


class SalaryAdvance(models.Model):
    """An interest-free advance repaid through monthly payroll installments.

    The status is derived from disbursement and repayments rather than stored,
    so it can never drift from the money actually recorded.
    """

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="salary_advances")
    amount = money_field()
    currency = models.CharField(max_length=3, default="RWF")
    issue_date = models.DateField()
    reason = models.TextField()
    installment_amount = money_field()
    first_repayment_month = models.DateField()
    notes = models.TextField(blank=True)
    disbursed_on = models.DateField(null=True, blank=True)
    disbursement_method = models.CharField(max_length=20, blank=True, choices=PAYMENT_METHODS)
    disbursement_reference = models.CharField(max_length=120, blank=True)
    approved_by = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-issue_date", "-id"]


class SalaryAdvanceRequest(models.Model):
    """An employee's request for an advance. Approval creates the SalaryAdvance."""

    STATUSES = [("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="salary_advance_requests")
    amount = money_field()
    currency = models.CharField(max_length=3, default="RWF")
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default="pending", db_index=True)
    decision_notes = models.TextField(blank=True)
    decided_by = models.CharField(max_length=200, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    advance = models.OneToOneField(SalaryAdvance, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="request")
    requested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-requested_at", "-id"]


class AdvanceRepayment(models.Model):
    """Money recovered against an advance. A payroll-sourced row counts as
    repaid once its payroll is paid; until then it is a scheduled deduction."""

    advance = models.ForeignKey(SalaryAdvance, on_delete=models.CASCADE, related_name="repayments")
    payroll = models.ForeignKey(Payroll, on_delete=models.CASCADE, null=True, blank=True,
                                related_name="advance_repayments")
    amount = money_field()
    repaid_on = models.DateField()
    source = models.CharField(max_length=10, choices=[("payroll", "Payroll deduction"), ("manual", "Direct repayment")])
    reference = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    recorded_by = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["repaid_on", "id"]
        constraints = [models.UniqueConstraint(fields=["advance", "payroll"], condition=models.Q(payroll__isnull=False),
                                               name="one_advance_deduction_per_payroll")]


class AssetIncident(models.Model):
    TYPES = [("damaged", "Damaged"), ("lost", "Lost"), ("misused", "Misused")]
    STATUSES = [("reported", "Reported"), ("under_review", "Under review"),
                ("resolved", "Resolved"), ("closed", "Closed")]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="asset_incidents")
    asset_name = models.CharField(max_length=200)
    asset_tag = models.CharField(max_length=100, blank=True)
    incident_type = models.CharField(max_length=20, choices=TYPES, default="damaged")
    incident_date = models.DateField()
    description = models.TextField()
    estimated_loss = money_field(default=0)
    currency = models.CharField(max_length=3, default="RWF")
    evidence = models.FileField(upload_to=evidence_path, blank=True,
                                validators=[FileExtensionValidator(EVIDENCE_EXTENSIONS)])
    status = models.CharField(max_length=20, choices=STATUSES, default="reported")
    investigation_findings = models.TextField(blank=True)
    employee_response = models.TextField(blank=True)
    resolution = models.TextField(blank=True)
    # Deducted through payroll only once the incident is resolved or closed.
    recovery_amount = money_field(default=0)
    recovery_authorization = models.TextField(blank=True)
    reported_by = models.CharField(max_length=200, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-incident_date", "-id"]


@receiver(pre_save, sender=AssetIncident)
def discard_replaced_incident_evidence(sender, instance, **kwargs):
    discard_replaced_file(sender, instance, "evidence")


class PlatformMessage(models.Model):
    """A message between the platform administrator and one company.

    Conversations are per company: every employer of that company talks to the
    administrator in the same thread, so a company's history survives a change
    of employer account. Employee matters are not carried here.
    """

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="platform_messages")
    # Kept for attribution only. The thread belongs to the business, so losing
    # the author to a deleted account must not take the message with it.
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                               blank=True, related_name="platform_messages_sent")
    from_admin = models.BooleanField()
    # How the sender chose to deliver it. "message" stays inside the dashboard
    # and nothing is emailed; "email" goes to the recipient's inbox only and
    # never appears in their thread. The sender keeps a record of both.
    channel = models.CharField(max_length=10, default="message", choices=[
        ("message", "Message"), ("email", "Email")])
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    # Set when the other side opens the thread, which is what clears the badge.
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["business", "created_at"])]

    def __str__(self):
        return f"{'Admin' if self.from_admin else self.business.name} message {self.pk}"
