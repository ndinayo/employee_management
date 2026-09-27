from datetime import date
from decimal import Decimal

from django.db import migrations, models
import django.core.validators
import django.db.models.deletion
import django.utils.timezone


def create_current_balances(apps, schema_editor):
    Employee = apps.get_model("api", "Employee")
    LeaveBalance = apps.get_model("api", "LeaveBalance")
    defaults = {"annual": Decimal("20.0"), "sick": Decimal("10.0"),
                "maternity": Decimal("90.0"), "unpaid": Decimal("0.0")}
    rows = [LeaveBalance(employee_id=employee_id, leave_type=kind, year=date.today().year,
                         days_allocated=days)
            for employee_id in Employee.objects.values_list("id", flat=True)
            for kind, days in defaults.items()]
    LeaveBalance.objects.bulk_create(rows, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [("api", "0012_attendance_clock_times")]

    operations = [
        migrations.AlterField(
            model_name="leaverequest", name="leave_type",
            field=models.CharField(choices=[("annual", "Annual"), ("sick", "Sick"),
                ("maternity", "Maternity"), ("unpaid", "Unpaid")], default="annual", max_length=20),
        ),
        migrations.AddField(model_name="leaverequest", name="requested_at",
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now), preserve_default=False),
        migrations.AddField(model_name="leaverequest", name="decided_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="leaverequest", name="decided_by", field=models.CharField(blank=True, max_length=200)),
        migrations.CreateModel(
            name="LeaveBalance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("leave_type", models.CharField(choices=[("annual", "Annual"), ("sick", "Sick"),
                    ("maternity", "Maternity"), ("unpaid", "Unpaid")], max_length=20)),
                ("year", models.PositiveIntegerField()),
                ("days_allocated", models.DecimalField(decimal_places=1, default=0, max_digits=5,
                    validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(366)])),
                ("employee", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name="leave_balances", to="api.employee")),
            ],
        ),
        migrations.AddConstraint(
            model_name="leavebalance",
            constraint=models.UniqueConstraint(fields=("employee", "leave_type", "year"),
                name="unique_employee_leave_balance"),
        ),
        migrations.RunPython(create_current_balances, migrations.RunPython.noop),
    ]
