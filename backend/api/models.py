from decimal import Decimal
from pathlib import Path
from uuid import uuid4

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


class Employee(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    department = models.CharField(max_length=100)
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


class Contract(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="contracts")
    title = models.CharField(max_length=200)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, default="active", choices=[
        ("draft", "Draft"), ("active", "Active"), ("ended", "Ended")])
    terms = models.TextField(blank=True)
    document = models.FileField(upload_to=contract_path, blank=True,
        validators=[FileExtensionValidator(["pdf", "doc", "docx"])])
    created_at = models.DateTimeField(auto_now_add=True)


class Attendance(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="attendance")
    date = models.DateField()
    status = models.CharField(max_length=20, default="present", choices=[
        ("present", "Present"), ("remote", "Remote"), ("absent", "Absent")])
    hours_worked = models.DecimalField(max_digits=4, decimal_places=2, default=0,
        validators=[MinValueValidator(0), MaxValueValidator(24)])
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["employee", "date"], name="unique_employee_attendance")]


class LeaveRequest(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="leave_requests")
    leave_type = models.CharField(max_length=20, default="annual", choices=[
        ("annual", "Annual"), ("sick", "Sick"), ("family", "Family responsibility"),
        ("unpaid", "Unpaid"), ("other", "Other")])
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, default="pending", choices=[
        ("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")])
    decision_notes = models.TextField(blank=True)


class Holiday(models.Model):
    name = models.CharField(max_length=200)
    date = models.DateField(unique=True)
    notes = models.TextField(blank=True)


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
