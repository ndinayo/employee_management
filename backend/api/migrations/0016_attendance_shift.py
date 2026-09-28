from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("api", "0015_contract_revision_and_message")]

    operations = [
        migrations.RemoveConstraint(
            model_name="attendance",
            name="unique_employee_attendance",
        ),
        migrations.AddField(
            model_name="attendance",
            name="shift",
            field=models.CharField(
                choices=[("morning", "Morning"), ("afternoon", "Afternoon"), ("night", "Night")],
                default="morning",
                max_length=20,
            ),
        ),
        migrations.AddConstraint(
            model_name="attendance",
            constraint=models.UniqueConstraint(
                fields=("employee", "date", "shift"),
                name="unique_employee_attendance_shift",
            ),
        ),
    ]
